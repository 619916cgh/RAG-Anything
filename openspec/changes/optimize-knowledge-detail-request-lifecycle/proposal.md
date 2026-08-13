## Why

The knowledge-base detail page now avoids stale result commits, but an aborted search or page navigation only cancels the caller's wait. The underlying shared HTTP requests can continue consuming browser connections and backend work, especially when users type quickly or switch pages repeatedly.

## What Changes

- Propagate request cancellation through document-summary and statistics fetches.
- Add reference-aware shared-request cancellation so one aborted consumer cannot cancel a request still needed by another consumer.
- Keep cache commits generation- and invalidation-safe, including aborted and failed requests.
- Avoid unconditional global terminal-task cleanup on every paginated detail-page read while preserving legacy full-list behavior.
- Add focused frontend and backend regression tests plus request-count/cancellation instrumentation.

## Capabilities

### New Capabilities
- `knowledge-detail-request-lifecycle`: Detail-page reads cancel obsolete work without canceling surviving consumers or corrupting scoped caches.

### Modified Capabilities
- `knowledge-base-document-summary-pagination`: Preserve paginated response and authorization behavior while bounding obsolete-request work.

## Impact

- Frontend: `frontend/src/utils/api.js`, `frontend/src/utils/knowledgeDetailCache.js`, and detail-page request lifecycle.
- Backend: `raganything/routers/knowledge.py` task cleanup/read path.
- Tests: frontend cache/API tests and document-summary route tests.
- No schema migration, public endpoint removal, or persisted-data format change.
