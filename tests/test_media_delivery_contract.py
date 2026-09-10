from pathlib import Path

import pytest

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


@pytest.mark.asyncio
async def test_worker_resolves_current_document_from_authoritative_status_backend():
    from process_worker import _get_current_task_doc_status

    class StatusStorage:
        async def get_docs_by_track_id(self, track_id):
            assert track_id == "task-1"
            return {
                "doc-1": {
                    "track_id": "task-1",
                    "chunks_list": ["chunk-1"],
                    "metadata": {},
                }
            }

    rag = type(
        "Rag",
        (),
        {"lightrag": type("LightRag", (), {"doc_status": StatusStorage()})()},
    )()
    document_id, status = await _get_current_task_doc_status(rag, "task-1")
    assert document_id == "doc-1"
    assert status["chunks_list"] == ["chunk-1"]


@pytest.mark.asyncio
async def test_worker_accepts_doc_status_model_from_pg_backend():
    from process_worker import _get_current_task_doc_status

    class StatusModel:
        def model_dump(self):
            return {
                "track_id": "task-1",
                "chunks_list": ["chunk-1"],
                "metadata": {},
            }

    class StatusStorage:
        async def get_docs_by_track_id(self, _track_id):
            return {"doc-1": StatusModel()}

    rag = type(
        "Rag",
        (),
        {"lightrag": type("LightRag", (), {"doc_status": StatusStorage()})()},
    )()
    document_id, status = await _get_current_task_doc_status(rag, "task-1")
    assert document_id == "doc-1"
    assert status["track_id"] == "task-1"


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
