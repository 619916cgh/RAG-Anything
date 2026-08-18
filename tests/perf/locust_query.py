"""SSE query load test.  Runtime credentials and reports must be outside the repo."""
from __future__ import annotations

import json
import os
import queue
import time
from pathlib import Path

import requests
from locust import HttpUser, between, events, task
from locust.exception import StopUser


def _runtime_dir() -> Path:
    root = Path(os.environ["RAG_PERF_RUN_DIR"]).resolve()
    temp = Path(os.getenv("TEMP", "/tmp")).resolve()
    if temp not in root.parents:
        raise RuntimeError("RAG_PERF_RUN_DIR must be beneath the system temp directory")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _credentials() -> queue.SimpleQueue:
    path = Path(os.environ["RAG_CREDENTIALS_FILE"])
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list) or not records:
        raise RuntimeError("credential file must contain a non-empty list")
    names = [record.get("username") for record in records]
    if any(not name for name in names) or len(set(names)) != len(names):
        raise RuntimeError("credentials must have unique non-empty usernames")
    result: queue.SimpleQueue = queue.SimpleQueue()
    for record in records:
        if not record.get("password") or not record.get("agent_id"):
            raise RuntimeError("credential record is incomplete")
        result.put(record)
    return result


_CREDENTIALS = _credentials()


def _events(response):
    event_name = "message"
    data: list[str] = []
    for line in response.iter_lines(chunk_size=1024, decode_unicode=True):
        if not line:
            if data:
                raw = "\n".join(data)
                if raw == "[DONE]":
                    yield "done", {}
                else:
                    try:
                        yield event_name, json.loads(raw)
                    except json.JSONDecodeError:
                        yield "malformed", {}
            event_name, data = "message", []
        elif line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())


class QueryUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        try:
            self.credential = _CREDENTIALS.get_nowait()
        except queue.Empty as exc:
            raise StopUser() from exc
        login = self.client.post("/api/auth/login", json={"username": self.credential["username"], "password": self.credential["password"]})
        if login.status_code != 200 or not login.json().get("access_token"):
            raise StopUser()
        self.token = login.json()["access_token"]

    @task
    def query(self):
        started = time.perf_counter()
        status = 0
        tokens = 0
        first = None
        error = None
        try:
            with requests.post(f"{self.host}/api/agents/{self.credential['agent_id']}/query/stream", json={"query": "性能测试查询", "retrieval_only": True}, headers={"Authorization": f"Bearer {self.token}", "Accept": "text/event-stream"}, stream=True, timeout=int(os.getenv("RAG_SSE_TIMEOUT", "120"))) as response:
                status = response.status_code
                if status == 200:
                    completed = False
                    for kind, payload in _events(response):
                        if kind == "token":
                            tokens += 1
                            first = first or time.perf_counter()
                        elif kind == "done":
                            completed = True
                            break
                        elif kind in {"error", "malformed"}:
                            error = kind
                            break
                    if not completed and error is None:
                        error = "eof_without_done"
                else:
                    error = f"http_{status}"
        except requests.RequestException as exc:
            error = type(exc).__name__
        elapsed = time.perf_counter() - started
        events.request.fire(request_type="SSE", name="/api/agents/{agent_id}/query/stream", response_time=elapsed * 1000, response_length=tokens, exception=Exception(error) if error else None, context={"ttft_ms": (first - started) * 1000 if first else None, "http_status": status})


@events.test_stop.add_listener
def write_marker(environment, **_kwargs):
    _runtime_dir().joinpath("query-locust-complete.json").write_text(json.dumps({"requests": environment.stats.total.num_requests, "failures": environment.stats.total.num_failures}), encoding="utf-8")
