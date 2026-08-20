"""Regression contracts for the superseding global KB visibility behavior.

The historical ``persist-kb-access-grants`` change is retained for audit, but
its runtime grant projection was superseded by global resource visibility.
These tests make that current boundary explicit without reviving the retired
``allowed_kbs`` mutation path.
"""

import pytest
from fastapi import HTTPException

from raganything import dependencies
from raganything.permissions import DEFAULT_ROLES, Permission
from raganything.routers.knowledge import _kb_capabilities_from_metadata


def _role_user(role_name: str, user_id: int = 9) -> dict:
    return {
        "id": user_id,
        "username": role_name,
        "is_admin": role_name == "super_admin",
        "role": {
            "name": role_name,
            "permissions": DEFAULT_ROLES[role_name]["permissions"],
        },
    }


@pytest.fixture
def kb_permission_context(monkeypatch):
    async def load_meta():
        return {"owned-kb": {"owner_id": 9}, "shared-kb": {"owner_id": 77}}

    async def has_permission(_user_id, permission):
        return permission in {
            Permission.KB_READ,
            Permission.KB_WRITE,
            Permission.KB_MANAGE,
            Permission.KB_DELETE,
        }

    monkeypatch.setattr("raganything.services.kb_service.load_kb_meta", load_meta)
    monkeypatch.setattr(dependencies, "_auth_has_permission", has_permission)


@pytest.mark.asyncio
async def test_existing_kb_requires_global_read_permission(kb_permission_context, monkeypatch):
    async def deny_read(_user_id, permission):
        return permission != Permission.KB_READ

    monkeypatch.setattr(dependencies, "_auth_has_permission", deny_read)
    with pytest.raises(HTTPException) as raised:
        await dependencies.verify_kb_access("shared-kb", {"id": 9})
    assert raised.value.status_code == 403


@pytest.mark.asyncio
async def test_unknown_kb_is_not_disclosed_as_permission_failure(kb_permission_context):
    with pytest.raises(HTTPException) as raised:
        await dependencies.verify_kb_access("missing-kb", {"id": 9})
    assert raised.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("role_name", ["super_admin", "dept_admin", "teacher", "assistant", "student"])
async def test_all_roles_with_kb_read_can_read_existing_cross_owner_kb(
    kb_permission_context, role_name
):
    assert await dependencies.verify_kb_access("shared-kb", _role_user(role_name)) == "shared-kb"


@pytest.mark.parametrize("role_name", ["super_admin", "dept_admin", "teacher", "assistant", "student"])
def test_kb_capabilities_are_projected_from_role_permissions(role_name):
    capabilities = _kb_capabilities_from_metadata(
        "shared-kb", {"owner_id": 77}, _role_user(role_name)
    )
    permissions = set(DEFAULT_ROLES[role_name]["permissions"])
    assert capabilities == {
        "read": True,
        "operate": Permission.KB_WRITE in permissions or role_name == "super_admin",
        "rename": Permission.KB_MANAGE in permissions or role_name == "super_admin",
        "delete": Permission.KB_DELETE in permissions or role_name == "super_admin",
    }


def test_retired_grant_field_is_not_projected_or_mutated():
    from raganything.routers.auth import AdminUpdateUserRequest

    request = AdminUpdateUserRequest(allowed_kbs=["shared-kb"])
    assert request.allowed_kbs == ["shared-kb"]

    import inspect
    from raganything.services import pg_auth_repo

    source = inspect.getsource(pg_auth_repo.update_user)
    assert "knowledge-base grants are retired" in source
