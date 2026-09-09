"""Targeted tests for backend route isolation and resource cleanup."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).parent.parent))

from raganything.permissions import Permission  # noqa: E402


def _route_dependency_names(router, path: str, method: str) -> list[str]:
    for route in router.routes:
        if getattr(route, "path", None) == path and method.upper() in getattr(route, "methods", set()):
            return [
                getattr(getattr(dep, "call", None), "__name__", repr(getattr(dep, "call", None)))
                for dep in route.dependant.dependencies
            ]
    raise AssertionError(f"route not found: {method} {path}")


class _Req:
    url = type("Url", (), {"path": "/api/test"})()
    method = "GET"
    client = None


class TestWorkflowRoutesRemoved:
    def test_workflow_routes_and_permissions_are_absent(self):
        from raganything.routers import admin

        paths = {route.path for route in admin.router.routes}
        assert not any(path.startswith("/workflows") for path in paths)
        assert "/ws/workflow-run/{run_id}" not in paths
        assert "/ws" in paths
        assert "/ws/monitor" in paths
        assert not hasattr(Permission, "WORKFLOW_READ")
        assert not hasattr(Permission, "WORKFLOW_WRITE")


# ── vision-settings read guard ────────────────────────────

class TestVisionSettingsReadGuard:
    def test_get_uses_read_guard_and_put_keeps_write_guard(self):
        from raganything.routers import knowledge

        get_names = _route_dependency_names(knowledge.router, "/kb/{kb}/vision-settings", "GET")
        # GET uses the named read-access helper (kb:read inside); no bare permission closure.
        assert "_verify_kb_vision_read_access" in get_names
        assert "require_kb_read" not in get_names
        put_names = _route_dependency_names(knowledge.router, "/kb/{kb}/vision-settings", "PUT")
        assert "_verify_kb_vision_write_access" in put_names

    @pytest.mark.asyncio
    async def test_read_guard_requires_kb_read(self, monkeypatch):
        from raganything.routers import knowledge

        async def allow_kb(kb, user):
            return kb

        async def deny_permission(user_id, permission):
            assert permission == Permission.KB_READ
            return False

        monkeypatch.setattr(knowledge, "verify_kb_access", allow_kb)
        monkeypatch.setattr("raganything.routers.knowledge._auth_has_permission", deny_permission)
        with pytest.raises(HTTPException) as exc:
            await knowledge._verify_kb_vision_read_access(
                kb="demo",
                current_user={"id": 9, "username": "s", "role": {"name": "student"}},
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_read_guard_allows_kb_read(self, monkeypatch):
        from raganything.routers import knowledge

        async def allow_kb(kb, user):
            return kb

        async def allow_permission(user_id, permission):
            return True

        monkeypatch.setattr(knowledge, "verify_kb_access", allow_kb)
        monkeypatch.setattr("raganything.routers.knowledge._auth_has_permission", allow_permission)
        result = await knowledge._verify_kb_vision_read_access(
            kb="demo",
            current_user={"id": 9, "username": "s", "role": {"name": "student"}},
        )
        assert result == "demo"


class TestCleanupKbResourcesOrdering:
    @pytest.mark.asyncio
    async def test_collects_file_paths_before_begin_deletion(self, monkeypatch, tmp_path):
        import raganything.services.kb_service as kb_service

        calls = []

        async def fake_load_doc_status(name):
            calls.append("collect_doc_status")
            return {"doc1": {"file_path": "uploads/report.pdf"}}

        async def fake_load_text_chunks(name):
            calls.append("collect_text_chunks")
            return {}

        def fake_begin_deletion(name):
            calls.append("begin_deletion")
            return []

        async def fake_wait_leases(name, timeout):
            return True

        async def fake_cancel_tags(name):
            return None

        async def fake_load_meta():
            return {}

        async def fake_save_meta(meta):
            return None

        class Transaction:
            def __init__(self, connection):
                self.connection = connection

            async def __aenter__(self):
                return None

            async def __aexit__(self, exc_type, exc, tb):
                return None

        class Connection:
            def transaction(self):
                return Transaction(self)

            async def fetch(self, _sql, *args):
                return []

            async def execute(self, _sql, *args):
                return "DELETE 0"

        class Acquire:
            def __init__(self):
                self.connection = Connection()

            async def __aenter__(self):
                return self.connection

            async def __aexit__(self, exc_type, exc, tb):
                return None

        class Pool:
            def acquire(self):
                return Acquire()

        from raganything import query_cache
        from raganything.services import pg_kb_meta_repo, pg_state_repo

        monkeypatch.setattr(pg_state_repo, "get_pg_pool", lambda: Pool())
        monkeypatch.setattr(
            pg_kb_meta_repo,
            "pg_delete_kb_meta",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            query_cache,
            "get_query_cache",
            lambda: SimpleNamespace(invalidate=lambda: None),
        )
        monkeypatch.setattr(kb_service, "_load_doc_status_json", fake_load_doc_status)
        monkeypatch.setattr(kb_service, "_load_text_chunks_json", fake_load_text_chunks)
        monkeypatch.setattr(kb_service.kb_instances, "begin_deletion", fake_begin_deletion)
        monkeypatch.setattr(kb_service.kb_instances, "wait_for_no_query_leases", fake_wait_leases)
        monkeypatch.setattr(kb_service, "_cancel_deferred_auto_tag_tasks", fake_cancel_tags)
        monkeypatch.setattr(kb_service, "load_kb_meta", fake_load_meta)
        monkeypatch.setattr(kb_service, "save_kb_meta", fake_save_meta)
        monkeypatch.setattr(kb_service, "kb_dir", lambda name: str(tmp_path / name))

        await kb_service.cleanup_kb_resources("demo")

        assert calls.index("collect_doc_status") < calls.index("begin_deletion")
        assert calls.index("collect_text_chunks") < calls.index("begin_deletion")


# ── agent conversation guard downgrade ─────────────────────

class TestAgentConversationGuards:
    def test_conversation_routes_use_agent_read(self):
        from raganything.routers import agent

        assert "require_agent_read" in _route_dependency_names(
            agent.router, "/agents/{agent_id}/conversations", "POST"
        )
        assert "require_agent_read" in _route_dependency_names(
            agent.router, "/agents/{agent_id}/conversations/{thread_id}", "PUT"
        )
        assert "require_agent_read" in _route_dependency_names(
            agent.router, "/agents/{agent_id}/conversations/{thread_id}", "DELETE"
        )
        assert "require_agent_write" in _route_dependency_names(
            agent.router,
            "/agents/{agent_id}/conversations/{thread_id}/messages/{message_id}",
            "PUT",
        )
