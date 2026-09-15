import logging
from types import SimpleNamespace

import pytest

from raganything.hybrid_search import ScoredChunk
from raganything.query.pipeline import QueryMixin
from raganything.services.query_execution import QueryExecutionScope


def _query_with_lightrag(lightrag):
    query = object.__new__(QueryMixin)
    query.lightrag = lightrag
    query.callback_manager = None
    query.logger = logging.getLogger("test.query-provenance")
    return query


def test_query_execution_scope_keeps_mutable_sink_out_of_mapping_identity():
    first_sink = [{"content": "sensitive retrieval content"}]
    second_sink = []
    first = QueryExecutionScope(
        "trace", "workspace", "revision", "permission", "settings", "llm", 1.0,
        provenance_sink=first_sink,
    )
    second = QueryExecutionScope(
        "trace", "workspace", "revision", "permission", "settings", "llm", 1.0,
        provenance_sink=second_sink,
    )

    assert len(first) == 7
    assert "provenance_sink" not in dict(first)
    assert "sensitive retrieval content" not in repr(first)
    assert first == second

    first.provenance_sink.append({"chunk_id": "chunk-1"})
    assert first.provenance_sink[-1]["chunk_id"] == "chunk-1"


@pytest.mark.asyncio
async def test_native_structured_query_populates_sink_and_relabels_context_once():
    class TextChunks:
        def __init__(self):
            self.calls = []

        async def get_by_ids(self, chunk_ids):
            self.calls.append(list(chunk_ids))
            return [
                {
                    "id": "chunk-a",
                    "full_doc_id": "doc-a",
                    "file_path": "/srv/uploads/a1b2c3d4_manual.pdf",
                    "content": "first persisted content",
                },
                {
                    "id": "chunk-b",
                    "full_doc_id": "doc-b",
                    "file_path": "/srv/uploads/notes.md",
                    "content": "second persisted content",
                },
            ]

    class LightRAG:
        def __init__(self):
            self.text_chunks = TextChunks()
            self.structured_calls = 0
            self.legacy_calls = 0

        async def aquery_llm(self, _query, *, param, system_prompt=None):
            assert param.only_need_context is True
            assert system_prompt is None
            self.structured_calls += 1
            return {
                "data": {
                    "chunks": [
                        {
                            "chunk_id": "chunk-a",
                            "content": "first raw content",
                            "file_path": "/srv/uploads/a1b2c3d4_manual.pdf",
                            "reference_id": "1",
                        },
                        {
                            "chunk_id": "chunk-b",
                            "content": "second raw content",
                            "file_path": "/srv/uploads/notes.md",
                            "reference_id": "2",
                        },
                    ]
                },
                "llm_response": {
                    "content": "LightRAG legacy context",
                    "response_iterator": None,
                    "is_streaming": False,
                },
            }

        async def aquery(self, *_args, **_kwargs):
            self.legacy_calls += 1
            raise AssertionError("aquery must not repeat native retrieval")

    lightrag = LightRAG()
    query = _query_with_lightrag(lightrag)
    sink = []

    context = await query.aquery(
        "question",
        mode="naive",
        only_need_context=True,
        query_execution_scope={"provenance_sink": sink},
    )

    assert lightrag.structured_calls == 1
    assert lightrag.legacy_calls == 0
    assert lightrag.text_chunks.calls == [["chunk-a", "chunk-b"]]
    assert "[来源 1]\n资料：manual.pdf\nfirst raw content" in context
    assert "[来源 2]\n资料：notes.md\nsecond raw content" in context
    assert [item["chunk_id"] for item in sink] == ["chunk-a", "chunk-b"]
    assert [item["document_id"] for item in sink] == ["doc-a", "doc-b"]
    assert [item["source_index"] for item in sink] == [1, 2]


@pytest.mark.asyncio
async def test_native_stream_returns_iterator_after_sink_is_ready():
    async def tokens():
        yield "first"
        yield "second"

    stream = tokens()

    class LightRAG:
        text_chunks = SimpleNamespace(
            get_by_ids=lambda _ids: _async_value([
                {"id": "chunk-a", "full_doc_id": "doc-a"}
            ])
        )

        async def aquery_llm(self, _query, *, param, system_prompt=None):
            assert param.stream is True
            return {
                "data": {"chunks": [{"chunk_id": "chunk-a", "content": "context"}]},
                "llm_response": {
                    "content": None,
                    "response_iterator": stream,
                    "is_streaming": True,
                },
            }

        async def aquery(self, *_args, **_kwargs):
            raise AssertionError("legacy query should not run")

    query = _query_with_lightrag(LightRAG())
    sink = []
    result = await query.aquery(
        "question",
        mode="mix",
        stream=True,
        query_execution_scope={"provenance_sink": sink},
    )

    assert sink[0]["document_id"] == "doc-a"
    assert [token async for token in result] == ["first", "second"]


async def _async_value(value):
    return value


@pytest.mark.asyncio
async def test_native_query_without_structured_api_keeps_legacy_fallback():
    class LightRAG:
        def __init__(self):
            self.calls = 0

        async def aquery(self, _query, *, param, system_prompt=None):
            self.calls += 1
            return "legacy result"

    lightrag = LightRAG()
    query = _query_with_lightrag(lightrag)
    sink = []

    result = await query.aquery(
        "question",
        mode="local",
        query_execution_scope={"provenance_sink": sink},
    )

    assert result == "legacy result"
    assert lightrag.calls == 1
    assert sink == []


@pytest.mark.asyncio
async def test_native_query_without_sink_uses_existing_path_without_metadata_lookup():
    class TextChunks:
        async def get_by_ids(self, _chunk_ids):
            raise AssertionError("metadata lookup should not run without a sink")

    class LightRAG:
        def __init__(self):
            self.text_chunks = TextChunks()
            self.legacy_calls = 0

        async def aquery_llm(self, *_args, **_kwargs):
            raise AssertionError("structured query should not run without a sink")

        async def aquery(self, _query, *, param, system_prompt=None):
            self.legacy_calls += 1
            return "existing result"

    lightrag = LightRAG()
    query = _query_with_lightrag(lightrag)

    result = await query.aquery("question", mode="global")

    assert result == "existing result"
    assert lightrag.legacy_calls == 1


@pytest.mark.asyncio
async def test_rrf_context_labels_follow_sink_order_and_document_chunk_identity():
    first = ScoredChunk(
        "shared-chunk", "first document content", 1.0, ["vector"],
        document_name="first.pdf",
    )
    first.full_doc_id = "doc-first"
    second = ScoredChunk(
        "shared-chunk", "second document content", 0.9, ["bm25"],
        document_name="second.pdf",
    )
    second.full_doc_id = "doc-second"

    class Engine:
        _lightrag = SimpleNamespace(chunk_entity_relation_graph=None)

        async def search(self, *_args, **_kwargs):
            return [first, second]

    query = object.__new__(QueryMixin)
    query.hybrid_search_engine = Engine()
    query.callback_manager = None
    query.logger = logging.getLogger("test.query-provenance.rrf")

    async def source_info(_chunk_ids):
        return {}

    query.batch_get_doc_source_info_async = source_info
    sink = []
    scope = {"provenance_sink": sink}

    context = await query._aquery_rrf(
        "question", only_need_context=True, query_execution_scope=scope
    )

    assert "[来源 1]\n资料：first.pdf\nfirst document content" in context
    assert "[来源 2]\n资料：second.pdf\nsecond document content" in context
    assert "片段2" not in context
    assert [(item["document_id"], item["chunk_id"]) for item in sink] == [
        ("doc-first", "shared-chunk"),
        ("doc-second", "shared-chunk"),
    ]

    repeated = await query._aquery_rrf(
        "question", only_need_context=True, query_execution_scope=scope
    )
    assert "[来源 1]" in repeated and "[来源 2]" in repeated
    assert len(sink) == 2


@pytest.mark.asyncio
async def test_rrf_context_omits_source_labels_when_references_are_disabled():
    chunk = ScoredChunk(
        "chunk-1", "电池电压应保持在 12V。", 1.0, ["vector"],
        document_name="manual.pdf",
    )
    chunk.full_doc_id = "doc-1"

    class Engine:
        _lightrag = SimpleNamespace(chunk_entity_relation_graph=None)

        async def search(self, *_args, **_kwargs):
            return [chunk]

    query = object.__new__(QueryMixin)
    query.hybrid_search_engine = Engine()
    query.callback_manager = None
    query.logger = logging.getLogger("test.query-provenance.rrf-disabled")

    async def source_info(_chunk_ids):
        return {}

    query.batch_get_doc_source_info_async = source_info

    context = await query._aquery_rrf(
        "question",
        only_need_context=True,
        query_execution_scope={"provenance_sink": []},
        include_references=False,
    )

    assert context == "电池电压应保持在 12V。"
    assert "[来源" not in context
    assert "资料：" not in context


@pytest.mark.asyncio
async def test_rrf_disabled_references_skip_citation_enforcement():
    retrieved_text = "电池电压应保持在 12V。" * 30
    chunk = ScoredChunk(
        "chunk-1", retrieved_text, 1.0, ["vector"],
        document_name="manual.pdf",
    )
    chunk.full_doc_id = "doc-1"

    class Engine:
        _lightrag = SimpleNamespace(chunk_entity_relation_graph=None)

        async def search(self, *_args, **_kwargs):
            return [chunk]

    query = object.__new__(QueryMixin)
    query.hybrid_search_engine = Engine()
    query.callback_manager = None
    query.logger = logging.getLogger("test.query-provenance.rrf-disabled")
    query.config = SimpleNamespace(enforce_citation=True)
    prompts = []

    async def source_info(_chunk_ids):
        return {}

    async def answer(prompt, system_prompt=None):
        prompts.append({"prompt": prompt, "system_prompt": system_prompt})
        return "电压应保持在 12V。"

    async def unexpected_citation_repair(*_args, **_kwargs):
        raise AssertionError("disabled references must not trigger citation repair")

    query.batch_get_doc_source_info_async = source_info
    query.llm_model_func = answer
    query._ensure_citations = unexpected_citation_repair

    result = await query._aquery_rrf(
        "question",
        query_execution_scope={"provenance_sink": []},
        include_references=False,
    )

    assert result == "电压应保持在 12V。"
    assert len(prompts) == 1
    assert "[来源" not in prompts[0]["prompt"]
    assert "本次检索未能获取到关联的文档文本内容" not in prompts[0]["prompt"]


@pytest.mark.asyncio
async def test_graph_context_registers_numeric_chunk_references():
    chunk = ScoredChunk(
        "chunk-graph", "graph content", 0.75, ["graph"],
        document_name="graph.pdf",
    )
    chunk.full_doc_id = "doc-graph"

    class GraphRetriever:
        _lightrag = SimpleNamespace(chunk_entity_relation_graph=None)

        async def search_with_paths(self, *_args, **_kwargs):
            return {
                "matched_entities": [
                    {"name": "entity", "type": "component", "degree": 1}
                ],
                "results": [{"chunk": chunk, "paths": []}],
                "graph_stats": {"total_entities": 1, "traversal_depth": 1},
            }

    query = object.__new__(QueryMixin)
    query.hybrid_search_engine = SimpleNamespace(graph_retriever=GraphRetriever())

    async def source_info(_chunk_ids):
        return {}

    query.batch_get_doc_source_info_async = source_info
    sink = []
    context = await query._aquery_graph(
        "question",
        only_need_context=True,
        query_execution_scope={"provenance_sink": sink},
    )

    assert "[来源 1]\n资料：graph.pdf" in context
    assert sink[0]["citation_label"] == "[来源 1]"
    assert sink[0]["document_id"] == "doc-graph"
    assert sink[0]["chunk_id"] == "chunk-graph"
