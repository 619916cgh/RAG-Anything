import json

import pytest

from raganything.parser.opendataloader_runner import (
    _discard_conversion_outputs,
    _output_size,
    _validate_page_json,
)


def _write_page_json(tmp_path, kids):
    path = tmp_path / "page.json"
    path.write_text(
        json.dumps({"file name": "input.pdf", "number of pages": 4, "kids": kids}),
        encoding="utf-8",
    )
    return path


def test_runner_accepts_a_single_requested_page(tmp_path):
    json_path = _write_page_json(
        tmp_path, [{"type": "paragraph", "page number": 2, "content": "ok"}]
    )

    _, count = _validate_page_json(json_path, 2)

    assert count == 1


def test_runner_rejects_output_from_another_page(tmp_path):
    json_path = _write_page_json(
        tmp_path, [{"type": "paragraph", "page number": 1, "content": "wrong"}]
    )

    with pytest.raises(ValueError, match="another page"):
        _validate_page_json(json_path, 2)


def test_runner_accepts_explicit_blank_page_artifact(tmp_path):
    json_path = _write_page_json(tmp_path, [])

    _, count = _validate_page_json(json_path, 3)

    assert count == 0


def test_runner_output_limit_helpers_remove_sdk_artifacts(tmp_path):
    (tmp_path / "runner-request.json").write_text("{}", encoding="utf-8")
    artifact = tmp_path / "generated.bin"
    artifact.write_bytes(b"x" * 128)

    assert _output_size(tmp_path) >= 128

    _discard_conversion_outputs(tmp_path)

    assert (tmp_path / "runner-request.json").is_file()
    assert not artifact.exists()
