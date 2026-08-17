from __future__ import annotations

import json

import pytest

from raganything.routers import agent as agent_router


class _Request:
    headers = {}


async def _body(response):
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
    return "".join(chunks)


def test_inventory_intent_is_strict_about_knowledge_base_stock():
    assert agent_router.detect_knowledge_inventory_intent("知识库中有多少个视频") == "video"
    assert agent_router.detect_knowledge_inventory_intent("资料库共有多少文档") == "document"
    assert agent_router.detect_knowledge_inventory_intent("知识库有多少") == "all"
    assert agent_router.detect_knowledge_inventory_intent("视频中有多少个零件") is None


@pytest.mark.asyncio
async def test_inventory_answer_streams_and_persists_without_retrieval_or_llm(monkeypatch):
    calls = {"messages": [], "record": 0}

    async def get_agent(_agent_id):
        return {"id": "agent-1", "name": "演示智能体", "icon": "", "kb_name": "demo"}

    async def create_conversation(*_args, **_kwargs):
        return {"id": "thread-1"}

    async def add_message(_agent_id, _thread_id, message):
        calls["messages"].append(message)

    async def record(*_args, **_kwargs):
        calls["record"] += 1

    async def inventory(_kb):
        return {
            "all": {"total": 3, "retrievable": 2, "content_processing": 0, "tag_processing": 1, "failed": 1},
            "types": {"video": {"total": 3, "retrievable": 2, "content_processing": 0, "tag_processing": 1, "failed": 1}},
        }

    monkeypatch.setattr(agent_router, "pg_get_agent", get_agent)
    monkeypatch.setattr(agent_router, "verify_kb_access", lambda kb, current_user: _async_value(kb))
    monkeypatch.setattr(agent_router, "pg_create_conversation", create_conversation)
    monkeypatch.setattr(agent_router, "pg_add_message", add_message)
    monkeypatch.setattr(agent_router, "record_query", record)
    monkeypatch.setattr(agent_router, "get_knowledge_inventory", inventory)
    monkeypatch.setattr(agent_router, "validate_query_input", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(agent_router, "acquire_query_kb", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("RAG must not run")))
    monkeypatch.setattr(agent_router, "authenticated_sse_events", lambda events, _user: events)

    response = await agent_router.agent_query_stream(
        "agent-1",
        agent_router.AgentQueryRequest(query="知识库中有多少个视频"),
        _Request(),
        current_user={"id": 7, "username": "tester"},
        _perm=None,
    )
    events = [json.loads(line[6:]) for line in (await _body(response)).splitlines() if line.startswith("data: ")]

    assert [event["type"] for event in events] == ["agent_info", "token", "done"]
    assert "总数 3" in events[1]["content"]
    assert events[2]["inventory"]["types"]["video"]["total"] == 3
    assert "citations" not in events[2]
    assert [message["role"] for message in calls["messages"]] == ["user", "assistant"]
    assert calls["record"] == 1


async def _async_value(value):
    return value
