## ADDED Requirements

### Requirement: Interactive streams signal acceptance and bounded progress
The agent streaming endpoint SHALL emit an additive `accepted` event before query-core acquisition and SHALL emit additive `heartbeat` events while the stream remains active without a business event. Existing event schemas remain compatible.

#### Scenario: Slow query-core acquisition
- **WHEN** query-core acquisition exceeds a normal UI feedback interval
- **THEN** the client receives `accepted` followed by heartbeat events before the first retrieval event

### Requirement: Browser SSE consumers time out stalled streams
The shared SSE client SHALL abort with a distinct timeout error after 20 seconds without a first data event or 45 seconds without a subsequent data event, while preserving caller-initiated cancellation semantics.

#### Scenario: Stream accepts HTTP but emits no data
- **WHEN** an SSE response remains open for more than 20 seconds without a data event
- **THEN** the client aborts it and the chat surface marks the answer retryable

#### Scenario: Caller cancels an active stream
- **WHEN** the caller aborts its signal before a timeout
- **THEN** the client reports cancellation rather than a timeout
