import pytest


def test_summary_route_declares_object_level_read_dependency():
    from raganything.routers import knowledge

    route = next(
        route for route in knowledge.router.routes
        if getattr(route, "path", None) == "/knowledge/document-summaries"
        and "GET" in getattr(route, "methods", set())
    )
    dependency_names = [
        getattr(getattr(dep, "call", None), "__name__", "")
        for dep in route.dependant.dependencies
    ]
    assert "verify_kb_access" in dependency_names


@pytest.mark.asyncio
async def test_json_summary_page_deduplicates_searches_and_slices(monkeypatch):
    from raganything.services import kb_service

    summaries = {
        f"doc-{index}": {
            "file_path": f"{index:08x}_Manual {index:03}.pdf",
            "status": "processed",
            "updated_at": f"2026-08-11T00:{index % 60:02}:00+00:00",
        }
        for index in range(23)
    }
    summaries["older-copy"] = {
        "file_path": "aaaaaaaa_Manual 022.pdf",
        "status": "processed",
        "updated_at": "2026-08-01T00:00:00+00:00",
    }
    summaries["missing-a"] = {"file_path": "", "status": "processed"}
    summaries["missing-b"] = {"file_path": None, "status": "processed"}

    monkeypatch.setattr(kb_service, "_pg_storage_ready", lambda: False)

    async def load_summaries(_kb):
        return summaries

    monkeypatch.setattr(kb_service, "_load_doc_status_summaries", load_summaries)
    result = await kb_service.load_document_summary_page(
        "demo", page=2, page_size=10, query="manual", runtime_tasks=[],
    )

    assert result["source"] == "json-fallback"
    assert result["total"] == 23
    assert result["total_pages"] == 3
    assert len(result["documents"]) == 10
    assert all(record["display_file"].startswith("Manual") for record in result["documents"])
    assert {record["full_id"] for record in result["documents"]}.isdisjoint({"older-copy"})

    missing = await kb_service.load_document_summary_page(
        "demo", page=1, page_size=10, query="", runtime_tasks=[],
    )
    assert missing["total"] == 25
    assert {"missing-a", "missing-b"}.issubset({
        record["full_id"] for record in missing["documents"]
    } | {record["full_id"] for record in await _all_pages(kb_service, summaries)})


async def _all_pages(kb_service, summaries):
    all_records = []
    for page in range(1, 4):
        result = await kb_service.load_document_summary_page(
            "demo", page=page, page_size=10, query="", runtime_tasks=[],
        )
        all_records.extend(result["documents"])
    return all_records


@pytest.mark.asyncio
async def test_summary_route_enriches_only_current_page_documents(monkeypatch):
    from raganything.routers import knowledge

    async def cleanup():
        return None

    async def active_tasks():
        return []

    async def load_page(*_args, **_kwargs):
        return {
            "documents": [
                {
                    "kind": "document",
                    "full_id": "doc-current",
                    "info": {
                        "file_path": "manual.pdf",
                        "status": "processed",
                        "chunks_count": 2,
                        "content_length": 20,
                        "metadata": {},
                    },
                },
                {
                    "kind": "runtime",
                    "full_id": "task-current",
                    "runtime_task": {
                        "id": "task-current",
                        "file": "uploading.pdf",
                        "status": "processing",
                    },
                },
            ],
            "total": 1000,
            "page": 2,
            "page_size": 10,
            "total_pages": 100,
            "has_next": True,
            "has_prev": True,
            "q": "manual",
        }

    observed = []

    async def tag_health(_kb, doc_ids):
        observed.extend(doc_ids)
        return {"doc-current": {"tag_status": "unmanaged", "tag_raw_status": "missing"}}

    async def upload_statuses(_kb, task_ids):
        assert set(task_ids) == {"task-current"}
        return {"task-current": "processing"}

    monkeypatch.setattr(knowledge, "cleanup_completed_tasks", cleanup)
    monkeypatch.setattr(knowledge, "get_all_tasks", active_tasks)
    monkeypatch.setattr(knowledge, "processing_tasks", {})
    monkeypatch.setattr(knowledge, "load_document_summary_page", load_page)
    monkeypatch.setattr(knowledge, "_document_tag_health_contract", tag_health)
    monkeypatch.setattr(knowledge, "pg_get_upload_statuses_by_task_ids", upload_statuses)

    result = await knowledge.list_document_summaries(
        page=2,
        page_size=10,
        q="manual",
        kb="demo",
        current_user={"id": 7},
    )

    assert observed == ["doc-current"]
    assert result["total"] == 1000
    assert result["page"] == 2
    assert result["documents"][0]["full_id"] == "doc-current"
    assert result["documents"][1]["full_id"] == "task-current"


@pytest.mark.asyncio
async def test_summary_route_preserves_same_name_runtime_phase_overlay(monkeypatch):
    from raganything.routers import knowledge

    async def noop():
        return None

    async def load_page(*_args, **_kwargs):
        return {
            "documents": [{
                "kind": "document",
                "full_id": "persisted-doc",
                "info": {
                    "file_path": "00000000_manual.pdf",
                    "status": "processed",
                    "chunks_count": 1,
                    "content_length": 10,
                    "metadata": {},
                },
            }],
            "total": 1,
            "page": 1,
            "page_size": 10,
            "total_pages": 1,
            "has_next": False,
            "has_prev": False,
            "q": "",
        }

    monkeypatch.setattr(knowledge, "cleanup_completed_tasks", noop)
    monkeypatch.setattr(knowledge, "get_all_tasks", lambda: _async_tasks([]))
    monkeypatch.setattr(knowledge, "processing_tasks", {
        "task-manual": {
            "id": "task-manual",
            "kb": "demo",
            "file": "manual.pdf",
            "status": "processing",
            "phase": "embedding",
        },
    })
    monkeypatch.setattr(knowledge, "load_document_summary_page", load_page)
    monkeypatch.setattr(knowledge, "_document_tag_health_contract", lambda *_: _async_value({}))
    monkeypatch.setattr(knowledge, "pg_get_upload_statuses_by_task_ids", lambda *_: _async_value({}))

    result = await knowledge.list_document_summaries(
        page=1, page_size=10, q="", kb="demo", current_user={"id": 7},
    )

    row = result["documents"][0]
    assert row["phase"] == "embedding"
    assert row["upload_task_id"] == "task-manual"


async def _async_value(value):
    return value


async def _async_tasks(value):
    return value
