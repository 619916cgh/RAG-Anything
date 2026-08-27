import asyncio
from email.utils import format_datetime
from datetime import datetime, timedelta, timezone

import pytest

from raganything.services.provider_governance import (
    InMemoryCircuitRepository,
    InMemoryLeaseRepository,
    ProviderBusyError,
    ProviderGovernor,
    ProviderPolicy,
    ProviderPriority,
    parse_retry_after,
)


class _RecordedMetrics:
    def __init__(self):
        self.events = []

    def observe(self, name, value, labels):
        self.events.append((name, value, dict(labels)))


def test_policy_defaults_are_private_and_fingerprinted():
    policy = ProviderPolicy()
    assert policy.concurrency_limit == 40
    assert policy.queue_timeout_seconds == 10
    assert policy.requests_per_minute is None
    assert "concurrency_limit" not in policy.public_dict()
    assert len(policy.fingerprint) == 64
    assert policy.fingerprint != ProviderPolicy(model="qwen-plus").fingerprint


def test_invalid_policy_rejected():
    with pytest.raises(ValueError):
        ProviderPolicy(concurrency_limit=0)
    with pytest.raises(ValueError):
        ProviderPolicy(queue_timeout_seconds=61)
    with pytest.raises(ValueError):
        ProviderPolicy(retry_base_seconds=2, retry_max_seconds=1)


def test_retry_after_is_bounded_and_safe():
    assert parse_retry_after("2", maximum=3) == 2
    assert parse_retry_after("-1", maximum=3) is None
    assert parse_retry_after("999", maximum=3) is None
    assert parse_retry_after("garbage", maximum=3) is None
    future = datetime.now(timezone.utc) + timedelta(seconds=2)
    parsed = parse_retry_after(format_datetime(future, usegmt=True), maximum=3)
    assert parsed is not None and 0 <= parsed <= 3


@pytest.mark.asyncio
async def test_priority_fifo_and_release():
    repo = InMemoryLeaseRepository()
    policy = ProviderPolicy(concurrency_limit=1, queue_timeout_seconds=1)
    governor = ProviderGovernor(repo)
    first = await governor.acquire(policy)
    low = asyncio.create_task(governor.acquire(policy, priority=ProviderPriority.BACKGROUND))
    high = asyncio.create_task(governor.acquire(policy, priority=ProviderPriority.QUERY))
    await asyncio.sleep(0.01)
    await governor.release(policy, first)
    selected = await asyncio.wait_for(high, 1)
    assert not low.done()
    await governor.release(policy, selected)
    await asyncio.wait_for(low, 1)


@pytest.mark.asyncio
async def test_queued_admission_updates_active_lease_metric():
    repo = InMemoryLeaseRepository()
    metrics = _RecordedMetrics()
    policy = ProviderPolicy(concurrency_limit=1, queue_timeout_seconds=1)
    governor = ProviderGovernor(repo, metrics=metrics)
    first = await governor.acquire(policy)
    waiting = asyncio.create_task(governor.acquire(policy))
    await asyncio.sleep(0.01)
    await governor.release(policy, first)
    second = await asyncio.wait_for(waiting, 1)
    await governor.release(policy, second)

    active_deltas = [value for name, value, _ in metrics.events if name == "provider_active_calls"]
    assert active_deltas == [1, -1, 1, -1]


@pytest.mark.asyncio
async def test_queue_cancellation_removes_waiter():
    repo = InMemoryLeaseRepository()
    policy = ProviderPolicy(concurrency_limit=1, queue_timeout_seconds=1)
    governor = ProviderGovernor(repo)
    lease = await governor.acquire(policy)
    pending = asyncio.create_task(governor.acquire(policy))
    await asyncio.sleep(0.01)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert not repo._waiters
    await governor.release(policy, lease)


@pytest.mark.asyncio
async def test_waiter_cancel_database_failure_does_not_mask_cancellation():
    class CancelFails(InMemoryLeaseRepository):
        async def cancel(self, waiter_id):
            raise RuntimeError("database unavailable")

    repo = CancelFails()
    policy = ProviderPolicy(concurrency_limit=1, queue_timeout_seconds=1)
    governor = ProviderGovernor(repo)
    lease = await governor.acquire(policy)
    pending = asyncio.create_task(governor.acquire(policy))
    await asyncio.sleep(0.01)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    await governor.release(policy, lease)


@pytest.mark.asyncio
async def test_retry_releases_before_backoff_and_circuit_opens():
    repo, circuit = InMemoryLeaseRepository(), InMemoryCircuitRepository()
    policy = ProviderPolicy(concurrency_limit=1, max_attempts=2, retry_base_seconds=.001,
                            retry_max_seconds=.01, circuit_failure_threshold=1)
    governor = ProviderGovernor(repo, circuit=circuit, sleep=lambda _: asyncio.sleep(0))
    class TooMany(Exception):
        status_code = 429
        headers = {"Retry-After": "0"}
    calls = 0
    async def fail():
        nonlocal calls
        calls += 1
        raise TooMany()
    with pytest.raises(TooMany):
        await governor.governed_call(policy, fail)
    assert calls == 2
    with pytest.raises(Exception) as caught:
        await governor.acquire(policy)
    assert getattr(caught.value, "code", None) == "provider_unavailable"


@pytest.mark.asyncio
async def test_cancellation_during_retry_backoff_leaves_no_lease():
    repo = InMemoryLeaseRepository()
    policy = ProviderPolicy(concurrency_limit=1, max_attempts=2, retry_base_seconds=.1)
    backoff_started = asyncio.Event()
    release_backoff = asyncio.Event()

    async def controlled_sleep(_delay):
        backoff_started.set()
        await release_backoff.wait()

    governor = ProviderGovernor(repo, sleep=controlled_sleep)

    class TooMany(Exception):
        status_code = 429
        headers = {"Retry-After": "1"}

    calls = 0

    async def fail():
        nonlocal calls
        calls += 1
        raise TooMany()

    task = asyncio.create_task(governor.governed_call(policy, fail))
    await asyncio.wait_for(backoff_started.wait(), 1)
    assert not repo._leases
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls == 1
    assert not repo._leases


@pytest.mark.asyncio
async def test_stream_does_not_retry_after_first_token():
    repo = InMemoryLeaseRepository()
    policy = ProviderPolicy(concurrency_limit=1, max_attempts=2, retry_base_seconds=.001)
    governor = ProviderGovernor(repo, sleep=lambda _: asyncio.sleep(0))

    async def provider_stream():
        yield "first"
        error = TimeoutError("late timeout")
        raise error

    calls = 0

    async def call():
        nonlocal calls
        calls += 1
        return provider_stream()

    tokens = []
    with pytest.raises(TimeoutError):
        async for token in governor.governed_stream(policy, call):
            tokens.append(token)
    assert tokens == ["first"]
    assert calls == 1
    assert not repo._leases


@pytest.mark.asyncio
async def test_scalar_stream_success_closes_a_half_open_circuit():
    repo, circuit = InMemoryLeaseRepository(), InMemoryCircuitRepository()
    policy = ProviderPolicy(
        concurrency_limit=1,
        circuit_failure_threshold=1,
        circuit_cooldown_seconds=.05,
    )
    governor = ProviderGovernor(repo, circuit=circuit)
    await circuit.failure(policy.fingerprint, 1, policy.circuit_cooldown_seconds)
    await asyncio.sleep(.1)

    async def scalar():
        return "first and only"

    assert [item async for item in governor.governed_stream(policy, scalar)] == ["first and only"]
    assert await circuit.allow(policy.fingerprint, policy.circuit_cooldown_seconds)


@pytest.mark.asyncio
async def test_circuit_metrics_expose_only_fixed_state_labels():
    repo, circuit = InMemoryLeaseRepository(), InMemoryCircuitRepository()
    metrics = _RecordedMetrics()
    policy = ProviderPolicy(concurrency_limit=1, circuit_failure_threshold=1)
    governor = ProviderGovernor(repo, circuit=circuit, metrics=metrics)

    class Overloaded(Exception):
        status_code = 429

    async def fail():
        raise Overloaded()

    with pytest.raises(Overloaded):
        await governor.governed_call(policy, fail)

    states = [labels["state"] for name, _value, labels in metrics.events if name == "provider_circuit_state"]
    assert states[-1] == "open"
    assert set(states) <= {"closed", "open", "half_open"}


@pytest.mark.asyncio
async def test_heartbeat_and_owner_fence_are_enforced():
    repo = InMemoryLeaseRepository()
    policy = ProviderPolicy(concurrency_limit=1, lease_ttl_seconds=.05, heartbeat_interval_seconds=.01)
    governor = ProviderGovernor(repo, sleep=lambda seconds: asyncio.sleep(seconds))
    lease = await governor.acquire(policy, owner="owner-a")
    assert await repo.heartbeat(lease.lease_id, "wrong-owner", .05) is False
    assert await repo.heartbeat(lease.lease_id, lease.owner, .05) is True
    assert await repo.release(lease.lease_id, "wrong-owner") is False
    await governor.release(policy, lease)
    assert not repo._leases


@pytest.mark.asyncio
async def test_release_database_failure_does_not_mask_provider_error():
    class ReleaseFails(InMemoryLeaseRepository):
        async def release(self, lease_id, owner, reason="success"):
            raise RuntimeError("database unavailable")

    repo = ReleaseFails()
    policy = ProviderPolicy(concurrency_limit=1, max_attempts=1)
    governor = ProviderGovernor(repo)

    class UpstreamFailure(Exception):
        status_code = 400

    async def fail():
        raise UpstreamFailure("invalid request")

    with pytest.raises(UpstreamFailure):
        await governor.governed_call(policy, fail)


@pytest.mark.asyncio
async def test_release_hang_is_bounded_and_does_not_mask_provider_error():
    class ReleaseHangs(InMemoryLeaseRepository):
        async def release(self, lease_id, owner, reason="success"):
            await asyncio.Event().wait()

    repo = ReleaseHangs()
    policy = ProviderPolicy(
        concurrency_limit=1,
        lease_ttl_seconds=0.2,
        heartbeat_interval_seconds=0.05,
        max_attempts=1,
    )
    governor = ProviderGovernor(repo)

    class UpstreamFailure(Exception):
        status_code = 400

    async def fail():
        raise UpstreamFailure("invalid request")

    with pytest.raises(UpstreamFailure):
        await asyncio.wait_for(governor.governed_call(policy, fail), 1)


@pytest.mark.asyncio
async def test_release_database_failure_does_not_mask_stream_cancellation():
    class ReleaseFails(InMemoryLeaseRepository):
        async def release(self, lease_id, owner, reason="success"):
            raise RuntimeError("database unavailable")

    repo = ReleaseFails()
    policy = ProviderPolicy(concurrency_limit=1, max_attempts=1)
    governor = ProviderGovernor(repo)
    started = asyncio.Event()

    async def provider_stream():
        started.set()
        await asyncio.Event().wait()
        yield "never"

    async def call():
        return provider_stream()

    task = asyncio.create_task(governor.governed_stream(policy, call).__anext__())
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
