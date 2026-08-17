import pytest
from fastapi import HTTPException

from raganything import dependencies


@pytest.fixture(autouse=True)
def global_kb_permissions(monkeypatch):
    async def fake_load_kb_meta():
        return {"teacher-kb": {"owner_id": 7, "owner_username": "teacher"}}

    async def fake_has_permission(user_id, permission):
        return permission in {"kb:read", "kb:write", "kb:manage", "kb:delete"}

    monkeypatch.setattr("raganything.services.kb_service.load_kb_meta", fake_load_kb_meta)
    monkeypatch.setattr(dependencies, "_auth_has_permission", fake_has_permission)


@pytest.mark.asyncio
@pytest.mark.parametrize("role_name", ["super_admin", "dept_admin", "teacher", "assistant", "student"])
async def test_all_roles_with_read_permission_can_access_another_users_kb(role_name):
    actor = {"id": 9, "role": {"name": role_name}}
    assert await dependencies.verify_kb_access("teacher-kb", actor) == "teacher-kb"


@pytest.mark.asyncio
async def test_kb_operation_is_global_permission_not_owner_or_grant():
    actor = {"id": 9, "role": {"name": "assistant"}}
    assert await dependencies.verify_kb_operate_access("teacher-kb", actor) == "teacher-kb"


@pytest.mark.asyncio
async def test_unknown_kb_returns_not_found():
    with pytest.raises(HTTPException) as exc:
        await dependencies.verify_kb_access("missing", {"id": 9})
    assert exc.value.status_code == 404
