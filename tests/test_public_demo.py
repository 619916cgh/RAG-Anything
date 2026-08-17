from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

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
            return "[来源 云端资料.pdf] 云端检索内容"

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
    monkeypatch.setattr(agent, "_build_agent_system_prompt", lambda _agent: "system")
    monkeypatch.setattr(agent, "_build_agent_llm", lambda _runtime: fake_llm)
    monkeypatch.setattr(agent, "_recall_controlled_media_with_budget", fake_recall)

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
    assert calls == {"released": 1, "history": 0}


@pytest.mark.asyncio
async def test_demo_stream_accepts_before_cold_knowledge_base_acquisition(monkeypatch):
    gate = asyncio.Event()

    async def slow_acquire(*_args, **_kwargs):
        await gate.wait()

    monkeypatch.setattr(demo, "acquire_query_kb", slow_acquire)
    events = demo._demo_events(_share(), {}, "question", object())
    try:
        first = json.loads((await anext(events))[6:])
        assert first == {"type": "accepted", "demo": True}
    finally:
        await events.aclose()


@pytest.mark.asyncio
async def test_demo_stream_times_out_without_waiting_for_cold_acquisition(monkeypatch):
    gate = asyncio.Event()

    async def slow_acquire(*_args, **_kwargs):
        await gate.wait()

    monkeypatch.setattr(demo, "acquire_query_kb", slow_acquire)
    monkeypatch.setattr(demo, "load_kb_meta", lambda: _async_value({"cloud-kb": {}}))
    monkeypatch.setattr(demo, "release_demo_query", lambda _share_id: _async_none())
    monkeypatch.setattr(demo, "_DEMO_QUERY_TIMEOUT", 0.01)
    events = demo._demo_events(_share(), {}, "question", object())
    try:
        assert json.loads((await anext(events))[6:])["type"] == "accepted"
        timeout_event = json.loads((await asyncio.wait_for(anext(events), timeout=0.5))[6:])
        assert timeout_event["type"] == "error"
    finally:
        await events.aclose()


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
    monkeypatch.setattr(agent, "_build_agent_system_prompt", lambda _agent: "system")
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


async def _async_none():
    return None


async def _async_value(value):
    return value
