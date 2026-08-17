## Why

An agent query can exceed its retrieval deadline before emitting any SSE event. A generator-cleanup failure can then suppress the terminal error, leaving the browser with an empty assistant message and an indefinitely active request. The production incident returned HTTP 200 with a zero-byte body, so transport success alone is insufficient.

## What Changes

- Emit additive, content-free stream lifecycle events before slow query-core acquisition and while that acquisition is pending.
- Ensure terminal SSE errors survive cleanup failures, including cross-context `ContextVar` resets.
- Add bounded browser deadlines for waiting for the first SSE event and for later idle periods, while preserving caller cancellation and existing terminal events.
- Present a definite retryable error instead of leaving an empty assistant placeholder.
- Add focused backend and frontend regression coverage for the zero-body timeout path.

## Capabilities

### New Capabilities

- `agent-stream-resilience`: Bounded, observable agent SSE startup, progress, and terminal-error behavior.

### Modified Capabilities

- `frontend-thinking-display`: The chat view turns an SSE startup or idle timeout into a visible terminal message rather than a perpetual loading state.

## Impact

Affected code includes `raganything/routers/agent.py`, the stream-context selection helpers, `frontend/src/utils/api.js`, `frontend/src/pages/AgentChatPage.jsx`, focused backend/frontend tests, and this OpenSpec change. No database migration, uploaded document, Worker task, authentication policy, or API-breaking change is required.
