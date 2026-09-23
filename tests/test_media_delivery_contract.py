from pathlib import Path
import hashlib

import pytest

from raganything.services import media_delivery_contract
from raganything.services.media_delivery_contract import (
    audit_media_delivery_v2,
    mark_media_delivery_v2,
)
from raganything.services.provenance import CitationProvenanceError


class Pool:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        return self.results.pop(0)


def _catalog():
    return [{
        "media_id": "image-1",
        "kb": "kb-a",
        "document_id": "doc-1",
        "chunk_id": "chunk-1",
        "status": "persisted",
    }]


@pytest.mark.asyncio
async def test_image_contract_requires_matching_catalog_provenance():
    provenance = [{
        "document_id": "doc-1",
        "chunk_id": "chunk-1",
        "source_sha256": "a" * 64,
        "modality": "image",
        "media_id": "image-1",
    }]
    pool = Pool(provenance)

    await audit_media_delivery_v2(
        kb_name="kb-a",
        document_id="doc-1",
        source_sha256="a" * 64,
        chunk_ids=["chunk-1"],
        metadata={
            "odl_media_catalog": _catalog(),
            "image_media_incomplete": False,
            "image_media_counts": {
                "eligible_elements": 1,
                "valid_manifest_media": 1,
                "persisted_image_chunks": 1,
                "catalog_media": 1,
            },
        },
        require_video=False,
        pool=pool,
    )


@pytest.mark.asyncio
async def test_image_contract_rejects_catalog_without_matching_provenance():
    pool = Pool([{
        "document_id": "doc-1",
        "chunk_id": "chunk-1",
        "source_sha256": "a" * 64,
        "modality": "image",
        "media_id": "other-image",
    }])

    with pytest.raises(CitationProvenanceError):
        await audit_media_delivery_v2(
            kb_name="kb-a",
            document_id="doc-1",
            source_sha256="a" * 64,
            chunk_ids=["chunk-1"],
            metadata={
                "odl_media_catalog": _catalog(),
                "image_media_incomplete": False,
                "image_media_counts": {
                    "eligible_elements": 1,
                    "valid_manifest_media": 1,
                    "persisted_image_chunks": 1,
                    "catalog_media": 1,
                },
            },
            require_video=False,
            pool=pool,
        )


@pytest.mark.asyncio
async def test_video_contract_requires_asset_segment_and_exact_provenance(
    tmp_path, monkeypatch,
):
    import hashlib

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    video = uploads / "clip.mp4"
    video.write_bytes(b"video")
    source_hash = hashlib.sha256(b"video").hexdigest()
    monkeypatch.chdir(tmp_path)
    pool = Pool(
        [{
            "document_id": "doc-1",
            "chunk_id": "chunk-1",
            "source_sha256": source_hash,
            "modality": "video",
            "media_id": "video-1",
        }],
        [{
            "media_id": "video-1",
            "document_id": "doc-1",
            "source_sha256": source_hash,
            "server_path": str(video.resolve()),
            "status": "ready",
        }],
        [{
            "segment_id": "segment-1",
            "media_id": "video-1",
            "chunk_id": "chunk-1",
            "start_ms": 0,
            "end_ms": 1000,
            "status": "ready",
            "document_name": "clip.mp4",
            "source_sha256": source_hash,
            "segment_source_sha256": source_hash,
            "provenance_media_id": "video-1",
            "provenance_segment_id": "segment-1",
            "provenance_start_ms": 0,
            "provenance_end_ms": 1000,
            "locator_status": "exact",
        }],
    )

    await audit_media_delivery_v2(
        kb_name="kb-a",
        document_id="doc-1",
        source_sha256=source_hash,
        chunk_ids=["chunk-1"],
        metadata={},
        require_video=True,
        pool=pool,
    )


@pytest.mark.asyncio
async def test_video_contract_rejects_missing_exact_provenance(tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    video = uploads / "clip.mp4"
    video.write_bytes(b"video")
    monkeypatch.chdir(tmp_path)
    pool = Pool(
        [{
            "document_id": "doc-1",
            "chunk_id": "chunk-1",
            "source_sha256": "b" * 64,
            "modality": "video",
            "media_id": "video-1",
        }],
        [{
            "media_id": "video-1",
            "document_id": "doc-1",
            "source_sha256": "b" * 64,
            "server_path": str(video.resolve()),
            "status": "ready",
        }],
        [{
            "segment_id": "segment-1",
            "media_id": "video-1",
            "chunk_id": "chunk-1",
            "start_ms": 0,
            "end_ms": 1000,
            "status": "ready",
            "document_name": None,
            "source_sha256": None,
            "segment_source_sha256": "b" * 64,
            "provenance_media_id": None,
            "provenance_segment_id": None,
            "provenance_start_ms": None,
            "provenance_end_ms": None,
            "locator_status": None,
        }],
    )

    with pytest.raises(CitationProvenanceError):
        await audit_media_delivery_v2(
            kb_name="kb-a",
            document_id="doc-1",
            source_sha256="b" * 64,
            chunk_ids=["chunk-1"],
            metadata={},
            require_video=True,
            pool=pool,
        )


def test_mark_media_delivery_v2_preserves_existing_metadata():
    assert mark_media_delivery_v2({"task_id": "task-1"}) == {
        "task_id": "task-1",
        "media_delivery_version": 2,
    }


class _AsyncContext:
    def __init__(self, value, events, label):
        self.value = value
        self.events = events
        self.label = label

    async def __aenter__(self):
        self.events.append(f"{self.label}-enter")
        return self.value

    async def __aexit__(self, exc_type, _exc, _tb):
        self.events.append(
            f"{self.label}-rollback" if exc_type else f"{self.label}-commit"
        )


class _WorkerConnection:
    def __init__(self, rows, events, update_result="UPDATE 1"):
        self.rows = rows
        self.events = events
        self.update_result = update_result
        self.fetch_call = None
        self.execute_call = None

    def transaction(self):
        return _AsyncContext(self, self.events, "transaction")

    async def fetch(self, sql, *args):
        self.fetch_call = (sql, args)
        self.events.append("status-read")
        return self.rows

    async def execute(self, sql, *args):
        self.execute_call = (sql, args)
        self.events.append("marker-write")
        return self.update_result


class _WorkerPool:
    def __init__(self, connection, events):
        self.connection = connection
        self.events = events

    def acquire(self):
        return _AsyncContext(self.connection, self.events, "connection")


@pytest.mark.asyncio
async def test_worker_commits_media_contract_in_one_pg_transaction(monkeypatch):
    from process_worker import _commit_media_delivery_v2
    from raganything.services import media_delivery_contract, pg_state_repo

    events = []
    connection = _WorkerConnection([{
        "id": "doc-1",
        "status": "processed",
        "chunks_list": ["chunk-1"],
        "metadata": {"task_id": "task-1", "preserved": True},
        "track_id": "task-1",
    }], events)
    pool = _WorkerPool(connection, events)

    async def audit(**kwargs):
        events.append("audit")
        assert kwargs["pool"] is connection
        assert kwargs["document_id"] == "doc-1"
        assert kwargs["chunk_ids"] == ["chunk-1"]
        assert kwargs["metadata"]["preserved"] is True

    monkeypatch.setattr(pg_state_repo, "get_pg_pool", lambda: pool)
    monkeypatch.setattr(media_delivery_contract, "audit_media_delivery_v2", audit)

    await _commit_media_delivery_v2(
        kb_name="kb-a", task_id="task-1",
        source_sha256="a" * 64, require_video=True,
    )

    read_sql, read_args = connection.fetch_call
    assert "workspace=$1 AND track_id=$2 FOR UPDATE" in read_sql
    assert read_args == ("./rag_storage_kb-a", "task-1")
    update_sql, update_args = connection.execute_call
    assert "jsonb_set" in update_sql
    assert "media_delivery_version" in update_sql
    assert update_args == ("./rag_storage_kb-a", "doc-1", "task-1")
    assert events == [
        "connection-enter", "transaction-enter", "status-read", "audit",
        "marker-write", "transaction-commit", "connection-commit",
    ]


@pytest.mark.asyncio
async def test_worker_accepts_json_encoded_pg_status_fields(monkeypatch):
    from process_worker import _commit_media_delivery_v2
    from raganything.services import media_delivery_contract, pg_state_repo

    events = []
    connection = _WorkerConnection([{
        "id": "doc-1", "status": "processed",
        "chunks_list": '["chunk-1"]',
        "metadata": '{"preserved":true}', "track_id": "task-1",
    }], events)

    async def audit(**kwargs):
        assert kwargs["chunk_ids"] == ["chunk-1"]
        assert kwargs["metadata"] == {"preserved": True}

    monkeypatch.setattr(
        pg_state_repo, "get_pg_pool",
        lambda: _WorkerPool(connection, events),
    )
    monkeypatch.setattr(media_delivery_contract, "audit_media_delivery_v2", audit)

    await _commit_media_delivery_v2(
        kb_name="kb-a", task_id="task-1",
        source_sha256="a" * 64, require_video=False,
    )

    assert connection.execute_call is not None


@pytest.mark.asyncio
async def test_worker_rejects_non_processed_status(monkeypatch):
    from process_worker import _commit_media_delivery_v2
    from raganything.services import pg_state_repo

    events = []
    connection = _WorkerConnection([{
        "id": "doc-1", "status": "processing",
        "chunks_list": ["chunk-1"], "metadata": {}, "track_id": "task-1",
    }], events)
    monkeypatch.setattr(
        pg_state_repo, "get_pg_pool",
        lambda: _WorkerPool(connection, events),
    )

    with pytest.raises(CitationProvenanceError):
        await _commit_media_delivery_v2(
            kb_name="kb-a", task_id="task-1",
            source_sha256="a" * 64, require_video=False,
        )

    assert connection.execute_call is None
    assert "transaction-rollback" in events


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [[], [
    {"id": "doc-1", "status": "processed", "chunks_list": ["chunk-1"], "metadata": {}, "track_id": "task-1"},
    {"id": "doc-2", "status": "processed", "chunks_list": ["chunk-2"], "metadata": {}, "track_id": "task-1"},
]])
async def test_worker_rejects_ambiguous_pg_status_and_rolls_back(monkeypatch, rows):
    from process_worker import _commit_media_delivery_v2
    from raganything.services import pg_state_repo

    events = []
    connection = _WorkerConnection(rows, events)
    monkeypatch.setattr(
        pg_state_repo, "get_pg_pool", lambda: _WorkerPool(connection, events)
    )

    with pytest.raises(CitationProvenanceError):
        await _commit_media_delivery_v2(
            kb_name="kb-a", task_id="task-1",
            source_sha256="a" * 64, require_video=False,
        )

    assert connection.execute_call is None
    assert "transaction-rollback" in events


@pytest.mark.asyncio
async def test_worker_redacts_pg_pool_failure(monkeypatch):
    from process_worker import _commit_media_delivery_v2
    from raganything.services import pg_state_repo

    def unavailable():
        raise RuntimeError("private database detail")

    monkeypatch.setattr(pg_state_repo, "get_pg_pool", unavailable)
    with pytest.raises(
        CitationProvenanceError,
        match="Required media delivery persistence is unavailable",
    ) as captured:
        await _commit_media_delivery_v2(
            kb_name="kb-a", task_id="task-1",
            source_sha256="a" * 64, require_video=False,
        )
    assert "private database detail" not in str(captured.value)


@pytest.mark.asyncio
async def test_worker_contract_failure_rolls_back_without_marker(monkeypatch):
    from process_worker import _commit_media_delivery_v2
    from raganything.services import media_delivery_contract, pg_state_repo

    events = []
    connection = _WorkerConnection([{
        "id": "doc-1", "status": "processed", "chunks_list": ["chunk-1"],
        "metadata": {}, "track_id": "task-1",
    }], events)

    async def reject(**_kwargs):
        events.append("audit")
        raise CitationProvenanceError("contract incomplete")

    monkeypatch.setattr(
        pg_state_repo, "get_pg_pool",
        lambda: _WorkerPool(connection, events),
    )
    monkeypatch.setattr(media_delivery_contract, "audit_media_delivery_v2", reject)

    with pytest.raises(CitationProvenanceError, match="contract incomplete"):
        await _commit_media_delivery_v2(
            kb_name="kb-a", task_id="task-1",
            source_sha256="a" * 64, require_video=True,
        )

    assert connection.execute_call is None
    assert "transaction-rollback" in events


def test_worker_finalizes_lightrag_before_media_delivery_transaction():
    import inspect
    import process_worker

    source = inspect.getsource(process_worker.process_file)
    assert source.index("_flush_background_tasks_and_finalize") < source.index(
        "_commit_media_delivery_v2"
    )


@pytest.mark.asyncio
async def test_contract_rejects_missing_chunk_provenance():
    with pytest.raises(CitationProvenanceError):
        await audit_media_delivery_v2(
            kb_name="kb-a",
            document_id="doc-1",
            source_sha256="c" * 64,
            chunk_ids=["chunk-1", "chunk-2"],
            metadata={},
            require_video=False,
            pool=Pool([{
                "document_id": "doc-1",
                "chunk_id": "chunk-1",
                "source_sha256": "c" * 64,
                "modality": "text",
                "media_id": None,
            }]),
        )


@pytest.mark.asyncio
async def test_image_contract_rejects_inconsistent_counts():
    with pytest.raises(CitationProvenanceError):
        await audit_media_delivery_v2(
            kb_name="kb-a",
            document_id="doc-1",
            source_sha256="a" * 64,
            chunk_ids=["chunk-1"],
            metadata={
                "odl_media_catalog": _catalog(),
                "image_media_incomplete": False,
                "image_media_counts": {
                    "eligible_elements": 1,
                    "valid_manifest_media": 1,
                    "persisted_image_chunks": 0,
                    "catalog_media": 1,
                },
            },
            require_video=False,
            pool=Pool([{
                "document_id": "doc-1",
                "chunk_id": "chunk-1",
                "source_sha256": "a" * 64,
                "modality": "image",
                "media_id": "image-1",
            }]),
        )


@pytest.mark.asyncio
async def test_image_contract_rejects_catalog_without_counts():
    with pytest.raises(CitationProvenanceError):
        await audit_media_delivery_v2(
            kb_name="kb-a",
            document_id="doc-1",
            source_sha256="a" * 64,
            chunk_ids=["chunk-1"],
            metadata={"odl_media_catalog": _catalog()},
            require_video=False,
            pool=Pool([{
                "document_id": "doc-1",
                "chunk_id": "chunk-1",
                "source_sha256": "a" * 64,
                "modality": "image",
                "media_id": "image-1",
            }]),
        )


@pytest.mark.asyncio
async def test_video_contract_rejects_replaced_file(tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    video = uploads / "clip.mp4"
    video.write_bytes(b"replacement")
    monkeypatch.chdir(tmp_path)
    pool = Pool(
        [{
            "document_id": "doc-1", "chunk_id": "chunk-1",
            "source_sha256": "b" * 64, "modality": "video", "media_id": "video-1",
        }],
        [{
            "media_id": "video-1", "document_id": "doc-1",
            "source_sha256": "b" * 64, "server_path": str(video.resolve()),
            "status": "ready",
        }],
    )
    with pytest.raises(CitationProvenanceError):
        await audit_media_delivery_v2(
            kb_name="kb-a", document_id="doc-1", source_sha256="b" * 64,
            chunk_ids=["chunk-1"], metadata={}, require_video=True, pool=pool,
        )


def test_media_sha_verification_cache_avoids_rehashing_unchanged_file(
    tmp_path, monkeypatch
):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video-content")
    expected = hashlib.sha256(video.read_bytes()).hexdigest()
    calls = {"count": 0}
    real_hash = media_delivery_contract.media_file_sha256

    def counted_hash(path):
        calls["count"] += 1
        return real_hash(path)

    monkeypatch.setattr(
        media_delivery_contract, "media_file_sha256", counted_hash
    )
    media_delivery_contract._MEDIA_HASH_CACHE.clear()

    assert media_delivery_contract.media_file_sha256_matches(video, expected)
    assert media_delivery_contract.media_file_sha256_matches(video, expected)
    assert calls["count"] == 1
