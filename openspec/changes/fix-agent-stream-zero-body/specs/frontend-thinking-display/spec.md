## ADDED Requirements

### Requirement: Bounded agent-stream feedback
The shared browser SSE client SHALL raise a distinct retryable timeout error when no data event arrives before the configured first-event deadline or when an active stream exceeds the configured idle deadline. A caller-initiated abort MUST remain distinguishable from a timeout.

#### Scenario: HTTP success without a first data event
- **WHEN** an agent SSE response remains open beyond the first-event deadline without a data event
- **THEN** the client aborts the request and reports a retryable timeout instead of waiting indefinitely

#### Scenario: Idle stream after acceptance
- **WHEN** an agent stream has emitted at least one data event but no later event arrives before the idle deadline
- **THEN** the client aborts the request and reports a retryable timeout

#### Scenario: User cancels an active query
- **WHEN** the caller aborts an agent stream before either deadline
- **THEN** the client reports cancellation and does not label the result as a timeout

### Requirement: Chat surface completes stalled assistant placeholders
The agent chat surface SHALL turn a stream timeout into a completed assistant message with a retryable error state and SHALL restore the send controls.

#### Scenario: First-event timeout in the chat page
- **WHEN** the shared stream client reports a first-event timeout
- **THEN** the placeholder assistant message is completed with a retryable error and the page no longer shows an active loading state
