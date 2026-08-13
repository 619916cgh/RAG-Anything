import pytest


@pytest.mark.asyncio
async def test_get_all_tasks_filters_and_bounds_local_runtime_tasks(monkeypatch):
    from raganything.services import state_service

    monkeypatch.setattr(state_service, "_task_pg_ready", lambda: False)
    monkeypatch.setattr(state_service, "processing_tasks", {
        "other": {"id": "other", "kb": "other-kb", "started_at": "2026-08-12T03:00:00+00:00"},
        "first": {"id": "first", "kb": "demo", "started_at": "2026-08-12T02:00:00+00:00"},
        "second": {"id": "second", "kb": "demo", "started_at": "2026-08-12T01:00:00+00:00"},
    })

    tasks = await state_service.get_all_tasks(kb_name="demo", limit=1)

    assert [task["id"] for task in tasks] == ["first"]
