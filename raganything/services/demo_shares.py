"""PostgreSQL-backed public demo capability links.

Raw link secrets deliberately exist only while a super administrator creates a
share or while a visitor submits one.  They are never returned from lookup
methods, logs, or persisted rows.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any


DEFAULT_RATE_PER_MINUTE = 10
DEFAULT_MAX_CONCURRENT = 2


@dataclass(frozen=True)
class DemoShare:
    share_id: str
    agent_id: str
    kb_name: str
    created_by: int
    created_at: datetime | None
    revoked_at: datetime | None
    max_requests_per_minute: int
    max_concurrent_queries: int


def _pool():
    from raganything.services.pg_state_repo import get_pg_pool
    return get_pg_pool()


def hash_demo_token(token: str) -> str:
    """Hash an opaque token without retaining or logging its plaintext."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_demo_token() -> str:
    return secrets.token_urlsafe(32)


def _row_to_share(row: Any) -> DemoShare:
    return DemoShare(
        share_id=str(row["share_id"]),
        agent_id=str(row["agent_id"]),
        kb_name=str(row["kb_name"]),
        created_by=int(row["created_by"]),
        created_at=row.get("created_at") if hasattr(row, "get") else row["created_at"],
        revoked_at=row.get("revoked_at") if hasattr(row, "get") else row["revoked_at"],
        max_requests_per_minute=int(row["max_requests_per_minute"]),
        max_concurrent_queries=int(row["max_concurrent_queries"]),
    )


def public_share_payload(share: DemoShare) -> dict[str, object]:
    return {
        "share_id": share.share_id,
        "agent_id": share.agent_id,
        "kb_name": share.kb_name,
        "created_by": share.created_by,
        "created_at": share.created_at.isoformat() if share.created_at else None,
        "revoked_at": share.revoked_at.isoformat() if share.revoked_at else None,
        "max_requests_per_minute": share.max_requests_per_minute,
        "max_concurrent_queries": share.max_concurrent_queries,
    }


async def create_demo_share(agent_id: str, kb_name: str, created_by: int) -> tuple[DemoShare, str]:
    token = new_demo_token()
    share_id = uuid.uuid4()
    row = await _pool().fetchrow(
        """
        INSERT INTO demo_shares (share_id, token_hash, agent_id, kb_name, created_by)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING *
        """,
        share_id, hash_demo_token(token), agent_id, kb_name, created_by,
    )
    return _row_to_share(row), token


async def list_demo_shares() -> list[DemoShare]:
    rows = await _pool().fetch("SELECT * FROM demo_shares ORDER BY created_at DESC")
    return [_row_to_share(row) for row in rows]


async def revoke_demo_share(share_id: str) -> bool:
    try:
        parsed_id = uuid.UUID(share_id)
    except (ValueError, TypeError, AttributeError):
        return False
    result = await _pool().execute(
        "UPDATE demo_shares SET revoked_at = COALESCE(revoked_at, NOW()) WHERE share_id = $1",
        parsed_id,
    )
    return result.endswith("1")


async def authenticate_demo_share(share_id: str, token: str) -> DemoShare | None:
    """Authenticate a share without disclosing whether its ID or secret failed."""
    try:
        parsed_id = uuid.UUID(share_id)
    except (ValueError, TypeError, AttributeError):
        return None
    if not isinstance(token, str) or not 32 <= len(token) <= 256:
        return None
    token_hash = hash_demo_token(token)
    row = await _pool().fetchrow(
        "SELECT * FROM demo_shares WHERE share_id = $1 AND revoked_at IS NULL",
        parsed_id,
    )
    if row is None or not hmac.compare_digest(str(row["token_hash"]), token_hash):
        return None
    return _row_to_share(row)


async def get_active_demo_share(share_id: str) -> DemoShare | None:
    try:
        parsed_id = uuid.UUID(share_id)
    except (ValueError, TypeError, AttributeError):
        return None
    row = await _pool().fetchrow(
        "SELECT * FROM demo_shares WHERE share_id = $1 AND revoked_at IS NULL",
        parsed_id,
    )
    return _row_to_share(row) if row else None


async def acquire_demo_query(share: DemoShare) -> bool:
    """Atomically count a request and reserve one share-scoped query slot."""
    row = await _pool().fetchrow(
        """
        UPDATE demo_shares
        SET rate_window_started_at = CASE
                WHEN NOW() - rate_window_started_at >= INTERVAL '60 seconds' THEN NOW()
                ELSE rate_window_started_at
            END,
            rate_request_count = CASE
                WHEN NOW() - rate_window_started_at >= INTERVAL '60 seconds' THEN 1
                ELSE rate_request_count + 1
            END,
            active_queries = active_queries + 1
        WHERE share_id = $1
          AND revoked_at IS NULL
          AND active_queries < max_concurrent_queries
          AND (NOW() - rate_window_started_at >= INTERVAL '60 seconds'
               OR rate_request_count < max_requests_per_minute)
        RETURNING share_id
        """,
        uuid.UUID(share.share_id),
    )
    return row is not None


async def release_demo_query(share_id: str) -> None:
    try:
        parsed_id = uuid.UUID(share_id)
    except (ValueError, TypeError, AttributeError):
        return
    await _pool().execute(
        "UPDATE demo_shares SET active_queries = GREATEST(active_queries - 1, 0) WHERE share_id = $1",
        parsed_id,
    )
