from __future__ import annotations

import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from raganything.routers import demo
from raganything.services.demo_shares import (
    DemoShare,
    hash_demo_token,
    public_share_payload,
    revoke_demo_share,
)


def _share() -> DemoShare:
    return DemoShare(
        share_id="00000000-0000-4000-8000-000000000001", agent_id="demo-agent",
        kb_name="cloud-kb", created_by=1, created_at=None, revoked_at=None,
        max_requests_per_minute=10, max_concurrent_queries=2,
    )


def test_public_share_payload_never_contains_token_or_hash():
    payload = public_share_payload(_share())
    assert "token" not in payload
    assert "hash" not in payload
    assert hash_demo_token("a" * 43) != "a" * 43


@pytest.mark.parametrize("role", ["dept_admin", "teacher", "assistant", "student"])
def test_only_super_admin_can_manage_demo_shares(role):
    with pytest.raises(HTTPException) as exc:
        demo._require_super_admin({"is_admin": False, "role": {"name": role}})
    assert exc.value.status_code == 403
    assert demo._require_super_admin({"is_admin": True, "role": {"name": "super_admin"}})["is_admin"]


def test_demo_query_schema_rejects_all_client_scope_overrides():
    with pytest.raises(ValidationError):
        demo.DemoQueryRequest(query="hello", kb="other-kb")
    with pytest.raises(ValidationError):
        demo.DemoQueryRequest(query="hello", image="data:image/png;base64,x")


def test_media_grant_is_share_and_media_scoped(monkeypatch):
    monkeypatch.setenv("DEMO_MEDIA_GRANT_SECRET", "test-secret")
    grant = demo._media_grant(_share().share_id, "media-a", 4_000_000_000)
    assert demo._verify_media_grant(_share().share_id, "media-a", grant)
    assert not demo._verify_media_grant(_share().share_id, "media-b", grant)


def test_demo_sources_expose_display_names_without_paths():
    sources = demo._safe_demo_sources(
        "[来源 C:\\private\\lesson.pdf]\ntext\n[来源 lesson.pdf]\nmore"
    )
    assert sources == [{"name": "lesson.pdf"}]


def test_demo_citation_uses_deep_allowlist_and_share_scoped_media(monkeypatch):
    monkeypatch.setenv("DEMO_MEDIA_GRANT_SECRET", "test-secret")
    citation = demo._safe_demo_citation(_share(), {
        "citation_id": "citation-1",
        "index": 2,
        "document_id": "doc-1",
        "document_name": r"C:\private\lesson.pdf",
        "chunk_id": "chunk-1",
        "excerpt": "可见内容\nfile_path=C:\\private\\image.png\n保留此行",
        "page": 3,
        "section_path": ["章节", "", 7],
        "modality": "image",
        "locator_status": "exact",
        "legacy_status": "legacy_unavailable",
        "media_id": "media-1",
        "media_url": "/api/knowledge/media/private?token=raw",
        "source_sha256": "a" * 64,
        "token": "top-secret",
        "metadata": {"server_path": "/srv/private"},
        "unknown": {"grant": "private-grant"},
        "image": {
            "media_id": "media-1",
            "element_id": "figure-1",
            "figure_label": "图 3-2",
            "bbox": {"x": 10, "y": 20, "width": 30, "height": 40, "token": "bbox-token"},
            "bbox_coordinate_system": {
                "type": "pdf-points", "width": 600, "height": 800,
                "origin": "bottom-left", "server_path": "/srv/page.png",
            },
            "media_url": "/api/knowledge/media/private?grant=raw",
            "file_path": r"C:\private\figure.png",
            "metadata": {"token": "nested-token"},
        },
        "video_segment": {
            "media_id": "media-1", "segment_id": "seg-1",
            "start_ms": 1_000, "end_ms": 4_000,
            "media_url": "https://private.invalid/video",
            "frame_refs": [{
                "frame_id": "frame-1", "media_id": "media-1",
                "element_id": "frame-element", "timestamp_ms": 1_500,
                "index": 1, "file_path": "/private/frame.jpg",
                "token": "frame-token", "unknown": {"grant": "frame-grant"},
            }],
        },
        "video_segments": [{
            "media_id": "media-1", "segment_id": "seg-2",
            "start_ms": 4_000, "end_ms": 8_000,
            "frame_refs": [{"frame_id": "frame-2", "timestamp_ms": 4_500, "server_path": "/srv/frame.jpg"}],
            "source_sha256": "b" * 64,
        }],
    })

    assert citation is not None
    assert citation["document_name"] == "lesson.pdf"
    assert citation["section_path"] == ["章节"]
    assert citation["image"]["bbox"] == {"x": 10, "y": 20, "width": 30, "height": 40}
    assert citation["image"]["bbox_coordinate_system"] == {
        "type": "pdf-points", "width": 600, "height": 800, "origin": "bottom-left",
    }
    assert citation["video_segment"] == {
        "media_id": "media-1", "segment_id": "seg-1",
        "start_ms": 1_000, "end_ms": 4_000,
        "frame_refs": [{
            "frame_id": "frame-1", "media_id": "media-1",
            "element_id": "frame-element", "timestamp_ms": 1_500, "index": 1,
        }],
    }
    assert citation["video_segments"] == [{
        "media_id": "media-1", "segment_id": "seg-2",
        "start_ms": 4_000, "end_ms": 8_000,
        "frame_refs": [{"frame_id": "frame-2", "timestamp_ms": 4_500}],
    }]
    assert "private" not in citation["excerpt"].lower()
    assert "可见内容" in citation["excerpt"] and "保留此行" in citation["excerpt"]

    serialized = json.dumps(citation, ensure_ascii=False)
    for forbidden in (
        "file_path", "server_path", "source_sha256", "metadata", "unknown",
        "top-secret", "nested-token", "frame-token", "raw", "private.invalid",
    ):
        assert forbidden not in serialized

    expected_prefix = f"/api/demo/{_share().share_id}/media/media-1?grant="
    assert citation["media_url"].startswith(expected_prefix)
    assert citation["image"]["media_url"] == citation["media_url"]
    grant = parse_qs(urlparse(citation["media_url"]).query)["grant"][0]
    assert demo._verify_media_grant(_share().share_id, "media-1", grant)
    assert not demo._verify_media_grant(_share().share_id, "media-2", grant)


def test_demo_video_citation_can_issue_media_without_image(monkeypatch):
    monkeypatch.setenv("DEMO_MEDIA_GRANT_SECRET", "test-secret")
    citation = demo._safe_demo_citation(_share(), {
        "document_name": "lesson.mp4",
        "modality": "video",
        "video_segment": {
            "media_id": "video-1", "segment_id": "seg-1",
            "start_ms": 1_000, "end_ms": 3_000,
        },
    })

    assert citation is not None
    assert citation["media_id"] == "video-1"
    assert citation["media_url"].startswith(
        f"/api/demo/{_share().share_id}/media/video-1?grant="
    )
    assert "image" not in citation


@pytest.mark.parametrize("citation", [
    {
        "document_name": "lesson.pdf", "media_id": "media-a",
        "image": {"media_id": "media-b", "media_url": "https://private.invalid/a"},
    },
    {
        "document_name": "lesson.mp4",
        "video_segment": {"media_id": "media-a", "start_ms": 0, "end_ms": 1_000},
        "video_segments": [{"media_id": "media-b", "start_ms": 1_000, "end_ms": 2_000}],
    },
    {
        "document_name": "lesson.pdf", "media_id": "../../private",
        "image": {"media_id": "bad/id", "media_url": "/api/knowledge/media/private"},
    },
    {
        "document_name": "lesson.pdf", "media_id": "media-a",
        "image": {"media_id": "bad/id", "element_id": "figure-1"},
    },
])
def test_demo_citation_media_identity_conflicts_fail_closed(monkeypatch, citation):
    monkeypatch.setenv("DEMO_MEDIA_GRANT_SECRET", "test-secret")
    safe = demo._safe_demo_citation(_share(), citation)
    assert safe is not None
    assert "media_url" not in json.dumps(safe, ensure_ascii=False)
    assert "private" not in json.dumps(safe, ensure_ascii=False)


@pytest.mark.asyncio
async def test_invalid_share_id_cannot_reach_revoke_database(monkeypatch):
    monkeypatch.setattr(
        "raganything.services.demo_shares._pool",
        lambda: pytest.fail("invalid identifiers must not query the database"),
    )
    assert await revoke_demo_share("not-a-share-id") is False


@pytest.mark.asyncio
async def test_validated_share_agent_rejects_changed_knowledge_base(monkeypatch):
    async def get_agent(_agent_id):
        return {"id": "demo-agent", "kb_name": "other-kb"}

    async def get_metadata():
        return {"cloud-kb": {}, "other-kb": {}}

    monkeypatch.setattr(demo, "pg_get_agent", get_agent)
    monkeypatch.setattr(demo, "load_kb_meta", get_metadata)
    with pytest.raises(HTTPException) as exc:
        await demo._validated_share_agent(_share())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_demo_stream_uses_fixed_scope_and_never_persists_conversation(monkeypatch):
    calls = {"released": 0, "history": 0}

    class Instance:
        config = SimpleNamespace(enforce_citation=False)

        async def aquery(self, query, **kwargs):
            assert query == "云端问题"
            assert kwargs["only_need_context"] is True
            assert kwargs["query_execution_scope"].permission_scope.startswith("demo:")
            kwargs["query_execution_scope"].provenance_sink.append({
                "source_index": 1,
                "citation_label": "[来源 1]",
                "chunk_id": "chunk-1",
                "document_id": "doc-1",
                "full_doc_id": "doc-1",
                "document_name": "云端资料.pdf",
                "file_path": "/private/云端资料.pdf",
                "content": "云端检索内容",
            })
            return "[来源 1]\n资料：云端资料.pdf\n云端检索内容"

    class Lease:
        key = None

        def __init__(self):
            self.instance = Instance()

        async def release(self):
            calls["released"] += 1

    async def get_metadata():
        return {"cloud-kb": {"updated_at": "revision"}}

    async def acquire(kb, **_kwargs):
        assert kb == "cloud-kb"
        return Lease()

    async def fake_recall(*_args):
        return [], "", "none", False

    async def fake_llm(*_args, **_kwargs):
        async def stream():
            yield "云端"
            yield "回答"
        return stream()

    class FakePromptBuilder:
        def __init__(self, **_kwargs):
            pass

        def retrieval_context(self, _context):
            pass

        def user_query(self, _query, _instruction):
            pass

        def build(self):
            return "prompt", "system"

    from raganything.routers import agent
    monkeypatch.setattr(demo, "load_kb_meta", get_metadata)
    monkeypatch.setattr(demo, "acquire_query_kb", acquire)
    monkeypatch.setattr(demo, "release_demo_query", lambda _share_id: _async_none())
    monkeypatch.setattr(demo, "get_active_demo_share", lambda _share_id: _async_value(_share()))
    monkeypatch.setattr(demo, "PromptBuilder", FakePromptBuilder)
    monkeypatch.setattr(agent, "_normalise_agent_config_values", lambda value: value)
    monkeypatch.setattr(agent, "_build_agent_system_prompt", lambda _agent, **_kwargs: "system")
    monkeypatch.setattr(agent, "_build_agent_llm", lambda _runtime: fake_llm)
    monkeypatch.setattr(agent, "_recall_controlled_media_with_budget", fake_recall)
    monkeypatch.setattr(
        agent,
        "_provenance_citations_from_scope",
        lambda _scope, _kb, answer: (
            calls.__setitem__("citation_answer", answer)
            or _async_value([{
                "citation_id": "demo:1",
                "document_id": "doc-1",
                "document_name": "云端资料.pdf",
                "chunk_id": "chunk-1",
                "excerpt": "云端检索内容",
                "page": 2,
                "section_path": [],
                "modality": "text",
                "locator_status": "page",
            }])
        ),
    )

    agent_value = {
        "id": "demo-agent", "name": "demo", "icon": "", "kb_name": "cloud-kb",
        "llm_model": "model", "query_mode": "hybrid", "enable_rerank": False,
        "chunk_top_k": 5, "retrieval_top_k": 10, "include_references": True,
        "max_response_tokens": 256, "temperature": 0.0, "system_prompt": "",
    }
    events = [event async for event in demo._demo_events(_share(), agent_value, "云端问题", object())]
    decoded = [json.loads(line[6:]) for line in events]
    assert "".join(event.get("content", "") for event in decoded if event["type"] == "token") == "云端回答"
    assert decoded[-1]["type"] == "done"
    assert decoded[-1]["sources"] == [{"name": "云端资料.pdf"}]
    assert decoded[-1]["images"] == []
    assert decoded[-1]["citations"][0]["document_name"] == "云端资料.pdf"
    assert decoded[-1]["citations"][0]["page"] == 2
    assert "/private/" not in json.dumps(decoded[-1], ensure_ascii=False)
    assert calls == {"released": 1, "history": 0, "citation_answer": "云端回答"}


@pytest.mark.asyncio
async def test_demo_empty_context_done_keeps_success_payload_shape(monkeypatch):
    calls = {"released": 0}

    class Instance:
        async def aquery(self, *_args, **_kwargs):
            return "[no-context]"

    class Lease:
        instance = Instance()

        async def release(self):
            calls["released"] += 1

    from raganything.routers import agent
    monkeypatch.setattr(demo, "load_kb_meta", lambda: _async_value({"cloud-kb": {}}))
    monkeypatch.setattr(demo, "acquire_query_kb", lambda *_args, **_kwargs: _async_value(Lease()))
    monkeypatch.setattr(demo, "release_demo_query", lambda _share_id: _async_none())
    monkeypatch.setattr(agent, "_normalise_agent_config_values", lambda value: value)
    monkeypatch.setattr(agent, "_build_agent_system_prompt", lambda _agent, **_kwargs: "system")

    agent_value = {
        "id": "demo-agent", "llm_model": "model", "query_mode": "hybrid",
        "enable_rerank": False, "chunk_top_k": 5, "retrieval_top_k": 10,
        "include_references": True, "max_response_tokens": 256,
    }
    events = [
        event async for event in demo._demo_events(
            _share(), agent_value, "question", object()
        )
    ]
    done = json.loads(events[-1][6:])

    assert done == {
        "type": "done", "demo": True, "fallback": True,
        "citations": [], "images": [], "sources": [],
    }
    assert calls["released"] == 1


@pytest.mark.asyncio
async def test_demo_stream_stops_before_nonstreaming_answer_after_revocation(monkeypatch):
    class Instance:
        async def aquery(self, *_args, **_kwargs):
            return "[来源 lesson.pdf] context"

    class Lease:
        def __init__(self):
            self.instance = Instance()

        async def release(self):
            pass

    class FakePromptBuilder:
        def __init__(self, **_kwargs):
            pass

        def retrieval_context(self, _context):
            pass

        def user_query(self, _query, _instruction):
            pass

        def build(self):
            return "prompt", "system"

    async def fake_llm(*_args, **_kwargs):
        return "should not be exposed"

    async def revoked_share(_share_id):
        return None

    from raganything.routers import agent
    monkeypatch.setattr(demo, "load_kb_meta", lambda: _async_value({"cloud-kb": {}}))
    monkeypatch.setattr(demo, "acquire_query_kb", lambda *_args, **_kwargs: _async_value(Lease()))
    monkeypatch.setattr(demo, "release_demo_query", lambda _share_id: _async_none())
    monkeypatch.setattr(demo, "get_active_demo_share", revoked_share)
    monkeypatch.setattr(demo, "PromptBuilder", FakePromptBuilder)
    monkeypatch.setattr(agent, "_normalise_agent_config_values", lambda value: value)
    monkeypatch.setattr(agent, "_build_agent_system_prompt", lambda _agent, **_kwargs: "system")
    monkeypatch.setattr(agent, "_build_agent_llm", lambda _runtime: fake_llm)

    agent_value = {
        "id": "demo-agent", "llm_model": "model", "query_mode": "hybrid",
        "enable_rerank": False, "chunk_top_k": 5, "retrieval_top_k": 10,
        "include_references": True, "max_response_tokens": 256,
    }
    events = [event async for event in demo._demo_events(_share(), agent_value, "question", object())]
    decoded = [json.loads(line[6:]) for line in events]
    assert not any(event.get("content") == "should not be exposed" for event in decoded)
    assert decoded[-1]["type"] == "error"


@pytest.mark.asyncio
async def test_demo_react_honors_saved_config_and_filters_references(monkeypatch):
    calls = {
        "search_tool": None,
        "agentic": None,
        "system_prompt": None,
        "recall": 0,
    }

    class Instance:
        config = SimpleNamespace(enforce_citation=False)

        async def finalize_storages(self):
            return None

    class Lease:
        instance = Instance()

        async def release(self):
            return None

    class FakeSearchTool:
        def __init__(self, instance, **kwargs):
            calls["search_tool"] = {"instance": instance, **kwargs}

    class FakeAgenticRAG:
        def __init__(self, **kwargs):
            calls["agentic"] = kwargs

        def register_tool(self, tool):
            self.tool = tool

        async def run_stream(self, query):
            assert query == "question"
            yield SimpleNamespace(
                type="token", content="电池 ", answer=None, observation=None
            )
            yield SimpleNamespace(
                type="token", content="[来", answer=None, observation=None
            )
            yield SimpleNamespace(
                type="token", content="源 1]", answer=None, observation=None
            )
            yield SimpleNamespace(
                type="thinking", content=None, answer=None, observation="raw source"
            )
            yield SimpleNamespace(
                type="token", content="正常", answer=None, observation=None
            )
            yield SimpleNamespace(
                type="done",
                content=None,
                answer="电池 [来源 1]正常",
                observation=None,
            )

    def build_system_prompt(_agent, **kwargs):
        calls["system_prompt"] = kwargs
        return "system"

    async def fake_recall(*_args):
        calls["recall"] += 1
        return [], "", "none", False

    async def unexpected_citation(*_args, **_kwargs):
        raise AssertionError("disabled references must not construct citations")

    from raganything.routers import agent as agent_router
    import raganything.agentic_rag as agentic_module

    monkeypatch.setattr(demo, "load_kb_meta", lambda: _async_value({"cloud-kb": {}}))
    monkeypatch.setattr(demo, "acquire_query_kb", lambda *_args, **_kwargs: _async_value(Lease()))
    monkeypatch.setattr(demo, "release_demo_query", lambda _share_id: _async_none())
    monkeypatch.setattr(demo, "get_active_demo_share", lambda _share_id: _async_value(_share()))
    monkeypatch.setattr(agent_router, "_build_agent_system_prompt", build_system_prompt)
    monkeypatch.setattr(agent_router, "_build_agent_llm", lambda _runtime: object())
    monkeypatch.setattr(agent_router, "_recall_controlled_media_with_budget", fake_recall)
    monkeypatch.setattr(agent_router, "_provenance_citations_from_scope", unexpected_citation)
    monkeypatch.setattr(agentic_module, "AgenticRAG", FakeAgenticRAG)
    monkeypatch.setattr(agentic_module, "SearchTool", FakeSearchTool)

    agent_value = {
        "id": "demo-agent", "name": "demo", "kb_name": "cloud-kb",
        "llm_model": "qwen-max", "query_mode": "graph", "agent_mode": "react",
        "enable_rerank": True, "chunk_top_k": 3, "retrieval_top_k": 7,
        "include_references": False, "max_response_tokens": 1024,
        "temperature": 0.2, "system_prompt": "", "use_default_prompt": False,
    }
    events = [
        event async for event in demo._demo_events(
            _share(), agent_value, "question", object()
        )
    ]
    decoded = [json.loads(line[6:]) for line in events]
    token_text = "".join(
        event.get("content", "")
        for event in decoded
        if event["type"] == "token"
    )

    assert token_text == "电池 正常"
    assert calls["system_prompt"] == {"include_references": False}
    assert calls["search_tool"]["query_mode"] == "graph"
    assert calls["search_tool"]["top_k"] == 7
    assert calls["search_tool"]["chunk_top_k"] == 3
    assert calls["search_tool"]["enable_rerank"] is True
    assert calls["search_tool"]["include_references"] is False
    assert calls["agentic"]["mode"] == "react"
    assert calls["agentic"]["max_response_tokens"] == 1024
    assert decoded[-1]["citations"] == []
    assert decoded[-1]["sources"] == []
    assert decoded[-1]["images"] == []
    assert calls["recall"] == 0
    assert "raw source" not in json.dumps(decoded, ensure_ascii=False)


@pytest.mark.asyncio
async def test_demo_cot_uses_retrieved_context_and_filters_references(monkeypatch):
    calls = {"aquery": None, "agentic": None, "recall": 0}

    class Instance:
        async def aquery(self, query, **kwargs):
            calls["aquery"] = {"query": query, **kwargs}
            return "[来源 1]\n资料：manual.pdf\n电池电压是 12V。" * 20

        async def finalize_storages(self):
            return None

    class Lease:
        instance = Instance()

        async def release(self):
            return None

    class FakeAgenticRAG:
        def __init__(self, **kwargs):
            calls["agentic"] = kwargs

        async def run_with_context(self, query, context):
            assert query == "question"
            assert "[来源 1]" in context
            return SimpleNamespace(
                answer="电池电压是 12V。[来源 1]\n\n📚 参考来源\n[来源 1] — 原文",
                trace=[],
            )

    async def fake_recall(*_args):
        calls["recall"] += 1
        return [], "", "none", False

    async def unexpected_citation(*_args, **_kwargs):
        raise AssertionError("disabled references must not construct citations")

    from raganything.routers import agent as agent_router
    import raganything.agentic_rag as agentic_module

    monkeypatch.setattr(demo, "load_kb_meta", lambda: _async_value({"cloud-kb": {}}))
    monkeypatch.setattr(demo, "acquire_query_kb", lambda *_args, **_kwargs: _async_value(Lease()))
    monkeypatch.setattr(demo, "release_demo_query", lambda _share_id: _async_none())
    monkeypatch.setattr(demo, "get_active_demo_share", lambda _share_id: _async_value(_share()))
    monkeypatch.setattr(agent_router, "_build_agent_system_prompt", lambda *_args, **_kwargs: "system")
    monkeypatch.setattr(agent_router, "_build_agent_llm", lambda _runtime: object())
    monkeypatch.setattr(agent_router, "_recall_controlled_media_with_budget", fake_recall)
    monkeypatch.setattr(agent_router, "_provenance_citations_from_scope", unexpected_citation)
    monkeypatch.setattr(agentic_module, "AgenticRAG", FakeAgenticRAG)

    agent_value = {
        "id": "demo-agent", "name": "demo", "kb_name": "cloud-kb",
        "llm_model": "qwen-max", "query_mode": "local", "agent_mode": "cot",
        "enable_rerank": False, "chunk_top_k": 4, "retrieval_top_k": 9,
        "include_references": False, "max_response_tokens": 2048,
        "temperature": 0.0, "system_prompt": "", "use_default_prompt": False,
    }
    events = [
        event async for event in demo._demo_events(
            _share(), agent_value, "question", object()
        )
    ]
    decoded = [json.loads(line[6:]) for line in events]
    token_text = "".join(
        event.get("content", "")
        for event in decoded
        if event["type"] == "token"
    )

    assert token_text == "电池电压是 12V。\n\n"
    assert calls["aquery"]["mode"] == "local"
    assert calls["aquery"]["top_k"] == 9
    assert calls["aquery"]["chunk_top_k"] == 4
    assert calls["aquery"]["enable_rerank"] is False
    assert calls["agentic"]["mode"] == "cot"
    assert decoded[-1]["citations"] == []
    assert decoded[-1]["sources"] == []
    assert decoded[-1]["images"] == []
    assert calls["recall"] == 0


async def _async_none():
    return None


async def _async_value(value):
    return value
