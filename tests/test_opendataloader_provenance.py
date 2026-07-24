"""Private OpenDataLoader provenance-reference validation tests."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from raganything.parser.office_parser import PageTrackedContent
from raganything.processor.doc_processor import DocProcessorMixin


def _content_hash(blocks):
    return hashlib.sha256(
        json.dumps(blocks, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _mixin(output_root):
    mixin = DocProcessorMixin()
    mixin.config = SimpleNamespace(
        parser="opendataloader",
        pdf_parser="",
        parser_output_dir=str(output_root),
        parse_method="auto",
    )
    mixin.logger = MagicMock()
    return mixin


def _tracked_content(tmp_path):
    output_root = tmp_path / "output"
    sidecar_path = output_root / "document" / "run-1" / "document_provenance.json"
    sidecar_path.parent.mkdir(parents=True)
    blocks = [{"type": "text", "text": "safe", "page_idx": 0}]
    coverage = {
        "source_total_pages": 1,
        "successful_pages": [1],
        "failed_pages": [],
        "skipped_pages": [],
        "blank_pages": [],
    }
    content_hash = _content_hash(blocks)
    sidecar_path.write_text(
        json.dumps(
            {
                "adapter_schema_version": "1",
                "coverage": coverage,
                "normalized_content_sha256": content_hash,
            }
        ),
        encoding="utf-8",
    )
    sidecar_hash = hashlib.sha256(sidecar_path.read_bytes()).hexdigest()
    content = PageTrackedContent(
        blocks,
        coverage,
        provenance_ref={
            "schema": "odl-provenance-ref-v1",
            "relative_path": sidecar_path.relative_to(output_root).as_posix(),
            "sha256": sidecar_hash,
            "normalized_content_sha256": content_hash,
            "adapter_schema": "1",
        },
    )
    return output_root, content, coverage


def test_sidecar_reference_is_relative_and_revalidates_from_cache(tmp_path):
    output_root, content, coverage = _tracked_content(tmp_path)
    mixin = _mixin(output_root)

    stored_ref = mixin._validated_odl_provenance_ref(content, coverage)

    assert stored_ref is not None
    assert stored_ref["relative_path"] == "document/run-1/document_provenance.json"
    assert "path" not in stored_ref

    status_metadata = mixin._parser_status_metadata(
        output_root / "source.pdf", content, coverage
    )
    assert status_metadata == {
        "page_coverage": coverage,
        "provenance_ref": stored_ref,
    }

    cached_content = PageTrackedContent(
        list(content), coverage, provenance_ref=stored_ref
    )
    assert mixin._validated_odl_provenance_ref(cached_content, coverage) == stored_ref


def test_sidecar_reference_rejects_content_or_sidecar_tampering(tmp_path):
    output_root, content, coverage = _tracked_content(tmp_path)
    mixin = _mixin(output_root)

    assert mixin._validated_odl_provenance_ref(content, coverage) is not None
    content.append({"type": "text", "text": "changed", "page_idx": 0})
    assert mixin._validated_odl_provenance_ref(content, coverage) is None

    output_root, content, coverage = _tracked_content(tmp_path / "second")
    mixin = _mixin(output_root)
    sidecar_path = next(output_root.rglob("*_provenance.json"))
    sidecar_path.write_text("{}", encoding="utf-8")
    assert mixin._validated_odl_provenance_ref(content, coverage) is None


class _MemoryParseCache:
    def __init__(self):
        self.records = {}
        self.upserts = 0

    async def get_by_id(self, key):
        return self.records.get(key)

    async def upsert(self, records):
        self.records.update(records)
        self.upserts += 1

    async def index_done_callback(self):
        return None


@pytest.mark.asyncio
async def test_odl_cache_reuses_only_a_validated_identical_identity(tmp_path):
    output_root, content, _coverage = _tracked_content(tmp_path)
    mixin = _mixin(output_root)
    mixin.parse_cache = _MemoryParseCache()
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.7\ncache fixture")

    cache_key = mixin._generate_cache_key(source)
    await mixin._store_cached_result(cache_key, content, "doc-cache", source)

    cached = await mixin._get_cached_result(cache_key, source)

    assert cached is not None
    cached_content, cached_doc_id = cached
    assert cached_doc_id == "doc-cache"
    assert list(cached_content) == list(content)
    assert cached_content.provenance_ref["relative_path"] == (
        "document/run-1/document_provenance.json"
    )
    assert mixin.parse_cache.upserts == 1


@pytest.mark.asyncio
async def test_odl_cache_misses_when_behavior_identity_changes(tmp_path):
    output_root, content, _coverage = _tracked_content(tmp_path)
    mixin = _mixin(output_root)
    mixin.parse_cache = _MemoryParseCache()
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.7\nidentity fixture")

    old_identity = {
        "backend": "opendataloader",
        "sdk_version": "2.5.0",
        "fast_mode": True,
        "threads": 1,
        "schema": "1",
    }
    new_identity = {**old_identity, "sdk_version": "2.5.1"}
    with patch(
        "raganything.parser.opendataloader_parser.OpenDataLoaderParser.cache_identity",
        return_value=old_identity,
    ):
        old_key = mixin._generate_cache_key(source)
        await mixin._store_cached_result(old_key, content, "doc-old", source)

    with patch(
        "raganything.parser.opendataloader_parser.OpenDataLoaderParser.cache_identity",
        return_value=new_identity,
    ):
        new_key = mixin._generate_cache_key(source)
        cached = await mixin._get_cached_result(old_key, source)

    assert new_key != old_key
    assert cached is None
