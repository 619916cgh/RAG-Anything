## Context

The agent route creates an HTTP SSE response but waits for `acquire_query_kb()` before its first yield. A cold shared core can be delayed by initialization or embedding dependencies. The browser fetch succeeds and then waits indefinitely for `reader.read()`. In the observed timeout path, a `ContextVar` token reset raised during finalization and masked the already-prepared terminal stream error.

## Goals / Non-Goals

**Goals:**

- Give an authenticated caller prompt, content-free confirmation that a query was accepted.
- Keep a healthy pending stream observable without exposing internal model, storage, or document information.
- Bound browser waiting for an initial event and later event silence.
- Preserve manual cancellation and existing `token`, `thinking`, `error`, and `done` event contracts.
- Ensure cleanup failures are logged but cannot replace a terminal SSE error.

**Non-Goals:**

- Changing model, embedding, retrieval budgets, authorization, or retrying the query automatically.
- Cancelling a detached shared query-core initialization that another request can reuse.
- Changing refresh-token or session-generation behavior.

## Decisions

### Additive lifecycle events

The generator will yield `accepted` before slow query-core acquisition, then `heartbeat` at a bounded interval while that acquisition remains pending. Both events contain only lifecycle metadata. This provides feedback without leaking query content or internal dependency state. Reusing a `thinking` payload was rejected because it would blur transport lifecycle and user-facing reasoning.

### Poll acquisition within the existing deadline

The route will wait for the core in short intervals up to the current retrieval deadline, yielding heartbeats between intervals. On deadline expiry it detaches the shared acquisition task with its exception consumed, matching the current non-cancelling behavior. This is preferred to a second independent initialization because it preserves core-cache coordination.

### Fail-open cleanup, fail-closed response

Each context reset and resource release is isolated in finalization. A cleanup exception is recorded server-side but must not override an already-yielded terminal `error` event. This directly addresses the zero-body incident while retaining ordinary cleanup.

### Shared client deadlines

`streamSSE` owns a first-event deadline and an idle deadline because all current stream consumers share it. It aborts its internal request controller and raises a distinct timeout error; an external caller abort remains an `AbortError`. The chat page maps that timeout to a completed, retryable assistant message. The server heartbeat prevents normal long initialization from being misclassified as idle.

## Risks / Trade-offs

- [A slow but progressing provider exceeds the client deadline] -> Server heartbeats reset the idle timer and deadlines are configurable constants with focused tests.
- [A shared core initialization outlives a timed-out request] -> Preserve the current detached-task exception consumption so a later request can reuse a completed core.
- [New events affect older clients] -> Events are additive and ignored safely by clients that do not recognize them.
- [Finalization hides a resource issue] -> Log cleanup failures with the trace identifier but never request content or credentials.

## Migration Plan

No data migration is needed. Release the source-only change through the existing fast-release gate. Roll back by redeploying the prior committed image if health checks or focused acceptance fail; no database or volume rollback is involved.

## Open Questions

None. The production trace supplies the reproduction contract and the public event names remain additive.
