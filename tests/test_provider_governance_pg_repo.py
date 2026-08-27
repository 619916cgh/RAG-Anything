"""Repository protocol tests that do not require a PostgreSQL server.

The optional migration-runner integration test exercises the same SQL against
a disposable database when ``MIGRATION_TEST_DATABASE_URL`` is configured.
These tests keep the admission/fencing contract observable on ordinary local
development machines without falling back to process-local enforcement.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import datetime, timedelta, timezone

import pytest

from raganything.services import provider_governance_repo as pg_repo
from raganything.services.provider_governance import PostgresLeaseRepository


class _Transaction(AbstractAsyncContextManager):
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Connection:
    def __init__(self, *, fetchvals=(), fetchrows=(), execute_results=()):
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.fetchvals = list(fetchvals)
        self.fetchrows = list(fetchrows)
        self.execute_results = list(execute_results)

    def transaction(self):
        return _Transaction()

    async def execute(self, query, *args):
        self.executed.append((query, args))
        if self.execute_results:
            return self.execute_results.pop(0)
        return "SELECT 1" if "pg_advisory_xact_lock" in query else "UPDATE 1"

    async def fetchval(self, query, *args):
        self.executed.append((query, args))
        assert self.fetchvals, f"Unexpected fetchval: {query}"
        return self.fetchvals.pop(0)

    async def fetchrow(self, query, *args):
        self.executed.append((query, args))
        assert self.fetchrows, f"Unexpected fetchrow: {query}"
        return self.fetchrows.pop(0)


class _Acquire(AbstractAsyncContextManager):
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Pool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return _Acquire(self.connection)


def _queries(connection: _Connection, fragment: str):
    return [entry for entry in connection.executed if fragment in entry[0]]


@pytest.mark.asyncio
async def test_acquire_uses_fingerprint_advisory_lock_and_owner_fence(monkeypatch):
    expiry = datetime.now(timezone.utc) + timedelta(seconds=30)
    connection = _Connection(fetchvals=[0, expiry])
    monkeypatch.setattr(pg_repo, "get_pg_pool", lambda: _Pool(connection))

    lease = await pg_repo.ProviderGovernanceRepository().acquire(
        "profile-a", "owner-fence-a", "request-hash-a", 0, 2, 30
    )

    assert lease is not None
    assert lease.owner_fence == "owner-fence-a"
    assert _queries(connection, "pg_advisory_xact_lock")[0][1] == ("provider:profile-a",)
    insert = _queries(connection, "INSERT INTO provider_call_leases")[0]
    assert insert[1][1:5] == ("profile-a", "owner-fence-a", "request-hash-a", 0)
    assert _queries(connection, "ttl_expired")


@pytest.mark.asyncio
async def test_waiter_captures_limit_and_claim_preserves_owner_fence(monkeypatch):
    now = datetime.now(timezone.utc)
    connection = _Connection(
        fetchvals=[0, 0, "waiter-a", now + timedelta(seconds=30)],
        fetchrows=[
            {"enqueue_seq": 7},
            {"profile_fingerprint": "profile-a"},
            {
                "profile_fingerprint": "profile-a",
                "owner_fence": "owner-fence-a",
                "request_hash": "request-hash-a",
                "priority": 0,
                "concurrency_limit": 3,
                "deadline_at": now + timedelta(seconds=20),
            },
        ],
    )
    monkeypatch.setattr(pg_repo, "get_pg_pool", lambda: _Pool(connection))
    repository = pg_repo.ProviderGovernanceRepository()

    waiter = await repository.enqueue(
        "profile-a", "request-hash-a", 0, now + timedelta(seconds=20), 100,
        owner_fence="owner-fence-a", concurrency_limit=3,
    )
    assert waiter is not None
    assert waiter.concurrency_limit == 3
    lease = await repository.claim_waiter("waiter-a", ttl_seconds=30)

    assert lease is not None
    assert lease.owner_fence == "owner-fence-a"
    waiter_insert = _queries(connection, "INSERT INTO provider_waiters")[0]
    assert waiter_insert[1][2:6] == ("owner-fence-a", "request-hash-a", 0, 3)
    lease_insert = _queries(connection, "INSERT INTO provider_call_leases")[0]
    assert lease_insert[1][2] == "owner-fence-a"


@pytest.mark.asyncio
async def test_claim_uses_queued_limit_not_a_claiming_instance_default(monkeypatch):
    now = datetime.now(timezone.utc)
    connection = _Connection(
        fetchvals=[3],
        fetchrows=[
            {"profile_fingerprint": "profile-a"},
            {
                "profile_fingerprint": "profile-a",
                "owner_fence": "owner-fence-a",
                "request_hash": "request-hash-a",
                "priority": 0,
                "concurrency_limit": 3,
                "deadline_at": now + timedelta(seconds=20),
            },
        ],
    )
    monkeypatch.setattr(pg_repo, "get_pg_pool", lambda: _Pool(connection))

    lease = await pg_repo.ProviderGovernanceRepository().claim_waiter(
        "waiter-a", ttl_seconds=30
    )

    assert lease is None
    assert not _queries(connection, "INSERT INTO provider_call_leases")


@pytest.mark.asyncio
async def test_owner_checked_heartbeat_release_and_waiter_cancel(monkeypatch):
    connection = _Connection(execute_results=["UPDATE 0", "UPDATE 1", "UPDATE 1"])
    monkeypatch.setattr(pg_repo, "get_pg_pool", lambda: _Pool(connection))
    repository = pg_repo.ProviderGovernanceRepository()

    assert not await repository.heartbeat("lease-a", "wrong-owner", 30)
    assert await repository.release("lease-a", "owner-fence-a", "cancelled")
    assert await repository.cancel_waiter("waiter-a")

    heartbeat = _queries(connection, "SET heartbeat_at")[0]
    assert heartbeat[1][:2] == ("lease-a", "wrong-owner")
    release = _queries(connection, "SET state='released'")[0]
    assert release[1][:2] == ("lease-a", "owner-fence-a")
    cancel = _queries(connection, "SET state='cancelled'")[0]
    assert "state='waiting'" in cancel[0]


@pytest.mark.asyncio
async def test_invalid_priority_or_limit_never_opens_a_database_connection(monkeypatch):
    def fail_pool():
        raise AssertionError("invalid admission must not access PostgreSQL")

    monkeypatch.setattr(pg_repo, "get_pg_pool", fail_pool)
    repository = pg_repo.ProviderGovernanceRepository()
    deadline = datetime.now(timezone.utc) + timedelta(seconds=1)

    assert await repository.acquire("profile-a", "owner", "request", 1, 1) is None
    assert await repository.enqueue("profile-a", "request", 20, deadline, 10, concurrency_limit=0) is None
    assert await repository.claim_waiter("waiter-a", ttl_seconds=0) is None


@pytest.mark.asyncio
async def test_expired_half_open_probe_is_reclaimed_by_one_new_owner(monkeypatch):
    now = datetime.now(timezone.utc)
    connection = _Connection(
        fetchrows=[
            {
                "state": "half_open",
                "cooldown_until": now - timedelta(seconds=20),
                "probe_expires_at": now - timedelta(seconds=1),
            }
        ],
        execute_results=["SELECT 1", "UPDATE 1"],
    )
    monkeypatch.setattr(pg_repo, "get_pg_pool", lambda: _Pool(connection))

    assert await pg_repo.PostgreSQLCircuitRepository().allow("profile-a", 30, "fresh-probe")
    recovery = _queries(connection, "state='half_open' AND probe_expires_at <= NOW()")
    assert len(recovery) == 1
    assert recovery[0][1][1] == "fresh-probe"


@pytest.mark.asyncio
async def test_stale_half_open_probe_cannot_close_or_reopen_new_probe(monkeypatch):
    stale_success = _Connection(execute_results=["UPDATE 0"])
    monkeypatch.setattr(pg_repo, "get_pg_pool", lambda: _Pool(stale_success))
    assert not await pg_repo.PostgreSQLCircuitRepository().success("profile-a", "stale-probe")
    success_update = _queries(stale_success, "WHERE provider_circuit_state.state <> 'half_open'")[0]
    assert success_update[1] == ("profile-a", "stale-probe")

    stale_failure = _Connection(fetchrows=[{"state": "half_open", "failure_count": 1, "probe_owner": "fresh-probe"}])
    monkeypatch.setattr(pg_repo, "get_pg_pool", lambda: _Pool(stale_failure))
    assert not await pg_repo.PostgreSQLCircuitRepository().failure("profile-a", 2, 30, "stale-probe")
    assert not _queries(stale_failure, "INSERT INTO provider_circuit_state")


class _AdapterRepository:
    def __init__(self):
        self.enqueued: dict[str, object] | None = None
        self.claimed: tuple[str, int] | None = None
        self.released: tuple[str, str, str] | None = None

    async def acquire(self, *args):
        return None

    async def enqueue(self, *args, **kwargs):
        self.enqueued = {"args": args, "kwargs": kwargs}
        return type("Waiter", (), {"id": "waiter-a"})()

    async def claim_waiter(self, waiter_id, *, ttl_seconds):
        self.claimed = (waiter_id, ttl_seconds)
        return pg_repo.ProviderLease(
            "lease-a", "profile-a", "owner-fence-a", "request-hash-a", 0,
            datetime.now(timezone.utc) + timedelta(seconds=30),
        )

    async def cancel_waiter(self, waiter_id):
        return True

    async def heartbeat(self, lease_id, owner, ttl_seconds):
        return owner == "owner-fence-a"

    async def release(self, lease_id, owner, reason):
        self.released = (lease_id, owner, reason)
        return owner == "owner-fence-a"


@pytest.mark.asyncio
async def test_adapters_do_not_depend_on_local_waiter_limit_state():
    backing = _AdapterRepository()
    enqueuer = PostgresLeaseRepository(backing)
    claimant = PostgresLeaseRepository(backing)
    enqueuer.set_limit("profile-a", 3)

    waiter = await enqueuer.enqueue("profile-a", "owner-a", 0, 10_000_000.0, 100)
    lease = await claimant.claim(waiter, 30)

    assert backing.enqueued is not None
    assert backing.enqueued["kwargs"]["concurrency_limit"] == 3
    assert backing.claimed == ("waiter-a", 30)
    assert lease is not None
    assert lease.owner == "owner-fence-a"
    assert await claimant.release(lease.lease_id, lease.owner)
    assert backing.released == ("lease-a", "owner-fence-a", "success")
