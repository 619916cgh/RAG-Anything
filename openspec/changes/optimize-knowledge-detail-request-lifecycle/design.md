## Context

The knowledge-base detail page already protects state from stale responses, but obsolete requests still consume browser connections and server work. The shared prefetch cache also needs cancellation semantics that distinguish one abandoned consumer from a request with no remaining consumers. The backend currently performs global terminal-task cleanup as part of every document-summary read, adding unrelated writes and contention to a read path.

## Goals / Non-Goals

**Goals:**
- Propagate abort signals through detail-page document and statistics requests.
- Cancel an underlying shared request only after its last consumer abandons it, without poisoning surviving consumers or caches.
- Keep cache keys, auth-generation checks, and invalidation behavior unchanged and race-safe.
- Remove unconditional global terminal-task cleanup from paginated detail reads without changing legacy full-list cleanup behavior.
- Preserve response contracts, authorization ordering, legacy endpoints, and JSON fallback behavior.

**Non-Goals:**
- No database schema or index migration.
- No change to document ordering, pagination semantics, task visibility, tag-health fields, or write authorization.
- No cancellation of unrelated graph, monitoring, upload-worker, or SSE requests.

## Decisions

1. **Reference-aware shared requests.** Each shared request owns one internal `AbortController` and a consumer count. `waitForSharedRequest` registers a consumer and returns a release function that is idempotent. An aborted consumer stops awaiting; when the count reaches zero while the request is pending, the internal controller aborts. A settled request releases bookkeeping without aborting completed work.
2. **Signal propagation at the snapshot boundary.** `loadKnowledgeDetailSnapshot` accepts an optional signal and passes it to both document-summary and stats `fetchJson` calls. `prefetchKnowledgeDetail` and page loaders pass their caller signal into the shared-request layer. This keeps cancellation scoped to one snapshot and prevents stale results from entering caches.
3. **Abort/error cache discipline.** Aborted or failed requests are removed from in-flight maps and never committed as cache values. Existing generation and invalidation tokens remain the final guard before a successful result is stored.
4. **Read-only task visibility.** The document-summary route no longer invokes global `cleanup_completed_tasks()` before reading. The legacy full-list endpoint retains its existing cleanup behavior; this change does not alter terminal-task retention policy.
5. **Bounded observability.** Add test instrumentation around fetch signals, shared-request aborts, and route cleanup invocation. No production logging of query contents or credentials is introduced.

## Risks / Trade-offs

- [A consumer can abandon a request just before another consumer subscribes] -> retain the existing in-flight entry through the current microtask turn and make release idempotent; a newly subscribed consumer gets the same promise or starts a fresh request after true cancellation.
- [Aggressive cancellation may increase refetches during rapid navigation] -> only abort when the final consumer releases, and keep successful page/stat caches independent.
- [Removing read-time cleanup may leave terminal runtime rows longer] -> retain the legacy full-list cleanup behavior and keep paginated runtime-task reads bounded by KB and row count.
- [Different fetch implementations may not support signals] -> pass the standard Fetch `signal` option and test the application wrapper rather than third-party internals.

## Migration Plan

1. Add the shared-request and signal changes, route read-path adjustment, and focused regression tests.
2. Run OpenSpec validation, frontend tests/build, backend focused tests, and request-count/cancellation instrumentation.
3. Deploy application and frontend together; monitor aborted-request rates, page latency, and task-table growth.
4. Roll back by reverting the application image/source overlay. No schema or persisted-data migration is required.

## Open Questions

- Confirm whether any non-detail caller relies on `cleanup_completed_tasks()` side effects from the summary endpoint; tests should establish that no such contract exists.
- Confirm production server image build can complete with the existing package mirror before attempting a live rollout.
