"""Safe presentation names for knowledge-base identifiers."""

from __future__ import annotations

import re
from typing import Any, Mapping


UNKNOWN_KNOWLEDGE_BASE_NAME = "未命名知识库"
_OPAQUE_KB_NAME_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def is_opaque_knowledge_base_name(value: object) -> bool:
    return isinstance(value, str) and bool(_OPAQUE_KB_NAME_RE.fullmatch(value.strip()))


def get_knowledge_base_display_name(metadata: Mapping[str, Any] | None, internal_name: object) -> str:
    """Return a user-facing KB name without exposing legacy opaque identifiers."""
    name = str(internal_name or "").strip()
    metadata = metadata if isinstance(metadata, Mapping) else {}
    display_name = next(
        (
            str(metadata.get(key) or "").strip()
            for key in ("display_name", "label", "name")
            if str(metadata.get(key) or "").strip()
        ),
        "",
    )
    if not display_name or (display_name == name and is_opaque_knowledge_base_name(name)):
        return UNKNOWN_KNOWLEDGE_BASE_NAME
    return display_name
