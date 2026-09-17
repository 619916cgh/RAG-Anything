"""Supervised RapidOCR child for OpenDataLoader scanned-page recovery."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from raganything.parser.opendataloader_parser import (
    ODLOcrError,
    OpenDataLoaderParser,
)

_REQUEST_SCHEMA = "odl-ocr-runner-request-v1"
_RESULT_SCHEMA = "odl-ocr-runner-result-v1"


def _write_result(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=path.name,
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=False, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _load_request(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as source:
        payload = json.load(source)
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != _REQUEST_SCHEMA
    ):
        raise ValueError("invalid OCR runner request schema")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    args = parser.parse_args()
    request_path = Path(args.request).resolve()
    result_path = request_path.parent / "ocr-result.json"

    payload: dict[str, Any]
    try:
        request = _load_request(request_path)
        pdf_path = Path(str(request["source_pdf"])).resolve(strict=True)
        pages = [int(page) for page in request["pages"]]
        render_scale = float(request["render_scale"])
        text_score = float(request["text_score"])
        engine = OpenDataLoaderParser._load_ocr_engine()
        page_results = []
        for page in pages:
            lines = OpenDataLoaderParser._ocr_page_lines(
                engine,
                pdf_path,
                page,
                render_scale=render_scale,
                text_score=text_score,
            )
            page_results.append({"page": page, "lines": lines})
        payload = {
            "schema_version": _RESULT_SCHEMA,
            "pages": page_results,
        }
    except ODLOcrError as exc:
        payload = {
            "schema_version": _RESULT_SCHEMA,
            "error": {
                "failure_code": exc.failure_code,
            },
        }
    except Exception:
        payload = {
            "schema_version": _RESULT_SCHEMA,
            "error": {
                "failure_code": "odl_ocr_failed",
            },
        }

    try:
        _write_result(result_path, payload)
    except Exception:
        return 1
    return 1 if payload.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
