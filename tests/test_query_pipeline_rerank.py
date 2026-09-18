"""Regression tests for the RRF rerank path in QueryMixin._aquery_rrf.

The rerank call previously executed without importing rerank_chunks, raising
NameError whenever enable_rerank=True and an API key was present, which made
the whole RRF query fail and fall back to a LightRAG hybrid query that had
already exhausted its deadline.
"""

import logging
import time
from types import SimpleNamespace

import pytest

from raganything.hybrid_search import ScoredChunk
from raganything.query.pipeline import QueryMixin, _log_rrf_context_trace


class FakeEngine:
    def __init__(self, chunks):
        self._chunks = chunks

    async def search(self, query, top_k=100, options=None):
        return list(self._chunks)


class FakeConfig:
    enforce_citation = False


async def _empty_source_infos(chunk_ids):
    return {}


def _make_pipeline(chunks, **overrides):
    attrs = {
        "hybrid_search_engine": FakeEngine(chunks),
        "lightrag": None,
        "config": FakeConfig(),
        "logger": logging.getLogger("test.query_pipeline_rerank"),
        "llm_model_func": None,
        "callback_manager": None,
        "batch_get_doc_source_info_async": _empty_source_infos,
    }
    attrs.update(overrides)
    return SimpleNamespace(**attrs)


def test_rrf_context_trace_records_hashes_without_content(monkeypatch, caplog):
    monkeypatch.setenv("AGENT_RETRIEVAL_TRACE_ENABLED", "true")
    chunk = ScoredChunk(
        chunk_id="chunk-1",
        content="secret context",
        score=1.0,
        sources=["bm25"],
    )

    with caplog.at_level(logging.INFO, logger="raganything.query.pipeline"):
        _log_rrf_context_trace(
            {"trace_id": "trace-1"},
            [chunk],
            "[来源 1]\nsecret context",
            stage="context_only",
        )

    assert "secret context" not in caplog.text
    assert '"context_sha256"' in caplog.text
    assert '"chunk_id": "chunk-1"' in caplog.text


def _chunks():
    return [
        ScoredChunk(chunk_id="c1", content="first chunk content", score=0.1, sources=["bm25"]),
        ScoredChunk(chunk_id="c2", content="second chunk content", score=0.2, sources=["vector"]),
    ]


@pytest.mark.asyncio
async def test_rerank_enabled_does_not_raise_and_reorders(monkeypatch):
    calls = {}

    async def fake_rerank(query, chunks, api_key="", top_n=10, model="qwen3-rerank", base_url=""):
        calls["query"] = query
        calls["chunks"] = list(chunks)
        # Reverse order: c2 becomes the top-ranked chunk
        return [(1, chunks[1]), (0, chunks[0])]

    monkeypatch.setattr("raganything.query.utils.rerank_chunks", fake_rerank)
    pipeline = _make_pipeline(_chunks())

    context = await QueryMixin._aquery_rrf(
        pipeline,
        "test query",
        only_need_context=True,
        enable_rerank=True,
        top_k=10,
    )

    assert calls["query"] == "test query"
    assert calls["chunks"] == ["first chunk content", "second chunk content"]
    # Re-ranked order surfaces in the built context (c2 first)
    assert context.index("second chunk content") < context.index("first chunk content")


@pytest.mark.asyncio
async def test_rerank_skipped_when_budget_is_insufficient(monkeypatch):
    called = {"value": False}

    async def fake_rerank(*args, **kwargs):
        called["value"] = True
        return []

    monkeypatch.setattr("raganything.query.utils.rerank_chunks", fake_rerank)
    pipeline = _make_pipeline(_chunks())
    scope = {"deadline_monotonic": time.monotonic() + 0.2}

    context = await QueryMixin._aquery_rrf(
        pipeline,
        "test query",
        only_need_context=True,
        enable_rerank=True,
        top_k=10,
        query_execution_scope=scope,
    )

    assert called["value"] is False
    assert context.index("first chunk content") < context.index("second chunk content")


@pytest.mark.asyncio
async def test_rerank_failure_degrades_to_fused_order(monkeypatch):
    async def failing_rerank(*args, **kwargs):
        raise RuntimeError("rerank api unreachable")

    monkeypatch.setattr("raganything.query.utils.rerank_chunks", failing_rerank)
    pipeline = _make_pipeline(_chunks())

    context = await QueryMixin._aquery_rrf(
        pipeline,
        "test query",
        only_need_context=True,
        enable_rerank=True,
        top_k=10,
    )

    assert "first chunk content" in context
    assert "second chunk content" in context
    assert context.index("first chunk content") < context.index("second chunk content")

@pytest.mark.asyncio
async def test_rerank_proceeds_without_deadline(monkeypatch):
    called = {"value": False}

    async def fake_rerank(query, chunks, api_key="", top_n=10, model="qwen3-rerank", base_url=""):
        called["value"] = True
        return [(1, chunks[1]), (0, chunks[0])]

    monkeypatch.setattr("raganything.query.utils.rerank_chunks", fake_rerank)
    pipeline = _make_pipeline(_chunks())

    context = await QueryMixin._aquery_rrf(
        pipeline,
        "test query",
        only_need_context=True,
        enable_rerank=True,
        top_k=10,
    )

    assert called["value"] is True
    assert context.index("second chunk content") < context.index("first chunk content")


@pytest.mark.asyncio
async def test_rrf_chunk_top_k_controls_context_and_source_registration():
    chunks = [
        ScoredChunk(
            chunk_id=f"c{index}",
            content=f"chunk-{index} content",
            score=1.0 / index,
            sources=["bm25"],
        )
        for index in range(1, 31)
    ]
    pipeline = _make_pipeline(chunks)

    context = await QueryMixin._aquery_rrf(
        pipeline,
        "test query",
        only_need_context=True,
        top_k=40,
        chunk_top_k=20,
        max_total_tokens=64000,
    )

    assert context.count("chunk-") == 20
    assert "chunk-20 content" in context
    assert "chunk-21 content" not in context

    small_context = await QueryMixin._aquery_rrf(
        pipeline,
        "test query",
        only_need_context=True,
        top_k=40,
        chunk_top_k=2,
        max_total_tokens=64000,
    )
    assert small_context.count("chunk-") == 2
    assert small_context.index("chunk-1 content") < small_context.index(
        "chunk-2 content"
    )


def test_module_import_tolerates_invalid_budget_env(monkeypatch):
    """The budget constant must parse safely at import time: a garbage env
    value must fall back to the 1.5s default instead of crashing the module."""
    import importlib

    import raganything.query.pipeline as pipeline_module

    monkeypatch.setenv("RRF_RERANK_MIN_BUDGET_SECONDS", "not-a-number")
    reloaded = importlib.reload(pipeline_module)
    assert reloaded._RRF_RERANK_MIN_BUDGET_SECONDS == 1.5
