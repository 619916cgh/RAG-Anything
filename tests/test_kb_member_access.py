import pytest
from fastapi import HTTPException

from raganything.dependencies import (
    verify_kb_access,
    verify_kb_manage_access,
    verify_kb_operate_access,
)
from raganything.permissions import DEFAULT_ROLES, Permission
from raganything.routers.knowledge import _kb_capabilities_from_metadata


@pytest.fixture(autouse=True)
def kb_metadata(monkeypatch):
    async def fake_load_kb_meta():
        return {"team-kb": {"owner_id": 10, "owner_username": "teacher-owner"}}

    monkeypatch.setattr("raganything.services.kb_service.load_kb_meta", fake_load_kb_meta)


def user(user_id, role_name, *, access_level=None):
    levels = {"team-kb": access_level} if access_level else {}
    return {
        "id": user_id,
        "is_admin": role_name == "super_admin",
        "role": {"name": role_name},
        "allowed_kbs": list(levels),
        "kb_access_levels": levels,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("role_name,access_level", [
    ("super_admin", None),
    ("dept_admin", "read"),
    ("teacher", "read"),
    ("assistant", "read"),
    ("student", "read"),
])
async def test_all_roles_can_read_owned_or_explicitly_granted_kb(role_name, access_level):
    actor = user(1, role_name, access_level=access_level)
    assert await verify_kb_access("team-kb", actor) == "team-kb"


@pytest.mark.asyncio
@pytest.mark.parametrize("role_name", ["dept_admin", "teacher", "assistant"])
async def test_read_grants_never_allow_content_operations(role_name):
    with pytest.raises(HTTPException) as exc:
        await verify_kb_operate_access("team-kb", user(1, role_name, access_level="read"))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("role_name", ["dept_admin", "teacher", "assistant"])
async def test_operate_grants_allow_content_scope_for_write_capable_roles(role_name):
    assert await verify_kb_operate_access("team-kb", user(1, role_name, access_level="operate")) == "team-kb"


@pytest.mark.asyncio
async def test_member_management_is_limited_to_super_admin_dept_scope_and_teacher_owner():
    assert await verify_kb_manage_access("team-kb", user(1, "super_admin")) == "team-kb"
    assert await verify_kb_manage_access("team-kb", user(1, "dept_admin", access_level="operate")) == "team-kb"
    assert await verify_kb_manage_access("team-kb", user(10, "teacher")) == "team-kb"

    for actor in (
        user(1, "dept_admin", access_level="read"),
        user(1, "teacher", access_level="operate"),
        user(1, "assistant", access_level="operate"),
        user(1, "student", access_level="read"),
    ):
        with pytest.raises(HTTPException) as exc:
            await verify_kb_manage_access("team-kb", actor)
        assert exc.value.status_code == 403


def test_kb_manage_is_only_granted_to_management_roles():
    assert Permission.KB_MANAGE in DEFAULT_ROLES["super_admin"]["permissions"]
    assert Permission.KB_MANAGE in DEFAULT_ROLES["dept_admin"]["permissions"]
    assert Permission.KB_MANAGE in DEFAULT_ROLES["teacher"]["permissions"]
    assert Permission.KB_MANAGE not in DEFAULT_ROLES["assistant"]["permissions"]
    assert Permission.KB_MANAGE not in DEFAULT_ROLES["student"]["permissions"]


@pytest.mark.parametrize("role_name", ["dept_admin", "teacher"])
def test_role_derived_read_only_capabilities_hide_mutations(role_name):
    current_user = user(1, role_name)
    current_user["role"]["permissions"] = DEFAULT_ROLES[role_name]["permissions"]

    capabilities = _kb_capabilities_from_metadata(
        "team-kb", {"owner_id": 10}, current_user,
    )

    assert capabilities == {
        "read": True,
        "operate": False,
        "rename": False,
        "manage_members": False,
        "delete": False,
    }


def test_dept_admin_operate_grant_projects_editor_capabilities():
    current_user = user(1, "dept_admin", access_level="operate")
    current_user["role"]["permissions"] = DEFAULT_ROLES["dept_admin"]["permissions"]

    capabilities = _kb_capabilities_from_metadata(
        "team-kb", {"owner_id": 10}, current_user,
    )

    assert capabilities["read"] is True
    assert capabilities["operate"] is True
    assert capabilities["rename"] is True
    assert capabilities["manage_members"] is True
    assert capabilities["delete"] is False
