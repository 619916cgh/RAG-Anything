from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from raganything.services import provenance


SHA_A = "a" * 64
SHA_B = "b" * 64


class _Transaction:
    def __init__(self, events):
        self.events = events

    async def __aenter__(self):
        self.events.append("transaction-enter")

    async def __aexit__(self, exc_type, exc, tb):
        self.events.append("transaction-exit")


class _Connection:
    def __init__(self, *, rows=None, failure=None):
        self.rows = rows or []
        self.failure = failure
        self.calls = []
        self.events = []

    def transaction(self):
        return _Transaction(self.events)

    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        if self.failure:
            raise self.failure
        return "DELETE 2" if sql.lstrip().startswith("DELETE") else "INSERT 0 1"

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        if self.failure:
            raise self.failure
        return self.rows


class _Acquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, tb):
        return None


class _Pool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return _Acquire(self.connection)


def _record(**overrides):
    record = {
        "kb_name": "kb-a",
        "document_id": "doc-1",
        "document_name": "01234567_manual.pdf",
        "chunk_id": "chunk-1",
        "source_sha256": SHA_A,
        "provenance_version": "odl-v1",
        "page": 3,
        "page_idx": 2,
        "page_idx_trusted": True,
        "section_path": ["方法", "安装"],
        "modality": "image",
        "media_id": "media/1",
        "element_id": "figure-1",
        "figure_label": "图 1",
        "bbox": [10, 20, 40, 60],
        "bbox_coordinate_system": {"type": "pdf-points", "width": 600},
        "locator_status": "exact",
        "excerpt": "安装步骤",
        "ingested_at": datetime(2026, 9, 8, tzinfo=timezone.utc),
    }
    record.update(overrides)
    return record


def test_migration_registers_constrained_provenance_table():
    sql = open("migrations/038_citation_provenance.sql", encoding="utf-8").read()
    manifest = json.load(open("migrations/migration_manifest.json", encoding="utf-8"))

    assert manifest["migrations"][-1] == {
        "sequence": 41,
        "id": "038_citation_provenance.sql",
    }
    assert "UNIQUE (kb_name, document_id, chunk_id, provenance_version)" in sql
    assert "source_sha256 ~ '^[0-9a-f]{64}$'" in sql
    assert "locator_status IN ('exact', 'page', 'document', 'unavailable')" in sql
    assert "segment_id              TEXT" in sql
    assert "idx_citation_provenance_reference" in sql
    assert "ADD COLUMN IF NOT EXISTS citations JSONB NOT NULL DEFAULT '[]'::jsonb" in sql
    assert "CONSTRAINT ck_query_history_citations" in sql
    assert "jsonb_typeof(citations) = 'array'" in sql


def test_normalize_provenance_record_unifies_page_and_nested_video():
    normalized = provenance.normalize_provenance_record({
        "kb": "kb-a",
        "full_doc_id": "doc-1",
        "file_path": r"C:\private\01234567_manual.pdf",
        "chunkId": "chunk-1",
        "source_sha256": SHA_A.upper(),
        "page_idx": "0",
        "page_index_base": 0,
        "section": "第一章",
        "video_segment": {
            "media_id": "video-1",
            "segment_id": "segment-1",
            "start_ms": 1000,
            "end_ms": 4000,
            "frame_refs": [{"index": 1}],
        },
    })

    assert normalized["document_name"] == "manual.pdf"
    assert normalized["page"] == 1
    assert normalized["page_idx"] == 0
    assert normalized["section_path"] == ["第一章"]
    assert normalized["source_sha256"] == SHA_A
    assert normalized["modality"] == "video"
    assert normalized["segment_id"] == "segment-1"
    assert normalized["locator_status"] == "exact"


def test_bare_page_idx_remains_internal_until_its_basis_is_trusted():
    normalized = provenance.normalize_provenance_record({
        "document_name": "manual.pdf", "page_idx": 4,
    })
    citation = provenance.build_provenance_citation({
        "document_name": "manual.pdf", "page_idx": 4,
    })

    assert normalized["page_idx"] == 4
    assert normalized["page"] is None
    assert citation["page"] is None
    assert "page_idx" not in citation


def test_build_image_citation_is_path_free_and_uses_controlled_url():
    citation = provenance.build_provenance_citation(
        _record(file_path=r"C:\private\manual.pdf", server_path=r"\\host\share\figure.png"),
        citation_id="citation-1",
        excerpt=(
            "保留的说明\n"
            "Image Path: C:\\private\\figure.png\n"
            "[图片路径：/uploads/private/figure.png]\n"
            "file://server/private.png\n"
            "server_path=C:\\private\\other.png"
        ),
        media_url="https://untrusted.invalid/private.png",
    )
    serialized = json.dumps(citation, ensure_ascii=False)

    assert citation["citation_id"] == "citation-1"
    assert citation["document_name"] == "manual.pdf"
    assert citation["page"] == 3
    assert citation["image"] == {
        "media_id": "media/1",
        "element_id": "figure-1",
        "figure_label": "图 1",
        "bbox": {"x": 10.0, "y": 20.0, "width": 30.0, "height": 40.0},
        "bbox_coordinate_system": {"type": "pdf-points", "width": 600},
        "media_url": "/api/knowledge/media/media%2F1?kb=kb-a",
    }
    assert citation["excerpt"] == "保留的说明"
    assert "page_idx" not in citation
    for forbidden in ("C:\\\\", "/uploads", "file://", "server_path", "file_path", "untrusted.invalid"):
        assert forbidden not in serialized
    assert "source_sha256" not in citation
    assert "kb_name" not in citation


def test_build_citation_deeply_sanitizes_structured_locator_fields():
    citation = provenance.build_provenance_citation(_record(
        bbox={
            "x": 10,
            "y": 20,
            "width": 30,
            "height": 40,
            "server_path": r"C:\private\bbox.json",
        },
        bbox_coordinate_system={
            "units": "PDF points",
            "origin": "bottom-left",
            "order": ["left", "bottom", "right", "top"],
            "width": 600,
            "height": 800,
            "file_path": r"C:\private\page.png",
            "token": "secret-coordinate-token",
        },
    ))

    assert citation["image"]["bbox"] == {
        "x": 10.0,
        "y": 20.0,
        "width": 30.0,
        "height": 40.0,
    }
    assert citation["image"]["bbox_coordinate_system"] == {
        "units": "PDF points",
        "origin": "bottom-left",
        "order": ["left", "bottom", "right", "top"],
        "width": 600.0,
        "height": 800.0,
    }
    serialized = json.dumps(citation, ensure_ascii=False)
    assert "server_path" not in serialized
    assert "file_path" not in serialized
    assert "secret-coordinate-token" not in serialized


def test_build_video_citation_whitelists_frame_reference_fields():
    citation = provenance.build_provenance_citation(_record(
        modality="video",
        media_id="video-1",
        segment_id="segment-1",
        start_ms=12000,
        end_ms=36000,
        frame_refs=[{
            "timestamp_ms": 12000,
            "index": 2,
            "frame_id": "frame-2",
            "server_path": r"C:\private\frame.jpg",
            "token": "secret-frame-token",
        }],
        bbox=None,
        bbox_coordinate_system=None,
        element_id="",
        figure_label="",
    ))

    assert citation["video_segment"]["frame_refs"] == [{
        "timestamp_ms": 12000.0,
        "index": 2.0,
        "frame_id": "frame-2",
    }]
    serialized = json.dumps(citation, ensure_ascii=False)
    assert "server_path" not in serialized
    assert "secret-frame-token" not in serialized


def test_build_video_citation_keeps_segment_identity_and_controlled_url():
    citation = provenance.build_provenance_citation(_record(
        modality="video",
        media_id="video 1",
        segment_id="segment-1",
        start_ms=12000,
        end_ms=36000,
        frame_refs=[{"timestamp_ms": 12000, "index": 2}],
        bbox=None,
        bbox_coordinate_system=None,
        element_id="",
        figure_label="",
    ))

    assert citation["media_url"] == "/api/knowledge/media/video%201?kb=kb-a"
    assert citation["video_segment"] == {
        "media_id": "video 1",
        "media_kb": "kb-a",
        "segment_id": "segment-1",
        "start_ms": 12000,
        "end_ms": 36000,
        "frame_refs": [{"timestamp_ms": 12000, "index": 2}],
    }
    assert citation["video_segments"] == [citation["video_segment"]]
    assert citation["media_kb"] == "kb-a"
    assert citation["start_ms"] == 12000
    assert citation["end_ms"] == 36000


def test_build_video_citation_sanitizes_and_rejects_conflicting_ranges():
    citation = provenance.build_provenance_citation(
        _record(
            modality="video", media_id="video-1", segment_id="segment-2",
            start_ms=2000, end_ms=3000, bbox=None,
            bbox_coordinate_system=None, element_id="", figure_label="",
        ),
        video_segments=[
            {
                "media_id": "video-1", "media_kb": "kb-a",
                "segment_id": "segment-1", "start_ms": 0, "end_ms": 1000,
                "server_path": r"C:\\private\\video.mp4",
                "legacy_grant": "legacy:secret",
                "media_url": "blob:private",
            },
            {
                "media_id": "other-video", "media_kb": "kb-a",
                "segment_id": "conflict", "start_ms": 0, "end_ms": 1000,
            },
        ],
    )

    assert [item["segment_id"] for item in citation["video_segments"]] == [
        "segment-1", "segment-2",
    ]
    serialized = json.dumps(citation, ensure_ascii=False)
    for forbidden in ("server_path", "legacy_grant", "legacy:secret", "blob:private", "other-video"):
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_batch_upsert_is_transactional_and_atomically_replaces_source_hash():
    connection = _Connection()
    result = await provenance.upsert_provenance_records(
        [_record(), _record(source_sha256=SHA_B)], pool=_Pool(connection)
    )

    # The same logical provenance version is last-write-wins within one batch.
    assert [item["source_sha256"] for item in result] == [SHA_B]
    assert connection.events == ["transaction-enter", "transaction-exit"]
    assert len(connection.calls) == 1
    insert_sql, insert_args = connection.calls[0]
    assert (
        "ON CONFLICT (\n        kb_name, document_id, chunk_id, provenance_version"
        in insert_sql
    )
    assert "source_sha256 = EXCLUDED.source_sha256" in insert_sql
    assert "DELETE FROM citation_provenance" not in insert_sql
    assert insert_args[4] == SHA_B
    assert insert_args[11] is None
    assert json.loads(insert_args[14]) == {
        "x": 10.0, "y": 20.0, "width": 30.0, "height": 40.0,
    }


@pytest.mark.asyncio
async def test_upsert_rejects_invalid_hash_and_propagates_write_failure():
    with pytest.raises(ValueError, match="source_sha256"):
        await provenance.upsert_provenance(_record(source_sha256="bad"), pool=_Pool(_Connection()))

    with pytest.raises(RuntimeError, match="write failed"):
        await provenance.upsert_provenance(
            _record(), pool=_Pool(_Connection(failure=RuntimeError("write failed")))
        )


@pytest.mark.asyncio
async def test_batch_get_does_not_guess_when_chunk_id_spans_documents():
    rows = [
        _record(),
        _record(document_id="doc-2"),
        _record(document_id="doc-3", chunk_id="chunk-unique"),
    ]
    result = await provenance.batch_get_provenance(
        "kb-a", ["chunk-1", "chunk-unique"], pool=_Pool(_Connection(rows=rows))
    )

    assert "chunk-1" not in result
    assert result["chunk-unique"]["document_id"] == "doc-3"


@pytest.mark.asyncio
async def test_reference_batch_resolves_same_chunk_per_document():
    connection = _Connection(rows=[_record(), _record(document_id="doc-2")])
    result = await provenance.batch_get_provenance_for_references(
        "kb-a",
        [
            {"document_id": "doc-1", "chunk_id": "chunk-1"},
            {"document_id": "doc-2", "chunk_id": "chunk-1"},
        ],
        pool=_Pool(connection),
    )

    assert result[("doc-1", "chunk-1")]["document_id"] == "doc-1"
    assert result[("doc-2", "chunk-1")]["document_id"] == "doc-2"
    select_sql = connection.calls[0][0]
    assert "SELECT \n    p.kb_name" in select_sql
    assert "p.document_id" in select_sql
    assert "p.chunk_id" in select_sql


@pytest.mark.asyncio
async def test_reads_fail_soft_but_deletes_fail_closed_when_pool_is_unavailable(monkeypatch):
    def unavailable():
        raise RuntimeError("pool unavailable")

    monkeypatch.setattr(provenance, "get_pg_pool", unavailable)
    assert await provenance.batch_get_provenance("kb-a", ["chunk-1"]) == {}
    assert await provenance.batch_get_provenance_for_references(
        "kb-a", [{"document_id": "doc-1", "chunk_id": "chunk-1"}]
    ) == {}
    with pytest.raises(RuntimeError, match="pool unavailable"):
        await provenance.delete_document_provenance("kb-a", "doc-1")
    with pytest.raises(RuntimeError, match="pool unavailable"):
        await provenance.delete_chunk_provenance("kb-a", "doc-1", "chunk-1")


@pytest.mark.asyncio
async def test_delete_fail_soft_only_accepts_explicit_undefined_table():
    undefined_table = RuntimeError("relation does not exist")
    undefined_table.sqlstate = "42P01"
    unavailable = RuntimeError("pool unavailable")
    unavailable.sqlstate = "08006"

    assert await provenance.delete_document_provenance(
        "kb-a", "doc-1", pool=_Pool(_Connection(failure=undefined_table)),
        fail_soft=True,
    ) == 0
    assert await provenance.delete_chunk_provenance(
        "kb-a", "doc-1", "chunk-1",
        pool=_Pool(_Connection(failure=undefined_table)), fail_soft=True,
    ) == 0

    with pytest.raises(RuntimeError, match="relation does not exist"):
        await provenance.delete_document_provenance(
            "kb-a", "doc-1", pool=_Pool(_Connection(failure=undefined_table)),
        )
    with pytest.raises(RuntimeError, match="pool unavailable"):
        await provenance.delete_document_provenance(
            "kb-a", "doc-1", pool=_Pool(_Connection(failure=unavailable)),
            fail_soft=True,
        )


@pytest.mark.asyncio
async def test_delete_helpers_are_scoped():
    connection = _Connection()
    pool = _Pool(connection)

    assert await provenance.delete_document_provenance("kb-a", "doc-1", pool=pool) == 2
    assert await provenance.delete_chunk_provenance("kb-a", "doc-1", "chunk-1", pool=pool) == 2
    assert connection.calls[0][1] == ("kb-a", "doc-1")
    assert connection.calls[1][1] == ("kb-a", "doc-1", "chunk-1")
