#!/usr/bin/env python3
"""Run the six Markdown QA sets against the six cloud agents.

The script intentionally contains no credentials. When executed inside the
application container it reads the existing DEFAULT_ADMIN_USERNAME and
DEFAULT_ADMIN_PASSWORD environment variables.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import os
import re
import socket
import statistics
import sys
import threading
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request


PROJECT_NUMBERS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
}
FILE_PATTERN = re.compile(r"^项目([一二三四五六])\s+(.+)\.md$")
QUESTION_PATTERN = re.compile(r"^\*\*(\d+)\.\s*问：(.*?)\*\*\s*$")
TERMINAL_EVENTS = {"done", "error"}
UNSAFE_CITATION_KEYS = {
    "path",
    "file_path",
    "local_path",
    "source_path",
    "url",
    "media_url",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_markdown(path: Path) -> list[dict[str, Any]]:
    project_match = FILE_PATTERN.match(path.name)
    if not project_match:
        raise ValueError(f"Unexpected QA file name: {path.name}")

    project_number = PROJECT_NUMBERS[project_match.group(1)]
    project_name = project_match.group(2)
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    records: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def finish_current() -> None:
        nonlocal current
        if current is None:
            return
        answer_lines = [line.rstrip() for line in current.pop("_answer_lines")]
        while answer_lines and not answer_lines[0].strip():
            answer_lines.pop(0)
        while answer_lines and not answer_lines[-1].strip():
            answer_lines.pop()
        if answer_lines:
            answer_lines[0] = re.sub(r"^\s*答[：:]\s*", "", answer_lines[0])
        answer = "\n".join(answer_lines).strip()
        current["answer"] = answer
        current["question_sha256"] = hashlib.sha256(
            current["question"].encode("utf-8")
        ).hexdigest()
        records.append(current)
        current = None

    for line in lines:
        match = QUESTION_PATTERN.match(line.rstrip())
        if match:
            finish_current()
            question_number = int(match.group(1))
            question = match.group(2).strip()
            current = {
                "project_number": project_number,
                "project_name": project_name,
                "source_file": path.name,
                "question_number": question_number,
                "question": question,
                "_answer_lines": [],
            }
        elif current is not None:
            current["_answer_lines"].append(line)

    finish_current()
    if not records:
        raise ValueError(f"No QA pairs found in {path}")
    return records


def load_qa_sets(input_dir: Path) -> list[dict[str, Any]]:
    files = sorted(
        (path for path in input_dir.iterdir() if FILE_PATTERN.match(path.name)),
        key=lambda path: PROJECT_NUMBERS[FILE_PATTERN.match(path.name).group(1)],
    )
    if len(files) != 6:
        raise ValueError(f"Expected 6 QA Markdown files, found {len(files)}")

    records: list[dict[str, Any]] = []
    for path in files:
        records.extend(parse_markdown(path))

    expected = list(range(1, len(records) + 1))
    actual = [item["question_number"] for item in records]
    if actual != expected:
        raise ValueError(
            "Question numbering is not contiguous from 1 through "
            f"{len(records)}"
        )
    return records


def sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: sanitize_value(item)
            for key, item in value.items()
            if key not in UNSAFE_CITATION_KEYS
        }
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    return value


def decode_http_error(exc: error.HTTPError) -> str:
    try:
        body = exc.read(4096).decode("utf-8", errors="replace")
    except Exception:
        body = ""
    return f"HTTP {exc.code}: {body[:1000]}"


class CloudClient:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.refresh_token = ""
        self._refresh_lock = threading.Lock()

    def _refresh_locked(self, timeout: float) -> bool:
        with self._refresh_lock:
            if not self.refresh_token:
                return False
            payload = json.dumps(
                {"refresh_token": self.refresh_token},
                ensure_ascii=False,
            ).encode("utf-8")
            req = request.Request(
                self.base_url + "/api/auth/refresh",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with request.urlopen(req, timeout=timeout) as response:
                    result = json.loads(response.read().decode("utf-8"))
            except Exception:
                return False
            token = result.get("access_token")
            refresh_token = result.get("refresh_token")
            if not token or not refresh_token:
                return False
            self.token = token
            self.refresh_token = refresh_token
            return True

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        timeout: float = 60,
    ) -> tuple[int, dict[str, Any]]:
        data = None
        headers = {"Authorization": f"Bearer {self.token}"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = request.Request(
            self.base_url + path,
            data=data,
            headers=headers,
            method=method,
        )
        for attempt in range(2):
            try:
                with request.urlopen(req, timeout=timeout) as response:
                    body = response.read()
                    return response.status, json.loads(body.decode("utf-8"))
            except error.HTTPError as exc:
                if exc.code != 401 or attempt or not self._refresh_locked(timeout):
                    raise
                req.remove_header("Authorization")
                req.add_header("Authorization", f"Bearer {self.token}")
        raise RuntimeError("Authenticated request retry loop exhausted")

    def login(
        self,
        username: str,
        password: str,
        timeout: float,
    ) -> tuple[str, str, dict[str, Any]]:
        payload = json.dumps(
            {"username": username, "password": password},
            ensure_ascii=False,
        ).encode("utf-8")
        req = request.Request(
            self.base_url + "/api/auth/login",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
        token = result.get("access_token")
        refresh_token = result.get("refresh_token")
        if not token or not refresh_token:
            raise RuntimeError(
                "Login response did not contain access and refresh tokens"
            )
        return token, refresh_token, result

    def list_agents(self) -> list[dict[str, Any]]:
        _, result = self._request("/api/agents")
        return list(result.get("agents") or [])

    def list_llm_profiles(self) -> list[dict[str, Any]]:
        _, result = self._request("/api/model-profiles?kind=llm")
        return list(result.get("profiles") or [])

    def probe_model_profile(self, profile_id: str) -> dict[str, Any]:
        _, result = self._request(
            f"/api/admin/model-profiles/{profile_id}/probe",
            method="POST",
        )
        return result

    def query_stream(
        self,
        agent_id: str,
        question: str,
        *,
        timeout: float,
    ) -> dict[str, Any]:
        payload = json.dumps(
            {
                "query": question,
                "thread_id": "",
                "vlm_enhanced": False,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        req = request.Request(
            self.base_url + f"/api/agents/{agent_id}/query/stream",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            method="POST",
        )

        started = time.perf_counter()
        event_counts: Counter[str] = Counter()
        answer_parts: list[str] = []
        warnings: list[str] = []
        done_event: dict[str, Any] | None = None
        error_message: str | None = None
        first_event_s: float | None = None
        first_token_s: float | None = None
        thread_id = ""
        query_id = ""
        http_status = 0
        answer_guard: dict[str, Any] | None = None

        try:
            for auth_attempt in range(2):
                try:
                    response = request.urlopen(req, timeout=timeout)
                    break
                except error.HTTPError as exc:
                    if (
                        exc.code != 401
                        or auth_attempt
                        or not self._refresh_locked(timeout)
                    ):
                        raise
                    req.remove_header("Authorization")
                    req.add_header("Authorization", f"Bearer {self.token}")
            else:
                raise RuntimeError("Authenticated stream retry loop exhausted")

            with response:
                http_status = response.status
                while True:
                    if time.perf_counter() - started > timeout:
                        raise TimeoutError(
                            f"Request exceeded {timeout:.1f}s total timeout"
                        )
                    line = response.readline()
                    if not line:
                        break
                    stripped = line.decode("utf-8", errors="replace").strip()
                    if not stripped.startswith("data:"):
                        continue
                    raw = stripped[5:].strip()
                    if not raw:
                        continue
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    event_type = str(event.get("type") or "unknown")
                    event_counts[event_type] += 1
                    if first_event_s is None:
                        first_event_s = round(time.perf_counter() - started, 3)
                    if event_type == "agent_info":
                        thread_id = str(event.get("thread_id") or "")
                    elif event_type == "token":
                        if first_token_s is None:
                            first_token_s = round(
                                time.perf_counter() - started,
                                3,
                            )
                        answer_parts.append(str(event.get("content") or ""))
                    elif event_type == "replace":
                        answer_parts[:] = [
                            str(event.get("content") or "")
                        ]
                        guard_payload = event.get("answer_guard")
                        if isinstance(guard_payload, dict):
                            answer_guard = sanitize_value(guard_payload)
                    elif event_type == "warning":
                        warnings.append(str(event.get("content") or event))
                    elif event_type == "error":
                        error_message = str(
                            event.get("content")
                            or event.get("message")
                            or event
                        )
                    elif event_type == "done":
                        done_event = event
                        query_id = str(event.get("id") or "")
                        thread_id = (
                            str(event.get("thread_id") or "") or thread_id
                        )
                    if event_type in TERMINAL_EVENTS:
                        break
        except error.HTTPError as exc:
            return {
                "status": "http_error",
                "http_status": exc.code,
                "error": decode_http_error(exc),
                "answer": "".join(answer_parts),
                "citations": [],
                "fallback": None,
                "event_counts": dict(event_counts),
                "warnings": warnings,
                "first_event_s": first_event_s,
                "first_token_s": first_token_s,
                "server_elapsed_s": None,
                "total_s": round(time.perf_counter() - started, 3),
                "thread_id": thread_id,
                "query_id": query_id,
                "answer_guard": answer_guard,
            }
        except (TimeoutError, socket.timeout) as exc:
            return {
                "status": "timeout",
                "http_status": http_status,
                "error": str(exc),
                "answer": "".join(answer_parts),
                "citations": [],
                "fallback": None,
                "event_counts": dict(event_counts),
                "warnings": warnings,
                "first_event_s": first_event_s,
                "first_token_s": first_token_s,
                "server_elapsed_s": None,
                "total_s": round(time.perf_counter() - started, 3),
                "thread_id": thread_id,
                "query_id": query_id,
                "answer_guard": answer_guard,
            }
        except Exception as exc:
            return {
                "status": "exception",
                "http_status": http_status,
                "error": f"{type(exc).__name__}: {exc}",
                "answer": "".join(answer_parts),
                "citations": [],
                "fallback": None,
                "event_counts": dict(event_counts),
                "warnings": warnings,
                "first_event_s": first_event_s,
                "first_token_s": first_token_s,
                "server_elapsed_s": None,
                "total_s": round(time.perf_counter() - started, 3),
                "thread_id": thread_id,
                "query_id": query_id,
                "answer_guard": answer_guard,
            }

        answer = "".join(answer_parts).strip()
        citations = sanitize_value((done_event or {}).get("citations") or [])
        fallback = bool((done_event or {}).get("fallback"))
        if error_message:
            status = "sse_error"
        elif done_event is None:
            status = "incomplete"
        elif fallback:
            status = "fallback"
        elif not answer:
            status = "incomplete"
        else:
            status = "passed"

        return {
            "status": status,
            "http_status": http_status,
            "error": error_message,
            "answer": answer,
            "citations": citations,
            "fallback": fallback,
            "event_counts": dict(event_counts),
            "warnings": warnings,
            "first_event_s": first_event_s,
            "first_token_s": first_token_s,
            "server_elapsed_s": (
                done_event.get("elapsed") if done_event is not None else None
            ),
            "total_s": round(time.perf_counter() - started, 3),
            "thread_id": thread_id,
            "query_id": query_id,
            "answer_guard": answer_guard,
        }


def select_agents(
    agents: list[dict[str, Any]],
    requested_names: list[str],
) -> dict[str, dict[str, Any]]:
    by_name: dict[str, dict[str, Any]] = {}
    for agent in agents:
        name = str(agent.get("name") or "")
        if name in by_name:
            raise ValueError(f"Duplicate agent name: {name}")
        by_name[name] = agent

    selected: dict[str, dict[str, Any]] = {}
    for name in requested_names:
        if name not in by_name:
            raise ValueError(f"Agent not found: {name}")
        selected[name] = by_name[name]
    return selected


def load_existing_results(path: Path) -> tuple[list[dict[str, Any]], set[str]]:
    if not path.exists():
        return [], set()
    records: list[dict[str, Any]] = []
    completed: set[str] = set()
    with path.open("r", encoding="utf-8") as source:
        for line in source:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            records.append(record)
            completed.add(record_key(record))
    return records, completed


def record_key(record: dict[str, Any]) -> str:
    return "{}:{}".format(
        record.get("project_number"),
        record.get("question_number"),
    )


def append_json_line(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(record, ensure_ascii=False) + "\n")
        output.flush()
        os.fsync(output.fileno())


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * fraction)))
    return round(ordered[index], 3)


def write_outputs(
    output_dir: Path,
    records: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = output_dir / "metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    by_agent: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_agent.setdefault(str(record.get("agent_name") or ""), []).append(
            record
        )

    summary_rows: list[dict[str, Any]] = []
    for agent_name in metadata["agent_order"]:
        agent_records = by_agent.get(agent_name, [])
        statuses = Counter(
            str(record.get("status") or "unknown")
            for record in agent_records
        )
        durations = [
            float(record["total_s"])
            for record in agent_records
            if isinstance(record.get("total_s"), (int, float))
        ]
        summary_rows.append(
            {
                "agent_name": agent_name,
                "agent_id": metadata["agents"][agent_name]["id"],
                "kb_name": metadata["agents"][agent_name]["kb_name"],
                "total": len(agent_records),
                "passed": statuses["passed"],
                "fallback": statuses["fallback"],
                "sse_error": statuses["sse_error"],
                "http_error": statuses["http_error"],
                "timeout": statuses["timeout"],
                "incomplete": statuses["incomplete"],
                "exception": statuses["exception"],
                "avg_s": (
                    round(statistics.fmean(durations), 3)
                    if durations
                    else None
                ),
                "p50_s": percentile(durations, 0.50),
                "p95_s": percentile(durations, 0.95),
                "max_s": round(max(durations), 3) if durations else None,
                "citation_records": sum(
                    1
                    for record in agent_records
                    if record.get("citations")
                ),
            }
        )

    summary = {
        "run_id": metadata["run_id"],
        "generated_utc": utc_now(),
        "record_count": len(records),
        "overall": dict(
            Counter(str(record.get("status") or "unknown") for record in records)
        ),
        "agents": summary_rows,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with (output_dir / "summary.csv").open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as output:
        writer = csv.DictWriter(output, fieldnames=list(summary_rows[0]))
        writer.writeheader()
        writer.writerows(summary_rows)

    with (output_dir / "results.csv").open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as output:
        fields = [
            "agent_name",
            "agent_id",
            "kb_name",
            "project_number",
            "source_file",
            "question_number",
            "status",
            "fallback",
            "total_s",
            "first_event_s",
            "first_token_s",
            "citation_count",
            "question",
            "expected_answer",
            "answer",
            "error",
        ]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for record in records:
            row = dict(record)
            row["citation_count"] = len(record.get("citations") or [])
            writer.writerow({field: row.get(field) for field in fields})


async def run_tests(
    client: CloudClient,
    qa_records: list[dict[str, Any]],
    agents: dict[str, dict[str, Any]],
    *,
    agent_names_by_project: dict[int, str],
    output_dir: Path,
    concurrency: int,
    timeout: float,
    limit_per_agent: int | None,
    resume: bool,
    query_nonce: bool,
    max_consecutive_failures: int,
) -> list[dict[str, Any]]:
    results_path = output_dir / "results.jsonl"
    existing_records, completed = (
        load_existing_results(results_path) if resume else ([], set())
    )
    if not resume and results_path.exists():
        raise FileExistsError(
            f"Result file already exists; use --resume or choose another run: "
            f"{results_path}"
        )

    tasks: list[dict[str, Any]] = []
    per_agent_counts: Counter[int] = Counter()
    for qa in qa_records:
        project_number = int(qa["project_number"])
        if (
            limit_per_agent is not None
            and per_agent_counts[project_number] >= limit_per_agent
        ):
            continue
        per_agent_counts[project_number] += 1
        agent_name = agent_names_by_project[project_number]
        if agent_name not in agents:
            raise ValueError(f"Missing mapped agent: {agent_name}")
        task = {
            **qa,
            "agent_name": agent_name,
            "agent": agents[agent_name],
        }
        if record_key(task) in completed:
            continue
        tasks.append(task)

    semaphore = asyncio.Semaphore(concurrency)
    write_lock = asyncio.Lock()
    new_records: list[dict[str, Any]] = []
    circuit_state = {"consecutive_failures": 0, "aborted": False}

    async def execute(task: dict[str, Any]) -> None:
        async with semaphore:
            async with write_lock:
                if circuit_state["aborted"]:
                    print(
                        "circuit_open skipped={} Q{}".format(
                            task["agent_name"],
                            task["question_number"],
                        ),
                        flush=True,
                    )
                    return
            agent = task["agent"]
            agent_name = task["agent_name"]
            query = str(task["question"])
            if query_nonce:
                query = (
                    f"{query}\n\n"
                    "[本次真实测试唯一标识："
                    f"{output_dir.name}-{task['project_number']}-"
                    f"{task['question_number']}。仅用于避免模型缓存，请忽略。]"
                )
            result = await asyncio.to_thread(
                client.query_stream,
                str(agent["id"]),
                query,
                timeout=timeout,
            )
            record = {
                "run_id": output_dir.name,
                "timestamp_utc": utc_now(),
                "agent_name": agent_name,
                "agent_id": agent.get("id"),
                "kb_name": agent.get("kb_name"),
                "project_number": task["project_number"],
                "project_name": task["project_name"],
                "source_file": task["source_file"],
                "question_number": task["question_number"],
                "question_sha256": task["question_sha256"],
                "question": task["question"],
                "provider_query_sha256": hashlib.sha256(
                    query.encode("utf-8")
                ).hexdigest(),
                "expected_answer": task["answer"],
                **result,
            }
            async with write_lock:
                append_json_line(results_path, record)
                new_records.append(record)
                if record["status"] == "passed":
                    circuit_state["consecutive_failures"] = 0
                else:
                    circuit_state["consecutive_failures"] += 1
                    if (
                        circuit_state["consecutive_failures"]
                        >= max_consecutive_failures
                    ):
                        circuit_state["aborted"] = True
                print(
                    "[{}/{}] {} Q{} status={} fallback={} elapsed={}s".format(
                        len(existing_records) + len(new_records),
                        len(existing_records) + len(tasks),
                        agent_name,
                        task["question_number"],
                        record["status"],
                        record.get("fallback"),
                        record.get("total_s"),
                    ),
                    flush=True,
                )

    if tasks:
        await asyncio.gather(*(execute(task) for task in tasks))
    return existing_records + new_records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run cloud agent QA acceptance tests."
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("/app/qa-input"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("/app/output/cloud-agent-qa"),
    )
    parser.add_argument("--run-id")
    parser.add_argument("--username-env", default="DEFAULT_ADMIN_USERNAME")
    parser.add_argument("--password-env", default="DEFAULT_ADMIN_PASSWORD")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--limit-per-agent", type=int)
    parser.add_argument("--agents", default="测试1,测试2,测试3,测试4,测试5,测试6")
    parser.add_argument(
        "--project-number",
        type=int,
        choices=range(1, 7),
        help="Run only one project when combined with --agent-name.",
    )
    parser.add_argument(
        "--agent-name",
        help="Agent to use for the selected project.",
    )
    parser.add_argument(
        "--max-consecutive-failures",
        type=int,
        default=5,
    )
    parser.add_argument(
        "--query-nonce",
        action="store_true",
        help=(
            "Opt in to the legacy cache-busting suffix. It changes the "
            "retrieval query and must not be used for accuracy baselines."
        ),
    )
    parser.add_argument(
        "--allow-must-change",
        action="store_true",
        help="Continue when the account is marked must_change_password.",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.concurrency < 1 or args.concurrency > 6:
        raise SystemExit("--concurrency must be between 1 and 6")
    if args.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    if args.max_consecutive_failures < 1:
        raise SystemExit("--max-consecutive-failures must be positive")

    qa_records = load_qa_sets(args.input_dir)
    requested_agents = [
        item.strip() for item in args.agents.split(",") if item.strip()
    ]
    if (args.project_number is None) != (args.agent_name is None):
        raise SystemExit(
            "--project-number and --agent-name must be provided together"
        )
    if args.project_number is not None:
        requested_agents = [args.agent_name]
        qa_records = [
            record
            for record in qa_records
            if int(record["project_number"]) == args.project_number
        ]
        agent_names_by_project = {
            int(args.project_number): str(args.agent_name)
        }
    else:
        expected_agents = [f"测试{number}" for number in range(1, 7)]
        if requested_agents != expected_agents:
            raise SystemExit(
                "--agents must contain 测试1 through 测试6 in order"
            )
        agent_names_by_project = {
            number: f"测试{number}" for number in range(1, 7)
        }

    file_manifest = {
        path.name: {
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(
            args.input_dir.iterdir(),
            key=lambda path: path.name,
        )
        if FILE_PATTERN.match(path.name)
    }

    if args.dry_run:
        counts = Counter(
            int(record["project_number"]) for record in qa_records
        )
        print(f"qa_total={len(qa_records)}")
        for number in range(1, 7):
            print(f"测试{number}_questions={counts[number]}")
        for file_name, manifest in file_manifest.items():
            print(
                f"file={file_name} bytes={manifest['bytes']} "
                f"sha256={manifest['sha256']}"
            )
        return 0

    username = os.getenv(args.username_env)
    password = os.getenv(args.password_env)
    if not username or not password:
        raise SystemExit(
            f"Missing credential environment variables: "
            f"{args.username_env}, {args.password_env}"
        )

    run_id = args.run_id or (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )
    output_dir = args.output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    client = CloudClient(args.base_url, "")
    token, refresh_token, login = client.login(
        username,
        password,
        timeout=args.timeout,
    )
    client.token = token
    client.refresh_token = refresh_token
    must_change = bool(
        (login.get("user") or {}).get("must_change_password")
    )
    if must_change and not args.allow_must_change:
        raise SystemExit(
            "Account requires a password change; use --allow-must-change only "
            "under explicit authorization."
        )
    agents = select_agents(client.list_agents(), requested_agents)
    llm_profiles = client.list_llm_profiles()
    available_profiles = [
        profile
        for profile in llm_profiles
        if profile.get("available")
        and "mock" not in str(profile.get("model") or "").lower()
    ]
    if not available_profiles:
        raise RuntimeError("No available non-mock LLM profile")
    selected_profile = available_profiles[0]
    profile_probe = client.probe_model_profile(
        str(selected_profile.get("id") or "")
    )
    if not profile_probe.get("available"):
        raise RuntimeError("Selected LLM profile probe failed")
    metadata = {
        "run_id": run_id,
        "started_utc": utc_now(),
        "base_url": args.base_url,
        "concurrency": args.concurrency,
        "timeout_s": args.timeout,
        "limit_per_agent": args.limit_per_agent,
        "must_change_password": must_change,
        "must_change_override": args.allow_must_change,
        "query_nonce_enabled": bool(args.query_nonce),
        "max_consecutive_failures": args.max_consecutive_failures,
        "llm_profile": {
            "id": selected_profile.get("id"),
            "provider": selected_profile.get("provider"),
            "model": selected_profile.get("model"),
            "probe": profile_probe,
        },
        "agent_order": requested_agents,
        "agents": {
            name: {
                "id": agent.get("id"),
                "name": agent.get("name"),
                "kb_name": agent.get("kb_name"),
                "kb_display_name": agent.get("kb_display_name"),
                "llm_model": agent.get("llm_model"),
                "query_mode": agent.get("query_mode"),
                "agent_mode": agent.get("agent_mode"),
                "system_prompt_sha256": hashlib.sha256(
                    str(agent.get("system_prompt") or "").encode("utf-8")
                ).hexdigest(),
                "system_prompt_len": len(
                    str(agent.get("system_prompt") or "")
                ),
            }
            for name, agent in agents.items()
        },
        "qa_total": len(qa_records),
        "qa_files": file_manifest,
    }
    records = asyncio.run(
        run_tests(
            client,
            qa_records,
            agents,
            agent_names_by_project=agent_names_by_project,
            output_dir=output_dir,
            concurrency=args.concurrency,
            timeout=args.timeout,
            limit_per_agent=args.limit_per_agent,
            resume=args.resume,
            query_nonce=bool(args.query_nonce),
            max_consecutive_failures=args.max_consecutive_failures,
        )
    )
    metadata["finished_utc"] = utc_now()
    write_outputs(output_dir, records, metadata)
    print(f"output_dir={output_dir}")
    print(f"record_count={len(records)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
