"""Regression coverage for the reproducible OpenDataLoader contract probe."""

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pypdf import PdfReader


_SCRIPT = Path(__file__).parents[1] / "scripts" / "opendataloader_contract_probe.py"
_SPEC = importlib.util.spec_from_file_location("odl_contract_probe", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)


def test_synthetic_contract_fixture_is_reproducible_and_has_blank_page(tmp_path):
    fixture = tmp_path / "contract.pdf"
    expected = probe._make_fixture(fixture)

    assert len(PdfReader(str(fixture)).pages) == 5
    assert expected["page_1"][:3] == [
        "TOP_MARKER_LIST",
        "LIST_ITEM_ALPHA",
        "LIST_ITEM_BETA",
    ]
    assert expected["page_5"] == []


@pytest.mark.skipif(
    os.getenv("RUN_OPENDATALOADER_REAL_TESTS") != "1",
    reason="requires opendataloader-pdf==2.5.0 and local Java 17",
)
def test_real_contract_probe_records_page_proof_and_schema(tmp_path):
    output = tmp_path / "probe"
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--output", str(output)],
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads((output / "contract-report.json").read_text("utf-8"))

    assert report["sdk"] == "opendataloader-pdf==2.5.0"
    assert [page["state"] for page in report["pages"]] == [
        "content",
        "content",
        "content",
        "content",
        "blank",
    ]
    assert [page["element_pages"] for page in report["pages"]] == [
        [1],
        [2],
        [3],
        [4],
        [],
    ]
    expected_types = {
        1: {"list", "list item"},
        2: {"table"},
        3: {"image"},
        4: {"paragraph"},
        5: set(),
    }
    for page in report["pages"]:
        page_number = page["page"]
        types = {element["type"] for element in page["elements"]}
        assert expected_types[page_number] <= types
        assert set(report["fixture"]["proof_markers"][f"page_{page_number}"]) <= set(
            page["observed_markers"]
        )
        assert page["json_artifact_count"] == 1
        assert page["markdown_artifact_count"] == 1
        assert Path(page["json"]).parent == Path(f"page-{page_number:04d}")
        assert Path(page["markdown"]).parent == Path(f"page-{page_number:04d}")

    assert len({page["json"] for page in report["pages"]}) == 5
    assert len({page["markdown"] for page in report["pages"]}) == 5
    blank_page = report["pages"][-1]
    assert blank_page["observed_markers"] == []
    assert blank_page["markdown_sha256"] == hashlib.sha256(b"").hexdigest()
    assert report["bbox_observation"]["interpretation"].startswith("Raw SDK bbox values")
    assert report["negative_preflight"]["malformed"] != "accepted"
    assert report["negative_preflight"]["encrypted"] != "accepted"
