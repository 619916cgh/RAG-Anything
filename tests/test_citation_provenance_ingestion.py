import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


class _DocStatus:
    def __init__(self, value):
        self.value = value

    async def get_by_id(self, _doc_id):
        return self.value


class _TextChunks:
    def __init__(self, records):
        self.records = records

    async def get_by_ids(self, _chunk_ids):
        return self.records


@pytest.mark.asyncio
async def test_text_chunk_provenance_inherits_trusted_page_and_section(monkeypatch):
    from raganything.processor.doc_processor import DocProcessorMixin
    from raganything.services import pg_state_repo, provenance

    captured = AsyncMock()
    monkeypatch.setattr(pg_state_repo, "get_pg_pool", lambda: object())
    monkeypatch.setattr(provenance, "upsert_provenance_records", captured)

    processor = DocProcessorMixin()
    processor.logger = logging.getLogger("test.provenance.text")
    processor.lightrag = SimpleNamespace(
        workspace="./rag_storage_manuals",
        doc_status=_DocStatus({"chunks_list": ["chunk-1", "chunk-2"]}),
        text_chunks=_TextChunks(
            [
                {
                    "content": "[第 3 页]\n# 安全检查\n先断开主电源。",
                    "full_doc_id": "doc-1",
                    "chunk_order_index": 0,
                },
                {
                    "content": "确认端子无电压后继续操作。",
                    "full_doc_id": "doc-1",
                    "chunk_order_index": 1,
                },
            ]
        ),
    )

    await processor._persist_text_chunk_provenance(
        doc_id="doc-1",
        document_name="manual.pdf",
        kb_name="manuals",
        source_sha256="a" * 64,
    )

    records = captured.await_args.args[0]
    assert [record["page"] for record in records] == [3, 3]
    assert records[1]["section_path"] == ["安全检查"]
    assert all(record["locator_status"] == "page" for record in records)
    assert all(record["source_sha256"] == "a" * 64 for record in records)


@pytest.mark.asyncio
async def test_text_chunk_provenance_prefers_current_chunk_page_marker(monkeypatch):
    from raganything.processor.doc_processor import DocProcessorMixin
    from raganything.services import pg_state_repo, provenance

    captured = AsyncMock()
    monkeypatch.setattr(pg_state_repo, "get_pg_pool", lambda: object())
    monkeypatch.setattr(provenance, "upsert_provenance_records", captured)

    processor = DocProcessorMixin()
    processor.logger = logging.getLogger("test.provenance.text.page-transition")
    processor.lightrag = SimpleNamespace(
        doc_status=_DocStatus({"chunks_list": ["chunk-1", "chunk-2"]}),
        text_chunks=_TextChunks(
            [
                {
                    "content": "[第 3 页]\n上一页内容。",
                    "full_doc_id": "doc-1",
                    "chunk_order_index": "invalid",
                },
                {
                    "content": "[第 4 页]\n本页内容。",
                    "full_doc_id": "doc-1",
                    "chunk_order_index": 1,
                },
            ]
        ),
    )

    await processor._persist_text_chunk_provenance(
        doc_id="doc-1",
        document_name="manual.pdf",
        kb_name="manuals",
        source_sha256="d" * 64,
    )

    records = captured.await_args.args[0]
    assert [record["page"] for record in records] == [3, 4]


@pytest.mark.asyncio
async def test_text_chunk_without_page_marker_stays_document_only(monkeypatch):
    from raganything.processor.doc_processor import DocProcessorMixin
    from raganything.services import pg_state_repo, provenance

    captured = AsyncMock()
    monkeypatch.setattr(pg_state_repo, "get_pg_pool", lambda: object())
    monkeypatch.setattr(provenance, "upsert_provenance_records", captured)

    processor = DocProcessorMixin()
    processor.logger = logging.getLogger("test.provenance.text.unpaged")
    processor.lightrag = SimpleNamespace(
        doc_status=_DocStatus({"chunks_list": ["chunk-1"]}),
        text_chunks=_TextChunks(
            [
                {
                    "content": "普通文本没有可证明的页码。",
                    "full_doc_id": "doc-1",
                    "chunk_order_index": 0,
                }
            ]
        ),
    )

    await processor._persist_text_chunk_provenance(
        doc_id="doc-1",
        document_name="notes.txt",
        kb_name="notes",
        source_sha256="b" * 64,
    )

    record = captured.await_args.args[0][0]
    assert record["page"] is None
    assert record["page_idx"] is None
    assert record["locator_status"] == "document"


@pytest.mark.asyncio
async def test_odl_image_provenance_keeps_element_bbox_and_coordinate_system(
    monkeypatch,
):
    from raganything.processor.multimodal_processor import MultimodalProcessorMixin
    from raganything.services import pg_state_repo, provenance

    captured = AsyncMock()
    monkeypatch.setattr(pg_state_repo, "get_pg_pool", lambda: object())
    monkeypatch.setattr(provenance, "upsert_provenance_records", captured)

    processor = MultimodalProcessorMixin()
    processor.logger = logging.getLogger("test.provenance.image")
    processor.lightrag = SimpleNamespace(
        doc_status=_DocStatus(
            {
                "metadata": {
                    "citation_provenance": {
                        "version": "v1",
                        "kb_name": "manuals",
                        "document_name": "manual.pdf",
                        "source_sha256": "c" * 64,
                    }
                }
            }
        )
    )
    coordinate_system = {
        "units": "PDF points",
        "origin": "bottom-left",
        "order": ["left", "bottom", "right", "top"],
        "width": 612.0,
        "height": 792.0,
    }
    item = {
        "content_type": "image",
        "chunk_order_index": 4,
        "original_item": {
            "image_caption": ["图 3-2 主轴装配"],
            "_section_path": "装配 > 主轴",
            "_odl_media": {
                "media_id": "media-1",
                "page": 12,
                "element_id": "figure-3-2",
                "caption": "图 3-2 主轴装配",
            },
            "_provenance": {
                "source_page": 12,
                "page_idx": 11,
                "element_id": "figure-3-2",
                "element_type": "figure",
                "bbox": [72.0, 144.0, 300.0, 360.0],
                "bbox_coordinate_system": coordinate_system,
            },
        },
    }

    await processor._persist_multimodal_chunk_provenance(
        "doc-1",
        [item],
        {
            "chunk-image": {
                "chunk_order_index": 4,
                "content": "图片描述",
            }
        },
    )

    record = captured.await_args.args[0][0]
    assert record["page"] == 12
    assert record["media_id"] == "media-1"
    assert record["element_id"] == "figure-3-2"
    assert record["figure_label"] == "图 3-2"
    assert record["bbox"] == [72.0, 144.0, 300.0, 360.0]
    assert record["bbox_coordinate_system"] == coordinate_system
    assert record["locator_status"] == "exact"
