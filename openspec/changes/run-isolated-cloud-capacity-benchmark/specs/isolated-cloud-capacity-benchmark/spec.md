## ADDED Requirements

### Requirement: Isolated Linux capacity run ownership
The performance harness SHALL resolve an existing app reference to its immutable local image ID before creating a Linux-host run. It SHALL use a generated run ID, loopback-only listener bindings, a temporary run directory, generated credentials, and Compose resources that all carry the same run ownership label. It MUST NOT read production environment files, mount production volumes, mount mutable source into the tested app image, or call an external model endpoint.

#### Scenario: Safe run preflight
- **WHEN** a Linux capacity run is requested with an existing app image and sufficient configured host headroom
- **THEN** the harness SHALL record the image digest and generated ownership manifest before creating only labelled disposable resources

#### Scenario: Unsafe input rejection
- **WHEN** a run requests a non-loopback listener, missing image, production volume, source mount, or unsupported Docker context
- **THEN** the harness SHALL fail before starting a container

### Requirement: Bounded full-stack test profile
The harness SHALL provide a full-stack test profile containing mock-provider, PostgreSQL, Redis, migrate, app, Marker, and Nginx with independent disposable storage and explicit CPU, memory, PID, and bounded-log limits. Containers, volumes, and networks SHALL carry the run ownership label. Only Nginx MAY bind a loopback host port.

#### Scenario: Full-stack configuration rendering
- **WHEN** a full-stack run configuration is rendered
- **THEN** every service SHALL have the run ownership label and explicit bounded resources
- **AND** the app SHALL receive only internal mock text and visual model endpoints

### Requirement: Independent staged SSE workload evidence
The harness SHALL generate one disposable identity and session-capable workload per virtual user, seed a retrieval-ready fixture before the query matrix, and execute cold, hot, and staged `1`, `5`, `10`, `20`, `35`, and `50` virtual-user SSE measurements. It SHALL persist redacted request-level TTFB, TTFT, completion duration, JSON data-type event ordering, HTTP status class, retrieval evidence, and bounded error evidence. It SHALL separately report enforced source-address rate-limit behavior and an isolated test-stack application-capacity mode; it MUST NOT classify 429 as application saturation.

#### Scenario: Distinct virtual-user stage
- **WHEN** a query stage starts with N virtual users
- **THEN** the harness SHALL provide N distinct credentials and agents without exhausting a shared credential queue

#### Scenario: Session-capable query measurement
- **WHEN** a virtual user issues its first and subsequent queries
- **THEN** the workload SHALL create a session first and reuse its thread identifier for later requests

#### Scenario: Retrieval readiness failure
- **WHEN** a seeded fixture or its query retrieval evidence is not retrieval-ready
- **THEN** the harness SHALL skip the query capacity matrix and report the gate classification

### Requirement: Continuous stop-aware evidence collection
The harness SHALL collect five-second redacted samples for owned-service and load-generator resources, host memory/load/disk, PostgreSQL connections/activity/lock waits, Redis memory/commands, queue state/oldest age, and configured metrics snapshots while load is active. It SHALL stop new load on owned-service OOM/restart, RSS above 80 percent of a limit or CPU above 85 percent for three samples, 5xx/timeout rate above 1 percent, unexpected application-capacity 429, host available memory below 8 GiB, free disk below 20 GiB, queue age above 120 seconds, or production health regression, then collect a ten-minute recovery period.

#### Scenario: Threshold breach
- **WHEN** a configured stop condition is observed during a stage
- **THEN** the harness SHALL stop escalation, record the breached capacity boundary, and continue recovery sampling without starting the next stage

### Requirement: Upload readiness gate and separated matrix
The harness SHALL create unique text and PDF upload fixtures and SHALL record HTTP acceptance separately from task terminal state and retrieval readiness. It MUST NOT execute upload concurrency or soak measurements unless the unique text diagnostic reaches `retrieval_ready` and classifies the same-KB duplicate behavior.

#### Scenario: Upload diagnostic failure
- **WHEN** the text diagnostic terminates without retrieval-ready state
- **THEN** the harness SHALL emit the terminal classification and skip upload throughput conclusions

#### Scenario: Upload matrix eligibility
- **WHEN** the text diagnostic is retrieval-ready and duplicate classification is recorded
- **THEN** the harness SHALL run text and PDF concurrency stages separately and record queue age and Worker outcomes

### Requirement: Scoped cleanup and layered reporting
The harness SHALL record exact labelled container, volume, and network IDs in the ownership manifest and SHALL remove only resources that match the manifest ID, Compose project label, and run-id label. It SHALL remove generated credentials and the temporary run directory after copying the sanitized report outside it. The report SHALL distinguish tool tests, isolated mock runtime results, resource samples, and unmeasured real-model, production, browser, and multi-instance behavior.

#### Scenario: Run cleanup
- **WHEN** a completed or stopped run is cleaned up
- **THEN** the harness SHALL verify each target carries the recorded run label before removing it
- **AND** it SHALL preserve the sanitized summary outside the disposable run directory
