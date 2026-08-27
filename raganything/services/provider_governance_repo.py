"""PostgreSQL coordination primitives for provider-governed model calls.

The repository deliberately stores only opaque request hashes, profile
fingerprints and bounded state/reason codes.  Admission is serialized with a
fingerprint-scoped advisory lock so empty-set races cannot exceed a provider
limit across app workers or instances.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from raganything.services.pg_state_repo import get_pg_pool


@dataclass(frozen=True)
class ProviderLease:
    id: str
    profile_fingerprint: str
    owner_fence: str
    request_hash: str
    priority: int
    expires_at: datetime | None = None


@dataclass(frozen=True)
class ProviderWaiter:
    id: str
    profile_fingerprint: str
    request_hash: str
    priority: int
    concurrency_limit: int
    enqueue_seq: int
    deadline_at: datetime
    state: str = "waiting"


def _lock_key(fingerprint: str) -> str:
    return f"provider:{fingerprint}"


def _is_supported_priority(priority: int) -> bool:
    return priority in (0, 10, 20)


class ProviderGovernanceRepository:
    async def acquire(
        self, profile_fingerprint: str, owner_fence: str, request_hash: str,
        priority: int, concurrency_limit: int, ttl_seconds: int = 30,
    ) -> ProviderLease | None:
        """Atomically acquire an available provider lease, or return None."""
        if concurrency_limit <= 0 or ttl_seconds <= 0 or not _is_supported_priority(priority):
            return None
        lease_id = str(uuid.uuid4())
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", _lock_key(profile_fingerprint))
                await conn.execute(
                    "UPDATE provider_call_leases SET state='released', released_at=NOW(), release_reason='ttl_expired' "
                    "WHERE profile_fingerprint=$1 AND state='active' AND expires_at <= NOW()",
                    profile_fingerprint,
                )
                active = await conn.fetchval(
                    "SELECT COUNT(*) FROM provider_call_leases WHERE profile_fingerprint=$1 AND state='active' AND expires_at > NOW()",
                    profile_fingerprint,
                )
                if int(active or 0) >= concurrency_limit:
                    return None
                await conn.execute(
                    "INSERT INTO provider_call_leases(id,profile_fingerprint,owner_fence,request_hash,priority,expires_at) "
                    "VALUES($1::uuid,$2,$3,$4,$5,NOW()+$6 * INTERVAL '1 second')",
                    lease_id, profile_fingerprint, owner_fence, request_hash, priority, ttl_seconds,
                )
                expires = await conn.fetchval("SELECT expires_at FROM provider_call_leases WHERE id=$1::uuid", lease_id)
        return ProviderLease(lease_id, profile_fingerprint, owner_fence, request_hash, priority, expires)

    async def enqueue(
        self, profile_fingerprint: str, request_hash: str, priority: int,
        deadline_at: datetime, queue_capacity: int,
        owner_fence: str | None = None,
        concurrency_limit: int = 40,
    ) -> ProviderWaiter | None:
        """Insert a bounded waiter; return None when the queue is full."""
        if (
            queue_capacity <= 0
            or concurrency_limit <= 0
            or not _is_supported_priority(priority)
        ):
            return None
        waiter_id = str(uuid.uuid4())
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", _lock_key(profile_fingerprint))
                await conn.execute(
                    "UPDATE provider_waiters SET state='timed_out', finished_at=NOW(), cancel_reason='deadline' "
                    "WHERE profile_fingerprint=$1 AND state='waiting' AND deadline_at <= NOW()",
                    profile_fingerprint,
                )
                waiting = await conn.fetchval(
                    "SELECT COUNT(*) FROM provider_waiters WHERE profile_fingerprint=$1 AND state='waiting'",
                    profile_fingerprint,
                )
                if int(waiting or 0) >= queue_capacity:
                    return None
                row = await conn.fetchrow(
                    "INSERT INTO provider_waiters(id,profile_fingerprint,owner_fence,request_hash,priority,concurrency_limit,deadline_at) "
                    "VALUES($1::uuid,$2,$3,$4,$5,$6,$7) RETURNING enqueue_seq",
                    waiter_id, profile_fingerprint, owner_fence or request_hash,
                    request_hash, priority, concurrency_limit, deadline_at,
                )
        return ProviderWaiter(
            waiter_id, profile_fingerprint, request_hash, priority,
            concurrency_limit, int(row["enqueue_seq"]), deadline_at,
        )

    async def claim_waiter(
        self, waiter_id: str, ttl_seconds: int = 30,
    ) -> ProviderLease | None:
        """Claim the oldest eligible waiter while fencing concurrent claimers."""
        if ttl_seconds <= 0:
            return None
        lease_id = str(uuid.uuid4())
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                waiter = await conn.fetchrow(
                    "SELECT profile_fingerprint FROM provider_waiters "
                    "WHERE id=$1::uuid AND state='waiting'", waiter_id,
                )
                if waiter is None:
                    return None
                fp = waiter["profile_fingerprint"]
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", _lock_key(fp))
                waiter = await conn.fetchrow(
                    "SELECT profile_fingerprint,owner_fence,request_hash,priority,concurrency_limit,deadline_at FROM provider_waiters "
                    "WHERE id=$1::uuid AND state='waiting' FOR UPDATE", waiter_id,
                )
                if waiter is None:
                    return None
                # Use the immutable policy captured when the caller queued.
                queued_limit = int(waiter["concurrency_limit"])
                await conn.execute(
                    "UPDATE provider_call_leases SET state='released',released_at=NOW(),release_reason='ttl_expired' "
                    "WHERE profile_fingerprint=$1 AND state='active' AND expires_at <= NOW()", fp,
                )
                if waiter["deadline_at"] <= datetime.now(waiter["deadline_at"].tzinfo):
                    await conn.execute("UPDATE provider_waiters SET state='timed_out',finished_at=NOW(),cancel_reason='deadline' WHERE id=$1::uuid", waiter_id)
                    return None
                active = await conn.fetchval("SELECT COUNT(*) FROM provider_call_leases WHERE profile_fingerprint=$1 AND state='active' AND expires_at > NOW()", fp)
                if int(active or 0) >= queued_limit:
                    return None
                # Priority/FIFO gate: an older/higher-priority waiter wins.
                candidate = await conn.fetchval(
                    "SELECT id FROM provider_waiters WHERE profile_fingerprint=$1 AND state='waiting' AND deadline_at > NOW() "
                    "ORDER BY priority ASC, enqueue_seq ASC LIMIT 1", fp)
                if str(candidate) != waiter_id:
                    return None
                await conn.execute(
                    "INSERT INTO provider_call_leases(id,profile_fingerprint,owner_fence,request_hash,priority,expires_at) "
                    "VALUES($1::uuid,$2,$3,$4,$5,NOW()+$6 * INTERVAL '1 second')", lease_id, fp, waiter["owner_fence"], waiter["request_hash"], waiter["priority"], ttl_seconds,
                )
                await conn.execute("UPDATE provider_waiters SET state='claimed',lease_id=$2::uuid,claimed_at=NOW(),finished_at=NOW() WHERE id=$1::uuid", waiter_id, lease_id)
                expires = await conn.fetchval("SELECT expires_at FROM provider_call_leases WHERE id=$1::uuid", lease_id)
        return ProviderLease(lease_id, fp, waiter["owner_fence"], waiter["request_hash"], int(waiter["priority"]), expires)

    async def cancel_waiter(self, waiter_id: str, reason: str = "cancelled") -> bool:
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE provider_waiters SET state='cancelled',cancel_reason=$2,finished_at=NOW() WHERE id=$1::uuid AND state='waiting'",
                waiter_id, reason[:32],
            )
        return result == "UPDATE 1"

    async def heartbeat(self, lease_id: str, owner_fence: str, ttl_seconds: int = 30) -> bool:
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE provider_call_leases SET heartbeat_at=NOW(),expires_at=NOW()+$3 * INTERVAL '1 second' "
                "WHERE id=$1::uuid AND owner_fence=$2 AND state='active' AND expires_at > NOW()",
                lease_id, owner_fence, ttl_seconds,
            )
        return result == "UPDATE 1"

    async def release(self, lease_id: str, owner_fence: str, reason: str = "completed") -> bool:
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE provider_call_leases SET state='released',released_at=NOW(),release_reason=$3 "
                "WHERE id=$1::uuid AND owner_fence=$2 AND state='active'",
                lease_id, owner_fence, reason[:32],
            )
        return result == "UPDATE 1"


provider_governance_repository = ProviderGovernanceRepository()


class PostgreSQLCircuitRepository:
    """Fingerprint-scoped durable circuit state with a single half-open probe."""

    async def allow(self, fingerprint: str, cooldown_seconds: float, probe_owner: str | None = None) -> bool:
        pool = get_pg_pool()
        probe_owner = probe_owner or uuid.uuid4().hex
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", _lock_key(f"circuit:{fingerprint}"))
                row = await conn.fetchrow(
                    "SELECT state,cooldown_until,probe_expires_at FROM provider_circuit_state WHERE profile_fingerprint=$1 FOR UPDATE",
                    fingerprint,
                )
                if row is None or row["state"] == "closed":
                    return True
                if row["state"] == "half_open":
                    # A caller can disappear between obtaining the one probe
                    # and recording success/failure.  Its fencing window is
                    # deliberately finite so that the durable circuit cannot
                    # remain half-open forever after a worker crash.
                    if row["probe_expires_at"] is None or row["probe_expires_at"] > datetime.now(row["probe_expires_at"].tzinfo):
                        return False
                    result = await conn.execute(
                        "UPDATE provider_circuit_state SET probe_owner=$2,probe_expires_at=NOW()+$3 * INTERVAL '1 second',updated_at=NOW() "
                        "WHERE profile_fingerprint=$1 AND state='half_open' AND probe_expires_at <= NOW()",
                        fingerprint, probe_owner, max(1, int(cooldown_seconds)),
                    )
                    return result == "UPDATE 1"
                # An expired open state admits exactly one transactionally-fenced probe.
                if row["cooldown_until"] is not None and row["cooldown_until"] <= datetime.now(row["cooldown_until"].tzinfo):
                    result = await conn.execute(
                        "UPDATE provider_circuit_state SET state='half_open',probe_owner=$2,probe_expires_at=NOW()+$3 * INTERVAL '1 second',updated_at=NOW() "
                        "WHERE profile_fingerprint=$1 AND state='open' AND cooldown_until <= NOW()",
                        fingerprint, probe_owner, max(1, int(cooldown_seconds)),
                    )
                    return result == "UPDATE 1"
                return False

    async def state(self, fingerprint: str) -> str:
        """Read one bounded state label for metrics without payload data."""
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            state = await conn.fetchval(
                "SELECT state FROM provider_circuit_state WHERE profile_fingerprint=$1",
                fingerprint,
            )
        return state if state in {"closed", "open", "half_open"} else "closed"

    async def success(self, fingerprint: str, probe_owner: str | None = None) -> bool:
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "INSERT INTO provider_circuit_state(profile_fingerprint,state,failure_count,updated_at) VALUES($1,'closed',0,NOW()) "
                "ON CONFLICT(profile_fingerprint) DO UPDATE SET state='closed',failure_count=0,opened_at=NULL,cooldown_until=NULL,probe_owner=NULL,probe_expires_at=NULL,updated_at=NOW() "
                "WHERE provider_circuit_state.state <> 'half_open' OR provider_circuit_state.probe_owner=$2",
                fingerprint, probe_owner,
            )
        return result == "INSERT 0 1" or result == "UPDATE 1"

    async def failure(self, fingerprint: str, threshold: int, cooldown_seconds: float,
                      probe_owner: str | None = None) -> bool:
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", _lock_key(f"circuit:{fingerprint}"))
                row = await conn.fetchrow(
                    "SELECT state,failure_count,probe_owner FROM provider_circuit_state WHERE profile_fingerprint=$1 FOR UPDATE",
                    fingerprint,
                )
                if row is not None and row["state"] == "half_open" and row["probe_owner"] != probe_owner:
                    return False
                failures = int(row["failure_count"]) + 1 if row else 1
                should_open = (row is not None and row["state"] == "half_open") or failures >= threshold
                state = "open" if should_open else "closed"
                result = await conn.execute(
                    "INSERT INTO provider_circuit_state(profile_fingerprint,state,failure_count,opened_at,cooldown_until,updated_at) "
                    "VALUES($1,$2,$3,CASE WHEN $2='open' THEN NOW() END,CASE WHEN $2='open' THEN NOW()+$4 * INTERVAL '1 second' END,NOW()) "
                    "ON CONFLICT(profile_fingerprint) DO UPDATE SET state=EXCLUDED.state,failure_count=EXCLUDED.failure_count,opened_at=EXCLUDED.opened_at,cooldown_until=EXCLUDED.cooldown_until,probe_owner=NULL,probe_expires_at=NULL,updated_at=NOW()",
                    fingerprint, state, failures, max(1, int(cooldown_seconds)),
                )
                return result == "INSERT 0 1" or result == "UPDATE 1"
