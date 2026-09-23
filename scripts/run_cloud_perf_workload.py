"""Run redacted, session-aware workloads for an isolated cloud performance run."""
from __future__ import annotations

import argparse
import json
import os
import statistics
import threading
import time
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import requests


TERMINAL_UPLOAD_STATES = {"completed", "failed", "deleted", "cancelled", "terminal_failed"}
_SAFE_EVENT_TYPES = frozenset({"accepted", "agent_info", "retrieval", "thinking", "token", "warning", "done", "error"})
_SAFE_ERROR_CODES = frozenset({"query_core_acquire", "pre_agent_info_setup", "unknown"})
_MAX_EVENT_SEQUENCE = 64
# Mock Profile B keeps its historical diagnostic gate. Real Qwen acceptance uses
# the user-approved SLO and is selected only by the explicit runner profile.
PROFILE_B_TTFT_P95_MAX_MS = 5000 if os.environ.get("PERF_PROVIDER_PROFILE") == "qwen" else 2100
PROFILE_B_TOTAL_P95_MAX_MS = 15000 if os.environ.get("PERF_PROVIDER_PROFILE") == "qwen" else 2700


def _inside_temp(path: Path) -> Path:
    root = path.resolve()
    temp = Path(os.getenv("TMPDIR", os.getenv("TEMP", "/tmp"))).resolve()
    if root == temp or temp not in root.parents:
        raise ValueError("run directory must be a child of the system temporary directory")
    return root


def _loopback_base_url(value: str) -> str:
    base_url = value.rstrip("/")
    if not base_url.startswith("http://127.0.0.1:"):
        raise ValueError("base URL must use a loopback port")
    return base_url


def _credentials(run_dir: Path) -> list[dict[str, Any]]:
    records = json.loads(run_dir.joinpath("credentials.json").read_text(encoding="utf-8"))
    if not isinstance(records, list) or not records:
        raise RuntimeError("credential file must contain generated records")
    names = [str(record.get("username") or "") for record in records]
    if len(names) != len(set(names)) or not all(names):
        raise RuntimeError("virtual-user identities must be distinct")
    if any(not all(record.get(key) for key in ("password", "agent_id", "kb")) for record in records):
        raise RuntimeError("generated credential record is incomplete")
    return records


def _events(response: requests.Response) -> Iterator[tuple[str, dict[str, Any]]]:
    data: list[str] = []
    for line in response.iter_lines(chunk_size=1024, decode_unicode=True):
        if not line:
            if not data:
                continue
            raw, data = "\n".join(data), []
            if raw == "[DONE]":
                yield "done", {}
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                yield "malformed", {}
                continue
            yield str(payload.get("type") or "message"), payload
        elif line.startswith(":"):
            yield "heartbeat", {}
        elif line.startswith("data:"):
            data.append(line[5:].strip())
    if data:
        yield "malformed", {}


def _safe_event_type(kind: str) -> str:
    """Return a fixed event class without retaining untrusted event names."""
    return kind if kind in _SAFE_EVENT_TYPES else "other"


def _safe_error_code(payload: dict[str, Any]) -> str:
    """Keep only the fixed test-image diagnostic code, never arbitrary payload data."""
    code = payload.get("code")
    return str(code) if code in _SAFE_ERROR_CODES else ""


def _error_phase(event_sequence: list[str]) -> str:
    """Classify an error only by the public protocol position, never payload text."""
    if "agent_info" not in event_sequence:
        return "before_agent_info"
    if "retrieval" not in event_sequence:
        return "after_agent_info_before_retrieval"
    if "token" not in event_sequence:
        return "after_retrieval_before_token"
    return "after_token_persistence_or_terminal"


def _protocol_class(event_sequence: list[str], terminal_kind: str) -> str:
    """Return one fixed protocol finding for the redacted diagnostic trace."""
    terminal_events = [kind for kind in event_sequence if kind in {"done", "error"}]
    first_terminal = next((index for index, kind in enumerate(event_sequence) if kind in {"done", "error"}), None)
    if first_terminal is not None and first_terminal != len(event_sequence) - 1:
        return "event_after_terminal"
    if len(terminal_events) > 1:
        return "multiple_terminal_events"
    if terminal_kind in {"done", "error"} and event_sequence.count("accepted") != 1:
        return "accepted_count_invalid"
    if terminal_kind in {"done", "error"} and event_sequence and event_sequence[0] != "accepted":
        return "accepted_not_first"
    if terminal_kind == "done" and "agent_info" not in event_sequence:
        return "done_without_agent_info"
    return ""


def _profile_b_protocol_class(result: dict[str, Any]) -> str:
    """Fail closed for Profile B without retaining any event payload values."""
    trace = result.get("protocol_trace")
    if isinstance(trace, dict):
        if trace.get("unknown_event_seen") or trace.get("error_event_seen") or result.get("terminal_kind") != "done":
            return "unexpected_event_or_terminal"
        if trace.get("event_after_terminal"):
            return "event_after_terminal"
        if int(trace.get("terminal_count") or 0) != 1:
            return "done_sequence_invalid"
        if trace.get("first_event") != "accepted" or int(trace.get("accepted_count") or 0) != 1:
            return "accepted_sequence_invalid"
        if not trace.get("agent_info_seen") or not trace.get("token_seen"):
            return "required_event_missing"
        return ""
    sequence = list(result.get("event_sequence") or [])
    if result.get("event_sequence_truncated"):
        return "event_sequence_truncated"
    if "other" in sequence or "error" in sequence or result.get("terminal_kind") != "done":
        return "unexpected_event_or_terminal"
    if result.get("protocol_class"):
        return str(result["protocol_class"])
    if not sequence or sequence[0] != "accepted" or sequence.count("accepted") != 1:
        return "accepted_sequence_invalid"
    if sequence.count("done") != 1 or sequence[-1] != "done":
        return "done_sequence_invalid"
    if "agent_info" not in sequence or "token" not in sequence:
        return "required_event_missing"
    return ""


def _new_protocol_trace() -> dict[str, Any]:
    return {
        "first_event": "",
        "accepted_count": 0,
        "agent_info_seen": False,
        "token_seen": False,
        "terminal_count": 0,
        "event_after_terminal": False,
        "unknown_event_seen": False,
        "error_event_seen": False,
    }


def _record_protocol_event(trace: dict[str, Any], safe_kind: str) -> None:
    if not trace["first_event"]:
        trace["first_event"] = safe_kind
    if trace["terminal_count"]:
        trace["event_after_terminal"] = True
    if safe_kind == "accepted":
        trace["accepted_count"] += 1
    elif safe_kind == "agent_info":
        trace["agent_info_seen"] = True
    elif safe_kind == "token":
        trace["token_seen"] = True
    elif safe_kind in {"done", "error"}:
        trace["terminal_count"] += 1
    if safe_kind == "other":
        trace["unknown_event_seen"] = True
    if safe_kind == "error":
        trace["error_event_seen"] = True


def _profile_b_summary(rows: list[dict[str, Any]], *, stopped: bool) -> dict[str, Any]:
    """Return the aggregate-only Profile B result; independent load requests are not retries."""
    successes = [row for row in rows if row.get("outcome") == "success"]
    protocol_classes = Counter(
        classification for classification in (_profile_b_protocol_class(row) for row in rows) if classification
    )
    protocol_failures = sum(protocol_classes.values())
    retries = sum(max(0, int(row.get("retry_count") or 0)) for row in rows)
    timings = {
        field: {
            f"p{int(percentile * 100)}": _percentile(
                [float(row[field]) for row in successes if row.get(field) is not None], percentile
            )
            for percentile in (0.5, 0.95, 0.99)
        }
        for field in ("ttfb_ms", "ttft_ms", "total_ms")
    }
    phase_names = (
        "accepted_to_agent_info_ms",
        "agent_info_to_retrieval_ms",
        "retrieval_to_first_chunk_ms",
        "first_chunk_to_done_ms",
        "accepted_to_first_chunk_ms",
        "accepted_to_done_ms",
    )
    def phase_value(row: dict[str, Any], field: str) -> float | None:
        values = row.get("sse_phase_ms")
        if not isinstance(values, dict) or values.get(field) is None:
            return None
        try:
            return float(values[field])
        except (TypeError, ValueError):
            return None

    phase_timings = {
        field: {
            f"p{int(percentile * 100)}": _percentile(
                [
                    value
                    for row in successes
                    for value in (phase_value(row, field),)
                    if value is not None
                ],
                percentile,
            )
            for percentile in (0.5, 0.95, 0.99)
        }
        for field in phase_names
    }
    ttft_p95 = timings["ttft_ms"]["p95"]
    total_p95 = timings["total_ms"]["p95"]
    passed = bool(rows) and len(successes) == len(rows) and not stopped and retries == 0 and protocol_failures == 0
    passed = (
        passed and ttft_p95 is not None and total_p95 is not None
        and ttft_p95 <= PROFILE_B_TTFT_P95_MAX_MS
        and total_p95 <= PROFILE_B_TOTAL_P95_MAX_MS
    )
    return {
        "requests": len(rows), "successes": len(successes), "retries": retries,
        "protocol_failures": protocol_failures,
        "protocol_failure_classes": dict(sorted(protocol_classes.items())),
        "timing_ms": timings,
        "sse_phase_ms": phase_timings,
        "latency_gates_ms": {"ttft_p95_max": PROFILE_B_TTFT_P95_MAX_MS, "total_p95_max": PROFILE_B_TOTAL_P95_MAX_MS},
        "ttft_p95_ms": ttft_p95, "total_p95_ms": total_p95, "passed": passed,
    }


def _login(base_url: str, record: dict[str, Any], timeout: float) -> str:
    response = requests.post(
        f"{base_url}/api/auth/login",
        json={"username": record["username"], "password": record["password"]},
        timeout=timeout,
    )
    if response.status_code != 200:
        raise RuntimeError(f"login_http_{response.status_code}")
    token = response.json().get("access_token")
    if not token:
        raise RuntimeError("login_missing_token")
    return str(token)


def _stream_query(
    session: requests.Session,
    base_url: str,
    record: dict[str, Any],
    token: str,
    timeout: float,
    *,
    thread_id: str | None,
    retrieval_only: bool,
) -> tuple[dict[str, Any], str | None]:
    started = time.perf_counter()
    started_at = round(time.time(), 3)
    result: dict[str, Any] = {
        "outcome": "failed", "error_class": "unknown", "http_class": "0xx",
        "ttfb_ms": None, "ttft_ms": None, "total_ms": None, "token_count": 0,
        "event_sequence": [], "event_count": 0, "event_sequence_truncated": False,
        "protocol_trace": _new_protocol_trace(),
        "terminal_kind": "none", "error_phase": "",
        "protocol_class": "", "error_code": "", "retrieval_context_present": False, "retrieval_source_count": 0,
        "thread_reused": bool(thread_id), "thread_relation": "reused" if thread_id else "new",
        "started_at": started_at, "finished_at": None,
        "sse_phase_ms": {},
    }
    next_thread = thread_id
    event_marks: dict[str, float] = {}
    try:
        request_payload: dict[str, Any] = {
            "query": "What does the isolated performance fixture contain?",
            "retrieval_only": retrieval_only,
        }
        if thread_id:
            request_payload["thread_id"] = thread_id
        response = session.post(
            f"{base_url}/api/agents/{record['agent_id']}/query/stream/internal",
            json=request_payload,
            headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
            stream=True,
            timeout=timeout,
        )
        result["ttfb_ms"] = round((time.perf_counter() - started) * 1000, 3)
        result["http_class"] = f"{response.status_code // 100}xx"
        if response.status_code != 200:
            result["error_class"] = "limiter_429" if response.status_code == 429 else f"http_{response.status_code}"
            result["outcome"] = "limited" if response.status_code == 429 else "failed"
            return result, next_thread
        done = False
        error_seen = False
        for kind, payload in _events(response):
            event_now = time.perf_counter()
            safe_kind = _safe_event_type(kind)
            result["event_count"] += 1
            _record_protocol_event(result["protocol_trace"], safe_kind)
            if len(result["event_sequence"]) < _MAX_EVENT_SEQUENCE:
                result["event_sequence"].append(safe_kind)
            else:
                result["event_sequence_truncated"] = True
            if kind == "agent_info" and payload.get("thread_id"):
                next_thread = str(payload["thread_id"])
            if kind == "accepted":
                event_marks.setdefault("accepted", event_now)
            elif kind == "agent_info":
                event_marks.setdefault("agent_info", event_now)
            elif kind == "retrieval":
                event_marks.setdefault("retrieval", event_now)
                result["retrieval_context_present"] = bool(payload.get("context_present"))
                result["retrieval_source_count"] = int(payload.get("text_source_count") or 0)
            elif kind == "token" and str(payload.get("content") or "").strip():
                result["token_count"] += 1
                # Count the first non-empty streamed chunk without retaining its content.
                event_marks.setdefault("first_chunk", event_now)
                if result["ttft_ms"] is None:
                    result["ttft_ms"] = round((time.perf_counter() - started) * 1000, 3)
            elif kind == "error":
                error_seen = True
                result["terminal_kind"] = "error"
                result["error_code"] = _safe_error_code(payload)
            elif kind == "malformed":
                result["error_class"] = "sse_malformed"
                result["terminal_kind"] = "malformed"
                break
            elif kind == "done":
                done = True
                event_marks.setdefault("done", event_now)
                result["terminal_kind"] = "done"
                if payload.get("fallback"):
                    result["error_class"] = "retrieval_fallback"
        result["protocol_class"] = _protocol_class(result["event_sequence"], result["terminal_kind"])
        if result["protocol_class"]:
            result["error_class"] = f"sse_protocol_{result['protocol_class']}"
        elif error_seen:
            result["error_phase"] = _error_phase(result["event_sequence"])
            result["error_class"] = f"sse_error_{result['error_code'] or result['error_phase']}"
        elif result["terminal_kind"] == "malformed":
            pass
        elif result["error_class"] == "retrieval_fallback":
            pass
        elif not done:
            result["terminal_kind"] = "eof"
            result["error_class"] = "eof_without_done"
        elif retrieval_only and not result["retrieval_context_present"]:
            result["error_class"] = "retrieval_missing"
        elif not retrieval_only and result["ttft_ms"] is None:
            result["error_class"] = "done_without_token"
        else:
            result["outcome"] = "success"
            result["error_class"] = ""
    except requests.Timeout:
        result["error_class"] = "timeout"
        result["terminal_kind"] = "transport_error"
    except requests.RequestException as exc:
        result["error_class"] = type(exc).__name__.lower()
        result["terminal_kind"] = "transport_error"
    finally:
        marks = locals().get("event_marks", {})
        phase_pairs = (
            ("accepted_to_agent_info_ms", "accepted", "agent_info"),
            ("agent_info_to_retrieval_ms", "agent_info", "retrieval"),
            ("retrieval_to_first_chunk_ms", "retrieval", "first_chunk"),
            ("first_chunk_to_done_ms", "first_chunk", "done"),
            ("accepted_to_first_chunk_ms", "accepted", "first_chunk"),
            ("accepted_to_done_ms", "accepted", "done"),
        )
        result["sse_phase_ms"] = {
            name: round((marks[end] - marks[start]) * 1000, 3)
            for name, start, end in phase_pairs
            if start in marks and end in marks and marks[end] >= marks[start]
        }
        result["total_ms"] = round((time.perf_counter() - started) * 1000, 3)
        result["finished_at"] = round(time.time(), 3)
        if thread_id and next_thread != thread_id:
            result["thread_relation"] = "reused_changed"
    return result, next_thread


def _safe_task_failure(task: dict[str, Any]) -> tuple[str, str]:
    """Map untrusted task diagnostics to fixed, content-free acceptance labels."""
    raw_stage = str(task.get("failure_stage") or "").strip().lower()
    stage = raw_stage if raw_stage in {
        "initializing", "model_preflight", "parsing", "embedding", "vlm_ocr",
        "ocr", "indexing", "entity_extraction", "graph_index", "finalize",
        "quota", "retrieval_readiness", "tagging", "timeout", "video_processing",
        "worker",
    } else "other"
    detail = " ".join(
        str(task.get(key) or "")
        for key in ("failure_code", "error_message", "error", "outcome")
    ).lower()
    # Provider/governor failures often include the word "embedding" because
    # they originate in the embedding preflight. Attribute those to the
    # provider boundary first so readiness failures remain actionable.
    if any(marker in detail for marker in ("provider", "dashscope", "provider_call_leases", "provider_waiters")):
        family = "provider"
    elif any(marker in detail for marker in ("embedding", "vector", "embed")):
        family = "embedding"
    elif "timeout" in detail or "超时" in detail:
        family = "timeout"
    elif any(marker in detail for marker in ("auth", "credential", "api key", "unauthorized", "forbidden")):
        family = "auth"
    elif any(marker in detail for marker in ("postgres", "database", "connection", "db ")):
        family = "database"
    elif "retrieval" in detail:
        family = "retrieval"
    else:
        family = "other"
    return stage, family


def _task_status(base_url: str, record: dict[str, Any], token: str, task_id: str, timeout: float) -> tuple[str | None, str, str]:
    response = requests.get(
        f"{base_url}/api/upload/tasks", params={"kb": record["kb"]},
        headers={"Authorization": f"Bearer {token}"}, timeout=timeout,
    )
    if response.status_code != 200:
        return None, "other", "other"
    for item in response.json().get("tasks", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("task_id") or "") == task_id:
            stage, family = _safe_task_failure(item)
            return str(item.get("status") or "").lower(), stage, family
    return None, "other", "other"


def _fixture_bytes(kind: str, run_id: str, vu: int, sequence: int | str) -> tuple[str, bytes, str]:
    fixtures = Path(__file__).resolve().parents[1] / "tests" / "perf" / "fixtures"
    if kind == "text":
        content = fixtures.joinpath("sample.txt").read_bytes() + f"\nrun={run_id} vu={vu} sequence={sequence}\n".encode("ascii")
        return f"fixture-{vu:03d}-{sequence}.txt", content, "text/plain"
    if kind == "pdf":
        # A trailing PDF comment preserves the fixed non-OCR fixture while
        # making each request content-unique for the duplicate gate.
        content = fixtures.joinpath("cloud_fixture.pdf").read_bytes() + f"\n% run={run_id} vu={vu} sequence={sequence}\n".encode("ascii")
        return f"fixture-{vu:03d}-{sequence}.pdf", content, "application/pdf"
    raise ValueError("fixture kind must be text or pdf")


def _upload_unique_fixture(base_url: str, record: dict[str, Any], token: str, run_id: str, timeout: float, *, kind: str, sequence: int | str, check_duplicate: bool) -> dict[str, Any]:
    filename, content, media_type = _fixture_bytes(kind, run_id, int(record["vu"]), sequence)
    headers = {"Authorization": f"Bearer {token}"}
    started = time.perf_counter()
    result: dict[str, Any] = {
        "http_status": 0, "terminal_status": "", "terminal_failure_stage": "other",
        "terminal_failure_family": "other", "classification": "unknown", "duplicate_http_status": 0,
    }
    response = requests.post(
        f"{base_url}/api/upload", params={"kb": record["kb"], "enable_image": "false", "enable_table": "false", "enable_equation": "false"},
        files={"file": (filename, content, media_type)}, headers=headers, timeout=timeout,
    )
    result["http_status"] = response.status_code
    result["accept_ms"] = round((time.perf_counter() - started) * 1000, 3)
    if response.status_code != 200:
        result["classification"] = f"upload_http_{response.status_code}"
        return result
    task_id = str(response.json().get("task_id") or "")
    if not task_id:
        result["classification"] = "accepted_without_task_id"
        return result
    deadline = time.monotonic() + timeout
    status: str | None = None
    while time.monotonic() < deadline:
        status, failure_stage, failure_family = _task_status(base_url, record, token, task_id, timeout)
        if status in TERMINAL_UPLOAD_STATES:
            result["terminal_failure_stage"] = failure_stage
            result["terminal_failure_family"] = failure_family
            break
        time.sleep(2)
    result["terminal_status"] = status or "not_observed"
    if status != "completed":
        result["classification"] = f"terminal_{status or 'timeout'}"
        return result
    retrieval_deadline = time.monotonic() + timeout
    retrieval_ready = False
    while time.monotonic() < retrieval_deadline:
        health = requests.get(
            f"{base_url}/api/knowledge/retrieval-health", params={"kb": record["kb"]}, headers=headers, timeout=timeout,
        )
        if health.status_code == 200 and bool(health.json().get("healthy")):
            retrieval_ready = True
            break
        time.sleep(1)
    if not retrieval_ready:
        result["classification"] = "completed_not_retrieval_ready"
        return result
    if not check_duplicate:
        result["classification"] = "retrieval_ready"
        return result
    duplicate = requests.post(
        f"{base_url}/api/upload", params={"kb": record["kb"]},
        files={"file": (filename, content, media_type)}, headers=headers, timeout=timeout,
    )
    result["duplicate_http_status"] = duplicate.status_code
    result["classification"] = "retrieval_ready" if duplicate.status_code == 409 else f"duplicate_http_{duplicate.status_code}"
    return result


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 3)


def _write_ndjson(path: Path, row: dict[str, Any], lock: threading.Lock) -> None:
    with lock, path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n")


def readiness(base_url: str, run_dir: Path, timeout: float) -> int:
    records = _credentials(run_dir)
    run_id = json.loads(run_dir.joinpath("manifest.json").read_text(encoding="utf-8"))["run_id"]
    outcomes: list[dict[str, Any]] = []
    for record in records:
        token = _login(base_url, record, timeout)
        upload = _upload_unique_fixture(base_url, record, token, str(run_id), timeout, kind="text", sequence=0, check_duplicate=True)
        query = {"outcome": "skipped"}
        if upload["classification"] == "retrieval_ready":
            with requests.Session() as session:
                query, _unused = _stream_query(session, base_url, record, token, timeout, thread_id=None, retrieval_only=True)
        outcomes.append({"vu": record["vu"], "upload": upload, "retrieval_query": query})
    path = run_dir.joinpath("retrieval-gate.json")
    path.write_text(json.dumps(outcomes, ensure_ascii=True, sort_keys=True), encoding="utf-8")
    ready = all(item["upload"]["classification"] == "retrieval_ready" and item["retrieval_query"].get("outcome") == "success" and item["retrieval_query"].get("retrieval_source_count", 0) > 0 for item in outcomes)
    print(f"retrieval-gate: {'passed' if ready else 'failed'} ({len(outcomes)} virtual users)")
    return 0 if ready else 2


def upload_stage(base_url: str, run_dir: Path, users: int, timeout: float, label: str, kind: str, *, diagnostic: bool) -> int:
    records = _credentials(run_dir)[:users]
    if len(records) != users:
        raise ValueError("generated credential count is below requested virtual users")
    manifest = json.loads(run_dir.joinpath("manifest.json").read_text(encoding="utf-8"))
    run_id = str(manifest["run_id"])
    output = run_dir.joinpath(f"upload-{label}.json")
    if diagnostic:
        records = records[:1]
    else:
        diagnostic_result = json.loads(run_dir.joinpath("upload-diagnostic.json").read_text(encoding="utf-8"))
        if diagnostic_result.get("classification") != "retrieval_ready" or diagnostic_result.get("duplicate_http_status") != 409:
            raise RuntimeError("upload concurrency requires a retrieval-ready text duplicate diagnostic")
    rows: list[dict[str, Any]] = []
    lock = threading.Lock()

    def worker(index: int, record: dict[str, Any]) -> None:
        try:
            token = _login(base_url, record, timeout)
            result = _upload_unique_fixture(
                base_url, record, token, run_id, timeout,
                kind=kind, sequence=f"{label}-{index + 1}", check_duplicate=diagnostic,
            )
        except Exception as exc:
            result = {"http_status": 0, "terminal_status": "", "classification": type(exc).__name__.lower(), "duplicate_http_status": 0}
        result.update({"vu": record["vu"], "fixture_kind": kind})
        with lock:
            rows.append(result)

    threads = [threading.Thread(target=worker, args=(index, record), daemon=True) for index, record in enumerate(records)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    completed = sum(row["classification"] == "retrieval_ready" for row in rows)
    payload = {"label": label, "fixture_kind": kind, "requests": len(rows), "retrieval_ready": completed, "outcomes": rows}
    output.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True), encoding="utf-8")
    if diagnostic:
        run_dir.joinpath("upload-diagnostic.json").write_text(json.dumps(rows[0], ensure_ascii=True, sort_keys=True), encoding="utf-8")
    print(f"upload-{label}: {completed}/{len(rows)} retrieval-ready")
    return 0 if completed == len(rows) else 2


def recovery(run_dir: Path, duration: float, interval: float) -> int:
    output = run_dir.joinpath("recovery.ndjson")
    output.unlink(missing_ok=True)
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        with output.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"timestamp": round(time.time(), 3), "kind": "recovery_sample", "stop_file_present": run_dir.joinpath("stop-load.json").exists()}, ensure_ascii=True) + "\n")
        time.sleep(interval)
    return 0


def query_stage(base_url: str, run_dir: Path, users: int, duration: float, ramp: float, timeout: float, label: str) -> int:
    records = _credentials(run_dir)[:users]
    if len(records) != users:
        raise ValueError("generated credential count is below requested virtual users")
    manifest = json.loads(run_dir.joinpath("manifest.json").read_text(encoding="utf-8"))
    rate_limit_mode = str(manifest.get("rate_limit_mode") or "")
    if rate_limit_mode not in {"enforced", "capacity"}:
        raise RuntimeError("run manifest does not declare a rate-limit mode")
    if str(manifest.get("diagnostic_mode") or "") == "authorized-30-40-50-ladder":
        if users != manifest.get("diagnostic_stage"):
            raise RuntimeError("ladder query users must match the manifest-approved stage")
    profile_b = manifest.get("resource_profile") == "profile-b"
    if profile_b:
        if users != manifest.get("profile_b_stage") or label != f"profile-b-{users}" or duration + ramp > 90:
            raise RuntimeError("Profile B query stage does not match the approved manifest")
    gate = json.loads(run_dir.joinpath("retrieval-gate.json").read_text(encoding="utf-8"))
    if len(gate) < users or any(item["upload"]["classification"] != "retrieval_ready" or item["retrieval_query"].get("outcome") != "success" for item in gate[:users]):
        raise RuntimeError("retrieval-ready gate has not passed for this stage")
    stop_file = run_dir.joinpath("stop-load.json")
    ndjson = run_dir.joinpath(f"query-{label}.ndjson")
    ndjson.unlink(missing_ok=True)
    write_lock = threading.Lock()
    start = time.monotonic()
    steady_deadline = start + ramp + duration

    def worker(index: int, record: dict[str, Any]) -> None:
        if ramp:
            time.sleep((ramp / users) * index)
        try:
            token = _login(base_url, record, timeout)
        except Exception as exc:
            _write_ndjson(ndjson, {"stage": label, "vu": record["vu"], "outcome": "failed", "error_class": type(exc).__name__.lower(), "http_class": "0xx"}, write_lock)
            return
        thread_id: str | None = None
        attempt = 0
        with requests.Session() as session:
            while time.monotonic() < steady_deadline and not stop_file.exists():
                attempt += 1
                result, thread_id = _stream_query(session, base_url, record, token, timeout, thread_id=thread_id, retrieval_only=False)
                result.update({"stage": label, "vu": record["vu"], "attempt": attempt, "retry_count": 0, "timestamp": round(time.time(), 3), "rate_limit_mode": rate_limit_mode})
                _write_ndjson(ndjson, result, write_lock)
                if result["outcome"] == "limited" and rate_limit_mode == "enforced":
                    continue
                if result["outcome"] != "success":
                    break

    threads = [threading.Thread(target=worker, args=(index, record), daemon=True) for index, record in enumerate(records)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    rows = [json.loads(line) for line in ndjson.read_text(encoding="utf-8").splitlines()] if ndjson.exists() else []
    successful = [row for row in rows if row.get("outcome") == "success"]
    limited = [row for row in rows if row.get("outcome") == "limited"]
    non_limiter_requests = len(rows) - len(limited)
    summary = {
        "stage": label, "users": users, "requests": len(rows), "successes": len(successful),
        "rate_limit_mode": rate_limit_mode, "limiter_429": len(limited),
        "success_rate_excluding_enforced_429": round(len(successful) / non_limiter_requests, 5) if non_limiter_requests else 0.0,
        "ttft_ms": {f"p{int(p * 100)}": _percentile([float(row["ttft_ms"]) for row in successful if row.get("ttft_ms") is not None], p) for p in (0.5, 0.95, 0.99)},
        "total_ms": {f"p{int(p * 100)}": _percentile([float(row["total_ms"]) for row in successful if row.get("total_ms") is not None], p) for p in (0.5, 0.95, 0.99)},
        "error_classes": dict(sorted(Counter(str(row.get("error_class") or "") for row in rows if row.get("error_class")).items())),
        "terminal_kinds": dict(sorted(Counter(str(row.get("terminal_kind") or "") for row in rows if row.get("terminal_kind")).items())),
        "error_phases": dict(sorted(Counter(str(row.get("error_phase") or "") for row in rows if row.get("error_phase")).items())),
        "error_codes": dict(sorted(Counter(str(row.get("error_code") or "") for row in rows if row.get("error_code")).items())),
        "protocol_classes": dict(sorted(Counter(str(row.get("protocol_class") or "") for row in rows if row.get("protocol_class")).items())),
        "stopped": stop_file.exists(),
    }
    if profile_b:
        summary["profile_b"] = _profile_b_summary(rows, stopped=summary["stopped"])
    run_dir.joinpath(f"query-{label}.json").write_text(json.dumps(summary, ensure_ascii=True, sort_keys=True), encoding="utf-8")
    print(f"query-stage {label}: {summary['successes']}/{summary['requests']} successful")
    capacity_429 = rate_limit_mode == "capacity" and bool(limited)
    if profile_b:
        return 0 if summary["profile_b"]["passed"] else 2
    return 0 if summary["success_rate_excluding_enforced_429"] >= 0.99 and not summary["stopped"] and not capacity_429 else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--mode", choices=("readiness", "query", "upload-diagnostic", "upload-stage", "recovery"), required=True)
    parser.add_argument("--users", type=int, default=1)
    parser.add_argument("--duration", type=float, default=600)
    parser.add_argument("--ramp", type=float, default=120)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--label", default="stage")
    parser.add_argument("--fixture-kind", choices=("text", "pdf"), default="text")
    args = parser.parse_args()
    if args.users < 1 or args.users > 50 or args.duration <= 0 or args.ramp < 0:
        raise ValueError("invalid stage dimensions")
    run_dir = _inside_temp(Path(args.run_dir))
    base_url = _loopback_base_url(args.base_url)
    if args.mode == "readiness":
        return readiness(base_url, run_dir, args.timeout)
    if args.mode == "upload-diagnostic":
        return upload_stage(base_url, run_dir, args.users, args.timeout, args.label, "text", diagnostic=True)
    if args.mode == "upload-stage":
        return upload_stage(base_url, run_dir, args.users, args.timeout, args.label, args.fixture_kind, diagnostic=False)
    if args.mode == "recovery":
        return recovery(run_dir, args.duration, max(1.0, args.ramp or 5.0))
    return query_stage(base_url, run_dir, args.users, args.duration, args.ramp, args.timeout, args.label)


if __name__ == "__main__":
    raise SystemExit(main())
