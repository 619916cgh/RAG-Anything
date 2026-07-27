#!/usr/bin/env python3
"""Generate and probe the pinned OpenDataLoader PDF artifact contract.

This script is intentionally opt-in: it imports the optional SDK and starts a
local JVM.  It creates a synthetic, non-sensitive PDF with known positions and
semantic inputs, converts every page through the public ``convert`` API one at
a time, and writes a bounded JSON report with only artifact identities and
schema observations.  Raw converter output stays in the selected output
directory/CI artifact and is never committed as release evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


_SDK = "opendataloader-pdf"
_VERSION = "2.5.0"
_CONVERT_OPTIONS = {
    "format": ["json", "markdown"],
    "quiet": True,
    "use_struct_tree": True,
    "image_output": "external",
    "image_format": "png",
    "table_method": "default",
    "reading_order": "xycut",
    "threads": "1",
}

# These are deliberately plain ASCII tokens so their presence can be checked
# without depending on font shaping or OCR.  They are evidence for the output
# of this synthetic fixture only; they are not a general quality metric.
_PAGE_PROOF_MARKERS = {
    1: ("TOP_MARKER_LIST", "LIST_ITEM_ALPHA", "LIST_ITEM_BETA", "BOTTOM_MARKER_LIST"),
    2: ("TABLE_MARKER",),
    3: ("IMAGE_MARKER",),
    4: ("FORMULA_MARKER",),
    5: (),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _java_version() -> str:
    java = shutil.which("java")
    if not java:
        java_home = os.environ.get("JAVA_HOME")
        if java_home:
            candidate = (
                Path(java_home) / "bin" / ("java.exe" if os.name == "nt" else "java")
            )
            if candidate.is_file():
                java = str(candidate)
    if not java:
        return "missing"
    completed = subprocess.run(
        [java, "-version"], capture_output=True, text=True, check=False, timeout=15
    )
    text = (completed.stderr or completed.stdout).splitlines()
    return text[0][:200] if text else "unreported"


def _make_fixture(path: Path) -> dict[str, list[str]]:
    """Create a five-page, non-sensitive PDF with known semantic inputs."""
    from PIL import Image as PillowImage
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Table

    styles = getSampleStyleSheet()
    normal = styles["BodyText"]
    image_path = path.with_suffix(".png")
    PillowImage.new("RGB", (48, 48), color=(0, 80, 200)).save(image_path)
    story: list[Any] = [
        Paragraph("TOP_MARKER_LIST", styles["Heading2"]),
        Paragraph("• LIST_ITEM_ALPHA", normal),
        Paragraph("• LIST_ITEM_BETA", normal),
        Paragraph("BOTTOM_MARKER_LIST", normal),
        PageBreak(),
        Paragraph("TABLE_MARKER", styles["Heading2"]),
    ]
    table = Table(
        [["H_A", "H_B"], ["CELL_ALPHA", "CELL_BETA"], ["CELL_GAMMA", "CELL_DELTA"]],
        colWidths=[2 * inch, 2 * inch],
    )
    table.setStyle(
        [
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ]
    )
    story.extend(
        [
            table,
            PageBreak(),
            Paragraph("IMAGE_MARKER", styles["Heading2"]),
            Image(str(image_path), width=1 * inch, height=1 * inch),
            PageBreak(),
            Paragraph("FORMULA_MARKER", styles["Heading2"]),
            Paragraph("E = mc<super>2</super>", normal),
            PageBreak(),
            PageBreak(),
        ]
    )
    SimpleDocTemplate(str(path), pagesize=letter).build(story)
    return {
        "page_1": [
            "TOP_MARKER_LIST",
            "LIST_ITEM_ALPHA",
            "LIST_ITEM_BETA",
            "BOTTOM_MARKER_LIST",
        ],
        "page_2": ["TABLE_MARKER", "H_A", "CELL_ALPHA"],
        "page_3": ["IMAGE_MARKER"],
        "page_4": ["FORMULA_MARKER", "E = mc2"],
        "page_5": [],
    }


def _walk(elements: list[Any], markers: tuple[str, ...]) -> list[dict[str, Any]]:
    observed: list[dict[str, Any]] = []
    stack = list(elements)
    while stack:
        element = stack.pop()
        if not isinstance(element, dict):
            continue
        bbox = element.get("bbox") or element.get("bounding box")
        text = str(element.get("text") or element.get("content") or "")
        observed.append(
            {
                "type": str(element.get("type") or ""),
                "page": element.get("page number"),
                "bbox": bbox if isinstance(bbox, list) and len(bbox) == 4 else None,
                "field_names": sorted(str(key) for key in element)[:32],
                "has_table_fields": any("table" in str(key).lower() for key in element),
                "has_image_fields": any("image" in str(key).lower() for key in element),
                "has_formula_fields": any(
                    "formula" in str(key).lower() for key in element
                ),
                "text_markers": [marker for marker in markers if marker in text],
            }
        )
        for key in ("kids", "children", "list items"):
            value = element.get(key)
            if isinstance(value, list):
                stack.extend(value)
    return observed


def _probe_page(
    convert: Any, pdf: Path, output: Path, page: int, markers: tuple[str, ...]
) -> dict[str, Any]:
    page_dir = output / f"page-{page:04d}"
    page_dir.mkdir(parents=True, exist_ok=False)
    convert(
        input_path=str(pdf),
        output_dir=str(page_dir),
        pages=str(page),
        **_CONVERT_OPTIONS,
    )
    json_files = sorted(page_dir.rglob("*.json"))
    markdown_files = sorted(page_dir.rglob("*.md"))
    if len(json_files) != 1 or len(markdown_files) != 1:
        raise RuntimeError(
            f"page {page}: expected exactly one JSON and Markdown artifact"
        )
    data = json.loads(json_files[0].read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("kids"), list):
        raise RuntimeError(f"page {page}: JSON root must contain a kids list")
    observed = _walk(data["kids"], markers)
    observed_pages = sorted(
        {item["page"] for item in observed if isinstance(item["page"], int)}
    )
    if observed_pages and observed_pages != [page]:
        raise RuntimeError(f"page {page}: page marker mismatch: {observed_pages}")
    return {
        "page": page,
        "state": "blank" if not data["kids"] else "content",
        "reported_page_count": data.get("number of pages"),
        "element_pages": observed_pages,
        "json": json_files[0].relative_to(output).as_posix(),
        "json_artifact_count": len(json_files),
        "json_sha256": _sha256(json_files[0]),
        "markdown": markdown_files[0].relative_to(output).as_posix(),
        "markdown_artifact_count": len(markdown_files),
        "markdown_sha256": _sha256(markdown_files[0]),
        "observed_markers": sorted(
            {
                marker
                for element in observed
                for marker in element["text_markers"]
            }
        ),
        "elements": observed,
    }


def _bbox_observation(pages: list[dict[str, Any]]) -> dict[str, Any]:
    """Record fixture bbox values without assigning coordinate semantics."""
    marker_bboxes: dict[str, list[Any]] = {}
    for element in pages[0].get("elements", []):
        bbox = element.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        for marker in element.get("text_markers", []):
            marker_bboxes[marker] = bbox
    return {
        "marker_bboxes": marker_bboxes,
        "interpretation": (
            "Raw SDK bbox values only; this probe does not assert units, axis origin, "
            "or bbox field ordering."
        ),
    }


def _negative_preflight(fixture: Path, output: Path) -> dict[str, str]:
    """Record deterministic local preflight behaviour for invalid PDFs."""
    from pypdf import PdfReader, PdfWriter

    malformed = output / "malformed.pdf"
    malformed.write_bytes(fixture.read_bytes()[:96])
    encrypted = output / "encrypted.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt("contract-only")
    with encrypted.open("wb") as handle:
        writer.write(handle)
    results: dict[str, str] = {}
    for name, candidate in {"malformed": malformed, "encrypted": encrypted}.items():
        try:
            reader = PdfReader(str(candidate))
            _ = len(reader.pages)
            results[name] = "accepted"
        except Exception as exc:  # report class only; never record user content
            results[name] = type(exc).__name__
    # Verify the generated fixture itself remains readable.
    results["fixture_pages"] = str(len(PdfReader(str(fixture)).pages))
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        help="empty output directory; defaults to a temp directory",
    )
    args = parser.parse_args()
    if importlib.metadata.version(_SDK) != _VERSION:
        raise RuntimeError(f"requires {_SDK}=={_VERSION}")
    output = (
        args.output.resolve()
        if args.output
        else Path(tempfile.mkdtemp(prefix="odl-contract-"))
    )
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise RuntimeError("output directory must be empty")
    fixture = output / "synthetic-contract.pdf"
    expected = _make_fixture(fixture)
    from pypdf import PdfReader
    from opendataloader_pdf import convert

    source_pages = len(PdfReader(str(fixture)).pages)
    pages = [
        _probe_page(convert, fixture, output, page, _PAGE_PROOF_MARKERS[page])
        for page in range(1, source_pages + 1)
    ]
    report = {
        "schema": "opendataloader-contract-probe-v1",
        "sdk": f"{_SDK}=={_VERSION}",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "java": _java_version(),
        "fixture": {
            "sha256": _sha256(fixture),
            "pages": source_pages,
            "expected_markers": expected,
            "proof_markers": {
                f"page_{page}": list(markers)
                for page, markers in _PAGE_PROOF_MARKERS.items()
            },
        },
        "convert_options": _CONVERT_OPTIONS,
        "pages": pages,
        "bbox_observation": _bbox_observation(pages),
        "negative_preflight": _negative_preflight(fixture, output),
    }
    report_path = output / "contract-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
