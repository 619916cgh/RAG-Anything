"""Focused regressions for the current global KB visibility/RBAC contract.

The historical per-user ``allowed_kbs`` grant projection is intentionally not
restored here.  These tests pin the superseding behavior: KB visibility is
global for callers with the corresponding RBAC permission, while mutations
remain permission-gated and stale sessions are rejected by generation.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from raganything import dependencies
from raganything.permissions import DEFAULT_ROLES, Permission
from raganything.routers import knowledge
from raganything.services import pg_auth_repo


def _user(role_name: str, user_id: int = 9) -> dict:
    permissions = DEFAULT_ROLES[role_name]["permissions"]
    return {
        "id": user_id,
        "username": role_name,
        "is_admin": role_name == "super_admin",
        "role": {"name": role_name, "permissions": permissions},
    }


@pytest.fixture
def two_kb_metadata(monkeypatch):
    async def fake_load_kb_meta():
        return {
            "owner-kb": {
                "owner_id": 7,
                "owner_username": "owner",
                "created": "2026-01-01T00:00:00+00:00",
            },
            "second-kb": {
                "owner_id": 8,
                "owner_username": "other-owner",
                "created": "2026-01-02T00:00:00+00:00",
            },
        }

    async def fake_stats(_names):
        return {}

    monkeypatch.setattr(knowledge, "load_kb_meta", fake_load_kb_meta)
    monkeypatch.setattr(knowledge, "_compute_kb_stats_batch_fast", fake_stats)
    return fake_load_kb_meta


@pytest.mark.asyncio
@pytest.mark.parametrize("role_name", ["super_admin", "dept_admin", "teacher", "assistant", "student"])
async def test_all_rbac_roles_with_kb_read_can_read_foreign_kb(monkeypatch, role_name):
    async def fake_load_kb_meta():
        return {"foreign-kb": {"owner_id": 101}}

    async def allow_read(_user_id, permission):
        return permission == Permission.KB_READ

    monkeypatch.setattr("raganything.services.kb_service.load_kb_meta", fake_load_kb_meta)
    monkeypatch.setattr(dependencies, "_auth_has_permission", allow_read)

    assert await dependencies.verify_kb_access("foreign-kb", _user(role_name)) == "foreign-kb"


@pytest.mark.asyncio
async def test_kb_read_denial_returns_403_without_cross_owner_data(monkeypatch):
    async def fake_load_kb_meta():
        return {"foreign-kb": {"owner_id": 101}}

    async def deny(_user_id, permission):
        assert permission == Permission.KB_READ
        return False

    monkeypatch.setattr("raganything.services.kb_service.load_kb_meta", fake_load_kb_meta)
    monkeypatch.setattr(dependencies, "_auth_has_permission", deny)

    with pytest.raises(HTTPException) as exc:
        await dependencies.verify_kb_access("foreign-kb", _user("student"))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_kb_write_and_manage_denial_are_independent_from_read(monkeypatch):
    async def fake_load_kb_meta():
        return {"foreign-kb": {"owner_id": 101}}

    async def allow_read_only(_user_id, permission):
        return permission == Permission.KB_READ

    monkeypatch.setattr("raganything.services.kb_service.load_kb_meta", fake_load_kb_meta)
    monkeypatch.setattr(dependencies, "_auth_has_permission", allow_read_only)
    actor = _user("student")

    assert await dependencies.verify_kb_access("foreign-kb", actor) == "foreign-kb"
    for checker in (dependencies.verify_kb_operate_access, dependencies.verify_kb_manage_access):
        with pytest.raises(HTTPException) as exc:
            await checker("foreign-kb", actor)
        assert exc.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("role_name", ["super_admin", "dept_admin", "teacher", "assistant", "student"])
async def test_kb_list_projects_global_visibility_and_role_capabilities(two_kb_metadata, role_name):
    result = await knowledge.list_kbs(current_user=_user(role_name))
    listed = {item["name"]: item for item in result["knowledge_bases"]}

    assert set(listed) == {"owner-kb", "second-kb"}
    capabilities = listed["second-kb"]["capabilities"]
    permissions = set(DEFAULT_ROLES[role_name]["permissions"])
    assert capabilities["read"] is True
    assert capabilities["operate"] is (Permission.KB_WRITE in permissions)
    assert capabilities["rename"] is (Permission.KB_MANAGE in permissions)
    assert capabilities["delete"] is (Permission.KB_DELETE in permissions)


@pytest.mark.asyncio
async def test_session_generation_change_invalidates_existing_authenticated_session(monkeypatch):
    current_user = {"id": 42, "session_generation": 3, "token_jti": "jti"}
    account = {"id": 42, "is_active": True, "archived_at": None, "session_generation": 3}

    async def token_not_revoked(_jti):
        return False

    async def current_account(_user_id):
        return account

    monkeypatch.setattr(dependencies, "_auth_is_token_revoked", token_not_revoked)
    monkeypatch.setattr(dependencies, "get_user_by_id", current_account)

    assert await dependencies.account_session_is_current(current_user) is True
    account["session_generation"] = 4
    assert await dependencies.account_session_is_current(current_user) is False


@pytest.mark.asyncio
async def test_repository_rejects_legacy_allowed_kbs_before_database_mutation():
    with pytest.raises(ValueError, match="retired"):
        await pg_auth_repo.update_user(7, {"allowed_kbs": ["team-kb"]}, actor_id=1)
