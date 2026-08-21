# -*- coding: utf-8 -*-
"""
RAG-Anything WebSocket Service.

Layer: Service
Primary Responsibility: WebSocket connection tracking, broadcasting,
    progress emission, event logging.
Key Dependencies: fastapi (WebSocket), asyncio

Extracted from routers/shared.py. All WebSocket management is centralized here.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import WebSocket

ws_logger = logging.getLogger("rag_server.ws")

# ── WebSocket State ────────────────────────────────────────

ws_clients: list[WebSocket] = []
"""Authenticated ordinary task-event connections."""

monitor_ws_clients: list[WebSocket] = []
"""Explicitly monitor-authorized event connections."""

_ws_sessions: dict[WebSocket, dict[str, Any]] = {}
"""Authenticated account session snapshot for each connected WebSocket."""

_event_lock = asyncio.Lock()
"""Lock for thread-safe event list mutation."""

processing_events: list[dict] = []
"""In-memory event log (max 200 entries)."""


# ── Broadcast ──────────────────────────────────────────────

def _event_pg_ready() -> bool:
    """Return whether the PG pool is ready for monitor-event persistence."""
    try:
        from raganything.services.pg_state_repo import get_pg_pool
        get_pg_pool()
        return True
    except RuntimeError:
        return False

_TASK_EVENT_FIELDS = {
    "type", "task_id", "progress", "phase", "phase_status", "status",
    "outcome", "failure_stage",
}
_MONITOR_EVENT_FIELDS = {"time", "event", "outcome", "failure_stage", "status"}


async def is_ws_session_current(session: dict[str, Any]) -> bool:
    """Fail closed before accepting input or delivering a WS event."""
    return await _session_is_current(session)


async def ws_send_to_owner(owner_user_id: int | None, data: dict[str, Any]) -> None:
    """Deliver a minimally projected task event to its durable owner only."""
    if not isinstance(owner_user_id, int) or owner_user_id <= 0:
        ws_logger.warning("Dropping task event without an owner: type=%s", data.get("type"))
        return
    payload = {key: value for key, value in data.items() if key in _TASK_EVENT_FIELDS}
    if not payload.get("type"):
        return
    dead = []
    for ws in ws_clients:
        try:
            session = _ws_sessions.get(ws, {})
            if not await _session_is_current(session):
                await ws.close(code=4001, reason="Account session is no longer valid")
                dead.append(ws)
                continue
            if session.get("id") != owner_user_id:
                continue
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in ws_clients:
            ws_clients.remove(ws)
        _ws_sessions.pop(ws, None)


async def ws_broadcast(data: dict[str, Any], *, owner_user_id: int | None = None) -> None:
    """Compatibility boundary for task events.

    Ordinary task updates are no longer global broadcasts. Callers must supply
    a server-derived owner; missing ownership is intentionally dropped.
    """
    await ws_send_to_owner(owner_user_id, data)


async def ws_monitor_broadcast(event: dict[str, Any]) -> None:
    """Deliver aggregate, projected monitor events to authorized sockets."""
    payload = {key: value for key, value in event.items() if key in _MONITOR_EVENT_FIELDS}
    dead = []
    for ws in monitor_ws_clients:
        try:
            if not await _session_is_current(_ws_sessions.get(ws, {})):
                await ws.close(code=4001, reason="Account session is no longer valid")
                dead.append(ws)
                continue
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in monitor_ws_clients:
            monitor_ws_clients.remove(ws)
        _ws_sessions.pop(ws, None)


async def _session_is_current(session: dict[str, Any]) -> bool:
    """Fail closed before delivering a WS event to an existing connection."""
    user_id = session.get("id")
    if not user_id:
        return False
    try:
        from raganything.services.auth import get_user_by_id, is_token_revoked

        jti = session.get("token_jti")
        if not jti or await is_token_revoked(jti):
            return False
        account = await get_user_by_id(user_id)
        return bool(
            account and account.get("is_active") and account.get("archived_at") is None
            and int(account.get("session_generation", 0)) == int(session.get("session_generation"))
        )
    except (TypeError, ValueError):
        return False
    except Exception:
        return False


# ── Progress ───────────────────────────────────────────────

async def emit_progress(
    task_id: str, progress: int, msg: str = "", *, owner_user_id: int | None = None
) -> None:
    """Emit a progress update for a processing task.

    Updates PG + local cache via ``update_task_progress()`` and broadcasts
    to all WS clients.

    Args:
        task_id: Processing task identifier
        progress: Progress percentage (0-100)
        msg: Human-readable progress message
    """
    from raganything.services.state_service import update_task_progress

    await update_task_progress(task_id, progress, message=msg)
    await ws_send_to_owner(owner_user_id, {
        "type": "progress",
        "task_id": task_id,
        "progress": progress,
    })


# ── Events ─────────────────────────────────────────────────

async def load_persisted_monitor_events(limit: int = 200) -> int:
    """Warm the in-memory event window from persistent storage."""
    global processing_events
    if not _event_pg_ready():
        return len(processing_events)

    try:
        from raganything.services.pg_state_repo import get_monitor_events as _pg_get_monitor_events
        events = await _pg_get_monitor_events(limit=limit)
    except Exception as exc:
        ws_logger.warning("Failed to load persisted monitor events: %s", exc)
        return len(processing_events)

    async with _event_lock:
        processing_events[:] = events[-limit:]
        return len(processing_events)


async def get_monitor_events(
    limit: int = 50,
    *,
    user_id: Optional[int] = None,
    is_admin: bool = False,
) -> list[dict[str, Any]]:
    """Get recent monitor events from PG, falling back to memory if needed."""
    if limit <= 0:
        return []

    if _event_pg_ready():
        try:
            from raganything.services.pg_state_repo import get_monitor_events as _pg_get_monitor_events
            if is_admin:
                return await _pg_get_monitor_events(limit=limit)
            return await _pg_get_monitor_events(limit=limit, user_id=user_id, include_global=True)
        except Exception as exc:
            ws_logger.warning("Failed to query persisted monitor events: %s", exc)

    async with _event_lock:
        if is_admin or user_id is None:
            return processing_events[-limit:]
        visible = [
            current_event for current_event in processing_events
            if current_event.get("user_id", 0) in (0, user_id)
        ]
        return visible[-limit:]

async def add_event(event: str, user_id: int = 0, **kw: Any) -> None:
    """Add a processing event to the in-memory log.

    Maintains a rolling window of 200 events.

    Args:
        event: Event name
        user_id: Associated user ID
        **kw: Additional event fields
    """
    global processing_events
    e = {
        "time": datetime.now().astimezone().isoformat(),
        "event": event,
        "user_id": user_id,
        **kw,
    }
    async with _event_lock:
        processing_events.append(e)
        if len(processing_events) > 200:
            processing_events[:] = processing_events[-200:]
    if _event_pg_ready():
        try:
            from raganything.services.pg_state_repo import insert_monitor_event
            await insert_monitor_event(e)
        except Exception as exc:
            ws_logger.warning("Failed to persist monitor event %s: %s", event, exc)
    await ws_monitor_broadcast(e)


# ── Connection Management ──────────────────────────────────

def register_general_ws(ws: WebSocket, session: dict[str, Any]) -> None:
    """Register a general WebSocket together with its validated session."""
    ws_clients.append(ws)
    _ws_sessions[ws] = dict(session)


def register_monitor_ws(ws: WebSocket, session: dict[str, Any]) -> None:
    """Register a monitor-authorized connection separately from task sockets."""
    monitor_ws_clients.append(ws)
    _ws_sessions[ws] = dict(session)


def unregister_general_ws(ws: WebSocket) -> None:
    """Remove a general WebSocket and its authentication snapshot."""
    if ws in ws_clients:
        ws_clients.remove(ws)
    _ws_sessions.pop(ws, None)


def unregister_monitor_ws(ws: WebSocket) -> None:
    if ws in monitor_ws_clients:
        monitor_ws_clients.remove(ws)
    _ws_sessions.pop(ws, None)


__all__ = [
    "ws_clients",
    "monitor_ws_clients",
    "processing_events",
    "ws_broadcast",
    "ws_send_to_owner",
    "ws_monitor_broadcast",
    "is_ws_session_current",
    "emit_progress",
    "load_persisted_monitor_events",
    "get_monitor_events",
    "add_event",
    "register_general_ws",
    "unregister_general_ws",
    "register_monitor_ws",
    "unregister_monitor_ws",
]
