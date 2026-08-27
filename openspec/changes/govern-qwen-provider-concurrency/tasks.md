## 1. Inventory and private policy

- [x] 1.1 Inventory every Qwen-capable LLM/VLM outbound path and add a contract manifest covering `vision_models.py` builders/contextual proxies, agent summary/agentic fallbacks, query rewrite/rerank/citation repair, image/VLM paths, legacy KB callbacks, autorepair, workflow execution, and background upload calls.
- [x] 1.2 Add the server-private provider governance profile/config model with canonical fingerprint, defaults (concurrency 40, queue timeout 10), bounded retry fields, finite queue capacity, and explicit unenforced/unknown RPM/TPM state.
- [ ] 1.3 Preserve public model/profile/settings DTO redaction and compatibility for legacy `MAX_ASYNC`, personal quotas, profile snapshots, and existing catalog consumers; add leakage regression tests including admin settings routes.
- [x] 1.4 Define query/upload/background priority constants, the uniform `provider_busy` HTTP/SSE error contract, and the user-lease -> retrieval -> provider-call ordering without changing stored user quotas.

## 2. Durable PostgreSQL coordination

- [x] 2.1 Add migration 036 for provider call leases, bounded waiters, and shared circuit state with owner fencing, TTL/heartbeat fields, priority/FIFO sequence, state indexes, and no sensitive payload columns.
- [ ] 2.2 Register migration 036 in the manifest/checksum chain without editing historical migrations; add rollback/recovery notes and backup-acknowledgement release gates.
- [x] 2.3 Implement repository transactions using fingerprint-scoped advisory locking, expired-lease reclaim, atomic admission, waiter claim/cancel/timeout, owner-checked heartbeat/release, and idempotent exceptional cleanup.
- [ ] 2.4 Add disposable PostgreSQL fresh/upgrade/repeat/intentional-failure/rollback tests, including two app instances sharing one limit, empty-set admission races, TTL fencing, heartbeat mismatch, database failure, cancellation, and no leaked waiter/lease rows.

## 3. Provider governor runtime

- [x] 3.1 Implement `provider_governance` service APIs for acquire, heartbeat, release, cancellation, bounded priority queueing, timeout, and sanitized error mapping; never use an in-process semaphore as the provider-wide cap.
- [x] 3.2 Integrate the governor with existing user query leases so the user lease remains for fairness/retrieval while provider leases cover only one actual outbound call and do not occupy a slot during SSE idle time or retry backoff.
- [x] 3.3 Clamp query-local `MAX_ASYNC`/fan-out to the provider limit and retain personal settings; add compatibility tests proving requests over 40 queue rather than fail through the legacy provider outer limit.
- [x] 3.4 Add lease lifecycle tests for success, provider error, cancellation during wait and in-flight call, TTL expiry, heartbeat loss, release failure, and restart recovery.

## 4. Govern every model call

- [x] 4.1 Inject the governed wrapper into the central LLM/VLM and contextual constructors and prove each call acquires/releases a provider lease independently.
- [x] 4.2 Adapt direct query pipeline calls for rewrite, rerank, citation repair, and image/VLM work, including the DashScope rerank path, to use profile-backed governed adapters.
- [x] 4.3 Adapt agent summary, agentic fallback, legacy KB callbacks, autorepair, workflow execution, and upload/background model tasks; reject ungoverned fallback calls when no usable profile is available.
- [ ] 4.4 Add inventory-driven contract tests for all listed entry points, sequential/multiple calls in one SSE request, release on exception/cancel, and absence of a governor lease spanning the full SSE lifecycle.

## 5. Retry and circuit policy

- [x] 5.1 Implement pre-first-token retry classification for 429/408/409/timeouts/confirmed 503 with total-attempt bounds, legal bounded `Retry-After` parsing, jittered exponential backoff, and no retry for auth/parameter/other 4xx or local errors.
- [ ] 5.2 Ensure every retry reacquires a provider lease, releases before sleeping, stops on caller cancellation, and never retries after the first streamed token; cover string and async-iterator provider return types.
- [x] 5.3 Implement fingerprint-scoped durable circuit closed/open/half-open transitions, cooldown, failure classification, and a single cross-instance probe; return sanitized busy/unavailable outcomes while open.
- [ ] 5.4 Add deterministic fake-clock tests for retry delays, attempt exhaustion, Retry-After malformed/negative/oversized values, stream-start boundaries, cancellation, circuit transitions, and two-instance half-open fencing.

## 6. Metrics and redaction

- [ ] 6.1 Add low-cardinality provider metrics for active calls, queue wait, queue/rejection/cancellation/timeout outcomes, success/429/timeout/5xx, retry counts/reasons, circuit state, call duration, and first-token duration with documented units and allowlisted labels.
- [ ] 6.2 Add usage reservation/settlement bookkeeping only when upstream usage is returned; keep RPM/TPM unenforced for unknown/missing usage and roll back reservations on failure/cancel.
- [ ] 6.3 Add metric/log redaction tests and scrape assertions proving no query, answer, token, key, raw endpoint, user/KB/trace identifier, unbounded fingerprint, or raw exception label; verify disabled/idempotent setup and multi-instance aggregation.

## 7. Code-level verification

- [x] 7.1 Run focused provider, migration, wrapper, retry, circuit, redaction, and compatibility tests with the repository `.venv` Python; add py_compile/import checks for all changed modules.
- [x] 7.2 Run OpenSpec strict validation and diff/summary checks; review the final call-entry inventory and confirm no public governance fields or secrets are introduced.
- [x] 7.3 Update `PROJECT_SUMMARY.md` as the coordinator-owned closeout with implementation facts, test evidence, and explicit unverified boundaries; do not include credentials, user data, or runtime artifacts.

## 8. Isolated real-Qwen acceptance

- [x] 8.1 Extend the existing manifest-owned isolated capacity runner for an optional real-Qwen provider mode, preserving disposable App/PostgreSQL/Redis/Nginx resources, 50 synthetic users, isolated KB/agents, restricted-key injection, controlled profile fingerprint, and quota evidence gates before enabling RPM/TPM.
- [ ] 8.2 Run the strict `10 -> 20 -> 30 -> 40 -> 50` real-Qwen ladder through the project runner with fresh resources per rung, complete SSE ordering/terminal checks, TTFT P95 <= 5 seconds, full-answer P95 <= 15 seconds, stable queue age, no unexpected provider errors/retries, and app/PG/resource health gates.
- [ ] 8.3 After each rung collect ten-minute recovery with exactly 120 healthy five-second samples, verify no OOM/restarts/pool wait growth, and clean only manifest-owned temporary resources; stop on the first hard failure.
- [ ] 8.4 Classify a stopped rung as application queue, Qwen quota/429/timeout, retrieval, database, or resource failure and report the result as profile/quota/topology-specific evidence; do not deploy or raise production limits from this acceptance.
