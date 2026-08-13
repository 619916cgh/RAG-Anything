import json
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_strict_readiness_rejects_missing_postgres_vector_store(monkeypatch):
    from raganything.services import document_quality

    async def no_table(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "raganything.services.pg_embedding_identity.resolve_vector_chunk_table",
        no_table,
    )
    monkeypatch.setattr(
        "raganything.services.pg_state_repo.get_pg_pool",
        lambda: object(),
    )

    result = await document_quality.evaluate_content_readiness(
        "demo", ["chunk-1"], {"chunk-1": {"content": "valid text"}}, require_postgres=True,
    )

    assert result["ready"] is False
    assert result["reason_code"] == "retrieval_store_unavailable"
    assert result["store_status"] == "vector_table_missing"


@pytest.mark.asyncio
async def test_strict_readiness_reports_missing_vectors(monkeypatch):
    from raganything.services import document_quality

    class Pool:
        async def fetch(self, *_args):
            return []

    async def table(*_args, **_kwargs):
        return "VDB_CHUNKS"

    monkeypatch.setattr(
        "raganything.services.pg_embedding_identity.resolve_vector_chunk_table", table,
    )
    monkeypatch.setattr("raganything.services.pg_state_repo.get_pg_pool", lambda: Pool())

    result = await document_quality.evaluate_content_readiness(
        "demo", ["chunk-1"], {"chunk-1": {"content": "valid text"}}, require_postgres=True,
    )

    assert result["ready"] is False
    assert result["reason_code"] == "missing_vectors"


@pytest.mark.asyncio
async def test_retrieval_health_endpoint_returns_only_requested_kb(monkeypatch):
    from raganything.routers import knowledge

    async def statuses(kb):
        assert kb == "allowed"
        return {"allowed-doc": {}, "other-doc": {}}

    async def health(kb, doc_id):
        assert kb == "allowed"
        return {"ready": doc_id == "allowed-doc", "reason_code": "missing_vectors", "expected_count": 2, "text_count": 2, "vector_count": 0}

    monkeypatch.setattr(knowledge, "_load_doc_status_json", statuses)
    monkeypatch.setattr(knowledge, "evaluate_document_retrieval_health", health)

    result = await knowledge.get_retrieval_health(kb="allowed")

    assert result["kb"] == "allowed"
    assert result["documents"] == [{
        "doc_id": "other-doc", "reason_code": "missing_vectors",
        "expected_count": 2, "text_count": 2, "vector_count": 0,
    }]


@pytest.mark.asyncio
async def test_retrieval_repair_reuses_durable_stage_job(monkeypatch):
    from raganything.routers import knowledge

    async def statuses(_kb):
        return {"doc-full": {}}

    async def health(_kb, _doc):
        return {"ready": False, "reason_code": "missing_vectors"}

    async def enqueue(kb, doc_id, *, reason_code):
        return {"id": 9, "kb_name": kb, "doc_id": doc_id, "stage": "retrieval_readiness", "last_error": reason_code}

    monkeypatch.setattr(knowledge, "_load_doc_status_json", statuses)
    monkeypatch.setattr(knowledge, "evaluate_document_retrieval_health", health)
    monkeypatch.setattr("raganything.services.document_repair.enqueue_retrieval_repair", enqueue)

    result = await knowledge.repair_document_retrieval("doc", kb="allowed")

    assert result["status"] == "queued"
    assert result["reason_code"] == "missing_vectors"
    assert result["repair_job"]["stage"] == "retrieval_readiness"


@pytest.mark.asyncio
async def test_retrieval_repair_rejects_ambiguous_document_prefix(monkeypatch):
    from fastapi import HTTPException
    from raganything.routers import knowledge

    async def statuses(_kb):
        return {"doc-a1": {}, "doc-a2": {}}

    monkeypatch.setattr(knowledge, "_load_doc_status_json", statuses)

    with pytest.raises(HTTPException) as exc:
        await knowledge.repair_document_retrieval("doc-a", kb="allowed")

    assert exc.value.status_code == 409


def test_release_candidate_inventory_is_read_only(tmp_path, monkeypatch):
    from scripts import release_candidate_inventory as inventory

    (tmp_path / "openspec" / "changes" / "change-a").mkdir(parents=True)
    calls = []

    def fake_git(_root, *args):
        calls.append(args)
        return " M PROJECT_SUMMARY.md\n?? openspec/changes/change-a/tasks.md\n?? src/new.py\n"

    monkeypatch.setattr(inventory, "_git", fake_git)
    result = inventory.inventory(tmp_path)

    assert calls == [("status", "--porcelain=v1", "--untracked-files=all")]
    assert result["summary"] == {
        "owned": 1, "shared": 1, "unowned": 1, "generated-candidate": 0,
    }


def test_acceptance_guard_writes_non_releasable_evidence(tmp_path):
    from scripts import run_isolated_release_acceptance as acceptance

    evidence = tmp_path / "evidence.json"
    exit_code = acceptance.main([
        "--target-id", "production",
        "--working-dir", str(tmp_path),
        "--health-url", "http://127.0.0.1:1",
        "--cleanup-command", "cleanup-test",
        "--evidence", str(evidence),
    ])

    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert payload["release_recommendation"] == "not-releasable"
    assert payload["failure_class"] == "target-guard"


def test_acceptance_stops_after_required_stage_failure(tmp_path, monkeypatch):
    from scripts import run_isolated_release_acceptance as acceptance

    repo_root = tmp_path / "repo"
    (repo_root / "migrations").mkdir(parents=True)
    (repo_root / "migrations" / "migration_manifest.json").write_text("{}", encoding="utf-8")
    working_dir = tmp_path / "staging-target"
    working_dir.mkdir()
    seen = []

    def stage(name, _command, _cwd):
        seen.append(name)
        return {
            "name": name, "outcome": "failed", "duration_seconds": 0,
            "failure_class": "exit-1", "detail": "expected",
        }

    monkeypatch.setattr(acceptance, "_stage_result", stage)
    result = acceptance.run_acceptance(type("Args", (), {
        "non_production": True,
        "target_id": "staging-test",
        "working_dir": working_dir,
        "repo_root": repo_root,
        "stage_command": [
            "migration-fresh=run-migration", "migration-upgrade=run-upgrade",
            "migration-repeat=run-repeat", "migration-failure=run-failure",
            "roles=run-roles", "worker=run-worker",
        ],
        "cleanup_command": "cleanup-test",
        "health_url": "http://127.0.0.1:1",
    })())

    assert seen == ["migration-fresh", "cleanup"]
    assert [stage["outcome"] for stage in result["stages"]] == ["failed", "skipped", "skipped", "skipped", "skipped", "skipped", "skipped", "failed"]
    assert result["release_recommendation"] == "not-releasable"


def test_acceptance_command_start_failure_is_sanitized(tmp_path):
    from scripts import run_isolated_release_acceptance as acceptance

    result = acceptance._stage_result("worker", ["missing-command-for-acceptance"], tmp_path)

    assert result["outcome"] == "failed"
    assert result["failure_class"] == "command-unavailable"


def test_acceptance_evidence_redacts_secret_and_absolute_path():
    from scripts import run_isolated_release_acceptance as acceptance

    detail = acceptance.sanitize_evidence_detail(
        "password=super-secret failed at C:\\acceptance\\worker\\output.log"
    )

    assert "super-secret" not in detail
    assert "C:\\acceptance" not in detail
    assert "<path>" in detail


@pytest.mark.asyncio
async def test_tagging_failure_keeps_retrieval_ready_upload_completed(monkeypatch):
    from raganything.services import kb_service, state_service, ws_service

    calls = []

    async def update(*args, **kwargs):
        calls.append(("upload", args, kwargs))
        return {"id": 1}

    async def complete(*args, **kwargs):
        calls.append(("complete", args, kwargs))

    async def event(*args, **kwargs):
        calls.append(("event", args, kwargs))

    async def broadcast(*args, **kwargs):
        calls.append(("broadcast", args, kwargs))

    monkeypatch.setattr(kb_service, "pg_update_upload_status_by_task_id", update)
    monkeypatch.setattr(state_service, "complete_task", complete)
    monkeypatch.setattr(ws_service, "add_event", event)
    monkeypatch.setattr(ws_service, "ws_broadcast", broadcast)

    await kb_service._finalize_tagging_failure(
        "task-1", "demo", "source.pdf", 7, "doc-1", "tag service failed", "hash-1",
        claim_owner="owner", claim_generation=2,
    )

    upload = calls[0]
    assert upload[1][1] == "completed"
    assert upload[2]["outcome"] == "degraded"
    assert calls[1] == ("complete", ("task-1",), {"outcome": "degraded", "warning": "Document retrieval completed, but automatic tagging needs repair"})


@pytest.mark.asyncio
async def test_retrieval_not_ready_schedules_fenced_retry_without_completion(monkeypatch, tmp_path):
    from raganything.services import kb_service, state_service, ws_service
    import raganything.services.upload_retry as upload_retry
    import raganything.services.user_settings as user_settings

    file_path = tmp_path / "sample.txt"
    file_path.write_text("sample", encoding="utf-8")
    calls = []

    class EmptyStream:
        async def readline(self):
            return b""

    class SuccessfulWorker:
        returncode = 0
        stdout = EmptyStream()
        stderr = EmptyStream()

        async def wait(self):
            return 0

    async def no_op(*_args, **_kwargs):
        return None

    async def settings(_task_id):
        return {
            "settings": {"ingestion": {"chunking_strategy": "fixed_size"}},
            "revision": 1,
            "fingerprint": "test",
        }

    def identity(_snapshot):
        return {"identity_hash": "test"}

    async def update(*_args, **_kwargs):
        return {"id": 1}

    async def resolve(*_args, **_kwargs):
        return "doc-1"

    async def unhealthy(*_args, **_kwargs):
        return {
            "ready": False, "reason_code": "missing_vectors",
            "expected_count": 2, "text_count": 2, "vector_count": 0,
        }

    async def schedule(**kwargs):
        calls.append(kwargs)
        return {"id": 9}

    async def complete(*_args, **_kwargs):
        raise AssertionError("retrieval-not-ready task must not complete")

    async def create_worker(*_args, **_kwargs):
        return SuccessfulWorker()

    monkeypatch.setattr(kb_service, "_upload_is_cancelling", lambda *_args: no_op())
    monkeypatch.setattr(kb_service, "_pg_storage_ready", lambda: True)
    monkeypatch.setattr(kb_service, "pg_update_upload_status_by_task_id", update)
    monkeypatch.setattr(kb_service, "_resolve_uploaded_document_id", resolve)
    monkeypatch.setattr(kb_service, "_register_processing_file", lambda *_args: None)
    monkeypatch.setattr(kb_service, "_unregister_processing_file", lambda *_args: None)
    monkeypatch.setattr(kb_service, "_kb_worker_procs", {})
    monkeypatch.setattr(kb_service, "_get_ocr_worker_slot", lambda: __import__("asyncio").Semaphore(1))
    monkeypatch.setattr(kb_service.asyncio, "create_subprocess_exec", create_worker)
    monkeypatch.setattr(user_settings, "get_task_settings_snapshot", settings)
    monkeypatch.setattr(user_settings, "load_task_text_embedding_identity", identity)
    monkeypatch.setattr(upload_retry, "schedule_upload_retry", schedule)
    monkeypatch.setattr(state_service, "upsert_task_state", no_op)
    monkeypatch.setattr(state_service, "update_task_progress", no_op)
    monkeypatch.setattr(state_service, "complete_task", complete)
    monkeypatch.setattr(state_service, "processing_tasks", {})
    monkeypatch.setattr(ws_service, "emit_progress", no_op)
    monkeypatch.setattr(ws_service, "add_event", no_op)
    monkeypatch.setattr(ws_service, "ws_broadcast", no_op)
    monkeypatch.setattr(
        "raganything.services.document_quality.evaluate_document_retrieval_health",
        unhealthy,
    )

    await kb_service._process_uploaded_file(
        "task-1", str(file_path), "sample.txt", kb_name="demo", user_id=7,
        claim_owner="owner-1", claim_generation=3,
    )

    assert len(calls) == 1
    retry = calls[0]
    assert retry["stage"] == "retrieval_readiness"
    assert retry["root_type"] == "missing_vectors"
    assert retry["error"] == "retrieval_not_ready:missing_vectors expected=2 text=2 vectors=0"
    assert retry["claim_owner"] == "owner-1"
    assert retry["claim_generation"] == 3


@pytest.mark.asyncio
async def test_stale_retrieval_readiness_retry_does_not_fall_through_to_failure(monkeypatch, tmp_path):
    from raganything.services import kb_service, state_service, ws_service
    import raganything.services.upload_retry as upload_retry
    import raganything.services.user_settings as user_settings

    file_path = tmp_path / "sample.txt"
    file_path.write_text("sample", encoding="utf-8")
    finalized = []

    class EmptyStream:
        async def readline(self):
            return b""

    class SuccessfulWorker:
        returncode = 0
        stdout = EmptyStream()
        stderr = EmptyStream()

        async def wait(self):
            return 0

    async def no_op(*_args, **_kwargs):
        return None

    async def settings(_task_id):
        return {"settings": {"ingestion": {"chunking_strategy": "fixed_size"}}}

    async def resolve(*_args, **_kwargs):
        return "doc-1"

    async def unhealthy(*_args, **_kwargs):
        return {"ready": False, "reason_code": "missing_vectors"}

    async def stale_schedule(**_kwargs):
        return None

    async def update(*_args, **_kwargs):
        return {"id": 1}

    async def unexpected_finalizer(*_args, **_kwargs):
        finalized.append(True)

    async def create_worker(*_args, **_kwargs):
        return SuccessfulWorker()

    monkeypatch.setattr(kb_service, "_upload_is_cancelling", lambda *_args: no_op())
    monkeypatch.setattr(kb_service, "_pg_storage_ready", lambda: True)
    monkeypatch.setattr(kb_service, "pg_update_upload_status_by_task_id", update)
    monkeypatch.setattr(kb_service, "_resolve_uploaded_document_id", resolve)
    monkeypatch.setattr(kb_service, "_register_processing_file", lambda *_args: None)
    monkeypatch.setattr(kb_service, "_unregister_processing_file", lambda *_args: None)
    monkeypatch.setattr(kb_service, "_kb_worker_procs", {})
    monkeypatch.setattr(kb_service, "_get_ocr_worker_slot", lambda: __import__("asyncio").Semaphore(1))
    monkeypatch.setattr(kb_service.asyncio, "create_subprocess_exec", create_worker)
    monkeypatch.setattr(user_settings, "get_task_settings_snapshot", settings)
    monkeypatch.setattr(user_settings, "load_task_text_embedding_identity", lambda _snapshot: {})
    monkeypatch.setattr(upload_retry, "schedule_upload_retry", stale_schedule)
    monkeypatch.setattr(kb_service, "_finalize_failed_upload", unexpected_finalizer)
    monkeypatch.setattr(state_service, "upsert_task_state", no_op)
    monkeypatch.setattr(state_service, "update_task_progress", no_op)
    monkeypatch.setattr(state_service, "processing_tasks", {})
    monkeypatch.setattr(ws_service, "emit_progress", no_op)
    monkeypatch.setattr(ws_service, "add_event", no_op)
    monkeypatch.setattr(ws_service, "ws_broadcast", no_op)
    monkeypatch.setattr(
        "raganything.services.document_quality.evaluate_document_retrieval_health",
        unhealthy,
    )

    await kb_service._process_uploaded_file(
        "task-1", str(file_path), "sample.txt", kb_name="demo", user_id=7,
        claim_owner="stale-owner", claim_generation=1,
    )

    assert finalized == []
