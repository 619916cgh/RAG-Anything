import json
from types import SimpleNamespace

import pytest

from tests.test_video_segment_citations import (
    _Request,
    _body,
    _wire_agent_stream_prerequisites,
)


def test_empty_context_detects_retrieval_failures_without_source_labels():
    from raganything.routers.agent import _is_empty_context

    assert _is_empty_context(
        "No relevant documents found for your query.",
        include_references=False,
    )
    assert _is_empty_context(
        "Graph query unavailable - knowledge graph is empty.",
        include_references=False,
    )
    assert not _is_empty_context(
        "电池电压应保持在 12V。",
        include_references=False,
    )


@pytest.mark.asyncio
async def test_standard_agent_reuses_citations_for_done_message_and_history(monkeypatch):
    from raganything.routers import agent as agent_router

    persisted_messages = []
    history_records = []

    class KB:
        config = SimpleNamespace(enforce_citation=False, vision_search_enabled=False)

        async def aquery(self, *_args, **kwargs):
            scope = kwargs["query_execution_scope"]
            scope.provenance_sink.append({
                "source_index": 1,
                "citation_label": "[来源 1]",
                "chunk_id": "chunk-1",
                "document_id": "doc-1",
                "full_doc_id": "doc-1",
                "document_name": "manual.pdf",
                "file_path": r"C:\private\manual.pdf",
                "content": "电池电压应保持在 12V。",
            })
            return "[来源 1]\n资料：manual.pdf\n电池电压应保持在 12V。"

        async def finalize_storages(self):
            return None

    _wire_agent_stream_prerequisites(
        monkeypatch, agent_mode="none", kb_instance=KB()
    )

    async def answer_with_citation(*_args, **_kwargs):
        return "电池电压应保持在 12V。[来源 1]"

    monkeypatch.setattr(
        agent_router.vision_models,
        "build_llm_callable",
        lambda *_args, **_kwargs: answer_with_citation,
    )

    async def save_message(_agent_id, _thread_id, message):
        persisted_messages.append(message)

    async def save_history(record, max_history=100):
        history_records.append(record)

    async def citations(scope, kb_name, answer=None):
        assert kb_name == "kb"
        assert "[来源 1]" in answer
        assert scope.provenance_sink[0]["document_id"] == "doc-1"
        return [{
            "citation_id": f"{scope.trace_id}:1",
            "document_id": "doc-1",
            "document_name": "manual.pdf",
            "chunk_id": "chunk-1",
            "excerpt": "电池电压应保持在 12V。",
            "page": 4,
            "section_path": ["维护"],
            "modality": "text",
            "locator_status": "page",
        }]

    monkeypatch.setattr(agent_router, "pg_add_message", save_message)
    monkeypatch.setattr(agent_router, "record_query", save_history)
    monkeypatch.setattr(agent_router, "_provenance_citations_from_scope", citations)

    response = await agent_router.agent_query_stream(
        "agent-1",
        agent_router.AgentQueryRequest(query="检查电池", thread_id="thread-1"),
        _Request(),
        current_user={"id": 7, "username": "user", "is_admin": True},
        _perm=None,
    )
    body = await _body(response)
    events = [
        json.loads(line[6:]) for line in body.splitlines()
        if line.startswith("data: ")
    ]
    done = next(event for event in events if event["type"] == "done")
    assistant = next(
        message for message in persisted_messages
        if message.get("role") == "assistant"
    )

    assert done["citations"] == assistant["citations"]
    assert done["citations"] == history_records[0]["citations"]
    assert done["citations"][0]["page"] == 4
    assert "C:\\private" not in json.dumps(done, ensure_ascii=False)


@pytest.mark.asyncio
async def test_disabled_references_omit_citations_from_stream_history_and_prompt(monkeypatch):
    from raganything.routers import agent as agent_router

    persisted_messages = []
    history_records = []
    retrieval_calls = []
    llm_calls = []
    retrieved_context = "电池电压应保持在 12V。" * 30

    class KB:
        config = SimpleNamespace(enforce_citation=False, vision_search_enabled=False)

        async def aquery(self, *_args, **kwargs):
            retrieval_calls.append(kwargs)
            kwargs["query_execution_scope"].provenance_sink.append({
                "source_index": 1,
                "citation_label": "[来源 1]",
                "chunk_id": "chunk-1",
                "document_id": "doc-1",
                "full_doc_id": "doc-1",
                "document_name": "manual.pdf",
                "content": "电池电压应保持在 12V。",
            })
            return retrieved_context

        async def finalize_storages(self):
            return None

    _wire_agent_stream_prerequisites(
        monkeypatch, agent_mode="none", kb_instance=KB()
    )

    async def get_agent_without_references(_agent_id):
        return {
            "id": "agent-1", "name": "agent", "kb_name": "kb", "owner_id": 7,
            "query_mode": "hybrid", "agent_mode": "none", "retrieval_top_k": 20,
            "chunk_top_k": 5, "enable_rerank": False, "include_references": False,
            "max_response_tokens": 512, "temperature": 0.0, "system_prompt": "",
            "use_default_prompt": True,
        }

    async def answer_with_citation(prompt, **kwargs):
        llm_calls.append({"prompt": prompt, **kwargs})
        return (
            "电池电压应保持在 12V。[来源 1]\n\n"
            "📚 参考来源\n[来源 1] — 原文：电池电压应保持在 12V。"
        )

    async def save_message(_agent_id, _thread_id, message):
        persisted_messages.append(message)

    async def save_history(record, max_history=100):
        history_records.append(record)

    async def unexpected_citation_build(*_args, **_kwargs):
        raise AssertionError("disabled references must not build citation DTOs")

    async def recalled_media(*_args, **_kwargs):
        return (
            [{"media_id": "image-1", "url": "/api/files/image?path=private"}],
            "",
            "test",
            False,
        )

    monkeypatch.setattr(agent_router, "pg_get_agent", get_agent_without_references)
    monkeypatch.setattr(
        agent_router.vision_models,
        "build_llm_callable",
        lambda *_args, **_kwargs: answer_with_citation,
    )
    monkeypatch.setattr(agent_router, "pg_add_message", save_message)
    monkeypatch.setattr(agent_router, "record_query", save_history)
    monkeypatch.setattr(agent_router, "_query_citations", unexpected_citation_build)
    monkeypatch.setattr(
        agent_router, "_recall_controlled_media_with_budget", recalled_media
    )

    response = await agent_router.agent_query_stream(
        "agent-1",
        agent_router.AgentQueryRequest(query="检查电池", thread_id="thread-1"),
        _Request(),
        current_user={"id": 7, "username": "user", "is_admin": True},
        _perm=None,
    )
    body = await _body(response)
    events = [
        json.loads(line[6:]) for line in body.splitlines()
        if line.startswith("data: ")
    ]
    done = next(event for event in events if event["type"] == "done")
    assistant = next(
        message for message in persisted_messages
        if message.get("role") == "assistant"
    )
    token_text = "".join(
        event.get("content", "")
        for event in events
        if event["type"] == "token"
    )

    assert retrieval_calls[0]["include_references"] is False
    assert "[来源" not in llm_calls[0]["prompt"]
    assert "本次检索未能获取到关联的文档文本内容" not in llm_calls[0]["prompt"]
    assert "不要输出来源标记" in llm_calls[0]["system_prompt"]
    assert done["citations"] == []
    assert done["images"] == []
    assert assistant["citations"] == []
    assert assistant.get("images", []) == []
    assert history_records[0]["citations"] == []
    assert history_records[0]["images"] == []
    assert token_text == assistant["content"] == history_records[0]["answer"]
    assert "[来源" not in token_text
    assert "参考来源" not in token_text


@pytest.mark.asyncio
async def test_disabled_references_filter_split_stream_before_sse_and_persistence(monkeypatch):
    from raganything.routers import agent as agent_router

    persisted_messages = []
    history_records = []

    class KB:
        config = SimpleNamespace(enforce_citation=False, vision_search_enabled=False)

        async def aquery(self, *_args, **_kwargs):
            return "电池电压应保持在 12V。" * 30

        async def finalize_storages(self):
            return None

    _wire_agent_stream_prerequisites(
        monkeypatch, agent_mode="none", kb_instance=KB()
    )

    async def get_agent_without_references(_agent_id):
        return {
            "id": "agent-1", "name": "agent", "kb_name": "kb", "owner_id": 7,
            "query_mode": "hybrid", "agent_mode": "none", "retrieval_top_k": 20,
            "chunk_top_k": 5, "enable_rerank": False, "include_references": False,
            "max_response_tokens": 512, "temperature": 0.0, "system_prompt": "",
            "use_default_prompt": True,
        }

    async def answer_stream(*_args, **_kwargs):
        async def stream():
            for token in ("电池电压 ", "12V。[来", "源 1]\n", "继续检查。"):
                yield token

        return stream()

    async def save_message(_agent_id, _thread_id, message):
        persisted_messages.append(message)

    async def save_history(record, max_history=100):
        history_records.append(record)

    monkeypatch.setattr(agent_router, "pg_get_agent", get_agent_without_references)
    monkeypatch.setattr(
        agent_router.vision_models,
        "build_llm_callable",
        lambda *_args, **_kwargs: answer_stream,
    )
    monkeypatch.setattr(agent_router, "pg_add_message", save_message)
    monkeypatch.setattr(agent_router, "record_query", save_history)
    monkeypatch.setattr(
        agent_router,
        "_query_citations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("disabled references must not build citation DTOs")
        ),
    )

    response = await agent_router.agent_query_stream(
        "agent-1",
        agent_router.AgentQueryRequest(query="检查电池", thread_id="thread-1"),
        _Request(),
        current_user={"id": 7, "username": "user", "is_admin": True},
        _perm=None,
    )
    body = await _body(response)
    events = [
        json.loads(line[6:]) for line in body.splitlines()
        if line.startswith("data: ")
    ]
    token_text = "".join(
        event.get("content", "")
        for event in events
        if event["type"] == "token"
    )
    assistant = next(
        message for message in persisted_messages
        if message.get("role") == "assistant"
    )

    assert token_text == assistant["content"] == history_records[0]["answer"]
    assert token_text == "电池电压 12V。\n继续检查。"
    assert "[来源" not in token_text


@pytest.mark.asyncio
async def test_provenance_citations_follow_answer_order_and_ignore_invalid_markers(monkeypatch):
    from raganything.routers import agent as agent_router
    from raganything.services.query_execution import QueryExecutionScope

    scope = QueryExecutionScope(
        "trace", "workspace", "revision", "permission", "settings", "llm", 1.0,
        provenance_sink=[
            {"source_index": 1, "document_id": "doc-1", "chunk_id": "chunk-1", "content": "one"},
            {"source_index": 2, "document_id": "doc-2", "chunk_id": "chunk-2", "content": "two"},
            {"source_index": 3, "document_id": "doc-3", "chunk_id": "chunk-3", "content": "three"},
        ],
    )

    async def persisted(_kb_name, references):
        return {
            (item["document_id"], item["chunk_id"]): {
                "document_id": item["document_id"],
                "chunk_id": item["chunk_id"],
                "document_name": f"{item['document_id']}.pdf",
                "source_sha256": "a" * 64,
            }
            for item in references
        }

    monkeypatch.setattr(
        "raganything.services.provenance.batch_get_provenance_for_references",
        persisted,
    )

    citations = await agent_router._provenance_citations_from_scope(
        scope,
        "kb",
        "先看[来源 3]，再看[来源 1]和重复的[来源 3]；忽略[来源 9]与[来源 文档]。",
    )

    assert [item["index"] for item in citations] == [3, 1]
    assert [item["document_id"] for item in citations] == ["doc-3", "doc-1"]


@pytest.mark.asyncio
async def test_provenance_citations_are_empty_without_valid_answer_markers():
    from raganything.routers import agent as agent_router
    from raganything.services.query_execution import QueryExecutionScope

    scope = QueryExecutionScope(
        "trace", "workspace", "revision", "permission", "settings", "llm", 1.0,
        provenance_sink=[
            {"source_index": 1, "document_id": "doc-1", "chunk_id": "chunk-1"},
        ],
    )

    assert await agent_router._provenance_citations_from_scope(
        scope, "kb", "回答没有引用标记"
    ) == []


@pytest.mark.asyncio
async def test_legacy_video_citations_follow_answer_source_markers(monkeypatch):
    from raganything.routers import agent as agent_router
    from raganything.services.query_execution import QueryExecutionScope

    scope = QueryExecutionScope(
        "trace", "workspace", "revision", "permission", "settings", "llm", 1.0,
        provenance_sink=[
            {
                "source_index": 1,
                "document_id": "video-doc",
                "chunk_id": "video-chunk",
                "document_name": "video.mp4",
                "_video_segments": [{
                    "segment_id": "video-segment",
                    "segment_index": 0,
                    "start_ms": 1000,
                    "end_ms": 2000,
                    "document_id": "video-doc",
                    "chunk_id": "video-chunk",
                    "media_id": "video-media",
                }],
            },
            {
                "source_index": 2,
                "document_id": "text-doc",
                "chunk_id": "text-chunk",
            },
        ],
    )
    context = (
        "[VIDEO_SEGMENT segment_id=video-segment media_id=video-media "
        "start_ms=1000 end_ms=2000 document_id=video-doc]\n"
        "[VIDEO_SEGMENT segment_id=other-segment media_id=other-media "
        "start_ms=3000 end_ms=4000 document_id=other-doc]"
    )

    async def no_persisted_citations(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(
        "raganything.services.provenance.batch_get_provenance_for_references",
        no_persisted_citations,
    )

    cited_video = await agent_router._query_citations(
        scope, "kb", context, "使用视频步骤。[来源 1]"
    )
    assert [item["media_id"] for item in cited_video] == ["video-media"]

    text_citations = await agent_router._query_citations(
        scope, "kb", context, "只使用文本资料。[来源 2]"
    )
    assert len(text_citations) == 1
    assert text_citations[0]["document_id"] == "text-doc"
    assert "media_id" not in text_citations[0]
    assert "video_segment" not in text_citations[0]
    assert await agent_router._query_citations(
        scope, "kb", context, "回答没有引用标记"
    ) == []


@pytest.mark.asyncio
async def test_legacy_video_citations_do_not_merge_unreferenced_same_document_chunk(
    monkeypatch,
):
    from raganything.routers import agent as agent_router
    from raganything.services.query_execution import QueryExecutionScope

    scope = QueryExecutionScope(
        "trace", "workspace", "revision", "permission", "settings", "llm", 1.0,
        provenance_sink=[
            {
                "source_index": 1,
                "document_id": "video-doc",
                "chunk_id": "chunk-1",
                "document_name": "video.mp4",
                "_video_segments": [{
                    "segment_id": "segment-1",
                    "segment_index": 0,
                    "start_ms": 1000,
                    "end_ms": 2000,
                    "document_id": "video-doc",
                    "chunk_id": "chunk-1",
                    "media_id": "video-media",
                }],
            },
            {
                "source_index": 2,
                "document_id": "video-doc",
                "chunk_id": "chunk-2",
                "document_name": "video.mp4",
                "_video_segments": [{
                    "segment_id": "segment-2",
                    "segment_index": 1,
                    "start_ms": 3000,
                    "end_ms": 4000,
                    "document_id": "video-doc",
                    "chunk_id": "chunk-2",
                    "media_id": "video-media",
                }],
            },
        ],
    )

    async def no_persisted_citations(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(
        "raganything.services.provenance.batch_get_provenance_for_references",
        no_persisted_citations,
    )

    citations = await agent_router._query_citations(
        scope,
        "kb",
        (
            "[VIDEO_SEGMENT segment_id=segment-1 media_id=video-media "
            "start_ms=1000 end_ms=2000 document_id=video-doc chunk_id=chunk-1]\n"
            "[VIDEO_SEGMENT segment_id=segment-2 media_id=video-media "
            "start_ms=3000 end_ms=4000 document_id=video-doc chunk_id=chunk-2]"
        ),
        "只引用第一个视频片段。[来源 1]",
    )

    assert [
        item["segment_id"] for item in citations[0]["video_segments"]
    ] == ["segment-1"]


@pytest.mark.asyncio
async def test_answer_path_ignores_video_marker_literal_from_chunk_text(monkeypatch):
    from raganything.routers import agent as agent_router
    from raganything.services.query_execution import QueryExecutionScope

    scope = QueryExecutionScope(
        "trace", "workspace", "revision", "permission", "settings", "llm", 1.0,
        provenance_sink=[{
            "source_index": 1,
            "document_id": "note-doc",
            "chunk_id": "note-chunk",
            "document_name": "note.txt",
        }],
    )

    async def no_persisted_citations(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(
        "raganything.services.provenance.batch_get_provenance_for_references",
        no_persisted_citations,
    )

    context = (
        "[来源 1]\n资料：note.txt\n正文示例："
        "[VIDEO_SEGMENT segment_id=fake media_id=fake-media "
        "start_ms=1000 end_ms=2000 document_id=note-doc chunk_id=note-chunk]"
    )
    citations = await agent_router._query_citations(
        scope, "kb", context, "引用普通文本。[来源 1]"
    )
    assert len(citations) == 1
    assert citations[0]["document_name"] == "note.txt"
    assert "media_id" not in citations[0]
    assert "video_segment" not in citations[0]


@pytest.mark.asyncio
async def test_query_citations_keeps_raw_legacy_marker_only_without_answer(monkeypatch):
    from raganything.routers import agent as agent_router
    from raganything.services.query_execution import QueryExecutionScope

    scope = QueryExecutionScope(
        "trace", "workspace", "revision", "permission", "settings", "llm", 1.0,
        provenance_sink=[],
    )

    async def no_persisted_citations(*_args, **_kwargs):
        return []

    monkeypatch.setattr(
        agent_router,
        "_provenance_citations_from_scope",
        no_persisted_citations,
    )
    context = (
        "[VIDEO_SEGMENT segment_id=legacy-segment media_id=legacy-media "
        "start_ms=1000 end_ms=2000 document_id=legacy-doc]"
    )

    citations = await agent_router._query_citations(
        scope, "kb", context, answer=None
    )

    assert [item["media_id"] for item in citations] == ["legacy-media"]


@pytest.mark.asyncio
async def test_legacy_video_sidecar_merges_into_one_numbered_citation(monkeypatch):
    from raganything.routers import agent as agent_router
    from raganything.services.query_execution import QueryExecutionScope

    scope = QueryExecutionScope(
        "trace", "workspace", "revision", "permission", "settings", "llm", 1.0,
        provenance_sink=[{
            "source_index": 1,
            "document_id": "video-doc",
            "chunk_id": "video-chunk",
            "document_name": "video.mp4",
            "content": "视频维护步骤。",
            "_video_segments": [{
                "segment_id": "segment-1",
                "segment_index": 0,
                "start_ms": 1000,
                "end_ms": 2000,
                "document_id": "video-doc",
                "chunk_id": "video-chunk",
                "media_id": "video-media",
            }],
        }],
    )

    async def no_persisted_citations(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(
        "raganything.services.provenance.batch_get_provenance_for_references",
        no_persisted_citations,
    )

    citations = await agent_router._query_citations(
        scope, "kb", "ignored raw context", "使用视频步骤。[来源 1]"
    )

    assert len(citations) == 1
    citation = citations[0]
    assert citation["citation_id"] == "trace:1"
    assert citation["index"] == 1
    assert citation["document_id"] == "video-doc"
    assert citation["chunk_id"] == "video-chunk"
    assert citation["excerpt"] == "视频维护步骤。"
    assert citation["legacy_status"] == "legacy_unavailable"
    assert citation["locator_status"] == "exact"
    assert citation["modality"] == "video"
    assert citation["media_id"] == "video-media"
    assert citation["video_segment"] == {
        "media_id": "video-media",
        "media_kb": "kb",
        "segment_id": "segment-1",
        "start_ms": 1000,
        "end_ms": 2000,
    }
    assert citation["video_segments"] == [{
        "media_id": "video-media",
        "media_kb": "kb",
        "segment_id": "segment-1",
        "start_ms": 1000,
        "end_ms": 2000,
    }]


@pytest.mark.asyncio
async def test_legacy_video_sidecar_survives_provenance_lookup_failure(monkeypatch):
    from raganything.routers import agent as agent_router
    from raganything.services.query_execution import QueryExecutionScope

    scope = QueryExecutionScope(
        "trace", "workspace", "revision", "permission", "settings", "llm", 1.0,
        provenance_sink=[{
            "source_index": 1,
            "document_id": "video-doc",
            "chunk_id": "video-chunk",
            "document_name": "video.mp4",
            "content": "视频维护步骤。",
            "_video_segments": [{
                "segment_id": "segment-1",
                "segment_index": 0,
                "start_ms": 1000,
                "end_ms": 2000,
                "document_id": "video-doc",
                "chunk_id": "video-chunk",
                "media_id": "video-media",
            }],
        }],
    )

    async def failing_lookup(*_args, **_kwargs):
        raise RuntimeError("provenance backend unavailable")

    monkeypatch.setattr(
        "raganything.services.provenance.batch_get_provenance_for_references",
        failing_lookup,
    )

    citations = await agent_router._query_citations(
        scope, "kb", "ignored raw context", "使用视频步骤。[来源 1]"
    )

    assert len(citations) == 1
    citation = citations[0]
    assert citation["citation_id"] == "trace:1"
    assert citation["index"] == 1
    assert citation["chunk_id"] == "video-chunk"
    assert citation["legacy_status"] == "legacy_unavailable"
    assert citation["video_segment"]["segment_id"] == "segment-1"


@pytest.mark.asyncio
async def test_unreferenced_legacy_video_is_empty_in_done_message_and_history(monkeypatch):
    from raganything.routers import agent as agent_router

    persisted_messages = []
    history_records = []

    class KB:
        config = SimpleNamespace(enforce_citation=False, vision_search_enabled=False)

        async def aquery(self, *_args, **kwargs):
            scope = kwargs["query_execution_scope"]
            scope.provenance_sink.append({
                "source_index": 1,
                "citation_label": "[来源 1]",
                "chunk_id": "video-chunk",
                "document_id": "video-doc",
                "full_doc_id": "video-doc",
                "document_name": "maintenance.mp4",
                "content": "视频维护步骤。",
                "_video_segments": [{
                    "segment_id": "segment-1",
                    "segment_index": 0,
                    "start_ms": 1000,
                    "end_ms": 2000,
                    "document_id": "video-doc",
                    "chunk_id": "video-chunk",
                    "media_id": "media-1",
                }],
            })
            return (
                "[来源 1]\n资料：maintenance.mp4\n视频维护步骤。\n"
                "[VIDEO_SEGMENT segment_id=segment-1 media_id=media-1 "
                "start_ms=1000 end_ms=2000 document_id=video-doc]"
            )

        async def finalize_storages(self):
            return None

    _wire_agent_stream_prerequisites(
        monkeypatch, agent_mode="none", kb_instance=KB()
    )

    async def answer_without_citation(*_args, **_kwargs):
        return "视频维护步骤已检索，但本回答未引用资料。"

    async def save_message(_agent_id, _thread_id, message):
        persisted_messages.append(message)

    async def save_history(record, max_history=100):
        history_records.append(record)

    monkeypatch.setattr(
        agent_router.vision_models,
        "build_llm_callable",
        lambda *_args, **_kwargs: answer_without_citation,
    )
    monkeypatch.setattr(agent_router, "pg_add_message", save_message)
    monkeypatch.setattr(agent_router, "record_query", save_history)

    response = await agent_router.agent_query_stream(
        "agent-1",
        agent_router.AgentQueryRequest(query="视频维护", thread_id="thread-1"),
        _Request(),
        current_user={"id": 7, "username": "user", "is_admin": True},
        _perm=None,
    )
    body = await _body(response)
    events = [
        json.loads(line[6:]) for line in body.splitlines()
        if line.startswith("data: ")
    ]
    done = next(event for event in events if event["type"] == "done")
    assistant = next(
        message for message in persisted_messages
        if message.get("role") == "assistant"
    )

    assert done["citations"] == []
    assert assistant["citations"] == []
    assert history_records[0]["citations"] == []
