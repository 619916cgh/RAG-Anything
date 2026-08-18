## ADDED Requirements

### Requirement: Disposable performance environment
The system SHALL provide a Compose-defined performance environment that does
not read the repository `.env`, does not use fixed production container names,
and uses separate network, volumes, credentials, storage paths and host port.

#### Scenario: Isolated stack starts
- **WHEN** an operator starts a generated performance run
- **THEN** its application uses only the run-specific database, Redis, storage
  and mock-provider endpoints

### Requirement: Deterministic mock model provider
The system SHALL provide OpenAI-compatible model, embedding and streaming chat
responses whose delays, token count and injected failure mode are configured
only by the test environment.

#### Scenario: Streamed mock query
- **WHEN** the application requests a streaming chat completion
- **THEN** the mock returns deterministic SSE chunks after the configured first-token delay

### Requirement: Safe workload evidence
The system SHALL record query and upload load-test evidence outside the source
tree, with a run identifier and without credentials, prompts, answers or raw
provider configuration in the summary.

#### Scenario: Benchmark phase completes
- **WHEN** a benchmark phase finishes
- **THEN** its latency, error classification, resource samples and metrics
  snapshots are stored in the run artifact directory

### Requirement: End-to-end SSE measurement
The system SHALL measure query elapsed time from before the HTTP streaming
request is opened and SHALL emit exactly one Locust request result per query.

#### Scenario: Successful streamed query
- **WHEN** a query receives its terminal SSE event
- **THEN** TTFT, total elapsed time, token rate and one successful request
  statistic are recorded
