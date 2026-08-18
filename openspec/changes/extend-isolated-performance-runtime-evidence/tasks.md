## 1. Isolated Runtime Contract

- [x] 1.1 Add explicit resource, logging, loopback, text/visual mock, and service-scope limits to the standalone low-resource Compose profile.
- [x] 1.2 Add a collision-resistant, manifest-backed runner preflight that rejects unsafe host/context/port/concurrency inputs and scopes cleanup to owned labels.
- [x] 1.3 Extend the deterministic provider with observable, redacted preflight evidence and bounded explicit fault injection.

## 2. Workload and Observation Tools

- [x] 2.1 Implement temporary run bootstrap for isolated administrator, KB, agent, test identity, and unique fixture creation without manual credential files.
- [x] 2.2 Refactor the query driver to write one redacted SSE outcome per attempt with TTFB, TTFT, complete duration, event ordering, and bounded errors.
- [x] 2.3 Extend the resource collector with structured container, PostgreSQL, Redis, metrics, queue-age, and unavailable-command observations.

## 3. Upload Terminal-State Gate

- [x] 3.1 Implement unique text upload diagnostic collection from HTTP acceptance through scoped terminal state and Worker evidence.
- [x] 3.2 Implement same-KB duplicate classification without changing application duplicate-document behavior.
- [x] 3.3 Block upload throughput conclusions when the retrieval-ready terminal-state gate does not pass.

## 4. Verification and Evidence

- [x] 4.1 Add focused tests for Compose isolation/limits, manifest ownership, bootstrap inputs, SSE timing/event outcomes, collector unavailable states, and upload terminal classification.
- [x] 4.2 Run static and focused tests plus Compose configuration validation using generated temporary inputs.
- [x] 4.3 Run one bounded direct-query/SSE low-resource mock execution, capture a recovery sample, and clean only manifest-owned resources.
- [x] 4.4 Run the upload terminal-state diagnostic only if host headroom remains safe; record its gate outcome without claiming upload throughput.
- [x] 4.5 Update PROJECT_SUMMARY.md and the redacted performance report with layered status, evidence, and explicit unexecuted boundaries.
