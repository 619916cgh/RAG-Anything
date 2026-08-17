from datetime import datetime, timezone
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_execute_workflow_returns_timezone_aware_timestamps(monkeypatch, tmp_path):
    from raganything import workflow_executor

    class OutputExecutor:
        async def execute(self, config, inputs, ctx):
            return {"formatted": "done"}

    monkeypatch.setattr(workflow_executor, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(workflow_executor, "EXECUTORS", {"output": OutputExecutor()})
    monkeypatch.setattr(
        "raganything.services.pg_state_repo.get_pg_pool",
        lambda: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )

    record = await workflow_executor.execute_workflow({
        "id": "workflow-1",
        "name": "Timezone contract",
        "nodes": [{"id": "output", "data": {"nodeType": "output"}}],
        "edges": [],
    })

    for timestamp in (record["started_at"], record["completed_at"], record["node_results"][0]["timestamp"]):
        parsed = datetime.fromisoformat(timestamp)
        assert parsed.utcoffset() == timezone.utc.utcoffset(parsed)


def test_user_visible_timestamp_producers_do_not_emit_naive_iso_values():
    root = Path(__file__).resolve().parents[1]
    source_paths = [root / "server.py", *(root / "raganything").rglob("*.py")]
    for path in source_paths:
        source = path.read_text(encoding="utf-8-sig")
        assert "datetime.now().isoformat()" not in source
