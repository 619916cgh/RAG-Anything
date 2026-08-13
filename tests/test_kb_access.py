import pytest
from fastapi import HTTPException

from raganything.dependencies import verify_kb_access, verify_kb_operate_access


@pytest.mark.asyncio
async def test_verify_kb_access_allows_owner_without_allowed_kbs(monkeypatch):
    async def fake_load_kb_meta():
        return {
            "owner-kb": {
                "owner_id": 7,
                "owner_username": "alice",
            }
        }

    monkeypatch.setattr(
        "raganything.services.kb_service.load_kb_meta",
        fake_load_kb_meta,
    )

    current_user = {
        "id": 7,
        "username": "alice",
        "is_admin": False,
        "allowed_kbs": [],
    }

    result = await verify_kb_access(kb="owner-kb", current_user=current_user)

    assert result == "owner-kb"


@pytest.mark.asyncio
async def test_verify_kb_access_rejects_non_owner_without_allowed_kbs(monkeypatch):
    async def fake_load_kb_meta():
        return {
            "owner-kb": {
                "owner_id": 7,
                "owner_username": "alice",
            }
        }

    monkeypatch.setattr(
        "raganything.services.kb_service.load_kb_meta",
        fake_load_kb_meta,
    )

    current_user = {
        "id": 9,
        "username": "bob",
        "is_admin": False,
        "allowed_kbs": [],
    }

    with pytest.raises(HTTPException) as exc:
        await verify_kb_access(kb="owner-kb", current_user=current_user)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("role_name, expected_status", [
    ("super_admin", 200),
    ("dept_admin", 200),
    ("teacher", 200),
    ("assistant", 403),
    ("student", 403),
])
async def test_role_derived_read_visibility_is_limited_to_three_roles(monkeypatch, role_name, expected_status):
    async def fake_load_kb_meta():
        return {"owner-kb": {"owner_id": 7, "owner_username": "alice"}}

    monkeypatch.setattr("raganything.services.kb_service.load_kb_meta", fake_load_kb_meta)
    actor = {
        "id": 9,
        "username": "bob",
        "is_admin": False,
        "role": {"name": role_name},
        "allowed_kbs": [],
        "kb_access_levels": {},
    }

    if expected_status == 200:
        assert await verify_kb_access(kb="owner-kb", current_user=actor) == "owner-kb"
        assert actor["allowed_kbs"] == []
        assert actor["kb_access_levels"] == {}
    else:
        with pytest.raises(HTTPException) as exc:
            await verify_kb_access(kb="owner-kb", current_user=actor)
        assert exc.value.status_code == expected_status


@pytest.mark.asyncio
@pytest.mark.parametrize("role_name", ["dept_admin", "teacher"])
async def test_role_derived_read_visibility_never_allows_operations(monkeypatch, role_name):
    async def fake_load_kb_meta():
        return {"owner-kb": {"owner_id": 7, "owner_username": "alice"}}

    monkeypatch.setattr("raganything.services.kb_service.load_kb_meta", fake_load_kb_meta)
    with pytest.raises(HTTPException) as exc:
        await verify_kb_operate_access(
            kb="owner-kb",
            current_user={"id": 9, "role": {"name": role_name}, "allowed_kbs": [], "kb_access_levels": {}},
        )
    assert exc.value.status_code == 403
