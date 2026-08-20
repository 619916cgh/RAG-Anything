import pytest


@pytest.mark.asyncio
async def test_task_events_are_owner_scoped_and_redacted(monkeypatch):
    from raganything.services import ws_service

    class Socket:
        def __init__(self):
            self.events = []
            self.closed = []

        async def send_json(self, payload):
            self.events.append(payload)

        async def close(self, code, reason):
            self.closed.append((code, reason))

    async def current(_session):
        return True

    monkeypatch.setattr(ws_service, "_session_is_current", current)
    owner, other = Socket(), Socket()
    ws_service.ws_clients[:] = []
    ws_service._ws_sessions.clear()
    ws_service.register_general_ws(owner, {"id": 11, "session_generation": 1, "token_jti": "owner"})
    ws_service.register_general_ws(other, {"id": 12, "session_generation": 1, "token_jti": "other"})

    await ws_service.ws_broadcast({
        "type": "progress", "task_id": "task-1", "progress": 10,
        "filename": "private.pdf", "kb": "private-kb", "error": "raw failure",
    }, owner_user_id=11)
    await ws_service.ws_broadcast({"type": "progress", "task_id": "missing"})

    assert owner.events == [{"type": "progress", "task_id": "task-1", "progress": 10}]
    assert other.events == []
    assert owner.closed == []
    ws_service.ws_clients[:] = []
    ws_service._ws_sessions.clear()


@pytest.mark.asyncio
async def test_revoked_session_closes_before_owner_delivery(monkeypatch):
    from raganything.services import ws_service

    calls = []

    class Socket:
        async def send_json(self, _payload):
            calls.append("send")

        async def close(self, code, reason):
            calls.append((code, reason))

    async def revoked(_session):
        return False

    socket = Socket()
    ws_service.ws_clients[:] = []
    ws_service._ws_sessions.clear()
    monkeypatch.setattr(ws_service, "_session_is_current", revoked)
    ws_service.register_general_ws(socket, {"id": 11, "session_generation": 1, "token_jti": "revoked"})
    await ws_service.ws_send_to_owner(11, {"type": "progress", "task_id": "task-1"})

    assert calls == [(4001, "Account session is no longer valid")]
    assert socket not in ws_service.ws_clients
