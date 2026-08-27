"""Provider-scoped concurrency, retry and circuit governance.

The service deliberately depends on a small repository protocol.  Production
implementations are backed by PostgreSQL (migration 036); tests and callers
may provide another durable implementation.  No process-local semaphore is
used for admission.
"""
from __future__ import annotations

import asyncio
import hashlib
import random
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from enum import IntEnum
from typing import Any, Protocol, TypeVar


class ProviderPriority(IntEnum):
    QUERY = 0
    UPLOAD = 10
    BACKGROUND = 20


class ProviderBusyError(RuntimeError):
    code = "provider_busy"

    def __init__(self, message: str = "provider is busy") -> None:
        super().__init__(message)


class ProviderUnavailableError(RuntimeError):
    code = "provider_unavailable"


@dataclass(frozen=True, slots=True)
class ProviderPolicy:
    provider: str = "qwen"
    model: str = "qwen"
    capability: str = "chat"
    policy_version: str = "1"
    concurrency_limit: int = 40
    requests_per_minute: int | None = None
    tokens_per_minute: int | None = None
    quota_verified: bool = False
    queue_timeout_seconds: float = 10.0
    queue_capacity: int = 100
    lease_ttl_seconds: float = 90.0
    heartbeat_interval_seconds: float = 20.0
    # One retry is the approved bounded policy.  More attempts make the
    # admission queue amplify an upstream outage rather than recover from it.
    max_attempts: int = 2
    retry_base_seconds: float = 0.5
    retry_max_seconds: float = 8.0
    circuit_failure_threshold: int = 5
    circuit_cooldown_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.concurrency_limit <= 0:
            raise ValueError("concurrency_limit must be positive")
        if not 0 < self.queue_timeout_seconds <= 60:
            raise ValueError("queue_timeout_seconds must be in (0, 60]")
        if self.queue_capacity <= 0:
            raise ValueError("queue_capacity must be positive")
        if self.lease_ttl_seconds <= self.heartbeat_interval_seconds:
            raise ValueError("lease TTL must exceed heartbeat interval")
        if not 1 <= self.max_attempts <= 5:
            raise ValueError("max_attempts must be between 1 and 5")
        if not 0 < self.retry_base_seconds <= self.retry_max_seconds <= 60:
            raise ValueError("retry bounds are invalid")
        if self.requests_per_minute is not None and self.requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be positive")
        if self.tokens_per_minute is not None and self.tokens_per_minute <= 0:
            raise ValueError("tokens_per_minute must be positive")

    @property
    def fingerprint(self) -> str:
        value = "|".join((self.provider, self.model, self.capability, self.policy_version))
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @property
    def fingerprint_hash(self) -> str:
        return self.fingerprint[:16]

    def public_dict(self) -> dict[str, str]:
        """Return only catalog identity; governance fields stay server-private."""
        return {"provider": self.provider, "model": self.model, "capability": self.capability}

    def effective_fanout(self, requested: int | None) -> int:
        return min(self.concurrency_limit, max(1, requested or self.concurrency_limit))


@dataclass(frozen=True, slots=True)
class ProviderLease:
    lease_id: str
    fingerprint: str
    owner: str
    expires_at: datetime | None = None


class LeaseRepository(Protocol):
    async def acquire_now(self, fingerprint: str, owner: str, priority: int, ttl_seconds: float) -> ProviderLease | None: ...
    async def enqueue(self, fingerprint: str, owner: str, priority: int, deadline: float, capacity: int) -> str | None: ...
    async def claim(self, waiter_id: str, ttl_seconds: float) -> ProviderLease | None: ...
    async def cancel(self, waiter_id: str) -> None: ...
    async def heartbeat(self, lease_id: str, owner: str, ttl_seconds: float) -> bool: ...
    async def release(self, lease_id: str, owner: str, reason: str = "success") -> bool: ...


class CircuitRepository(Protocol):
    async def allow(self, fingerprint: str, cooldown_seconds: float, probe_owner: str | None = None) -> bool: ...
    async def success(self, fingerprint: str, probe_owner: str | None = None) -> None: ...
    async def failure(self, fingerprint: str, threshold: int, cooldown_seconds: float,
                      probe_owner: str | None = None) -> None: ...


class MetricsSink(Protocol):
    def observe(self, name: str, value: float, labels: Mapping[str, str]) -> None: ...


class NullMetrics:
    def observe(self, name: str, value: float, labels: Mapping[str, str]) -> None:
        return None


class PrometheusMetrics:
    """Low-cardinality metrics adapter; labels are constructed only by _labels."""

    def __init__(self, *, registry=None) -> None:
        from prometheus_client import REGISTRY, Counter, Gauge, Histogram

        registry = registry or REGISTRY
        labels = ("provider", "capability", "profile", "priority")
        outcome_labels = (*labels, "outcome")
        self._active = self._collector(Gauge, "rag_provider_active_calls", "Active provider call leases", labels, registry)
        self._queue_wait = self._collector(Histogram, "rag_provider_queue_wait_seconds", "Provider queue wait in seconds", labels, registry)
        self._rejections = self._collector(Counter, "rag_provider_rejections_total", "Provider admission rejections", outcome_labels, registry)
        self._outcomes = self._collector(Counter, "rag_provider_call_outcomes_total", "Provider call outcomes", outcome_labels, registry)
        self._retries = self._collector(Counter, "rag_provider_retries_total", "Provider retry attempts", outcome_labels, registry)
        self._duration = self._collector(Histogram, "rag_provider_call_duration_seconds", "Provider outbound call duration", outcome_labels, registry)
        self._first_token = self._collector(Histogram, "rag_provider_first_token_seconds", "Provider first token duration", labels, registry)
        self._circuit = self._collector(
            Gauge,
            "rag_provider_circuit_state",
            "Provider circuit state (one current state series is 1)",
            (*labels, "state"),
            registry,
        )

    @staticmethod
    def _collector(factory, name: str, documentation: str, labels: tuple[str, ...], registry):
        existing = getattr(registry, "_names_to_collectors", {}).get(name)
        return existing or factory(name, documentation, labels, registry=registry)

    def observe(self, name: str, value: float, labels: Mapping[str, str]) -> None:
        base = {key: labels[key] for key in ("provider", "capability", "profile", "priority")}
        if name == "provider_active_calls":
            self._active.labels(**base).inc(value)
        elif name == "provider_queue_wait_seconds":
            self._queue_wait.labels(**base).observe(value)
        elif name == "provider_rejections_total":
            self._rejections.labels(**base, outcome=labels["outcome"]).inc(value)
        elif name == "provider_call_outcomes_total":
            self._outcomes.labels(**base, outcome=labels["outcome"]).inc(value)
        elif name == "provider_retries_total":
            self._retries.labels(**base, outcome=labels["outcome"]).inc(value)
        elif name == "provider_call_duration_seconds":
            self._duration.labels(**base, outcome=labels["outcome"]).observe(value)
        elif name == "provider_first_token_seconds":
            self._first_token.labels(**base).observe(value)
        elif name == "provider_circuit_state":
            state = labels["state"]
            for candidate in ("closed", "open", "half_open"):
                self._circuit.labels(**base, state=candidate).set(
                    value if candidate == state else 0
                )


def _labels(policy: ProviderPolicy, priority: ProviderPriority, outcome: str = "") -> dict[str, str]:
    labels = {"provider": policy.provider, "capability": policy.capability,
              "profile": policy.fingerprint_hash, "priority": priority.name.lower()}
    if outcome:
        labels["outcome"] = outcome
    return labels


def parse_retry_after(value: str | None, *, now: float | None = None, maximum: float = 60.0) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value.strip())
        if 0 <= seconds <= maximum:
            return seconds
        return None
    except (TypeError, ValueError):
        pass
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        delay = date.timestamp() - (time.time() if now is None else now)
        return delay if 0 <= delay <= maximum else None
    except (TypeError, ValueError, OverflowError):
        return None


def retryable_before_token(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", getattr(exc, "status", None))
    if status is not None:
        try:
            code = int(status)
        except (TypeError, ValueError):
            return False
        return code in {408, 409, 429, 503}
    return isinstance(exc, (TimeoutError, asyncio.TimeoutError))


T = TypeVar("T")


class ProviderGovernor:
    def __init__(self, repository: LeaseRepository, *, circuit: CircuitRepository | None = None,
                 metrics: MetricsSink | None = None, sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep) -> None:
        self.repository = repository
        self.circuit = circuit
        self.metrics = metrics or NullMetrics()
        self._sleep = sleep

    async def acquire(self, policy: ProviderPolicy, *, priority: ProviderPriority = ProviderPriority.QUERY,
                       owner: str | None = None) -> ProviderLease:
        owner = owner or hashlib.sha256(f"{time.time_ns()}".encode()).hexdigest()[:24]
        configure = getattr(self.repository, "set_limit", None)
        if configure is not None:
            configure(policy.fingerprint, policy.concurrency_limit)
        if self.circuit:
            if not await self.circuit.allow(policy.fingerprint, policy.circuit_cooldown_seconds, owner):
                await self._observe_circuit(policy, priority, fallback="open")
                self.metrics.observe("provider_rejections_total", 1, _labels(policy, priority, "circuit_open"))
                raise ProviderUnavailableError("provider unavailable")
            await self._observe_circuit(policy, priority, fallback="closed")
        lease = await self.repository.acquire_now(policy.fingerprint, owner, int(priority), policy.lease_ttl_seconds)
        if lease:
            self.metrics.observe("provider_active_calls", 1, _labels(policy, priority))
            return lease
        deadline = time.monotonic() + policy.queue_timeout_seconds
        waiter = await self.repository.enqueue(policy.fingerprint, owner, int(priority), deadline, policy.queue_capacity)
        if waiter is None:
            self.metrics.observe("provider_rejections_total", 1, _labels(policy, priority, "queue_full"))
            raise ProviderBusyError()
        started = time.monotonic()
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.metrics.observe("provider_rejections_total", 1, _labels(policy, priority, "timeout"))
                    raise ProviderBusyError()
                lease = await self.repository.claim(waiter, policy.lease_ttl_seconds)
                if lease:
                    self.metrics.observe("provider_queue_wait_seconds", time.monotonic() - started, _labels(policy, priority))
                    self.metrics.observe("provider_active_calls", 1, _labels(policy, priority))
                    return lease
                await self._sleep(min(0.1, remaining))
        except asyncio.CancelledError:
            self.metrics.observe("provider_rejections_total", 1, _labels(policy, priority, "cancelled"))
            raise
        finally:
            if 'lease' not in locals() or lease is None:
                # Cancellation/timeout cleanup is best effort.  A database
                # failure here must not replace the caller's cancellation or
                # the uniform provider_busy timeout result; the waiter is
                # still bounded by its durable deadline.
                with suppress(BaseException):
                    await self.repository.cancel(waiter)

    async def release(self, policy: ProviderPolicy, lease: ProviderLease, *, priority: ProviderPriority = ProviderPriority.QUERY,
                      reason: str = "success") -> None:
        released = await self.repository.release(lease.lease_id, lease.owner, reason)
        if released:
            self.metrics.observe("provider_active_calls", -1, _labels(policy, priority))
        if released:
            self.metrics.observe("provider_call_outcomes_total", 1, _labels(policy, priority, reason))

    async def _observe_circuit(
        self,
        policy: ProviderPolicy,
        priority: ProviderPriority,
        *,
        fallback: str,
    ) -> None:
        """Export only one of the three fixed circuit states.

        Third-party test adapters created before circuit-state metrics may not
        implement ``state``.  They remain compatible and receive the caller's
        conservative state, while the PostgreSQL implementation reports the
        durable value.
        """
        state = fallback
        if self.circuit is not None:
            state_reader = getattr(self.circuit, "state", None)
            if state_reader is not None:
                try:
                    observed = await state_reader(policy.fingerprint)
                    if observed in {"closed", "open", "half_open"}:
                        state = observed
                except Exception:
                    # Metrics must never change admission behavior.
                    pass
        labels = _labels(policy, priority)
        labels["state"] = state
        self.metrics.observe("provider_circuit_state", 1, labels)

    async def _heartbeat_until_done(self, policy: ProviderPolicy, lease: ProviderLease) -> None:
        """Keep a long outbound call alive without extending an SSE request lease.

        A failed heartbeat is deliberately not retried locally.  The durable
        repository fencing remains authoritative and the regular release path
        is still safe after a process restart or lease expiry.
        """
        while True:
            # Heartbeats intentionally use wall-clock scheduling. The injected
            # sleep hook is for retry/queue tests and may be a zero-delay fake.
            await asyncio.sleep(policy.heartbeat_interval_seconds)
            try:
                alive = await self.repository.heartbeat(
                    lease.lease_id, lease.owner, policy.lease_ttl_seconds
                )
            except Exception:
                return
            if not alive:
                return

    @staticmethod
    async def _stop_heartbeat(task: asyncio.Task[None]) -> None:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _release_best_effort(
        self,
        policy: ProviderPolicy,
        lease: ProviderLease,
        priority: ProviderPriority,
        reason: str,
    ) -> None:
        """Release a call lease without masking the provider/caller error.

        PostgreSQL release is owner-fenced and TTL bounded, so a transient
        database failure must not replace the original provider exception or
        cancellation.  Record the failure with the same bounded labels and
        let durable expiry reclaim the slot.
        """
        try:
            # A stuck pool connection must not hold an SSE/request task open
            # after the provider call has already ended.  The lease TTL is the
            # upper bound for this best-effort cleanup; expiry then reclaims
            # the slot if PostgreSQL remains unavailable.
            await asyncio.wait_for(
                self.release(policy, lease, priority=priority, reason=reason),
                timeout=min(5.0, max(0.1, policy.lease_ttl_seconds)),
            )
        except BaseException:
            self.metrics.observe(
                "provider_call_outcomes_total",
                1,
                _labels(policy, priority, "release_error"),
            )

    async def governed_call(self, policy: ProviderPolicy, call: Callable[[], Awaitable[T]], *,
                            priority: ProviderPriority = ProviderPriority.QUERY, owner: str | None = None) -> T:
        """Execute one non-streaming call; each retry acquires a fresh lease."""
        circuit_owner = owner or hashlib.sha256(f"circuit:{time.time_ns()}".encode()).hexdigest()[:24]
        for attempt in range(policy.max_attempts):
            lease = await self.acquire(policy, priority=priority, owner=circuit_owner)
            heartbeat = asyncio.create_task(self._heartbeat_until_done(policy, lease))
            call_started = time.monotonic()
            try:
                result = await call()
            except BaseException as exc:
                reason = _failure_reason(exc)
                await self._release_best_effort(policy, lease, priority, reason)
                self.metrics.observe("provider_call_duration_seconds", time.monotonic() - call_started, _labels(policy, priority, reason))
                await self._stop_heartbeat(heartbeat)
                if not retryable_before_token(exc) or attempt + 1 >= policy.max_attempts:
                    if self.circuit and _circuit_failure(exc):
                        await self.circuit.failure(
                            policy.fingerprint,
                            policy.circuit_failure_threshold,
                            policy.circuit_cooldown_seconds,
                            circuit_owner,
                        )
                        await self._observe_circuit(policy, priority, fallback="open")
                    raise
                delay = parse_retry_after(str(getattr(exc, "headers", {}).get("Retry-After", "")), maximum=policy.retry_max_seconds)
                delay = delay if delay is not None else min(policy.retry_max_seconds, policy.retry_base_seconds * (2 ** attempt) * random.uniform(.8, 1.2))
                self.metrics.observe("provider_retries_total", 1, _labels(policy, priority, _failure_reason(exc)))
                await self._sleep(delay)
                continue
            try:
                await self._release_best_effort(policy, lease, priority, "success")
                self.metrics.observe("provider_call_duration_seconds", time.monotonic() - call_started, _labels(policy, priority, "success"))
            finally:
                await self._stop_heartbeat(heartbeat)
            if self.circuit:
                await self.circuit.success(policy.fingerprint, circuit_owner)
                await self._observe_circuit(policy, priority, fallback="closed")
            return result
        raise ProviderBusyError()

    async def governed_stream(self, policy: ProviderPolicy, call: Callable[[], Awaitable[Any]], *,
                              priority: ProviderPriority = ProviderPriority.QUERY, owner: str | None = None) -> AsyncIterator[Any]:
        """Yield a provider stream while leasing only the network call.

        Retries are allowed until the first item is yielded. Once iteration
        starts, provider failures are terminal and the lease is released.
        """
        circuit_owner = owner or hashlib.sha256(f"circuit:{time.time_ns()}".encode()).hexdigest()[:24]
        for attempt in range(policy.max_attempts):
            lease = await self.acquire(policy, priority=priority, owner=circuit_owner)
            heartbeat = asyncio.create_task(self._heartbeat_until_done(policy, lease))
            call_started = time.monotonic()
            started = False
            retry = False
            retry_exc: BaseException | None = None
            reason = "success"
            try:
                stream = await call()
                if not hasattr(stream, "__aiter__"):
                    yield stream
                else:
                    async for item in stream:
                        if not started:
                            self.metrics.observe("provider_first_token_seconds", time.monotonic() - call_started, _labels(policy, priority))
                        started = True
                        yield item
            except BaseException as exc:
                reason = _failure_reason(exc) if not started else "stream_error"
                retry = (
                    not started
                    and retryable_before_token(exc)
                    and attempt + 1 < policy.max_attempts
                )
                retry_exc = exc
                if not retry:
                    if self.circuit and _circuit_failure(exc):
                        await self.circuit.failure(
                            policy.fingerprint,
                            policy.circuit_failure_threshold,
                            policy.circuit_cooldown_seconds,
                            circuit_owner,
                        )
                        await self._observe_circuit(policy, priority, fallback="open")
                    raise
            finally:
                await self._release_best_effort(policy, lease, priority, reason)
                self.metrics.observe("provider_call_duration_seconds", time.monotonic() - call_started, _labels(policy, priority, reason))
                await self._stop_heartbeat(heartbeat)
            if self.circuit and not retry:
                await self.circuit.success(policy.fingerprint, circuit_owner)
                await self._observe_circuit(policy, priority, fallback="closed")
            if not retry:
                return
            delay = parse_retry_after(
                str(getattr(retry_exc, "headers", {}).get("Retry-After", "")),
                maximum=policy.retry_max_seconds,
            )
            delay = delay if delay is not None else min(
                policy.retry_max_seconds,
                policy.retry_base_seconds * (2 ** attempt) * random.uniform(.8, 1.2),
            )
            self.metrics.observe("provider_retries_total", 1, _labels(policy, priority, reason))
            await self._sleep(delay)


class InMemoryLeaseRepository:
    """Small deterministic repository useful for unit tests and local dry runs.

    Production callers must use the PostgreSQL implementation; this class is
    intentionally not used as a provider-wide enforcement mechanism.
    """
    def __init__(self) -> None:
        self._leases: dict[str, ProviderLease] = {}
        self._waiters: dict[str, tuple[str, str, int, float, int]] = {}
        self._seq = 0
        self.limits: dict[str, int] = {}

    def set_limit(self, fingerprint: str, limit: int) -> None:
        self.limits[fingerprint] = limit

    async def acquire_now(self, fingerprint: str, owner: str, priority: int, ttl_seconds: float) -> ProviderLease | None:
        self._reclaim()
        if sum(1 for x in self._leases.values() if x.fingerprint == fingerprint) >= self.limits.get(fingerprint, 40):
            return None
        return self._new_lease(fingerprint, owner, ttl_seconds)

    async def enqueue(self, fingerprint: str, owner: str, priority: int, deadline: float, capacity: int) -> str | None:
        if sum(1 for x in self._waiters.values() if x[1] == fingerprint) >= capacity:
            return None
        self._seq += 1
        waiter = f"w{self._seq}"
        self._waiters[waiter] = (owner, fingerprint, priority, deadline, self._seq)
        return waiter

    async def claim(self, waiter_id: str, ttl_seconds: float) -> ProviderLease | None:
        self._reclaim()
        row = self._waiters.get(waiter_id)
        if not row:
            return None
        owner, fingerprint, priority, deadline, seq = row
        if deadline <= time.monotonic():
            return None
        eligible = sorted((v[2], v[4], k, v) for k, v in self._waiters.items() if v[1] == fingerprint)
        if eligible and eligible[0][2] != waiter_id:
            return None
        if sum(1 for x in self._leases.values() if x.fingerprint == fingerprint) >= self.limits.get(fingerprint, 40):
            return None
        self._waiters.pop(waiter_id, None)
        return self._new_lease(fingerprint, owner, ttl_seconds)

    async def cancel(self, waiter_id: str) -> None:
        self._waiters.pop(waiter_id, None)

    async def heartbeat(self, lease_id: str, owner: str, ttl_seconds: float) -> bool:
        lease = self._leases.get(lease_id)
        if not lease or lease.owner != owner or (lease.expires_at and lease.expires_at.timestamp() <= time.time()):
            return False
        self._leases[lease_id] = ProviderLease(lease_id, lease.fingerprint, owner, datetime.fromtimestamp(time.time() + ttl_seconds, timezone.utc))
        return True

    async def release(self, lease_id: str, owner: str, reason: str = "success") -> bool:
        lease = self._leases.get(lease_id)
        if not lease or lease.owner != owner:
            return False
        self._leases.pop(lease_id, None)
        return True

    def _new_lease(self, fingerprint: str, owner: str, ttl: float) -> ProviderLease:
        import uuid
        lease = ProviderLease(str(uuid.uuid4()), fingerprint, owner, datetime.fromtimestamp(time.time() + ttl, timezone.utc))
        self._leases[lease.lease_id] = lease
        return lease

    def _reclaim(self) -> None:
        now = datetime.now(timezone.utc)
        for key, lease in list(self._leases.items()):
            if lease.expires_at and lease.expires_at <= now:
                self._leases.pop(key, None)


class PostgresLeaseRepository:
    """Protocol adapter over :mod:`provider_governance_repo`.

    Keeping this adapter here lets the orchestration layer remain testable and
    avoids leaking the database repository's request-hash implementation into
    model adapters.  Its backing repository must be migration-036 compatible.
    """
    def __init__(self, repository: Any | None = None) -> None:
        if repository is None:
            from raganything.services.provider_governance_repo import provider_governance_repository
            repository = provider_governance_repository
        self._repository = repository
        self._limits: dict[str, int] = {}

    def set_limit(self, fingerprint: str, limit: int) -> None:
        self._limits[fingerprint] = limit

    async def acquire_now(self, fingerprint: str, owner: str, priority: int, ttl_seconds: float) -> ProviderLease | None:
        owner_fence = _opaque(owner)
        row = await self._repository.acquire(
            fingerprint, owner_fence, _opaque(owner), priority,
            self._limits.get(fingerprint, 40), max(1, int(ttl_seconds)),
        )
        return _to_lease(row)

    async def enqueue(self, fingerprint: str, owner: str, priority: int, deadline: float, capacity: int) -> str | None:
        remaining = max(0.0, deadline - time.monotonic())
        owner_fence = _opaque(owner)
        row = await self._repository.enqueue(
            fingerprint,
            _opaque(owner),
            priority,
            datetime.fromtimestamp(time.time() + remaining, timezone.utc),
            capacity,
            owner_fence=owner_fence,
            concurrency_limit=self._limits.get(fingerprint, 40),
        )
        if row is not None:
            return row.id
        return None

    async def claim(self, waiter_id: str, ttl_seconds: float) -> ProviderLease | None:
        row = await self._repository.claim_waiter(waiter_id, ttl_seconds=max(1, int(ttl_seconds)))
        return _to_lease(row)

    async def cancel(self, waiter_id: str) -> None:
        await self._repository.cancel_waiter(waiter_id)

    async def heartbeat(self, lease_id: str, owner: str, ttl_seconds: float) -> bool:
        return await self._repository.heartbeat(lease_id, owner, max(1, int(ttl_seconds)))

    async def release(self, lease_id: str, owner: str, reason: str = "success") -> bool:
        return await self._repository.release(lease_id, owner, reason)

def _opaque(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _to_lease(row: Any | None) -> ProviderLease | None:
    if row is None:
        return None
    return ProviderLease(row.id, row.profile_fingerprint, row.owner_fence, row.expires_at)


class InMemoryCircuitRepository:
    """Deterministic circuit store for tests; production uses PostgreSQL rows."""
    def __init__(self) -> None:
        self._state: dict[str, tuple[str, int, float]] = {}

    async def allow(self, fingerprint: str, cooldown_seconds: float, probe_owner: str | None = None) -> bool:
        state, failures, opened = self._state.get(fingerprint, ("closed", 0, 0.0))
        now = time.monotonic()
        if state == "open":
            if now - opened < cooldown_seconds:
                return False
            # The first caller fences the probe by moving to half-open.
            self._state[fingerprint] = ("half_open", failures, opened)
            return True
        if state == "half_open":
            return False
        return True

    async def success(self, fingerprint: str, probe_owner: str | None = None) -> None:
        self._state[fingerprint] = ("closed", 0, 0.0)

    async def failure(self, fingerprint: str, threshold: int, cooldown_seconds: float,
                      probe_owner: str | None = None) -> None:
        state, failures, _ = self._state.get(fingerprint, ("closed", 0, 0.0))
        failures += 1
        if state == "half_open" or failures >= threshold:
            self._state[fingerprint] = ("open", failures, time.monotonic())
        else:
            self._state[fingerprint] = ("closed", failures, 0.0)

    async def state(self, fingerprint: str) -> str:
        state, _failures, _opened = self._state.get(fingerprint, ("closed", 0, 0.0))
        return state


def _failure_reason(exc: BaseException) -> str:
    status = getattr(exc, "status_code", getattr(exc, "status", None))
    if status in (429, "429"):
        return "429"
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return "timeout"
    if status in (503, "503"):
        return "5xx"
    return "error"


def _circuit_failure(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", getattr(exc, "status", None))
    return isinstance(exc, (TimeoutError, asyncio.TimeoutError)) or status in (429, 500, 502, 503, 504, "429", "500", "502", "503", "504")


__all__ = ["ProviderGovernor", "ProviderPolicy", "ProviderLease", "ProviderPriority", "ProviderBusyError", "ProviderUnavailableError", "PrometheusMetrics", "parse_retry_after", "retryable_before_token", "LeaseRepository", "CircuitRepository", "InMemoryLeaseRepository", "InMemoryCircuitRepository", "PostgresLeaseRepository"]
