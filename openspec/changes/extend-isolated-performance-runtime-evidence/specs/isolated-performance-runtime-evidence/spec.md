## ADDED Requirements

### Requirement: Isolated low-resource runtime profile
The performance harness SHALL provide a standalone Compose profile for direct
mock query evidence. The profile MUST not load repository `.env`, attach to
existing databases or volumes, publish non-loopback ports, use fixed container
names, or include Marker, Nginx, or an upload Worker in the direct query
phase. It MUST set documented CPU/memory/log limits for every long-running
container and record them in a redacted run manifest.

#### Scenario: Safe profile configuration
- **WHEN** the generated run environment is rendered with Docker Compose
- **THEN** it contains only the isolated services, generated inputs, labelled
  volumes, and loopback ports required for that run

#### Scenario: Unsafe host or context is rejected
- **WHEN** the host free-resource floor, Docker context, port binding, or
  requested low-resource concurrency violates the profile policy
- **THEN** the runner MUST refuse to start containers and write a redacted
  preflight failure under the temporary run directory

### Requirement: Run-owned workload bootstrap and evidence manifest
The harness SHALL generate a collision-resistant run ID and a temporary run
directory beneath the operating-system temporary directory. It MUST provision
run-specific identities, KB, agent, and fixture through the isolated API,
configure text and visual embeddings exclusively against the mock provider,
and validate provider preflight before query load. Credentials, raw IDs, and
raw evidence MUST remain in the temporary run directory; published reports and
metrics labels MUST be redacted.

#### Scenario: Bootstrap succeeds without external provider configuration
- **WHEN** a fresh isolated profile is started with mock provider settings
- **THEN** bootstrap creates its run-specific workload, observes mock model and
  embedding traffic, and leaves no dependency on repository configuration

#### Scenario: Bootstrap preflight fails
- **WHEN** model discovery or either embedding profile cannot use the mock
- **THEN** the harness MUST stop before load and classify the run as bootstrap
  failure without falling back to another endpoint

### Requirement: Authoritative SSE measurements
The query driver SHALL create exactly one logical outcome for each attempted
SSE query. It MUST start timing before request connection, distinguish TTFB
from TTFT, define TTFT as request start through first non-empty token, and
measure complete duration from request start through stream termination. It
MUST persist redacted per-attempt observations containing status, event
milestones, token count, duration, and bounded error classification, from
which the report derives P50/P95/P99.

#### Scenario: Complete stream measurement
- **WHEN** the isolated agent emits accepted, token, and done events
- **THEN** the driver records the ordered events, one successful outcome, TTFT
  at the first token, and full wall time independent of server `done.elapsed`

#### Scenario: Incomplete or failed stream measurement
- **WHEN** a query has an HTTP failure, timeout, SSE error, malformed event, or
  EOF before done
- **THEN** the driver records exactly one failed outcome with its error class
  and MUST NOT emit a second custom statistic for the same attempt

### Requirement: Bounded resource and recovery evidence
The harness SHALL sample Docker container CPU, memory, disk/network counters,
restart counts, PostgreSQL connection/activity/lock state, Redis statistics,
queue state, and metrics snapshots where available. It MUST identify an
unavailable collection operation explicitly. A restart, health loss, resource
limit breach, or configured consecutive error threshold MUST stop the active
phase, trigger a 60-second recovery sample, and prevent any higher load phase.

#### Scenario: Stop threshold is reached
- **WHEN** a sampled stop threshold is reached during a low-resource phase
- **THEN** the runner stops new requests, records the threshold and sampled
  values, completes recovery sampling, and marks the phase failed

#### Scenario: Query phase completes
- **WHEN** the direct query phase finishes below stop thresholds
- **THEN** the runner records container/resource and metrics snapshots before
  and after the recovery interval without representing the result as capacity
  acceptance

### Requirement: Upload terminal-state diagnostic gate
The harness SHALL require a unique-content text upload diagnostic before it
reports upload throughput or Worker stability. It MUST track HTTP acceptance,
task/document reference, Worker claim, provider preflight, chunk/index signal,
terminal state, timeout, and distinct failure categories. Only the
implementation-defined retrieval-ready terminal state SHALL count as success.
The duplicate check SHALL upload the identical content only in the same
isolated KB and MUST not change product duplicate-document behavior.

#### Scenario: Unique upload reaches a retrieval-ready terminal state
- **WHEN** a generated fixture completes all upload stages in the isolated
  profile
- **THEN** the diagnostic records a successful terminal state and allows a
  later bounded upload phase to be considered

#### Scenario: Upload does not become retrieval-ready
- **WHEN** the upload is accepted but reaches a failed, stalled, duplicate, or
  unknown terminal state
- **THEN** the harness reports the classified terminal evidence and blocks
  upload throughput and Worker capacity conclusions

### Requirement: Scoped cleanup and layered report
The runner SHALL delete only containers, networks, volumes, and temporary
files recorded in its manifest and still bearing the exact run's Compose
project label. It MUST leave existing Docker resources, local databases,
repository files, `.env`, real models, and production systems untouched. The
published report MUST separately label code/contract tests, low-resource mock
runtime, query load, upload/Worker, Nginx, real provider, and production as
passed, failed, unexecuted, or not applicable.

#### Scenario: Cleanup of completed run
- **WHEN** a run reaches cleanup
- **THEN** the runner verifies manifest ownership and project labels before
  removing only its own resources and records any skipped resource as evidence

#### Scenario: Real provider is not configured
- **WHEN** no separate approved temporary provider credentials and budget are
  supplied
- **THEN** the report marks real-provider and production conclusions
  unexecuted and contains no external endpoint or credential value
