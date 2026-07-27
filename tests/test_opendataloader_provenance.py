"""Private OpenDataLoader provenance-reference validation tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
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
    sidecar_path = (
        output_root
        / "document_a1b2c3d4"
        / "run-12345678"
        / "document_provenance.json"
    )
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
    assert stored_ref["relative_path"] == (
        "document_a1b2c3d4/run-12345678/document_provenance.json"
    )
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


def test_dedicated_artifact_root_is_used_for_status_metadata(tmp_path):
    """doc_status must validate sidecars against ODL_ARTIFACT_ROOT, not OUTPUT_DIR."""
    artifact_root, content, coverage = _tracked_content(tmp_path)
    shared_output = tmp_path / "shared-output"
    shared_output.mkdir()
    mixin = _mixin(shared_output)
    mixin.config.odl_artifact_root = str(artifact_root)

    effective_root = mixin._effective_parser_output_dir(
        tmp_path / "source.pdf", str(shared_output)
    )
    metadata = mixin._parser_status_metadata(
        tmp_path / "source.pdf", content, coverage, effective_root
    )

    assert Path(effective_root) == artifact_root
    assert metadata["provenance_ref"]["relative_path"] == (
        "document_a1b2c3d4/run-12345678/document_provenance.json"
    )


@pytest.mark.skipif(not hasattr(__import__("os"), "symlink"), reason="symlinks unavailable")
def test_dedicated_artifact_root_rejects_shared_output_symlink_alias(tmp_path):
    artifact_root = tmp_path / "odl-artifacts"
    artifact_root.mkdir()
    shared_alias = tmp_path / "shared-output"
    try:
        shared_alias.symlink_to(artifact_root, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    mixin = _mixin(shared_alias)
    mixin.config.odl_artifact_root = str(artifact_root)

    with pytest.raises(ValueError, match="separate"):
        mixin._effective_parser_output_dir(tmp_path / "source.pdf", str(shared_alias))


def test_validated_sidecar_registers_only_a_server_owned_odl_run(tmp_path):
    output_root, content, coverage = _tracked_content(tmp_path)
    mixin = _mixin(output_root)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.7\nfixture")

    mixin._ensure_odl_artifact_registered(
        file_path=source,
        content_list=content,
        page_coverage=coverage,
        artifact_root=output_root,
        kb_id="staging-kb",
        doc_id="doc-owned",
    )

    from raganything.services.odl_artifact_lifecycle import (
        ArtifactOwner,
        OpenDataLoaderArtifactLifecycle,
    )

    record = OpenDataLoaderArtifactLifecycle(output_root).get(
        ArtifactOwner("staging-kb", "doc-owned")
    )
    assert record is not None
    assert record.run_relpath == "document_a1b2c3d4/run-12345678"


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
        "document_a1b2c3d4/run-12345678/document_provenance.json"
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
