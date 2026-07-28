#!/usr/bin/env python3
"""Probe the pinned SDK's single-page artifact contract without modifying source output."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any


def _page_numbers(elements: list[Any]) -> set[int]:
    pages: set[int] = set()
    stack = list(elements)
    while stack:
        element = stack.pop()
        if not isinstance(element, dict):
            continue
        if isinstance(element.get("page number"), int):
            pages.add(element["page number"])
        for key in ("kids", "children", "list items"):
            if isinstance(element.get(key), list):
                stack.extend(element[key])
    return pages


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _one_page(convert, pdf: Path, output: Path, page: int) -> dict[str, Any]:
    page_dir = output / f"page-{page:04d}"
    page_dir.mkdir(parents=True, exist_ok=False)
    convert(
        input_path=str(pdf),
        output_dir=str(page_dir),
        format=["json", "markdown"],
        quiet=True,
        use_struct_tree=True,
        image_output="external",
        image_format="png",
        table_method="default",
        reading_order="xycut",
        pages=str(page),
        threads="1",
    )
    json_files = sorted(page_dir.rglob("*.json"))
    markdown_files = sorted(page_dir.rglob("*.md"))
    if len(json_files) != 1 or len(markdown_files) != 1:
        raise RuntimeError(f"page {page}: expected one JSON and one Markdown artifact")
    data = json.loads(json_files[0].read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("kids"), list):
        raise RuntimeError(f"page {page}: invalid JSON schema")
    seen = _page_numbers(data["kids"])
    if seen and seen != {page}:
        raise RuntimeError(f"page {page}: output contains pages {sorted(seen)}")
    return {
        "page": page,
        "state": "blank" if not data["kids"] else "success",
        "reported_page_count": data.get("number of pages"),
        "element_pages": sorted(seen),
        "top_level_element_types": [
            item.get("type") for item in data["kids"] if isinstance(item, dict)
        ],
        "json": str(json_files[0].relative_to(output).as_posix()),
        "json_sha256": _sha256(json_files[0]),
        "markdown": str(markdown_files[0].relative_to(output).as_posix()),
        "markdown_sha256": _sha256(markdown_files[0]),
    }


def main() -> int:
    fixture_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", type=Path, default=fixture_dir / "contract_spike_test.pdf")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    from pypdf import PdfReader
    from opendataloader_pdf import convert

    pdf = args.pdf.resolve()
    output = args.output.resolve() if args.output else Path(tempfile.mkdtemp(prefix="odl-contract-"))
    source_pages = len(PdfReader(str(pdf)).pages)
    results: list[dict[str, Any]] = []
    for page in range(1, source_pages + 1):
        results.append(_one_page(convert, pdf, output, page))

    report = {
        "sdk": "opendataloader-pdf==2.5.0",
        "source": pdf.name,
        "source_total_pages": source_pages,
        "pages": results,
    }
    report_path = output / "contract-report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"Artifacts: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
