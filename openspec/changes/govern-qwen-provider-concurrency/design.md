## Context

The application already has per-user PostgreSQL query leases and a query-local `MAX_ASYNC`, but model calls can originate from several agent, retrieval, contextual, and multimodal paths. The isolated benchmark showed that a larger user population can reach a provider or host saturation boundary without proving a safe Qwen quota. The governor must therefore coordinate across workers and app instances, while preserving per-user fairness and keeping the public model catalog sanitized.

Constraints are PostgreSQL as the shared-state authority, FastAPI async request cancellation, SSE first-token semantics, existing upload/background queues, and no confirmed Qwen RPM/TPM values yet. A provider slot may cover one outbound request only; holding it for an entire SSE stream would underutilize the quota and make cancellation less predictable.

## Goals / Non-Goals

**Goals:**

- Enforce a shared initial Qwen concurrency cap of 40 by immutable profile fingerprint, with a bounded ten-second admission wait.
- Make lease acquisition, TTL expiry, heartbeats, cancellation, and exceptional release safe across workers and instances.
- Give interactive queries priority over uploads and background model work without starving lower priorities indefinitely.
- Apply identical admission, retry, circuit, and metric behavior to every LLM/VLM outbound call.
- Preserve user query leases, public profile privacy, and existing stream event ordering.
- Provide deterministic unit/integration contracts and an isolated real-Qwen 10 -> 20 -> 30 -> 40 -> 50 acceptance procedure.

**Non-Goals:**

- Increasing production `MAX_ASYNC`, worker count, or rate limits.
- Claiming RPM/TPM enforcement before controlled configuration contains verified Qwen quotas and usage responses.
- Replacing PostgreSQL leases with an in-process semaphore or introducing a second source of truth for user quotas.
- Retrofitting already-indexed documents or changing historical upload snapshots.
- Treating mock-provider tests, HTTP health, or code tests as real-Qwen or production acceptance.

## Decisions

### Immutable profile identity and private policy

Resolve each outbound model to a server-owned profile plus canonical fingerprint (provider, model, capability, and policy version). Governance fields live in a private runtime object/config table keyed by that fingerprint; public DTOs continue to expose only the existing sanitized catalog fields. Configuration validation rejects non-positive limits, queue timeouts outside the bounded policy, invalid retry values, and `MAX_ASYNC` above the provider cap. RPM/TPM are optional until explicitly marked verified; absent verification they are reported as unconfigured rather than enforced.

### PostgreSQL lease and queue protocol

Use migration 036 (added to the migration manifest without editing historical migrations) for provider lease, waiter, and circuit-state tables plus fingerprint/expiry/owner indexes. Acquisition runs in a short transaction protected by a fingerprint-scoped advisory lock: it reclaims expired leases, atomically counts active leases, and either inserts a lease or records a waiter with monotonic enqueue sequence, priority, deadline, and cancellation state. The queue has a configured finite capacity; claiming is ordered by priority then sequence and rechecks capacity so two instances cannot exceed the cap. A heartbeat extends only an owned, unexpired lease. Release is idempotent and records terminal reason. The waiter polls with bounded jitter and deletes/cancels its row on timeout, request cancellation, or task failure. Fresh, upgrade, repeat, intentional-failure, and rollback behavior is tested in disposable PostgreSQL before any controlled apply.

The governor owns no query contents, answer text, token text, user identifiers, or raw provider URLs. Queue rows use opaque lease/request hashes and low-cardinality priority/reason codes. PostgreSQL remains authoritative after restart; stale leases are recovered by expiry rather than process-local cleanup.

### Call-scoped wrapper and priority

Expose one async wrapper used by all LLM/VLM adapters. The wrapper acquires a provider lease immediately before the actual network call, starts the heartbeat for calls that can exceed the lease interval, and releases it in `finally`. Query calls use the highest priority; upload and background calls use lower priorities. `MAX_ASYNC` remains an inner fan-out bound and is resolved as `min(user/query setting, provider concurrency limit)` without mutating the stored user setting. The existing user query lease remains responsible for per-user fairness and retrieval lifetime, but interactive admission no longer uses the provider cap as its user-lease outer limit; calls over 40 wait in the provider queue and receive `provider_busy` only after its deadline.

### Retry and circuit policy

Only failures before the first streamed token are retryable: 429, 408, 409, timeouts, and confirmed 503. Parse `Retry-After` only when numeric seconds or a valid HTTP date within the configured maximum; otherwise use jittered exponential backoff capped by profile policy. Each retry reacquires a fresh provider lease and releases it before backoff, so a sleeping retry does not hold a slot. Authentication, parameter, local/programming, and other 4xx responses are terminal. Once a token is emitted, no retry is attempted. Circuit state is stored durably per fingerprint; it opens after a configured consecutive/rolling failure threshold, permits one cross-instance half-open probe after cooldown, and closes only after a successful probe. Queued calls receive a uniform sanitized `provider_busy` (HTTP 429 for non-streaming requests; an allowlisted SSE error code followed by stream termination after an already accepted request) or `provider_unavailable` classification.

### Metrics and logging

Emit low-cardinality metrics labelled only by provider, capability, profile fingerprint hash, priority, and bounded outcome/reason. Record active leases, queue wait, rejects/timeouts/cancellations, call and first-token latency, successes, 429/timeouts/5xx, retry count/reason, circuit state, and token reservation/settlement state only when upstream usage is present. Structured logs use the same allowlist and never include query, answer, token, secret, endpoint, or user identifiers.

### Acceptance isolation

The real-Qwen ladder runs from a disposable App/PostgreSQL/Redis/Nginx stack with 50 synthetic users, an isolated KB, and a restricted key supplied through controlled configuration. Stages are strictly sequential (`10 -> 20 -> 30 -> 40 -> 50`), require recovery and health gates before advancing, and stop on the first hard failure. Each stage checks SSE ordering, TTFT P95 <= 5 seconds, full-answer P95 <= 15 seconds, bounded queue wait, no unexpected provider errors/retries, resource/restart/pool health, ten-minute recovery, 120 health samples, and cleanup. Results are capacity evidence only for the measured model/quota/prompt/KB/topology.

## Risks / Trade-offs

- [A long-running call outlives its lease] -> Use a short TTL with heartbeat ownership checks and release on cancellation; reclaim only expired leases.
- [Priority queue starves uploads] -> Track wait age and add an explicit maximum lower-priority wait or starvation alert without allowing lower priority to bypass the provider cap.
- [A provider returns an ambiguous 503 or Retry-After] -> Retry only confirmed eligible classes, clamp delay, and expose a bounded reason code.
- [Database contention adds admission latency] -> Keep transactions short, index fingerprint/status/expiry, and measure queue wait separately from provider latency.
- [Usage is missing or malformed] -> Do not enforce TPM or settle reservations from estimates; mark usage unconfigured/unknown and retain only aggregate metrics.
- [Different call paths bypass the wrapper] -> Centralize adapter construction and add an inventory test that fails when a known LLM/VLM entry point lacks governor injection.
- [Real-Qwen acceptance consumes quota or leaks data] -> Use a separate key, disposable resources, synthetic users/KB, explicit stop rules, and post-stage cleanup; never read production config or traffic.

## Migration Plan

1. Add the provider policy/lease/waiter schema and repository methods with backward-compatible startup defaults; deploy code with governance disabled for profiles lacking a verified private policy.
2. Implement the wrapper, profile fingerprint resolution, priority callers, retry/circuit handling, metrics, and focused tests. Verify migration fresh/upgrade/repeat behavior in disposable PostgreSQL.
3. Enable the Qwen profile with concurrency 40 and queue timeout 10 in controlled staging only. Confirm all model entry points and two app instances share the same cap.
4. Run the isolated real-Qwen ladder and record quota verification before enabling RPM/TPM. Roll back by disabling the profile policy and reverting code; expired rows can be reclaimed without data migration.

## Open Questions

- Which exact Qwen model fingerprint and controlled RPM/TPM values will be approved for the real acceptance run?
- What lease TTL/heartbeat interval and circuit thresholds fit the provider's longest expected first-token latency?
- Does the existing provider adapter expose a reliable streamed usage event for TPM settlement, or must TPM remain unconfigured initially?
