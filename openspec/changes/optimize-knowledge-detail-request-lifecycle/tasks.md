## 1. Shared Request Cancellation

- [x] 1.1 Extend the shared detail-request registry with reference-counted consumers and an internal abort controller.
- [x] 1.2 Propagate caller signals through `loadKnowledgeDetailSnapshot`, document-summary fetches, and statistics fetches.
- [x] 1.3 Ensure aborted, failed, stale-generation, and invalidated responses are removed or excluded from cache commits.

## 2. Backend Read Path

- [x] 2.1 Remove unconditional global terminal-task cleanup from the paginated document-summary read route while preserving legacy full-list behavior.
- [x] 2.2 Add instrumentation or seam-level assertions proving authorization precedes task, document, tag-health, and statistics reads.

## 3. Regression Coverage

- [x] 3.1 Add frontend tests for signal propagation, one-consumer abort, all-consumer abort, no cache poisoning, and cache invalidation races.
- [x] 3.2 Add backend tests proving ordinary page reads do not clean terminal tasks and unauthorized requests perform no data reads.
- [x] 3.3 Run focused frontend/backend tests, strict OpenSpec validation, diff checks, and the production frontend build.

## 4. Release Evidence

- [x] 4.1 Record measured request counts, cancellation behavior, and page-bounded rendering evidence.
- [x] 4.2 Update `PROJECT_SUMMARY.md` with verified facts, remaining deployment/browser boundaries, and this task's conclusion.
