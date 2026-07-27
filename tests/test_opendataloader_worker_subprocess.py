"""New-process worker regressions for the OpenDataLoader PDF override."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


PROJECT_ROOT = Path(__file__).parents[1]


def _run_child(script: str, *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(PROJECT_ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    )


def _last_json_line(output: str, prefix: str) -> dict:
    lines = [line for line in output.splitlines() if line.startswith(prefix)]
    assert len(lines) == 1, output
    return json.loads(lines[0].removeprefix(prefix))


def test_new_process_worker_reads_pdf_parser_override(tmp_path):
    script = """
import asyncio
import json
import os
import process_worker as worker
from raganything.services import kb_service

class CaptureRAG:
    def __init__(self, **kwargs):
        self.config = kwargs['config']

worker.RAGAnything = CaptureRAG
worker.make_cached_embed_func = lambda func, *_args: func
kb_service._pg_storage_ready = lambda: False

rag = asyncio.run(worker.create_rag(working_dir=os.environ['WORKING_DIR']))
print('RESULT_JSON ' + json.dumps({'parser': rag.config.parser, 'pdf_parser': rag.config.pdf_parser}))
"""
    env = {
        **os.environ,
        "WORKING_DIR": str(tmp_path / "worker-store"),
        "PDF_PARSER": "opendataloader",
        "PARSER": "mineru",
    }

    result = _run_child(script, env=env)

    assert result.returncode == 0, result.stderr
    assert _last_json_line(result.stdout, "RESULT_JSON ") == {
        "parser": "mineru",
        "pdf_parser": "opendataloader",
    }


@pytest.mark.parametrize(
    ("exception_class", "failure_code"),
    [
        ("ODLConversionError", "odl_conversion"),
        ("ODLPageCoverageError", "pdf_page_coverage_incomplete"),
        ("ODLPreflightError", "odl_preflight"),
    ],
)
def test_new_process_odl_failure_is_terminal_and_inserts_no_partial_chunks(
    tmp_path, exception_class, failure_code
):
    source = tmp_path / "input.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    script = f"""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import process_worker as worker
from raganything.parser.opendataloader_parser import (
    ODLConversionError, ODLPageCoverageError, ODLPreflightError,
)

calls = []
class FakeRAG:
    config = SimpleNamespace(pdf_parser='opendataloader')
    def disable_atexit_cleanup(self): pass
    async def _ensure_lightrag_initialized(self): pass
    async def process_document_complete(self, *_args, **_kwargs):
        raise {exception_class}('parser stage failed')
    async def finalize_storages(self): pass
    async def insert_content_list(self, *_args, **_kwargs):
        calls.append('insert')

async def create_rag(*_args, **_kwargs): return FakeRAG()
async def no_preflight(*_args, **_kwargs): return None
async def no_vlm(*_args, **_kwargs): return 'unexpected'

worker.kb_dir = lambda _name: Path({str(tmp_path / "kb")!r})
worker.create_rag = create_rag
worker._preflight_embedding_service = no_preflight
worker._vlm_ocr_document = no_vlm
worker._fix_stuck_doc = lambda *_args, **_kwargs: None
code = asyncio.run(worker.process_file({str(source)!r}, 'odl'))
print('RESULT_JSON ' + json.dumps({{'exit_code': code, 'insert_calls': calls}}))
"""
    env = {
        **os.environ,
        "WORKING_DIR": str(tmp_path / "worker-store"),
        "PDF_PARSER": "opendataloader",
    }

    result = _run_child(script, env=env)

    assert result.returncode == 0, result.stderr
    assert _last_json_line(result.stdout, "RESULT_JSON ") == {
        "exit_code": 1,
        "insert_calls": [],
    }
    error = _last_json_line(result.stdout, "WORKER_ERROR_JSON ")
    assert error["stage"] == "parsing"
    assert error["failure_code"] == failure_code
    assert error["retryable"] is False


def test_new_process_worker_drains_registered_background_work(tmp_path):
    script = """
import asyncio
import json
import process_worker as worker
from raganything.processor.batch_processor import register_background_task

events = []
async def background():
    events.append('background-complete')
class FakeRAG:
    async def finalize_storages(self):
        events.append('storage-finalized')

async def main():
    task = asyncio.create_task(background())
    register_background_task(task)
    await worker._flush_background_tasks_and_finalize(FakeRAG(), 'sample.pdf')
    print('RESULT_JSON ' + json.dumps({'events': events, 'task_done': task.done()}))

asyncio.run(main())
"""
    result = _run_child(
        script,
        env={**os.environ, "WORKING_DIR": str(tmp_path / "worker-store")},
    )

    assert result.returncode == 0, result.stderr
    assert _last_json_line(result.stdout, "RESULT_JSON ") == {
        "events": ["background-complete", "storage-finalized"],
        "task_done": True,
    }
