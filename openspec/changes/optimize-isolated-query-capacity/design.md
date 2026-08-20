## Context

The completed isolated cloud benchmark used one application process limited to 2 CPU and 3 GiB memory, temporary PostgreSQL/Redis volumes, fixed mock LLM/embedding timing, and loopback Nginx. At five users it completed 5,184 requests with no error or resource breach; at ten users it completed 773 requests but app CPU exceeded 85 percent for three consecutive five-second samples. RSS stayed below one GiB and recovery was clean.

The endpoint performs authentication and permission checks before it starts its SSE generator, then streams accepted, query, model-token, and persistence events. Each protected SSE event currently revalidates the account session against PostgreSQL. The endpoint also attaches a per-query root logger handler and repeatedly drains its queue while retrieval runs. Both are plausible CPU/IO multipliers, but the next change MUST not assume either is the root cause without isolated evidence.

The working tree contains unrelated concurrent changes. This change owns only its new OpenSpec artifacts, profiling/test-only tooling, the smallest affected query-path files, their focused tests, and the coordinator-owned summary/report updates.

## Goals / Non-Goals

**Goals:**

- Attribute sustained application CPU during the existing mock-backed query workload to concrete call paths using an isolated, disposable stack.
- Remove only confirmed avoidable per-request or per-event work while preserving authorization, SSE ordering, session persistence, and metrics semantics.
- Re-run comparable five- and ten-user stages using the same 2 CPU/3 GiB limit, mock settings, readiness fixture, loopback Nginx, and stop conditions.
- After a recorded ten-user CPU-gate breach, collect one bounded, user-authorized 20-user isolated diagnostic sample to determine whether the same saturation behavior persists. It is not capacity acceptance.
- After the documented 20-user diagnostic, collect a user-authorized `30 -> 40 -> 50` diagnostic ladder only under the explicit per-rung recovery and health gates below. It is not capacity acceptance.
- Produce a capacity conclusion from measurements, including an explicit unchanged-boundary result when applicable.

**Non-Goals:**

- Changing the production rate-limit policy, increasing the CPU allocation, loosening the CPU stop condition, or adding application workers.
- Profiling or reading production processes, configuration, data, models, volumes, or network endpoints.
- Measuring real-model latency, multi-instance behavior, browser clients, PDF parsing, or upload capacity.
- Reclassifying a CPU-gate breach as a pass, changing the 2 CPU/3 GiB limit, or changing the standard 85 percent/three-sample CPU stop rule.

## Decisions

### Isolated sampling first

The runner will support a bounded standard-library cProfile window only after the temporary Compose stack is retrieval-ready and only through its run-labelled app container. A test-only image layer exposes a random-key-gated internal loopback control route, writes the raw profile only inside the temporary container, and the runner exports only app-code aggregate timing. It records the exact app image ID, container identifier, profile start/stop times, and sanitized evidence in the run directory before owned resources are removed.

Profiling within the isolated container is selected over host-wide tracing because it cannot observe production processes and preserves the benchmark's ownership boundary. The profiling control route is test-image-only, key-gated, disabled by default, absent from production images, and not documented in the schema; no source mount or production Compose change is added.

### Phase correlation and evidence threshold

The controller will align profile timestamps with request NDJSON, five-second app CPU samples, PostgreSQL activity, and query-phase histogram snapshots. It will identify a candidate only when the candidate appears consistently across the sustained high-CPU interval and an isolated focused test can distinguish the candidate's former and optimized behavior.

Changing a likely hotspot based on code inspection alone is rejected because the workload includes retrieval, PostgreSQL state, SSE serialization, and mock streaming, any of which can dominate differently on the fixed host.

### Sanitized stream-failure attribution before repair

The workload records a bounded allowlisted event sequence and event-order-derived phase for every isolated request. It records no event payload values: in particular, it never persists the router's generic exception message, request query, answer, token text, thread ID, or credentials. A `type:error` can therefore be separated from transport/framing failure and located before agent setup, retrieval, first token, or after tokens where persistence/terminal work is the remaining candidate set. A session-revalidation rejection has no `error` event and is recorded as an unterminated stream, preserving the distinction without changing security behavior.

This evidence is diagnostic only. It cannot distinguish individual exceptions that share an SSE phase, and no stable backend error code will be added unless the isolated phase evidence makes that additional interface surface necessary.

If phase-only evidence is insufficient, a disposable capacity image may add the
fixed allowlist code `query_core_acquire`, `pre_agent_info_setup`, or `unknown`
only when `PERF_SSE_PHASE_ATTRIBUTION=1`. A manifest-owned preflight must compile
and import the transformed app and verify the profiling route before Compose
startup. Preflight failure creates no isolated database, identity, or query
resources and records only a bounded failure class.

### Preserve per-event authorization with bounded revalidation

If profiling confirms session revalidation is material, protected SSE events will retain fail-closed authorization but use a request-local, short monotonic revalidation interval. A session is checked before the first protected event, then at most once during each small interval; revocation, disable, archival, or session-generation changes stop later events no later than the next interval. The content-free `accepted` event remains the sole unvalidated event.

This is preferred to removing checks or sharing a cross-user cache: authorization remains per request and no stale shared role/session state is introduced. The interval and behavior will be covered by deterministic tests.

### Avoid request-global logger work only if confirmed

If profiling attributes material cost to attaching a `LogCaptureHandler` to the shared logger, the normal text query path will attach it only while the UI-visible retrieval-progress feature needs it, and it will use a request-local logger/filter rather than processing unrelated records. Agentic and diagnostic behavior will keep the existing progress semantics until covered independently.

Globally raising logging levels or deleting query diagnostics is rejected because it would conceal operational evidence and could change unrelated request behavior.

### Comparable acceptance

An optimization is accepted only when focused correctness tests pass and the isolated ten-user stage no longer triggers its previous CPU stop condition, or it reaches a different documented stop condition. The controller may advance to 20 users only after the ten-user stage passes; it will never infer 20/35/50 capacity from a lower stage. The report compares request count, success/error classes, TTFT/total percentiles, CPU/RSS, PostgreSQL observations, and profile attribution to the baseline.

### User-authorized diagnostic escalation

The user may authorize diagnostic-only higher-concurrency stages after a ten-user stage has recorded the standard CPU gate and at least 60 seconds of recovery evidence. The explicit `30 -> 40 -> 50` ladder uses fresh disposable runs and an allow-list rather than arbitrary VU counts. Each rung requires full retrieval readiness with non-empty sources, a persisted prior result, at least 60 seconds of prior recovery, and healthy fixed production probes. In this explicit mode only, the resource policy records a 170-percent sustained CPU threshold over three samples and a 190-percent single-sample emergency threshold; RSS remains an 80-percent three-sample stop, and any non-successful query, OOM, restart, ownership, resource, or production-health breach is a hard stop. Each rung is fixed to 90 seconds and five-second samples, followed by at least 60 seconds of recovery and owned cleanup. The same test-only image, 2 CPU/3 GiB app limit, mock timing, fixture, loopback Nginx, ownership checks, and fixed production read-only probes remain active. The ladder cannot establish capacity, make ten users pass, authorize users above 50, or justify a production optimization.

## Risks / Trade-offs

- [Profiling changes process timing] -> Capture a short, labelled window and use it for attribution, while acceptance measurements run with profiling disabled.
- [A bounded session check delays revocation observation] -> Retain first-event validation, use a documented short interval, and test revocation/archival/session-generation behavior at the interval boundary.
- [A logging change removes useful progress events] -> Limit changes to a confirmed source, preserve event ordering tests, and keep complete diagnostic logging available.
- [The CPU boundary is intrinsic retrieval cost] -> Report it unchanged and recommend a larger instance or a separately designed retrieval architecture; do not bypass the stop rule.
- [Concurrent worktree edits overlap] -> Re-read affected files immediately before edits and do not stage unrelated files.

## Migration Plan

Add test-only profiling support and focused regression tests, profile the disposable cloud stack, then apply a minimal confirmed optimization. Run source-level checks and the comparable isolated stages. No migration, production configuration change, deployment, or production read is part of this change. Reverting the owned code and test-only profiling support restores prior behavior without data cleanup.

## Open Questions

- Which call path dominates the sustained ten-user CPU interval: per-event account revalidation, logger capture/drain, retrieval, JSON/SSE serialization, or another dependency?
- Does the confirmed optimization clear the ten-user CPU gate under identical conditions, or merely shift the boundary to another resource?
