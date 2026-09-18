#!/usr/bin/env python3
"""Capture the final RAG context for one QA project without calling an LLM."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raganything.services.kb_service import get_kb
from raganything.services.pg_auth_repo import get_user_by_username
from raganything.services.pg_state_repo import init_pg_pool
from raganything.services.query_execution import QueryExecutionScope
from raganything.services.user_settings import (
    available_sections_for_user,
    resolve_user_settings_for_task,
)


CHUNK_PATTERN = re.compile(r"\bchunk-[0-9a-fA-F-]{6,}\b")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture final agent RAG context without generation."
    )
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--kb", default="测试")
    parser.add_argument("--project-number", type=int, default=1)
    parser.add_argument("--username-env", default="DEFAULT_ADMIN_USERNAME")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--limit", type=int)
    return parser.parse_args()


async def main() -> int:
    args = parse_args()

    runner_path = Path(__file__).with_name("cloud_agent_qa_test.py")
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "cloud_agent_qa_test_for_probe",
        runner_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load QA parser")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    qa_records = [
        record
        for record in runner.load_qa_sets(args.input_dir)
        if int(record["project_number"]) == args.project_number
    ]
    if args.limit is not None:
        qa_records = qa_records[: args.limit]
    if not qa_records:
        raise SystemExit("No QA records selected")

    username = os.getenv(args.username_env)
    if not username:
        raise SystemExit(
            f"Missing user environment variable: {args.username_env}"
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / "contexts.jsonl"
    if output_path.exists():
        raise SystemExit(f"Output already exists: {output_path}")

    await init_pg_pool()
    user = await get_user_by_username(username)
    if not user:
        raise SystemExit("User not found")
    settings = await resolve_user_settings_for_task(
        int(user["id"]),
        permitted_sections=await available_sections_for_user(
            int(user["id"])
        ),
    )
    instance = await get_kb(args.kb)

    run_id = args.output_dir.name
    started = utc_now()
    with output_path.open("w", encoding="utf-8") as output:
        for record in qa_records:
            question = str(record["question"])
            trace_id = uuid.uuid4().hex[:12]
            scope = QueryExecutionScope(
                trace_id=trace_id,
                workspace=args.kb,
                corpus_revision="probe",
                permission_scope=f"user:{user['id']}",
                settings_fingerprint=settings.fingerprint,
                llm_profile_fingerprint="probe",
                deadline_monotonic=time.monotonic() + args.timeout,
                provenance_sink=[],
            )
            started_at = time.perf_counter()
            error = None
            context = ""
            try:
                context = await asyncio.wait_for(
                    instance.aquery(
                        question,
                        mode="hybrid",
                        vlm_enhanced=False,
                        only_need_context=True,
                        enable_rerank=False,
                        chunk_top_k=20,
                        top_k=40,
                        include_references=False,
                        retrieval_options=settings.retrieval,
                        query_execution_scope=scope,
                        max_entity_tokens=3000,
                        max_relation_tokens=2000,
                        max_total_tokens=16000,
                    ),
                    timeout=args.timeout,
                )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            elapsed = round(time.perf_counter() - started_at, 3)
            context_text = str(context or "")
            chunk_ids = sorted(set(CHUNK_PATTERN.findall(context_text)))
            result = {
                "run_id": run_id,
                "question_number": int(record["question_number"]),
                "project_number": int(record["project_number"]),
                "question_sha256": sha256_text(question),
                "context_present": bool(
                    context_text.strip()
                    and "[no-context]" not in context_text
                ),
                "context_chars": len(context_text),
                "context_sha256": sha256_text(context_text),
                "context_chunk_ids": chunk_ids,
                "context_chunk_count": len(chunk_ids),
                "elapsed_s": elapsed,
                "error": error,
                "context": context_text,
            }
            output.write(json.dumps(result, ensure_ascii=False) + "\n")
            output.flush()
            os.fsync(output.fileno())
            print(
                f"Q{record['question_number']} present={result['context_present']} "
                f"chars={result['context_chars']} chunks={len(chunk_ids)} "
                f"elapsed={elapsed}s error={bool(error)}",
                flush=True,
            )

    metadata = {
        "run_id": run_id,
        "started_utc": started,
        "finished_utc": utc_now(),
        "kb": args.kb,
        "project_number": args.project_number,
        "record_count": len(qa_records),
        "settings_fingerprint": settings.fingerprint,
        "query_mode": "hybrid",
        "retrieval_top_k": 40,
        "chunk_top_k": 20,
        "enable_rerank": False,
        "include_references": False,
        "agent_calls": False,
    }
    (args.output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"output_dir={args.output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
