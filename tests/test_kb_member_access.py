import pytest

from raganything.permissions import DEFAULT_ROLES
from raganything.routers.knowledge import _kb_capabilities_from_metadata


@pytest.mark.parametrize("role_name", ["super_admin", "dept_admin", "teacher", "assistant", "student"])
def test_kb_capabilities_are_role_based_not_owner_or_grant(role_name):
    user = {
        "id": 1,
        "is_admin": role_name == "super_admin",
        "role": {"name": role_name, "permissions": DEFAULT_ROLES[role_name]["permissions"]},
    }
    capabilities = _kb_capabilities_from_metadata(
        "team-kb", {"owner_id": 99, "owner_username": "other"}, user
    )

    assert capabilities["read"] is True
    assert capabilities["operate"] == ("kb:write" in DEFAULT_ROLES[role_name]["permissions"] or role_name == "super_admin")
    assert capabilities["rename"] == ("kb:manage" in DEFAULT_ROLES[role_name]["permissions"] or role_name == "super_admin")
    assert capabilities["delete"] == ("kb:delete" in DEFAULT_ROLES[role_name]["permissions"] or role_name == "super_admin")
    assert "manage_members" not in capabilities
