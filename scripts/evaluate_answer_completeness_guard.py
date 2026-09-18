#!/usr/bin/env python3
"""A/B the same-context answer-completeness guard without calling an Agent."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import request

from raganything.services.answer_completeness import (
    apply_answer_completeness_guard,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class OpenAICompatibleLLM:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float,
    ) -> None:
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _call(
        self,
        *,
        prompt: str,
        system_prompt: str,
        max_tokens: int,
        temperature: float,
        stream: bool,
    ) -> str:
        if stream:
            raise ValueError("streaming is not supported by this A/B runner")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        req = request.Request(
            self.url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=self.timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        choice = (body.get("choices") or [{}])[0]
        if choice.get("finish_reason") != "stop":
            raise ValueError("LLM did not finish normally")
        content = ((choice.get("message") or {}).get("content") or "").strip()
        if not content:
            raise ValueError("LLM returned empty content")
        return content

    async def __call__(self, **kwargs) -> str:
        return await asyncio.to_thread(self._call, **kwargs)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the same-context completeness guard A/B."
    )
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--contexts", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--audit-max-tokens", type=int, default=700)
    parser.add_argument("--revision-max-tokens", type=int, default=2048)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--allow-shared-provider", action="store_true")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    results = load_jsonl(args.results)
    contexts = {
        int(record["question_number"]): record
        for record in load_jsonl(args.contexts)
    }
    selected = [
        record
        for record in results
        if int(record["question_number"]) in contexts
    ]
    if args.limit is not None:
        selected = selected[: args.limit]
    if not selected:
        raise SystemExit("No matching results and contexts")

    base_url = os.getenv("JUDGE_LLM_BASE_URL", "").strip()
    api_key = os.getenv("JUDGE_LLM_API_KEY", "").strip()
    model = os.getenv("JUDGE_LLM_MODEL", "").strip()
    if args.allow_shared_provider:
        base_url = base_url or os.getenv("LLM_BINDING_HOST", "").strip()
        api_key = api_key or os.getenv("LLM_BINDING_API_KEY", "").strip()
        model = (
            model
            or os.getenv("LLM_BINDING_MODEL", "").strip()
            or os.getenv("LLM_MODEL", "").strip()
        )
    if not base_url or not api_key or not model:
        raise SystemExit("LLM provider is not configured")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / "guarded_results.jsonl"
    if output_path.exists():
        raise SystemExit(f"Output already exists: {output_path}")

    llm = OpenAICompatibleLLM(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout=args.timeout,
    )
    semaphore = asyncio.Semaphore(args.concurrency)
    write_lock = asyncio.Lock()
    summary_counts: Counter[str] = Counter()
    revision_count = 0

    async def one(record: dict[str, Any]) -> None:
        nonlocal revision_count
        async with semaphore:
            question_number = int(record["question_number"])
            context_record = contexts[question_number]
            started = time.perf_counter()
            result = await apply_answer_completeness_guard(
                question=str(record["question"]),
                context=str(context_record.get("context") or ""),
                draft_answer=str(record.get("answer") or ""),
                llm_callable=llm,
                audit_max_tokens=args.audit_max_tokens,
                revision_max_tokens=args.revision_max_tokens,
                timeout_seconds=args.timeout,
            )
            output_record = {
                **record,
                "run_id": str(record.get("run_id") or "") + "-guard",
                "first_answer": result.first_answer,
                "answer": result.final_answer,
                "answer_guard": result.metadata(),
                "answer_guard_elapsed_s": round(
                    time.perf_counter() - started,
                    3,
                ),
            }
            async with write_lock:
                with output_path.open("a", encoding="utf-8") as output:
                    output.write(
                        json.dumps(output_record, ensure_ascii=False) + "\n"
                    )
                    output.flush()
                    os.fsync(output.fileno())
                summary_counts[
                    "revision_used"
                    if result.used_revision
                    else "revision_not_used"
                ] += 1
                if result.revision_error:
                    summary_counts[
                        f"revision_error:{result.revision_error}"
                    ] += 1
                if result.used_revision:
                    revision_count += 1
                print(
                    f"Q{question_number} revision={result.used_revision} "
                    f"missing={len(result.missing_required_facts)} "
                    f"reason={result.reason}",
                    flush=True,
                )

    await asyncio.gather(*(one(record) for record in selected))
    manifest = {
        "started_output": str(output_path),
        "finished_utc": utc_now(),
        "input_results": str(args.results),
        "input_contexts": str(args.contexts),
        "count": len(selected),
        "revision_count": revision_count,
        "summary": dict(summary_counts),
        "model": model,
        "agent_calls": False,
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"output={output_path}")
    print(f"revision_count={revision_count}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(parse_args())))
