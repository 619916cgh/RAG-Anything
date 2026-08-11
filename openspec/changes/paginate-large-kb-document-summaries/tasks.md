## 1. Server-side summary contract

- [x] 1.1 Add a PostgreSQL-backed document-summary page loader with normalized display-name deduplication, search, stable ordering, exact totals, and JSON compatibility fallback.
- [x] 1.2 Add the authorized paginated summary route and page-bounded runtime-task, upload-status, health, and tag enrichment while preserving legacy row fields.
- [x] 1.3 Preserve the legacy full-list endpoint and cover new route validation, compatibility, task merge, and page-only tag-health behavior.

## 2. Detail-page data flow

- [x] 2.1 Add auth-scoped page caching and document-summary API client helpers with KB-wide invalidation.
- [x] 2.2 Migrate the knowledge-detail document tab to debounced server-side search, cancellable page requests, server metadata, page clamping, and cross-page selection.
- [x] 2.3 Add frontend cache, URL, stale-request, pagination, mutation, and selection regression tests.

## 3. Verification and project records

- [x] 3.1 Run focused backend/frontend tests, static checks, and production build; record the limits of any unavailable PostgreSQL or browser acceptance environment.
- [x] 3.2 Benchmark a warmed 10,000-document PostgreSQL page when the local environment is available, enforce the 1-second P95 gate, and inspect the query plan before considering indexes.
- [x] 3.3 Update `PROJECT_SUMMARY.md` with the implemented behavior, validation evidence, and any remaining deployment acceptance boundary.
