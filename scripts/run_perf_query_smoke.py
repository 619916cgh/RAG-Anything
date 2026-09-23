"""Bounded direct SSE observations for an isolated performance run."""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Iterator

import requests


def _inside_temp(path: Path) -> Path:
    root = path.resolve()
    temp = Path(os.getenv("TEMP", "/tmp")).resolve()
    if root == temp or temp not in root.parents:
        raise ValueError("run directory must be a child of the system temporary directory")
    return root


def _events(response: requests.Response) -> Iterator[tuple[str, dict]]:
    data: list[str] = []
    for line in response.iter_lines(chunk_size=1024, decode_unicode=True):
        if not line:
            if not data:
                continue
            raw = "\n".join(data)
            data = []
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


def _read_credentials(run_dir: Path) -> dict[str, str]:
    records = json.loads(run_dir.joinpath("credentials.json").read_text(encoding="utf-8"))
    if not isinstance(records, list) or len(records) != 1:
        raise RuntimeError("expected one generated credential record")
    record = records[0]
    if not all(record.get(key) for key in ("username", "password", "agent_id")):
        raise RuntimeError("generated credential record is incomplete")
    return record


def _login(base_url: str, credential: dict[str, str], timeout: float) -> str:
    response = requests.post(
        f"{base_url}/api/auth/login",
        json={"username": credential["username"], "password": credential["password"]},
        timeout=timeout,
    )
    if response.status_code != 200:
        raise RuntimeError(f"login_http_{response.status_code}")
    token = response.json().get("access_token")
    if not token:
        raise RuntimeError("login_missing_token")
    return str(token)


def _record(base_url: str, credential: dict[str, str], token: str, timeout: float) -> dict:
    session = requests.Session()
    started = None
    outcome = {
        "outcome": "failed",
        "error_class": "unknown",
        "http_status": 0,
        "ttfb_ms": None,
        "ttft_ms": None,
        "total_ms": None,
        "events": [],
        "token_count": 0,
    }
    try:
        # The logical SSE timer begins immediately before connection creation;
        # login is a separate authenticated operation, not stream latency.
        started = time.perf_counter()
        response = session.post(
            f"{base_url}/api/agents/{credential['agent_id']}/query/stream/internal",
            json={"query": "Isolated performance fixture", "retrieval_only": False},
            headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
            stream=True,
            timeout=timeout,
        )
        outcome["http_status"] = response.status_code
        outcome["ttfb_ms"] = round((time.perf_counter() - started) * 1000, 3)
        if response.status_code != 200:
            outcome["error_class"] = f"http_{response.status_code}"
            return outcome
        done = False
        for kind, payload in _events(response):
            if kind not in outcome["events"]:
                outcome["events"].append(kind)
            if kind == "token" and str(payload.get("content") or "").strip():
                outcome["token_count"] += 1
                if outcome["ttft_ms"] is None:
                    outcome["ttft_ms"] = round((time.perf_counter() - started) * 1000, 3)
            if kind == "error":
                outcome["error_class"] = "sse_error"
                return outcome
            if kind == "malformed":
                outcome["error_class"] = "sse_malformed"
                return outcome
            if kind == "done":
                done = True
                break
        if not done:
            outcome["error_class"] = "eof_without_done"
            return outcome
        if outcome["ttft_ms"] is None:
            outcome["error_class"] = "done_without_token"
            return outcome
        outcome["outcome"] = "success"
        outcome["error_class"] = ""
        return outcome
    except requests.Timeout:
        outcome["error_class"] = "timeout"
        return outcome
    except requests.RequestException as exc:
        outcome["error_class"] = type(exc).__name__.lower()
        return outcome
    finally:
        if started is not None:
            outcome["total_ms"] = round((time.perf_counter() - started) * 1000, 3)
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--attempts", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    if args.attempts < 1 or args.attempts > 20:
        raise ValueError("attempts must be between 1 and 20 for the low-resource profile")
    if not args.base_url.startswith("http://127.0.0.1:"):
        raise ValueError("base URL must use a loopback port")
    run_dir = _inside_temp(Path(args.run_dir))
    credential = _read_credentials(run_dir)
    try:
        token = _login(args.base_url.rstrip("/"), credential, args.timeout)
    except RuntimeError as exc:
        outcomes = [{"outcome": "failed", "error_class": str(exc), "http_status": 0, "ttfb_ms": None, "ttft_ms": None, "total_ms": None, "events": [], "token_count": 0}]
    else:
        outcomes = [_record(args.base_url.rstrip("/"), credential, token, args.timeout) for _ in range(args.attempts)]
    with run_dir.joinpath("query-outcomes.ndjson").open("w", encoding="utf-8") as handle:
        for outcome in outcomes:
            handle.write(json.dumps(outcome, ensure_ascii=True) + "\n")
    successes = sum(item["outcome"] == "success" for item in outcomes)
    print(f"query-smoke: {successes}/{len(outcomes)} successful")
    return 0 if successes == len(outcomes) else 2


if __name__ == "__main__":
    raise SystemExit(main())
