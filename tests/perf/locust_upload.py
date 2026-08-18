"""Upload workload for disposable performance environments only."""
from __future__ import annotations
import json, os, queue
from pathlib import Path
from locust import HttpUser, between, events, task
from locust.exception import StopUser

def load_records():
    records = json.loads(Path(os.environ["RAG_CREDENTIALS_FILE"]).read_text(encoding="utf-8"))
    result = queue.SimpleQueue()
    for record in records:
        if not all(record.get(key) for key in ("username", "password", "kb")):
            raise RuntimeError("each upload credential needs username, password and kb")
        result.put(record)
    return result

RECORDS = load_records()
FIXTURE = Path(__file__).with_name("fixtures").joinpath("sample.txt")

class UploadUser(HttpUser):
    wait_time = between(1, 3)
    def on_start(self):
        try: self.record = RECORDS.get_nowait()
        except queue.Empty as exc: raise StopUser() from exc
        response = self.client.post("/api/auth/login", json={"username": self.record["username"], "password": self.record["password"]})
        if response.status_code != 200: raise StopUser()
        self.token = response.json().get("access_token")
        if not self.token: raise StopUser()
    @task
    def upload(self):
        with FIXTURE.open("rb") as handle:
            response = self.client.post("/api/upload", params={"kb": self.record["kb"]}, files={"file": ("perf-sample.txt", handle, "text/plain")}, headers={"Authorization": f"Bearer {self.token}"}, catch_response=True)
            if response.status_code not in (200, 202): response.failure(f"upload HTTP {response.status_code}")
            else: response.success()
