"""Fail-closed supervision tests for the OpenDataLoader page runner."""

from __future__ import annotations

import hashlib
import json
import signal
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

import raganything.parser.opendataloader_parser as odl_module
from raganything.parser.opendataloader_parser import (
    ODLConversionError,
    ODLValidationError,
    OpenDataLoaderParser,
)


def _java_bin(tmp_path: Path) -> Path:
    java_bin = tmp_path / "jdk" / "bin" / "java.exe"
    java_bin.parent.mkdir(parents=True)
    java_bin.write_bytes(b"")
    return java_bin


def _runner_args(tmp_path: Path) -> tuple[Path, Path, Path]:
    return tmp_path / "input.pdf", tmp_path / "page", _java_bin(tmp_path)


def test_timeout_terminates_runner_and_fails_closed(monkeypatch, tmp_path):
    parser = OpenDataLoaderParser()
    source_pdf, page_dir, java_bin = _runner_args(tmp_path)
    process = MagicMock()
    process.wait.side_effect = subprocess.TimeoutExpired("runner", 0.01)
    terminated = []

    monkeypatch.setattr(odl_module.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        OpenDataLoaderParser,
        "_terminate_process_tree",
        staticmethod(lambda candidate: terminated.append(candidate)),
    )

    # Other parser tests reload this optional module, so resolve the exception
    # from the current module object rather than a stale imported class.
    with pytest.raises(odl_module.ODLConversionError, match="timed out"):
        parser._run_single_page_runner(source_pdf, page_dir, 1, 1, 0.01, java_bin)

    assert terminated == [process]
    assert (page_dir / "runner-request.json").is_file()
    assert not (page_dir / "runner-result.json").exists()


def test_runner_environment_excludes_worker_secrets(monkeypatch, tmp_path):
    parser = OpenDataLoaderParser()
    source_pdf, page_dir, java_bin = _runner_args(tmp_path)
    process = MagicMock()
    process.wait.return_value = 0
    captured = {}

    def fake_popen(*args, **kwargs):
        captured.update(kwargs["env"])
        result_path = page_dir / "runner-result.json"
        result_path.write_text("{}", encoding="utf-8")
        return process

    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-runner")
    monkeypatch.setattr(odl_module.subprocess, "Popen", fake_popen)

    with pytest.raises(odl_module.ODLValidationError):
        parser._run_single_page_runner(source_pdf, page_dir, 1, 1, 1, java_bin)

    assert "OPENAI_API_KEY" not in captured
    assert captured["JAVA_HOME"] == str(java_bin.parent.parent)


def test_windows_tree_kill_waits_for_runner_exit(monkeypatch):
    process = MagicMock(pid=4321)
    process.poll.return_value = None
    process.wait.return_value = None
    completed = MagicMock(returncode=0)

    run = MagicMock(return_value=completed)
    monkeypatch.setattr(odl_module.subprocess, "run", run)

    original_name = odl_module.os.name
    odl_module.os.name = "nt"
    try:
        OpenDataLoaderParser._terminate_process_tree(process)
    finally:
        odl_module.os.name = original_name

    run.assert_called_once_with(
        ["taskkill", "/PID", "4321", "/T", "/F"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
    )
    process.wait.assert_called_once_with(timeout=10)


def test_windows_tree_kill_failure_fails_closed(monkeypatch):
    process = MagicMock(pid=4321)
    process.poll.return_value = None

    monkeypatch.setattr(
        odl_module.subprocess, "run", lambda *args, **kwargs: MagicMock(returncode=1)
    )

    original_name = odl_module.os.name
    odl_module.os.name = "nt"
    try:
        with pytest.raises(odl_module.ODLConversionError, match="process-tree termination failed"):
            OpenDataLoaderParser._terminate_process_tree(process)
    finally:
        odl_module.os.name = original_name

    process.wait.assert_not_called()


def test_posix_tree_kill_escalates_to_sigkill(monkeypatch):
    process = MagicMock(pid=1234)
    process.poll.return_value = None
    process.wait.side_effect = [subprocess.TimeoutExpired("runner", 5), None]
    killpg = MagicMock()

    monkeypatch.setattr(odl_module.os, "killpg", killpg, raising=False)
    monkeypatch.setattr(odl_module.signal, "SIGKILL", 9, raising=False)

    original_name = odl_module.os.name
    odl_module.os.name = "posix"
    try:
        OpenDataLoaderParser._terminate_process_tree(process)
    finally:
        odl_module.os.name = original_name

    assert killpg.call_args_list == [
        ((1234, signal.SIGTERM),),
        ((1234, signal.SIGKILL),),
    ]
    assert process.wait.call_args_list == [
        call(timeout=5),
        call(timeout=10),
    ]


def test_missing_runner_result_fails_closed(monkeypatch, tmp_path):
    parser = OpenDataLoaderParser()
    source_pdf, page_dir, java_bin = _runner_args(tmp_path)
    process = MagicMock()
    process.wait.return_value = 0

    monkeypatch.setattr(odl_module.subprocess, "Popen", lambda *args, **kwargs: process)

    with pytest.raises(odl_module.ODLValidationError, match="valid result metadata"):
        parser._run_single_page_runner(source_pdf, page_dir, 1, 1, 1, java_bin)


def test_tampered_runner_artifact_hash_fails_closed(monkeypatch, tmp_path):
    parser = OpenDataLoaderParser()
    source_pdf, page_dir, java_bin = _runner_args(tmp_path)
    process = MagicMock()
    process.wait.return_value = 0

    def fake_popen(*args, **kwargs):
        request_path = Path(args[0][-1])
        output_root = request_path.parent
        json_path = output_root / "page.json"
        markdown_path = output_root / "page.md"
        json_path.write_text(
            json.dumps({"file name": "input.pdf", "number of pages": 1, "kids": []}),
            encoding="utf-8",
        )
        markdown_path.write_text("# page\n", encoding="utf-8")
        markdown_hash = hashlib.sha256(markdown_path.read_bytes()).hexdigest()
        (output_root / "runner-result.json").write_text(
            json.dumps(
                {
                    "schema_version": "opendataloader-runner-result-v1",
                    "pages": [
                        {
                            "page": 1,
                            "state": "blank",
                            "json_relpath": "page.json",
                            "json_sha256": "0" * 64,
                            "markdown_relpath": "page.md",
                            "markdown_sha256": markdown_hash,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return process

    monkeypatch.setattr(odl_module.subprocess, "Popen", fake_popen)

    with pytest.raises(odl_module.ODLValidationError, match="artifact identity check failed"):
        parser._run_single_page_runner(source_pdf, page_dir, 1, 1, 1, java_bin)


@pytest.mark.asyncio
async def test_worker_does_not_fallback_or_retry_odl_conversion_failure(
    monkeypatch, tmp_path, capsys
):
    import io
    import sys

    module = sys.modules.get("process_worker")
    if module is None:
        original_stdout = sys.stdout
        sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        try:
            import process_worker as module
        finally:
            sys.stdout = original_stdout

    pdf_path = tmp_path / "input.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    calls = []

    class FakeRAG:
        config = SimpleNamespace(pdf_parser="opendataloader")

        def disable_atexit_cleanup(self):
            return None

        async def _ensure_lightrag_initialized(self):
            return None

        async def process_document_complete(self, *args, **kwargs):
            raise ODLConversionError("OpenDataLoader page 1 timed out")

        async def finalize_storages(self):
            return None

        async def insert_content_list(self, *args, **kwargs):
            calls.append("insert")

    async def create_rag(*args, **kwargs):
        return FakeRAG()

    async def no_preflight(*args, **kwargs):
        return None

    async def no_vlm(*args, **kwargs):
        calls.append("vlm")
        return "unexpected"

    monkeypatch.setenv("WORKING_DIR", str(tmp_path / "working"))
    monkeypatch.setattr(module, "kb_dir", lambda name: tmp_path / "kb")
    monkeypatch.setattr(module, "create_rag", create_rag)
    monkeypatch.setattr(module, "_preflight_embedding_service", no_preflight)
    monkeypatch.setattr(module, "_vlm_ocr_document", no_vlm)
    monkeypatch.setattr(module, "_fix_stuck_doc", lambda *args, **kwargs: None)

    exit_code = await module.process_file(str(pdf_path), "odl")

    assert exit_code == 1
    assert calls == []
    error_lines = [
        line
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("WORKER_ERROR_JSON ")
    ]
    assert len(error_lines) == 1
    payload = json.loads(error_lines[0].removeprefix("WORKER_ERROR_JSON "))
    assert payload["stage"] == "parsing"
    assert payload["failure_code"] == "odl_conversion"
    assert payload["retryable"] is False


def test_parent_preserves_terminal_odl_worker_payload():
    from raganything.services.kb_service import WorkerProcessError, _parse_worker_error

    payload = {
        "stage": "parsing",
        "root_type": "ODLConversionError",
        "failure_code": "odl_conversion",
        "retryable": False,
        "message": "OpenDataLoader page 1 timed out",
        "secondary": [],
    }
    parsed = _parse_worker_error(
        ["unrelated cleanup warning", "WORKER_ERROR_JSON " + json.dumps(payload)],
        1,
    )
    error = WorkerProcessError(parsed)

    assert error.stage == "parsing"
    assert error.failure_code == "odl_conversion"
    assert error.retryable is False
