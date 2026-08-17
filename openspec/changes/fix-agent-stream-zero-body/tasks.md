## 1. Stream Lifecycle

- [x] 1.1 Emit additive accepted and heartbeat events before and during slow query-core acquisition without changing the retrieval deadline or authorization flow.
- [x] 1.2 Isolate stream finalization failures so a retrieval timeout retains its terminal SSE error and detached core work remains safely observed.

## 2. Browser Recovery

- [x] 2.1 Add shared first-event and idle SSE deadlines with distinct timeout codes while preserving caller abort and refresh-retry behavior.
- [x] 2.2 Render accepted lifecycle feedback and complete timed-out assistant placeholders as retryable errors.

## 3. Verification and Release

- [x] 3.1 Add focused backend and frontend regression tests for cold-core progress, timeout cleanup, first-event timeout, idle timeout, terminal events, and caller cancellation.
- [x] 3.2 Run focused tests, compilation, frontend build, OpenSpec strict validation, and scoped diff checks.
- [ ] 3.3 Update the project summary, create a scoped commit, deploy the full commit through the fast-release gate, and perform read-only host acceptance.
