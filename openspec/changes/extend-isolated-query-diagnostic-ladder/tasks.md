## 1. Profile B Runner Controls

- [x] 1.1 Add an explicit immutable Profile B configuration to the isolated runner and Compose layer: one app process, four CPU, six GiB, fixed mock inputs, loopback-only exposure, and a recorded image/runner identity.
- [x] 1.2 Add manifest validation for the ordered `1 -> 5 -> 10 -> 20 -> 30 -> 40 -> 50` allowlist, per-rung fresh ownership, predecessor evidence, and the 16 GiB memory/40 GiB disk host preflight.
- [x] 1.3 Implement quota-normalized CPU/RSS collection and hard-stop controls for the Profile B sustained/emergency thresholds, queue age, request/SSE failures, OOM/restart, ownership, host, and production-probe failures.

## 2. Evidence and Test Coverage

- [x] 2.1 Enforce complete bounded SSE terminal success, no retries, and Profile B TTFT/complete-response percentile limits in the workload summary without retaining payload content.
- [x] 2.2 Add the ten-minute recovery, triple-verified manifest-owned cleanup, and Profile A/Profile B-separated sanitized report classifications.
- [x] 2.3 Add focused unit and source-contract tests for Profile B limits, quota normalization, ordering/preflight gates, hard stops, recovery/cleanup, report separation, and production isolation.
- [x] 2.4 Diagnose repeatable 20 VU latency and redacted-trace evidence; correct preview-only protocol false positives and record the Profile B-only 2.1s/2.7s latency-gate basis.
- [x] 2.5 Separate query-gate exit status from recovery evidence, classify recovery failures with fixed sanitized categories, and fingerprint the fixed Profile B `MAX_ASYNC=4` configuration.

## 3. Isolated Rebaseline

- [x] 3.1 Run source-level tests, compilation, scoped diff checks, and OpenSpec strict validation for owned changes.
- [x] 3.2 On the approved isolated host, verify permitted production probes and Profile B host/image preflight, then execute fresh 1, 5, and 10 VU Profile B stages with recovery and cleanup evidence.
- [x] 3.2a Execute the explicitly authorized direct 50 VU Profile B diagnostic on a fresh isolated stack; retain all gates, record it as non-admissible diagnostic-only evidence, and do not advance the ordered ladder.
- [ ] 3.3 Execute fresh 20, 30, 40, and 50 VU Profile B stages strictly in order only while predecessor gates pass; record a hard-stop boundary and do not start later stages on failure.

## 4. Handoff

- [x] 4.1 Write the sanitized Profile B handoff, state its exact resource/mock boundary and all unverified environments, and update `PROJECT_SUMMARY.md` with the measured outcome.
