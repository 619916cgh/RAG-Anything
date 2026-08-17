from __future__ import annotations

import pytest


async def _async_value(value):
    return value


@pytest.mark.asyncio
async def test_inventory_counts_retrievable_content_and_tag_work_separately(monkeypatch):
    from raganything.services import knowledge_inventory

    records = [
        {
            "kind": "document", "full_id": "video-doc", "display_file": "lesson.mp4",
            "info": {"status": "processed", "chunks_count": 11, "metadata": {"content_ready": True}},
        },
        {
            "kind": "document", "full_id": "pdf-doc", "display_file": "manual.pdf",
            "info": {"status": "completed", "chunks_count": 2, "metadata": {"content_ready": True}},
        },
        {
            "kind": "runtime", "full_id": "task-upload", "display_file": "waiting.docx",
            "runtime_task": {"status": "processing"},
        },
        {
            "kind": "document", "full_id": "failed-doc", "display_file": "broken.pptx",
            "info": {"status": "failed", "chunks_count": 0, "metadata": {}},
        },
    ]

    monkeypatch.setattr(knowledge_inventory, "_merged_runtime_tasks", lambda _kb: _async_value([]))
    monkeypatch.setattr(knowledge_inventory, "load_document_summary_records", lambda *_args, **_kwargs: _async_value(records))
    monkeypatch.setattr(
        knowledge_inventory,
        "get_document_tag_health",
        lambda *_args: _async_value({
            "video-doc": {"tag_status": "running"},
            "pdf-doc": {"tag_status": "failed"},
        }),
    )

    inventory = await knowledge_inventory.get_knowledge_inventory("demo")

    assert inventory["all"] == {
        "total": 4,
        "retrievable": 2,
        "content_processing": 1,
        "tag_processing": 1,
        "failed": 1,
    }
    assert inventory["types"]["video"]["retrievable"] == 1
    assert inventory["types"]["video"]["tag_processing"] == 1
    assert inventory["types"]["pdf"]["retrievable"] == 1
    assert inventory["types"]["presentation"]["failed"] == 1
    assert "file" not in inventory and "documents" not in inventory


@pytest.mark.asyncio
async def test_inventory_keeps_graph_degraded_content_retrievable_and_survives_tag_read_failure(monkeypatch):
    from raganything.services import knowledge_inventory

    records = [{
        "kind": "document", "full_id": "degraded", "display_file": "engine.mp4",
        "info": {"status": "failed", "chunks_count": 3, "metadata": {"content_ready": True}},
    }]
    monkeypatch.setattr(knowledge_inventory, "_merged_runtime_tasks", lambda _kb: _async_value([]))
    monkeypatch.setattr(knowledge_inventory, "load_document_summary_records", lambda *_args, **_kwargs: _async_value(records))

    async def unavailable(*_args):
        raise ConnectionError("tag service unavailable")

    monkeypatch.setattr(knowledge_inventory, "get_document_tag_health", unavailable)
    inventory = await knowledge_inventory.get_knowledge_inventory("demo")

    assert inventory["all"] == {
        "total": 1,
        "retrievable": 1,
        "content_processing": 0,
        "tag_processing": 0,
        "failed": 0,
    }


@pytest.mark.asyncio
async def test_inventory_includes_failed_durable_upload_without_document_status(monkeypatch):
    from raganything.services import knowledge_inventory

    async def uploads(**kwargs):
        assert kwargs["exclude_statuses"] == ["completed", "processed", "deleted"]
        return ([{
            "id": "upload-1", "task_id": "task-failed", "filename": "broken.mp4",
            "status": "failed", "created_at": "2026-08-17T00:00:00+00:00",
        }], 1)

    monkeypatch.setattr(knowledge_inventory, "pg_list_uploads", uploads)
    monkeypatch.setattr(knowledge_inventory, "get_all_tasks", lambda **_kwargs: _async_value([]))
    monkeypatch.setattr(knowledge_inventory, "processing_tasks", {})
    tasks = await knowledge_inventory._merged_runtime_tasks("demo")

    assert tasks == [{
        "id": "task-failed", "file": "broken.mp4", "kb": "demo", "status": "failed",
        "error_message": "", "started_at": "2026-08-17T00:00:00+00:00", "updated_at": "",
    }]


def test_inventory_route_has_read_and_kb_scope_dependencies():
    from raganything.routers import knowledge

    route = next(route for route in knowledge.router.routes if getattr(route, "path", None) == "/knowledge/inventory")
    dependency_names = {
        getattr(getattr(dependency, "call", None), "__name__", "")
        for dependency in route.dependant.dependencies
    }
    assert "verify_kb_access" in dependency_names
    assert "require_kb_read" in dependency_names
