## 1. Profiling and attribution

- [x] 1.1 Add manifest-owned, bounded app-process CPU profiling to the isolated cloud runner with redacted correlation metadata and refusal of non-owned targets.
- [x] 1.2 Add focused tests for profiling ownership, timeout/unavailable reporting, and sanitized evidence handling.
- [x] 1.3 Run a retrieval-ready isolated profile stage and identify the sustained ten-user CPU hotspot from profile, request, resource, and database observations. (The profile did not confirm an avoidable app-code CPU hotspot; see the sanitized report.)
- [x] 1.4 Add content-free, bounded SSE event-order and failure-phase attribution to the isolated workload without modifying query behavior or authorization semantics.
- [x] 1.5 Run a fresh isolated 30-user attribution stage with the new trace and bounded app profile; classify the observed non-success result before considering a repair.
- [x] 1.6 Add immutable test-image py_compile/import/route preflight and explicitly gated fixed SSE phase-code attribution for isolated diagnosis only.

## 2. Confirmed query-path optimization

- [x] 2.1 Implement only the profile-confirmed minimal optimization without changing production resource limits, worker count, rate limits, or authorization scope.
- [x] 2.2 Add focused regression tests for the optimized behavior, including protected SSE events, authorization invalidation, session persistence, event ordering, and query timing metrics.

## 3. Verification and comparison

- [x] 3.1 Run focused test, compilation, diff, and OpenSpec validation for owned changes.
- [x] 3.2 Build or select the immutable isolated test image and remeasure comparable five- and ten-user stages with profiling disabled.
- [x] 3.3 Escalate only when the ten-user stage passes the unchanged stop rules; otherwise collect recovery evidence and record the current boundary.
- [x] 3.4 Run the user-authorized 20-user isolated diagnostic stage after a documented ten-user CPU gate and recovery. Use only the recorded 170%/three-sample and 190% emergency CPU policy, preserve all other hard stops, collect recovery evidence, perform owned cleanup, and report a diagnostic-only conclusion.
- [x] 3.5 Add explicit `30 -> 40 -> 50` ladder authorization, manifest allow-list, and error/ownership hard-stop coverage without changing standard capacity gates.
- [x] 3.6 Run fresh 30, 40, and 50-user diagnostic rungs sequentially. Require readiness, prior recovery, and healthy production probes before every rung; stop the ladder on any hard stop. (30-user rung completed; 40/50 were correctly blocked by the unchanged ten-user standard gate.)

## 4. Evidence handoff

- [x] 4.1 Write a sanitized comparison report that distinguishes hotspot attribution, code-level checks, isolated runtime measurements, and unverified production/real-model conclusions.
- [x] 4.3 Append the authorized diagnostic-stage evidence and its non-capacity conclusion to the sanitized report.
- [x] 4.4 Append sanitized per-rung ladder evidence, recovery, cleanup, and the non-capacity conclusion to the report.
- [x] 4.2 Update PROJECT_SUMMARY.md with the final measured boundary and verification scope without sensitive values or generated runtime data.
