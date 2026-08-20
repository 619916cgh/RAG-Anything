## ADDED Requirements

### Requirement: Isolated query CPU attribution
The performance harness SHALL collect a bounded CPU profile only from the manifest-owned application process in a disposable isolated run. The evidence SHALL identify the exact image ID, process, collection interval, tool result, and correlation timestamps, and SHALL exclude production containers, files, data, credentials, model endpoints, and arbitrary host processes.

#### Scenario: Profile a retrieval-ready isolated stage
- **WHEN** a retrieval-ready isolated query stage enters its configured profile window
- **THEN** the harness SHALL store redacted app-only profile evidence in the run directory and associate it with request and resource sample timestamps

#### Scenario: Profiling tool is unavailable
- **WHEN** the approved app-only profiler cannot be invoked within its bounded timeout
- **THEN** the harness SHALL record a distinct unavailable result and SHALL not claim hotspot attribution or capacity improvement from that stage

### Requirement: Evidence-backed query-path optimization
The system SHALL change query-path behavior only after isolated profile evidence identifies a repeatable avoidable cost and focused tests preserve authorization, SSE ordering, retrieval, session persistence, and metrics behavior.

#### Scenario: Candidate hotspot is unconfirmed
- **WHEN** the profile does not consistently attribute sustained CPU to an avoidable application operation
- **THEN** the system SHALL retain existing behavior and report the current capacity boundary without a speculative optimization

#### Scenario: Confirmed optimization retains protected stream semantics
- **WHEN** an optimized authenticated stream emits protected events
- **THEN** authorization invalidation, `accepted` handling, event ordering, terminal cleanup, persistence, and query timing metrics SHALL retain their established behavior

### Requirement: Sanitized SSE failure attribution
Before changing a query-path implementation in response to an isolated stream failure, the harness SHALL record only an allowlisted, content-free per-request event trace. The trace SHALL contain an anonymous virtual-user number, attempt number, request start/end timestamps, bounded event-type sequence with an explicit truncation flag, terminal kind, timing fields, thread-reuse relation, and an error phase derived only from event order. It SHALL NOT retain SSE payload values, error text, query text, answer text, credential, thread identifier, or exception string, except a test-image-only fixed error code from the explicit allowlist `query_core_acquire`, `pre_agent_info_setup`, and `unknown`.

#### Scenario: An application error event is observed
- **WHEN** an isolated stream emits an SSE `error` event
- **THEN** the harness SHALL classify it by its content-free phase relative to `agent_info`, `retrieval`, and the first `token`, and SHALL retain the complete bounded allowlisted event order for correlation with app-profile and resource timestamps

#### Scenario: The stream is rejected during session revalidation
- **WHEN** the protected stream ends because session revalidation prevents a later protected event
- **THEN** the harness SHALL classify the result as an unterminated stream rather than an application `error` event, and SHALL not weaken the per-event fail-closed authorization behavior

#### Scenario: Unexpected event or payload content is received
- **WHEN** an isolated stream contains an unknown event type or any error payload content
- **THEN** the trace SHALL replace the event type with a fixed `other` value and SHALL discard all payload values other than the explicit test-image-only fixed error-code allowlist

#### Scenario: Test image preflight fails
- **WHEN** the immutable test image cannot compile, import, or expose the expected test-only control route under the performance environment
- **THEN** the harness SHALL stop before Compose startup, record only `image_preflight_failed`, and SHALL not create isolated database, identity, or query resources

### Requirement: Comparable capacity remeasurement
The harness SHALL remeasure five and ten virtual-user query stages with profiling disabled for acceptance, using the same isolated image, two CPU/three GiB app limit, fixture/readiness gate, mock timing, loopback Nginx path, and stop conditions as the recorded baseline.

#### Scenario: Ten-user stage clears CPU gate
- **WHEN** the remeasured ten-user stage completes without three consecutive app CPU samples above 85 percent and without another stop condition
- **THEN** the report SHALL record the comparison and MAY execute the next configured stage under the same stop control

#### Scenario: Ten-user stage remains saturated
- **WHEN** the remeasured ten-user stage again crosses a resource or error stop condition
- **THEN** the harness SHALL stop escalation, collect recovery evidence, and report the observed boundary without asserting higher concurrency capacity

#### Scenario: User-authorized diagnostic stage after a CPU gate
- **WHEN** the ten-user stage has a documented CPU-gate breach, at least 60 seconds of recovery evidence, and explicit user authorization for a diagnostic stage
- **THEN** the harness MAY run one bounded 20-user isolated stage using a recorded 170-percent CPU threshold for three samples and a 190-percent single-sample emergency threshold, while retaining the 80-percent RSS, error, OOM, restart, and production-health stops; it SHALL collect recovery evidence and label all output diagnostic-only without asserting ten- or twenty-user capacity

#### Scenario: User-authorized diagnostic ladder
- **WHEN** explicit user authorization names the `30 -> 40 -> 50` diagnostic ladder after documented prior recovery
- **THEN** the harness SHALL use fresh isolated runs for only those exact VU stages, require retrieval readiness with non-empty sources and healthy fixed production probes before every rung, run each rung for at most 90 seconds with five-second samples, collect at least 60 seconds of recovery, and label every result diagnostic-only without asserting capacity

#### Scenario: Ladder hard stop
- **WHEN** a ladder rung has any non-successful query, 170-percent sustained CPU, 190-percent emergency CPU, RSS, OOM, restart, ownership, host-resource, or production-health breach
- **THEN** the harness SHALL stop that rung, collect recovery evidence, remove only its manifest-owned resources, and SHALL NOT start a later rung

### Requirement: Production isolation during optimization measurement
The optimization measurement SHALL not modify or read production application configuration, credentials, database, volumes, uploads, indexes, model endpoints, or runtime processes. It SHALL retain only the pre-approved read-only production container health/restart and loopback health probes.

#### Scenario: Attempted out-of-scope profile target
- **WHEN** a profile target is not a manifest-owned isolated application container
- **THEN** the harness SHALL refuse the operation and leave that target untouched

#### Scenario: Authorized diagnostic escalation
- **WHEN** a user authorizes the diagnostic stage after a CPU gate
- **THEN** the authorization SHALL NOT expand production reads, writes, profiling, configuration access, or resource ownership beyond the existing isolated-run boundary
