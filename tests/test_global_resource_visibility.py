import pytest
from fastapi import HTTPException

from raganything.routers import agent
from raganything.services import pg_agent_repo


@pytest.mark.asyncio
async def test_conversation_owner_check_has_no_super_admin_bypass(monkeypatch):
    async def foreign_thread(_agent_id, _thread_id):
        return {"id": "thread-b", "agent_id": "shared", "owner_id": 22, "messages": [{"content": "private"}]}

    monkeypatch.setattr(agent, "pg_get_conversation", foreign_thread)

    with pytest.raises(HTTPException) as exc:
        await agent._require_owned_conversation("shared", "thread-b", {"id": 1, "is_admin": True})

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_ownerless_conversation_is_not_readable(monkeypatch):
    async def ownerless_thread(_agent_id, _thread_id):
        return {"id": "legacy", "agent_id": "shared", "owner_id": 0, "messages": []}

    monkeypatch.setattr(agent, "pg_get_conversation", ownerless_thread)

    with pytest.raises(HTTPException) as exc:
        await agent._require_owned_conversation("shared", "legacy", {"id": 7})

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_shared_agent_directory_sql_has_no_agent_owner_filter(monkeypatch):
    calls = []

    class Pool:
        async def fetch(self, query, *args):
            calls.append((query, args))
            return []

    monkeypatch.setattr(pg_agent_repo, "_get_pool", lambda: Pool())
    assert await pg_agent_repo.pg_list_agents(user_id=7) == []
    query, args = calls[0]
    assert "WHERE a.owner_id" not in query
    assert "owner_id = $1" in query
    assert args == (7,)
