from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException

from raganything import dependencies
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
    assert agent_router.detect_knowledge_inventory_intent("这个知识库包含多少个文件") == "all"
    assert agent_router.detect_knowledge_inventory_intent("视频知识库有多少个文件") == "all"
    assert agent_router.detect_knowledge_inventory_intent("资料库共有多少文档") == "all"
    assert agent_router.detect_knowledge_inventory_intent("文档库文档数量") == "all"
    assert agent_router.detect_knowledge_inventory_intent("知识库有多少 Word 文档") == "document"
    assert agent_router.detect_knowledge_inventory_intent("知识库有多少 DOC") == "document"
    assert agent_router.detect_knowledge_inventory_intent("知识库有多少 docx") == "document"
    assert agent_router.detect_knowledge_inventory_intent("知识库有多少") == "all"
    assert agent_router.detect_knowledge_inventory_intent("视频中有多少个零件") is None
    assert agent_router.detect_knowledge_inventory_intent("知识库中的视频有多少个零件") is None
    assert agent_router.detect_knowledge_inventory_intent("知识库有多少视频和 PDF") is None


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
            "all": {"total": 6, "retrievable": 5, "content_processing": 0, "tag_processing": 1, "failed": 0},
            "types": {"video": {"total": 6, "retrievable": 5, "content_processing": 0, "tag_processing": 1, "failed": 0}},
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
        agent_router.AgentQueryRequest(query="这个知识库包含多少个文件"),
        _Request(),
        current_user={"id": 7, "username": "tester"},
        _perm=None,
    )
    events = [json.loads(line[6:]) for line in (await _body(response)).splitlines() if line.startswith("data: ")]

    assert [event["type"] for event in events] == ["accepted", "agent_info", "token", "done"]
    token_event = next(event for event in events if event["type"] == "token")
    agent_info_event = next(event for event in events if event["type"] == "agent_info")
    done_event = next(event for event in events if event["type"] == "done")
    assert "知识库文件库存：总数 6" in token_event["content"]
    assert "视频 6" in token_event["content"]
    assert done_event["inventory"]["all"]["total"] == 6
    assert done_event["inventory"]["types"]["video"]["total"] == 6
    assert done_event["citations"] == []
    assert agent_info_event["fixed_path"] == "knowledge_inventory"
    assert agent_info_event["config_applied"] is False
    assert done_event["fixed_path"] == "knowledge_inventory"
    assert done_event["config_applied"] is False
    assert [message["role"] for message in calls["messages"]] == ["user", "assistant"]
    assert calls["messages"][1]["fixed_path"] == "knowledge_inventory"
    assert calls["messages"][1]["config_applied"] is False
    assert calls["record"] == 1


@pytest.mark.asyncio
async def test_inventory_stream_accepts_before_blocking_preparation(monkeypatch):
    inventory_started = asyncio.Event()
    release_inventory = asyncio.Event()

    async def get_agent(_agent_id):
        return {"id": "agent-1", "name": "演示智能体", "icon": "", "kb_name": "demo"}

    async def inventory(_kb):
        inventory_started.set()
        await release_inventory.wait()
        return {
            "all": {"total": 0, "retrievable": 0, "content_processing": 0, "tag_processing": 0, "failed": 0},
            "types": {},
        }

    monkeypatch.setattr(agent_router, "pg_get_agent", get_agent)
    monkeypatch.setattr(agent_router, "verify_kb_access", lambda kb, current_user: _async_value(kb))
    monkeypatch.setattr(agent_router, "pg_create_conversation", lambda *_args, **_kwargs: _async_value({"id": "thread-1"}))
    monkeypatch.setattr(agent_router, "pg_add_message", lambda *_args, **_kwargs: _async_value(None))
    monkeypatch.setattr(agent_router, "record_query", lambda *_args, **_kwargs: _async_value(None))
    monkeypatch.setattr(agent_router, "get_knowledge_inventory", inventory)
    monkeypatch.setattr(agent_router, "validate_query_input", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(agent_router, "authenticated_sse_events", lambda events, _user: events)

    response = await agent_router.agent_query_stream(
        "agent-1",
        agent_router.AgentQueryRequest(query="这个知识库包含多少个文件"),
        _Request(),
        current_user={"id": 7, "username": "tester"},
        _perm=None,
    )
    assert not inventory_started.is_set()

    iterator = response.body_iterator
    first = await anext(iterator)
    assert json.loads(first[6:])["type"] == "accepted"
    assert not inventory_started.is_set()

    next_event = asyncio.create_task(anext(iterator))
    await asyncio.wait_for(inventory_started.wait(), timeout=1)
    assert not next_event.done()
    release_inventory.set()
    assert json.loads((await next_event)[6:])["type"] == "agent_info"
    await iterator.aclose()


@pytest.mark.asyncio
async def test_inventory_missing_agent_returns_http_404_before_stream(monkeypatch):
    monkeypatch.setattr(agent_router, "pg_get_agent", lambda _agent_id: _async_value(None))
    monkeypatch.setattr(agent_router, "validate_query_input", lambda *_args, **_kwargs: None)

    with pytest.raises(HTTPException) as raised:
        await agent_router.agent_query_stream(
            "missing-agent",
            agent_router.AgentQueryRequest(query="这个知识库包含多少个文件"),
            _Request(),
            current_user={"id": 7, "username": "tester"},
            _perm=None,
        )

    assert raised.value.status_code == 404


@pytest.mark.asyncio
async def test_inventory_kb_denial_returns_http_403_before_stream(monkeypatch):
    async def get_agent(_agent_id):
        return {"id": "agent-1", "name": "演示智能体", "kb_name": "private"}

    async def deny_kb(kb, current_user):
        raise HTTPException(403, "无权访问知识库")

    monkeypatch.setattr(agent_router, "pg_get_agent", get_agent)
    monkeypatch.setattr(agent_router, "verify_kb_access", deny_kb)
    monkeypatch.setattr(agent_router, "validate_query_input", lambda *_args, **_kwargs: None)

    with pytest.raises(HTTPException) as raised:
        await agent_router.agent_query_stream(
            "agent-1",
            agent_router.AgentQueryRequest(query="这个知识库包含多少个文件"),
            _Request(),
            current_user={"id": 7, "username": "tester"},
            _perm=None,
        )

    assert raised.value.status_code == 403


@pytest.mark.asyncio
async def test_inventory_invalid_thread_returns_http_404_before_stream(monkeypatch):
    async def get_agent(_agent_id):
        return {"id": "agent-1", "name": "演示智能体", "kb_name": "demo"}

    async def missing_thread(_agent_id, _thread_id, _current_user):
        raise HTTPException(404, "对话线程不存在")

    monkeypatch.setattr(agent_router, "pg_get_agent", get_agent)
    monkeypatch.setattr(
        agent_router, "verify_kb_access", lambda kb, current_user: _async_value(kb)
    )
    monkeypatch.setattr(agent_router, "_require_owned_conversation", missing_thread)
    monkeypatch.setattr(agent_router, "validate_query_input", lambda *_args, **_kwargs: None)

    with pytest.raises(HTTPException) as raised:
        await agent_router.agent_query_stream(
            "agent-1",
            agent_router.AgentQueryRequest(
                query="这个知识库包含多少个文件",
                thread_id="missing-thread",
            ),
            _Request(),
            current_user={"id": 7, "username": "tester"},
            _perm=None,
        )

    assert raised.value.status_code == 404


@pytest.mark.asyncio
async def test_empty_accepted_event_skips_repeat_session_lookup(monkeypatch):
    checks = 0

    async def events():
        yield 'data: {"type": "accepted"}\n\n'
        yield 'data: {"type": "agent_info"}\n\n'

    async def session_current(_user):
        nonlocal checks
        checks += 1
        return False

    monkeypatch.setattr(dependencies, "account_session_is_current", session_current)
    result = [event async for event in dependencies.authenticated_sse_events(events(), {"id": 7})]

    assert result == ['data: {"type": "accepted"}\n\n']
    assert checks == 1


async def _async_value(value):
    return value
