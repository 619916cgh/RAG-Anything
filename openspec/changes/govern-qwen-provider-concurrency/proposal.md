## Why

The current query path can admit many users without sharing a durable provider limit, so increasing `MAX_ASYNC` would move overload into the Qwen quota boundary and produce avoidable 429s, latency spikes, or slot leakage across workers. A provider-scoped governor is needed now because the existing isolated capacity evidence has not established a safe 40/50-user real-Qwen boundary.

## What Changes

- Add a server-side provider governor keyed by an immutable Qwen model profile/fingerprint, with PostgreSQL-backed global leases shared by workers and instances.
- Bound FIFO admission to 10 seconds, support cancellation and lease TTL/heartbeat/release, and prioritize interactive queries over uploads and background model work.
- Acquire a provider lease for each actual LLM/VLM outbound call rather than for an entire SSE lifetime; cap query-local `MAX_ASYNC` by the provider limit.
- Route every Qwen LLM/VLM construction path through the governor, including agent, RAG/rerank/citation repair, contextual, VLM/image, and agentic calls.
- Add bounded pre-first-token retry handling for eligible 429/408/409/timeouts/confirmed 503 responses, honoring bounded `Retry-After` and jittered exponential backoff; never retry after streaming starts or for authentication, parameter, or other 4xx failures.
- Keep governance fields private to server-side profiles and controlled configuration; expose no concurrency, quota, endpoint, credential, or token fields through public settings/profile APIs.
- Add low-cardinality, redacted provider metrics for active calls, queueing, outcomes, retries, circuit state, latency, first-token latency, and usage reservation/settlement only when upstream usage is returned.
- Preserve existing per-user PostgreSQL query leases and enforce the order `user lease -> retrieval -> provider lease -> Qwen call -> provider release`.
- Add focused code tests plus an isolated real-Qwen acceptance ladder for 10/20/30/40/50 VU, with the stated P95, queue, recovery, health, and cleanup gates; stop and classify the first failed rung.

## Capabilities

### New Capabilities

- `provider-governance`: Durable provider admission, priority queues, lease lifecycle, retries, circuit breaking, private profile limits, and redacted metrics for model calls.

### Modified Capabilities

- `adaptive-concurrency`: Clarify that the existing effective-concurrency resolver is bounded by the provider governor and that `MAX_ASYNC` is query-local rather than a provider-wide limit.

## Impact

- Affects model profile construction, agent/query and retrieval services, VLM/image paths, upload/background model task scheduling, provider metrics, PostgreSQL migrations/repositories, and focused test fixtures.
- Adds a shared provider-lease data model and runtime configuration, but does not change public profile DTOs or existing user quota storage.
- Adds isolated acceptance tooling and evidence requirements; no production deployment, quota claim, worker-count change, or real-Qwen traffic is part of proposal creation.
