"""Record one unique-upload terminal state before any upload load run."""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import requests


TERMINAL = {"completed", "failed", "deleted", "cancelled", "terminal_failed"}


def _inside_temp(path: Path) -> Path:
    root = path.resolve()
    temp = Path(os.getenv("TEMP", "/tmp")).resolve()
    if root == temp or temp not in root.parents:
        raise ValueError("run directory must be a child of the system temporary directory")
    return root


def _credentials(run_dir: Path) -> dict[str, str]:
    return json.loads(run_dir.joinpath("credentials.json").read_text(encoding="utf-8"))[0]


def _login(base_url: str, record: dict[str, str]) -> str:
    response = requests.post(
        f"{base_url}/api/auth/login",
        json={"username": record["username"], "password": record["password"]},
        timeout=30,
    )
    if response.status_code != 200 or not response.json().get("access_token"):
        raise RuntimeError(f"login failed with HTTP {response.status_code}")
    return str(response.json()["access_token"])


def _task(tasks: dict, task_id: str) -> dict | None:
    return next((item for item in tasks.get("tasks", []) if item.get("task_id") == task_id), None)


def classify_terminal(status: str, retrieval_healthy: bool | None) -> str:
    """Keep HTTP acceptance separate from a retrieval-ready upload result."""
    normalized = status.lower()
    if normalized == "completed":
        return "retrieval_ready" if retrieval_healthy else "completed_not_retrieval_ready"
    if normalized in {"failed", "terminal_failed"}:
        return "worker_terminal_failed"
    return f"terminal_{normalized}"


def classify_exception(stage: str, exc: Exception) -> str:
    """Return a bounded, redacted failure category for a diagnostic request."""
    prefix = "connection_error" if isinstance(exc, requests.RequestException) else "diagnostic_error"
    return f"{prefix}_{stage}"


def _write_result(run_dir: Path, result: dict[str, object]) -> None:
    run_dir.joinpath("upload-diagnostic.json").write_text(
        json.dumps(result, ensure_ascii=True), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    if not args.base_url.startswith("http://127.0.0.1:"):
        raise ValueError("base URL must use a loopback port")
    run_dir = _inside_temp(Path(args.run_dir))
    result: dict[str, object] = {
        "http_status": 0,
        "terminal_status": "",
        "classification": "unknown",
        "duplicate_http_status": 0,
        "duplicate_classification": "not_attempted",
        "error_class": "",
    }
    stage = "credentials"
    try:
        record = _credentials(run_dir)
        stage = "login"
        token = _login(args.base_url.rstrip("/"), record)
        headers = {"Authorization": f"Bearer {token}"}
        fixture = run_dir.joinpath("upload-fixture.txt")
        fixture.write_text(f"isolated upload fixture {time.time_ns()}\n", encoding="utf-8")
        stage = "upload"
        with fixture.open("rb") as handle:
            response = requests.post(
                f"{args.base_url.rstrip('/')}/api/upload",
                params={"kb": record["kb"], "enable_image": "false", "enable_table": "false", "enable_equation": "false"},
                files={"file": ("isolated-upload.txt", handle, "text/plain")},
                headers=headers,
                timeout=30,
            )
        result["http_status"] = response.status_code
        if response.status_code != 200:
            result["classification"] = f"upload_http_{response.status_code}"
        else:
            payload = response.json()
            task_id = str(payload.get("task_id") or "")
            if not task_id:
                result["classification"] = "accepted_without_task_id"
            else:
                stage = "poll"
                deadline = time.monotonic() + args.timeout
                latest = None
                while time.monotonic() < deadline:
                    tasks = requests.get(f"{args.base_url.rstrip('/')}/api/upload/tasks", params={"kb": record["kb"]}, headers=headers, timeout=20).json()
                    latest = _task(tasks, task_id)
                    if latest and str(latest.get("status") or "").lower() in TERMINAL:
                        break
                    time.sleep(2)
                if not latest:
                    result["classification"] = "task_not_observed"
                else:
                    status = str(latest.get("status") or "").lower()
                    result["terminal_status"] = status
                    if status == "completed":
                        stage = "retrieval_health"
                        health = requests.get(f"{args.base_url.rstrip('/')}/api/knowledge/retrieval-health", params={"kb": record["kb"]}, headers=headers, timeout=20)
                        result["classification"] = classify_terminal(status, health.status_code == 200 and bool(health.json().get("healthy")))
                    else:
                        result["classification"] = classify_terminal(status, None)
        stage = "duplicate"
        with fixture.open("rb") as handle:
            duplicate = requests.post(
                f"{args.base_url.rstrip('/')}/api/upload",
                params={"kb": record["kb"]},
                files={"file": ("isolated-upload.txt", handle, "text/plain")},
                headers=headers,
                timeout=30,
            )
        result["duplicate_http_status"] = duplicate.status_code
        result["duplicate_classification"] = "duplicate_confirmed" if duplicate.status_code == 409 else f"duplicate_http_{duplicate.status_code}"
    except Exception as exc:
        result["classification"] = classify_exception(stage, exc)
        result["error_class"] = type(exc).__name__
    finally:
        _write_result(run_dir, result)
    print(f"upload-diagnostic: {result['classification']}")
    return 0 if result["classification"] == "retrieval_ready" and result["duplicate_http_status"] == 409 else 2


if __name__ == "__main__":
    raise SystemExit(main())
