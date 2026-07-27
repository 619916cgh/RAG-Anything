import json
import sys
from types import ModuleType

import pytest

from raganything.parser.opendataloader_runner import (
    _contained,
    _discard_conversion_outputs,
    _output_size,
    _validate_page_json,
)
import raganything.parser.opendataloader_runner as runner


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


@pytest.mark.skipif(
    not hasattr(__import__("os"), "symlink"), reason="symlink unsupported"
)
def test_runner_page_json_symlink_is_rejected(tmp_path):
    target = _write_page_json(tmp_path, [])
    link = tmp_path / "link.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError, match="regular file"):
        runner._validate_page_json(link, 1)


@pytest.mark.skipif(
    not hasattr(__import__("os"), "symlink"), reason="symlink unsupported"
)
def test_runner_containment_rejects_symlink_even_inside_root(tmp_path):
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "artifact.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError, match="symbolic link"):
        _contained(link, tmp_path)


def test_runner_propagates_fixed_fast_local_options_and_heap(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\nfixture")
    output = tmp_path / "output"
    output.mkdir()
    request = output / "runner-request.json"
    request.write_text(
        json.dumps(
            {
                "schema_version": "opendataloader-runner-request-v1",
                "source_pdf": str(source),
                "output_root": str(output),
                "source_total_pages": 1,
                "page": 1,
                "java_heap": "-Xmx256m",
                "max_output_bytes": 4096,
            }
        ),
        encoding="utf-8",
    )
    captured = {}

    def fake_convert(**kwargs):
        captured.update(kwargs)
        (output / "page.json").write_text(
            json.dumps({"file name": "source.pdf", "number of pages": 1, "kids": []}),
            encoding="utf-8",
        )
        (output / "page.md").write_text("", encoding="utf-8")

    monkeypatch.setitem(
        sys.modules, "opendataloader_pdf", ModuleType("opendataloader_pdf")
    )
    sys.modules["opendataloader_pdf"].convert = fake_convert

    assert runner._run(request) == 0
    assert captured["pages"] == "1"
    assert captured["threads"] == "1"
    assert captured["format"] == ["json", "markdown"]
    assert captured["quiet"] is True
    assert captured["use_struct_tree"] is True
    assert captured["image_output"] == "external"
    assert captured["table_method"] == "default"
    assert captured["reading_order"] == "xycut"
    assert "content_safety_off" not in captured
    assert "hybrid" not in captured
    assert "remote" not in captured
    assert runner.os.environ["JAVA_TOOL_OPTIONS"] == "-Xmx256m"


def test_runner_output_limit_returns_structured_failure(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\nfixture")
    output = tmp_path / "output"
    output.mkdir()
    request = output / "runner-request.json"
    request.write_text(
        json.dumps(
            {
                "schema_version": "opendataloader-runner-request-v1",
                "source_pdf": str(source),
                "output_root": str(output),
                "source_total_pages": 1,
                "page": 1,
                "java_heap": "-Xmx256m",
                "max_output_bytes": 1,
            }
        ),
        encoding="utf-8",
    )

    def fake_convert(**_kwargs):
        (output / "page.json").write_text(
            json.dumps({"file name": "source.pdf", "number of pages": 1, "kids": []}),
            encoding="utf-8",
        )
        (output / "page.md").write_text("x", encoding="utf-8")

    module = ModuleType("opendataloader_pdf")
    module.convert = fake_convert
    monkeypatch.setitem(sys.modules, "opendataloader_pdf", module)

    assert runner._run(request) == 1
    result = json.loads((output / "runner-result.json").read_text(encoding="utf-8"))
    assert result["pages"][0]["state"] == "failed"
    assert not (output / "page.json").exists()


def test_runner_sdk_exception_returns_bounded_structured_failure(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\nfixture")
    output = tmp_path / "output"
    output.mkdir()
    request = output / "runner-request.json"
    request.write_text(
        json.dumps(
            {
                "schema_version": "opendataloader-runner-request-v1",
                "source_pdf": str(source),
                "output_root": str(output),
                "source_total_pages": 1,
                "page": 1,
                "java_heap": "-Xmx256m",
                "max_output_bytes": 4096,
            }
        ),
        encoding="utf-8",
    )

    def fail_convert(**_kwargs):
        raise RuntimeError("untrusted document body must not be emitted")

    module = ModuleType("opendataloader_pdf")
    module.convert = fail_convert
    monkeypatch.setitem(sys.modules, "opendataloader_pdf", module)

    assert runner._run(request) == 1
    result = json.loads((output / "runner-result.json").read_text(encoding="utf-8"))
    assert result["pages"] == [
        {"page": 1, "state": "failed", "failure": "RuntimeError"}
    ]
    assert "untrusted document body" not in json.dumps(result)


def test_runner_rejects_invalid_request_manifest(tmp_path):
    request = tmp_path / "runner-request.json"
    request.write_text(json.dumps({"schema_version": "unknown"}), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported runner request schema"):
        runner._run(request)
