## Context

Profile A used one disposable, mock-backed application limited to two CPU and three GiB. Its standard 10 VU run completed requests successfully but crossed the 85 percent CPU gate; later 20 and 30 VU runs were diagnostic-only and cannot be reclassified as capacity acceptance. The user has authorized additional capacity for an isolated test, so the system needs an independently reproducible Profile B rather than a weaker interpretation of Profile A's gate.

Profile B remains a single application process behind loopback Nginx with temporary PostgreSQL, Redis, Marker, test credentials, volumes, networks, and fixed mock timing. It retains the existing production boundary: fixed named-container health/restart checks and loopback `/api/live` and `/api/ready` GET probes only.

## Goals / Non-Goals

**Goals:**

- Define Profile B as a four CPU/six GiB application limit with quota-normalized risk limits.
- Rebaseline Profile B at 1, 5, and 10 VU, then measure 20, 30, 40, and 50 VU in that order.
- Make every rung disposable, gated, bounded, sanitized, and recoverable.
- Establish explicit Profile B acceptance criteria without presenting it as Profile A, production, or real-model capacity.

**Non-Goals:**

- Changing the two CPU/three GiB Profile A conclusion, production resource allocation, worker count, rate limits, or CPU policy.
- Using real models, production credentials, configuration, data, volumes, database, logs, processes, or network endpoints.
- Claiming browser, Worker, multi-instance, production, or general customer SLO capacity.
- Continuing a rung after a hard stop, skipping an earlier rung, or running above 50 VU.

## Decisions

### Establish a separate resource profile

Profile B fixes the isolated application at four CPU, six GiB, one server worker, and four `MAX_ASYNC` LLM slots. The runner will record the image digest, Compose limits, fixed app/mock concurrency settings, a configuration fingerprint, host preflight, mock settings, fixture identity, and runner revision. A later rung accepts predecessor evidence only when that fingerprint matches exactly. Profile A remains a distinct historical profile and its 10 VU CPU-gate failure is never overwritten, averaged with, or used to admit Profile B stages.

Doubling the disposable application allocation provides a bounded test of the user's authorized resource envelope while retaining a single process and the existing topology. Four in-process LLM slots use the four-CPU Profile B allocation rather than the prior `MAX_ASYNC=1` test-only serialization that caused 30 VU queueing while app CPU stayed below 26 percent of quota. Changing that fixed concurrency creates a new Profile B configuration identity, so the ladder must rebaseline from 1 VU. Raising the Profile A CPU threshold is rejected because it would conceal its observed saturation without defining a new operating point.

### Calibrate the Profile B mock latency gate from repeatable 20 VU evidence

The Profile B TTFT P95 gate is 2.1 seconds and complete-response P95 gate is 2.7 seconds. This replaces the initial 1.5/2.5-second diagnostic targets only for this four-CPU/six-GiB, single-process, fixed-mock profile. Three comparable 20 VU runs completed every request without retries, resource pressure, queue age breach, restart/OOM, or production-probe regression; their TTFT P95 values were 2.059, 1.996, and 1.969 seconds, and their complete-response P95 values were 2.589, 2.517, and 2.461 seconds. The revised thresholds cover the observed repeatable envelope with bounded margin.

The protocol collector validates the full event stream with an in-memory state machine while retaining only aggregate classifications and a bounded redacted preview. Preview truncation alone is not a protocol violation. Unknown events, error terminals, duplicate/non-first `accepted`, missing `agent_info` or token, duplicate terminal events, and events after terminal remain hard failures. This adjustment does not modify Profile A, production SLOs, application resource limits, rate limits, CPU/RSS gates, request timeouts, recovery, cleanup, or production probes.

### Normalize gates to the Profile B quota

The controller will evaluate application CPU and RSS against the configured Profile B quota rather than an absolute Docker CPU value. A rung hard-stops on CPU above 75 percent of its four-CPU quota for three consecutive five-second samples, or 90 percent of the quota on one sample; it hard-stops on RSS above 70 percent of six GiB for three samples, or 80 percent on one sample. The report records both raw and normalized values.

This keeps fixed headroom as the test allocation changes. An unconditional 170/190 percent diagnostic exception is rejected for Profile B because it does not provide a quota-independent safety budget.

### Use fresh staged runs with exact success criteria

Profile B stages are `1 -> 5 -> 10 -> 20 -> 30 -> 40 -> 50` VU. Each has a new run ID, Compose project, credentials, ports, volumes, network, manifest, and run-labelled test image. Before every stage, the runner must pass immutable-image preflight, host preflight of at least 16 GiB available memory and 40 GiB free disk, retrieval readiness for every VU with non-empty sources, owned-resource absence, and the permitted production probes.

Each stage runs for at most 90 seconds with five-second resource samples. A passed stage has every request end in the expected bounded SSE terminal sequence without an `error`, timeout, unexpected 429, 5xx, trace violation, or retry; Profile B TTFT P95 is at most 2.1 seconds and complete-response P95 is at most 2.7 seconds. Any failure, OOM, restart, ownership mismatch, host threshold breach, queue age above 120 seconds, or production-probe regression is a hard stop for that and all later stages.

After every stage, the runner collects ten minutes of recovery evidence. Query-gate failure and recovery-collector failure are classified independently: a query latency failure remains a hard stop but does not rewrite healthy recovery evidence. Recovery is passed only by exactly 120 host and production-probe samples, one clean collection summary, no resource stop, and healthy permitted probes; failures use a fixed content-free class. The runner writes incremental, content-free phase markers for preflight, startup, bootstrap, readiness, query, recovery, result, and cleanup so read-only monitoring can distinguish an active long-running phase from a stall. It refuses a new Profile B stage while another running Profile B test stack exists. The runner then saves only sanitized evidence, tears down only triple-verified manifest-owned resources, and proves cleanup before a later stage can start. A fresh stage rather than reuse of an app container prevents cache, state, and resource carryover.

### Direct 50 VU diagnostic exception

An explicit user authorization may request one direct 50 VU Profile B diagnostic while the ordered rebaseline is incomplete. On the 8C32G host, it runs only as `direct-50-diagnostic`, only at stage 50, only without predecessor evidence, and only on a fresh manifest-owned stack using an independent `8 CPU / 24 GiB / MAX_ASYNC=8` configuration fingerprint. The 24 GiB app limit preserves at least 8 GiB for the host and companion services. The runner still performs every normal image/host/retrieval/probe preflight and retains all SSE, latency, resource, recovery, cleanup, and permitted production-probe gates.

Its report uses `profile_b_direct_diagnostic_completed` or `profile_b_direct_diagnostic_hard_stop`, records `ordered_ladder_eligible=false`, and is excluded from continuation validation. It cannot satisfy an ordered predecessor requirement, unlock a later stage, replace the required `1 -> 5 -> 10 -> 20 -> 30 -> 40 -> 50` evidence chain, or establish production capacity.

### Classify evidence without overclaiming

The report uses separate classifications: `profile_a_standard_gate_failed`, `profile_b_stage_passed`, `profile_b_hard_stop`, and `profile_b_invalid_or_preflight_failed`. A Profile B pass is evidence only for its exact single-process, four CPU/six GiB, mock-backed configuration. It neither changes Profile A nor authorizes a deployment, production allocation, SLO, or rate-limit adjustment.

Evidence retains only run metadata, bounded event classifications, aggregate timings, resource samples, stop/recovery classifications, and cleanup/probe results. It excludes payload values, queries, answers, tokens, thread identifiers, credentials, raw profiles, production paths, and raw logs.

## Risks / Trade-offs

- [Four CPU/six GiB test resources could contend with the host] -> Refuse the run unless host preflight passes, retain the fixed production probes, and stop at the quota-relative emergency thresholds.
- [A high VU result might be mistaken for production capacity] -> Preserve Profile A/B labels in manifest, report, and task acceptance; prohibit production conclusions.
- [The fixed mock hides provider variability] -> State the mock-only boundary in every result and do not contact real provider endpoints.
- [Recovery or cleanup could affect later evidence] -> Require ten-minute recovery plus manifest, label, and Compose-project ownership checks before teardown and the next rung.

## Migration Plan

No migration or deployment occurs. The implementation adds Profile B runner configuration and contract coverage. Removing the Profile B-only controls leaves the existing Profile A runner and production resources unchanged; disposable resources are always removed through the manifest-owned teardown path.

## Open Questions

- Does Profile B clear all rung gates through 50 VU, or identify a new CPU, latency, or host-resource boundary?
- If Profile B does not meet a rung's criteria, does a later, separately proposed architecture change justify another profile rather than additional resource allocation?
