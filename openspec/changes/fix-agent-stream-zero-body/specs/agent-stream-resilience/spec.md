## ADDED Requirements

### Requirement: Agent stream announces acceptance before core acquisition
The authenticated agent streaming endpoint SHALL emit an additive `accepted` SSE event before waiting for a query core. The event MUST not contain query text, document content, model configuration, local paths, or credentials.

#### Scenario: Cold query-core acquisition
- **WHEN** an authorized query waits for query-core acquisition
- **THEN** the client receives an `accepted` event before the acquisition completes

### Requirement: Pending agent streams remain observable
The endpoint SHALL emit additive `heartbeat` SSE events at a bounded interval while query-core acquisition is pending and the request deadline has not elapsed.

#### Scenario: Slow core initialization
- **WHEN** query-core acquisition exceeds one heartbeat interval but remains within the retrieval deadline
- **THEN** the client receives one or more `heartbeat` events before the next business event

### Requirement: Terminal agent-stream errors survive cleanup failures
The endpoint SHALL emit a terminal `error` SSE event for a retrieval deadline failure. Finalization failures MUST be logged without replacing that terminal event or converting the response to an empty successful body.

#### Scenario: Context cleanup fails after a retrieval timeout
- **WHEN** retrieval reaches its deadline and a context reset raises during finalization
- **THEN** the client receives the terminal `error` event and the cleanup failure does not replace it
