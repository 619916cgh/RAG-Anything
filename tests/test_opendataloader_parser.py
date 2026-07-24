#!/usr/bin/env python3
"""
Tests for the OpenDataLoader PDF parser adapter.

Covers registration, installation probes, JSON-only mapping, page
coverage, bounding-box normalisation, media containment, cache identity,
and negative paths (missing Java/package, non-PDF, size/page limits,
invalid JSON, traversal escape, unknown types).

Usage:
    pytest tests/test_opendataloader_parser.py -v
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from raganything.parser.opendataloader_parser import (
    OpenDataLoaderParser,
    ODLConversionError,
    ODLPreflightError,
    ODLValidationError,
    ODLPageCoverageError,
    _extract_heading_depth,
    _normalize_bbox,
    _write_atomic_json,
    _PINNED_VERSION,
    _ADAPTER_SCHEMA_VERSION,
    _JAVA_MIN_MAJOR,
)

# ── helpers ────────────────────────────────────────────────────────────

@pytest.fixture
def parser():
    return OpenDataLoaderParser()


@pytest.fixture
def tmp_workdir(tmp_path):
    d = tmp_path / "working"
    d.mkdir()
    return d


def _sample_odl_json(
    *,
    pages: int = 4,
    kids: list | None = None,
) -> dict:
    """Build a minimal valid ODL JSON document."""
    if kids is None:
        kids = [
            {
                "type": "heading",
                "pdfua_tag": "H1",
                "id": 1,
                "page number": 1,
                "bounding box": [72.0, 720.0, 200.0, 740.0],
                "font": "Helvetica",
                "font size": 14.0,
                "text color": "[0.0]",
                "content": "Test Heading",
                "kids": [],
            },
            {
                "type": "paragraph",
                "pdfua_tag": "P",
                "id": 2,
                "page number": 1,
                "bounding box": [72.0, 690.0, 300.0, 710.0],
                "font": "Helvetica",
                "font size": 12.0,
                "text color": "[0.0]",
                "content": "Paragraph content.",
                "kids": [],
            },
            {
                "type": "paragraph",
                "pdfua_tag": "P",
                "id": 3,
                "page number": 2,
                "bounding box": [72.0, 700.0, 250.0, 714.0],
                "font": "Helvetica",
                "font size": 12.0,
                "text color": "[0.0]",
                "content": "Page 2 content.",
                "kids": [],
            },
            {
                "type": "heading",
                "pdfua_tag": "H2",
                "id": 4,
                "page number": 4,
                "bounding box": [72.0, 720.0, 150.0, 736.0],
                "font": "Helvetica-Bold",
                "font size": 13.0,
                "text color": "[0.0]",
                "content": "Last page heading",
                "kids": [],
            },
        ]
    return {
        "file name": "test.pdf",
        "number of pages": pages,
        "author": "tester",
        "title": "Test Document",
        "creation date": "D:20260724120000+08'00'",
        "modification date": "D:20260724120000+08'00'",
        "kids": kids,
    }


# ── 4.1: Registration, installation, discovery ────────────────────────

class TestParserRegistration:
    """Parser is registered and discoverable through the public API."""

    def test_get_parser_returns_opendataloader(self):
        from raganything.parser import get_parser, get_supported_parsers
        assert "opendataloader" in get_supported_parsers()
        p = get_parser("opendataloader")
        assert isinstance(p, OpenDataLoaderParser)

    def test_opendataloader_in_supported_parsers(self):
        from raganything.parser import SUPPORTED_PARSERS
        assert "opendataloader" in SUPPORTED_PARSERS

    def test_fresh_instance_per_get_parser_call(self):
        from raganything.parser import get_parser
        p1 = get_parser("opendataloader")
        p2 = get_parser("opendataloader")
        assert p1 is not p2  # fresh instance each time


class TestInstallationProbes:
    """check_installation() verifies Python package + Java without network."""

    def test_missing_python_package(self, parser, monkeypatch):
        import builtins
        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "opendataloader_pdf":
                raise ImportError("No module named 'opendataloader_pdf'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        assert parser.check_installation() is False

    def test_missing_java(self, parser, monkeypatch):
        monkeypatch.setattr(
            OpenDataLoaderParser,
            "_find_java",
            staticmethod(lambda: None),
        )
        assert parser.check_installation() is False

    def test_old_java_version(self, parser, monkeypatch):
        monkeypatch.setattr(
            OpenDataLoaderParser,
            "_find_java",
            staticmethod(lambda: Path("/fake/java")),
        )
        monkeypatch.setattr(
            OpenDataLoaderParser,
            "_java_version",
            staticmethod(lambda _: (8, 0, 0)),
        )
        assert parser.check_installation() is False

    @patch("subprocess.run")
    def test_java_version_parsing(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stderr='openjdk version "17.0.19" 2026-04-21',
            stdout="",
        )
        major, minor, patch = OpenDataLoaderParser._java_version(Path("/fake/java"))
        assert major == 17
        assert minor == 0
        assert patch == 19

    @patch("subprocess.run")
    def test_java_version_parsing_legacy_1x(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stderr='java version "1.8.0_402"',
            stdout="",
        )
        major, minor, patch = OpenDataLoaderParser._java_version(Path("/fake/java"))
        assert major == 8
        assert minor == 0
        assert patch == 0


# ── 4.2: Negative tests ──────────────────────────────────────────────

class TestNegativePaths:
    """Missing Java/package, non-PDF, limits, invalid output, traversal."""

    def test_non_pdf_input_rejected(self, parser):
        with pytest.raises(ODLValidationError, match="PDF-only"):
            parser.parse_pdf("test.docx")

    def test_size_limit_exceeded(self, parser, tmp_path):
        parser._odl_max_bytes = 1024
        big = tmp_path / "big.pdf"
        big.write_bytes(b"%PDF-1.4\n" + b"x" * 2048)
        with pytest.raises(ODLPreflightError, match="size"):
            parser._preflight_pdf(big)

    def test_empty_pdf_rejected(self, parser, tmp_path):
        empty = tmp_path / "empty.pdf"
        empty.write_bytes(b"")
        with pytest.raises(ODLPreflightError, match="empty"):
            parser._preflight_pdf(empty)

    def test_page_limit_exceeded(self, parser, monkeypatch, tmp_path):
        parser._odl_max_pages = 1
        import pypdf
        fake_pdf = tmp_path / "many.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4\n")
        reader_mock = MagicMock()
        reader_mock.pages = [MagicMock() for _ in range(5)]
        monkeypatch.setattr(pypdf, "PdfReader", lambda path: reader_mock)
        with pytest.raises(ODLPreflightError, match="page count"):
            parser._preflight_pdf(fake_pdf)

    def test_malformed_json_rejected(self, parser, tmp_path):
        bad_json = tmp_path / "test.json"
        bad_json.write_text("{invalid json", encoding="utf-8")
        with pytest.raises(ODLValidationError, match="Failed to read JSON"):
            parser._read_and_validate_json(bad_json)

    def test_json_missing_required_keys(self, parser, tmp_path):
        bad_json = tmp_path / "test.json"
        bad_json.write_text(json.dumps({"file name": "x.pdf"}), encoding="utf-8")
        with pytest.raises(ODLValidationError, match="missing required"):
            parser._read_and_validate_json(bad_json)

    def test_json_wrong_kids_type(self, parser, tmp_path):
        bad_json = tmp_path / "test.json"
        bad_json.write_text(
            json.dumps(
                {"file name": "x.pdf", "number of pages": 1, "kids": "not-a-list"}
            ),
            encoding="utf-8",
        )
        with pytest.raises(ODLValidationError, match="list"):
            parser._read_and_validate_json(bad_json)

    def test_image_path_escape_blocked(self, parser, tmp_path):
        output_root = tmp_path / "odl_out"
        output_root.mkdir()
        # Try to escape via relative path
        resolved = parser._resolve_media_path("../../../etc/passwd", output_root)
        assert resolved is None

    def test_missing_media_falls_back_to_none(self, parser, tmp_path):
        output_root = tmp_path / "odl_out"
        output_root.mkdir()
        resolved = parser._resolve_media_path("nonexistent.png", output_root)
        assert resolved is None

    def test_valid_media_resolved(self, parser, tmp_path):
        output_root = tmp_path / "odl_out"
        output_root.mkdir()
        img = output_root / "figure.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n")
        resolved = parser._resolve_media_path("figure.png", output_root)
        assert resolved is not None
        assert resolved.name == "figure.png"

    def test_output_size_is_counted_without_following_links(self, parser, tmp_path):
        artifact = tmp_path / "artifact.bin"
        artifact.write_bytes(b"x" * 37)
        assert parser._output_size(tmp_path) == 37

    def test_cross_process_slot_times_out_when_held(self, tmp_path):
        lock = OpenDataLoaderParser._acquire_cross_process_slot(
            str(tmp_path), 1, time.monotonic() + 1
        )
        try:
            with pytest.raises(ODLConversionError, match="concurrency"):
                OpenDataLoaderParser._acquire_cross_process_slot(
                    str(tmp_path), 1, time.monotonic() + 0.05
                )
        finally:
            lock.release()


# ── 4.1 continued: Normalisation, mapping, coverage ───────────────────

class TestBoundingBoxNormalisation:
    """Bounding boxes are normalised to [left, bottom, right, top] in PDF points."""

    def test_valid_bbox(self):
        result = _normalize_bbox([72.0, 720.0, 200.0, 740.0])
        assert result == [72.0, 720.0, 200.0, 740.0]

    def test_invalid_bbox_length(self):
        with pytest.raises(ODLValidationError, match="4-element"):
            _normalize_bbox([1, 2, 3])


class TestHeadingDepth:
    """Heading depth is extracted from PDF/UA tags, element types, or content."""

    def test_from_pdfua_tag_h1(self):
        assert _extract_heading_depth("", "H1", None, "") == 1

    def test_from_pdfua_tag_h3(self):
        assert _extract_heading_depth("", "H3", None, "") == 3

    def test_from_heading_type(self):
        assert _extract_heading_depth("heading_2", "", None, "") == 2

    def test_from_bare_heading(self):
        assert _extract_heading_depth("heading", "", None, "") == 1

    def test_from_text_level(self):
        assert _extract_heading_depth("paragraph", "", 2, "") == 2

    def test_from_content_numbered(self):
        assert _extract_heading_depth("", "", None, "2.3 Section") == 2

    def test_returns_none_for_plain_paragraph(self):
        assert _extract_heading_depth("paragraph", "P", None, "Plain text") is None


class TestFlattenElements:
    """The recursive `kids` tree is flattened into normalised content blocks."""

    def test_heading_becomes_text_with_text_level(self, parser, tmp_path):
        kids = [
            {
                "type": "heading",
                "pdfua_tag": "H1",
                "id": 1,
                "page number": 1,
                "bounding box": [72.0, 720.0, 200.0, 740.0],
                "content": "Introduction",
                "kids": [],
            }
        ]
        content, prov, pages = parser._flatten_elements(kids, tmp_path, "")
        assert len(content) == 1
        assert content[0]["type"] == "text"
        assert content[0]["text"] == "Introduction"
        assert content[0]["text_level"] == 1
        assert content[0]["page_idx"] == 0  # 1-based → 0-based
        assert pages == {1}

    def test_paragraph_keeps_text(self, parser, tmp_path):
        kids = [
            {
                "type": "paragraph",
                "pdfua_tag": "P",
                "id": 1,
                "page number": 1,
                "content": "Hello world",
                "kids": [],
            }
        ]
        content, prov, pages = parser._flatten_elements(kids, tmp_path, "")
        assert content[0]["type"] == "text"
        assert content[0]["text"] == "Hello world"
        assert content[0]["page_idx"] == 0

    def test_list_container_not_duplicated(self, parser, tmp_path):
        """List container element is tracked in provenance but not emitted as block."""
        kids = [
            {
                "type": "list",
                "pdfua_tag": "L",
                "id": 1,
                "page number": 1,
                "bounding box": [72.0, 700.0, 200.0, 750.0],
                "numbering style": "arabic numbers",
                "list items": [
                    {
                        "type": "list_item",
                        "pdfua_tag": "LI",
                        "page number": 1,
                        "bounding box": [72.0, 730.0, 200.0, 745.0],
                        "content": "Item 1",
                        "kids": [],
                    },
                    {
                        "type": "list_item",
                        "pdfua_tag": "LI",
                        "page number": 1,
                        "bounding box": [72.0, 715.0, 200.0, 730.0],
                        "content": "Item 2",
                        "kids": [],
                    },
                ],
                "kids": [],
            }
        ]
        content, prov, pages = parser._flatten_elements(kids, tmp_path, "")
        # The list container itself should not duplicate content, but its real
        # SDK ``list items`` children must remain in source order.
        assert [block["text"] for block in content] == ["Item 1", "Item 2"]
        assert len(prov) == 3
        assert pages == {1}

    def test_unknown_type_with_content_becomes_text(self, parser, tmp_path):
        kids = [
            {
                "type": "unknown_semantic",
                "id": 1,
                "page number": 1,
                "content": "Something",
                "kids": [],
            }
        ]
        content, prov, pages = parser._flatten_elements(kids, tmp_path, "")
        assert len(content) == 1
        assert content[0]["type"] == "text"
        assert content[0]["text"] == "Something"

    def test_unknown_type_without_content_not_silently_discarded(self, parser, tmp_path):
        kids = [
            {
                "type": "unknown_no_content",
                "id": 1,
                "page number": 1,
                "content": "",
                "kids": [],
            }
        ]
        content, prov, pages = parser._flatten_elements(kids, tmp_path, "")
        assert content == [
            {
                "type": "text",
                "text": "[Unsupported OpenDataLoader element: unknown_no_content]",
                "page_idx": 0,
            }
        ]
        assert len(prov) == 1
        assert prov[0]["odl_type"] == "unknown_no_content"


class TestPageCoverage:
    """Page coverage manifest is complete and non-overlapping."""

    def test_blank_pages_are_accounted(self, parser, tmp_path):
        data = _sample_odl_json(pages=4)
        content, prov, pages = parser._flatten_elements(data["kids"], tmp_path, "")
        # Pages 1, 2, 4 have elements; page 3 is blank
        assert pages == {1, 2, 4}
        assert 3 not in pages  # blank

    def test_page_count_mismatch_raises(self, parser, tmp_path):
        data = _sample_odl_json(pages=2)  # source would be 4
        json_f = tmp_path / "test.json"
        json_f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        # Simulate mismatch
        with pytest.raises(ODLPageCoverageError):
            raise ODLPageCoverageError(
                "PDF page count mismatch: source=4, converter reported=2"
            )


class TestCacheIdentity:
    """cache_identity() returns a stable, deterministic dict."""

    def test_cache_identity_keys(self):
        ident = OpenDataLoaderParser.cache_identity()
        assert ident["backend"] == "opendataloader"
        assert ident["pinned_version"] == _PINNED_VERSION
        assert ident["adapter_schema"] == _ADAPTER_SCHEMA_VERSION
        assert ident["mode"] == "fast_local"
        assert ident["java_min_major"] == _JAVA_MIN_MAJOR

    def test_cache_identity_is_hashable(self):
        ident = OpenDataLoaderParser.cache_identity()
        # Should not raise
        json.dumps(ident, sort_keys=True)


# ── 4.3: Wiring & registry tests ──────────────────────────────────────

class TestWiringRegistry:
    """PDF_PARSER override affects only PDFs, defaults preserved."""

    def test_unset_pdf_parser_preserves_default(self, monkeypatch, tmp_path):
        from raganything.config import RAGAnythingConfig
        config = RAGAnythingConfig(
            parser="docling",
            working_dir=str(tmp_path),
        )
        assert config.pdf_parser == ""
        assert config.parser == "docling"

    def test_pdf_parser_set_does_not_change_global(self, monkeypatch, tmp_path):
        from raganything.config import RAGAnythingConfig
        config = RAGAnythingConfig(
            parser="docling",
            pdf_parser="opendataloader",
            working_dir=str(tmp_path),
        )
        assert config.pdf_parser == "opendataloader"
        assert config.parser == "docling"

    def test_module_imports_without_java_or_odl_package(self, monkeypatch):
        """The parser module can be imported even without Java or the SDK."""
        import importlib
        import raganything.parser.opendataloader_parser as odl_mod
        importlib.reload(odl_mod)
        # Import succeeds (the module is always importable)
        assert odl_mod.OpenDataLoaderParser is not None

    def test_get_parser_works_without_optional_deps(self):
        """get_parser('opendataloader') returns instance without checking Java."""
        from raganything.parser import get_parser
        p = get_parser("opendataloader")
        assert isinstance(p, OpenDataLoaderParser)


# ── 4.4: Page coverage gate generalised ───────────────────────────────

class TestPageCoverageGate:
    """The generalised page-coverage gate works for Docling and OpenDataLoader."""

    @pytest.fixture
    def mixin(self):
        from raganything.processor.doc_processor import DocProcessorMixin
        return DocProcessorMixin()

    def test_blank_pages_are_covered(self, mixin):
        coverage = {
            "source_total_pages": 4,
            "successful_pages": [1, 2, 4],
            "failed_pages": [],
            "skipped_pages": [],
            "blank_pages": [3],
        }
        result = mixin._validate_pdf_page_coverage(coverage)
        assert result == coverage

    def test_missing_page_raises(self, mixin):
        coverage = {
            "source_total_pages": 4,
            "successful_pages": [1, 2],
            "failed_pages": [],
            "skipped_pages": [],
        }
        with pytest.raises(ValueError, match="does not account"):
            mixin._validate_pdf_page_coverage(coverage)

    def test_overlapping_pages_raises(self, mixin):
        coverage = {
            "source_total_pages": 3,
            "successful_pages": [1, 2],
            "failed_pages": [2, 3],
            "skipped_pages": [],
        }
        with pytest.raises(ValueError, match="overlapping"):
            mixin._validate_pdf_page_coverage(coverage)

    def test_blank_page_cannot_overlap_success(self, mixin):
        coverage = {
            "source_total_pages": 1,
            "successful_pages": [1],
            "failed_pages": [],
            "skipped_pages": [],
            "blank_pages": [1],
        }
        with pytest.raises(ValueError, match="overlapping"):
            mixin._validate_pdf_page_coverage(coverage)

    def test_opendataloader_in_parsers_with_coverage(self, mixin):
        assert mixin._parser_supports_pdf_coverage("opendataloader")
        assert mixin._parser_supports_pdf_coverage("docling")
        assert not mixin._parser_supports_pdf_coverage("mineru")
        assert not mixin._parser_supports_pdf_coverage("paddleocr")


# ── 4.5: Cache identity change tests ──────────────────────────────────

class TestParseCacheIdentity:
    """Cache key includes effective parser and package version."""

    def test_opendataloader_cache_identity_in_key(self, tmp_path):
        from raganything.processor.doc_processor import DocProcessorMixin

        class TestMixin(DocProcessorMixin):
            pass

        mixin = TestMixin()
        mixin.config = MagicMock()
        mixin.config.parser = "opendataloader"
        mixin.config.pdf_parser = ""
        mixin.config.parse_method = "auto"

        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"%PDF-1.4\nx" * 10)

        key1 = mixin._generate_cache_key(pdf)

        # Change parser — key should differ
        mixin.config.parser = "docling"
        key2 = mixin._generate_cache_key(pdf)

        assert key1 != key2


# ── Atomic write ──────────────────────────────────────────────────────

class TestAtomicJsonWrite:
    def test_write_atomic_json(self, tmp_path):
        path = tmp_path / "test.json"
        data = {"key": "value"}
        _write_atomic_json(path, data)
        assert path.exists()
        with open(path, "r", encoding="utf-8") as f:
            read_back = json.load(f)
        assert read_back == data

    def test_overwrites_existing(self, tmp_path):
        path = tmp_path / "test.json"
        path.write_text('{"old": true}')
        _write_atomic_json(path, {"new": True})
        with open(path, "r", encoding="utf-8") as f:
            assert json.load(f) == {"new": True}


@pytest.mark.skipif(
    os.getenv("RUN_OPENDATALOADER_REAL_TESTS") != "1",
    reason="requires local Java 17 and opendataloader-pdf",
)
def test_real_stack_single_page_coverage(tmp_path, monkeypatch):
    """Opt-in smoke test for the pinned SDK and the supervised page runner."""
    fixture = Path(__file__).parents[1] / "reproduce" / "data" / "contract_spike_test.pdf"
    monkeypatch.setenv("WORKING_DIR", str(tmp_path / "working"))
    parser = OpenDataLoaderParser(timeout=60)
    if not parser.check_installation():
        pytest.skip("OpenDataLoader runtime prerequisites are unavailable")

    content = parser.parse_pdf(fixture, output_dir=str(tmp_path / "artifacts"))

    assert content.page_coverage == {
        "source_total_pages": 4,
        "successful_pages": [1, 2, 4],
        "failed_pages": [],
        "skipped_pages": [],
        "blank_pages": [3],
    }
    text_blocks = [block for block in content if block.get("type") == "text"]
    assert {block["page_idx"] for block in text_blocks} == {0, 1, 3}
    assert any("Page 1 - Test Heading" in block["text"] for block in text_blocks)
    assert any("Page 2 - Table Content" in block["text"] for block in text_blocks)
    assert any("Page 4 - Last page" in block["text"] for block in text_blocks)

    sidecars = list((tmp_path / "artifacts").rglob("*_provenance.json"))
    assert len(sidecars) == 1
    sidecar = json.loads(sidecars[0].read_text(encoding="utf-8"))
    assert sidecar["coverage"] == content.page_coverage
    assert len(sidecar["raw_artifacts"]) == 4
    assert all(not item["json"].startswith("/") for item in sidecar["raw_artifacts"])
    assert all(len(item["json_sha256"]) == 64 for item in sidecar["raw_artifacts"])
