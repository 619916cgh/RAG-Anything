## 1. Backend Read Contract

- [x] 1.1 Add direct document-status resolution that preserves exact and unique-prefix document IDs without whole-KB hydration on the normal path.
- [x] 1.2 Add a PostgreSQL-native document-chunk page query with shared row/count/token predicates, stable ordering, legacy fallback, and no silent PG failure fallback.
- [x] 1.3 Extend the chunk route with compatible paged/filter parameters, page-bounded enrichment, and bounded phase/response metrics.

## 2. Frontend Lifecycle

- [x] 2.1 Extend the document-chunk API client with an opt-in paged request contract while retaining the no-parameter legacy URL.
- [x] 2.2 Convert the chunk maintenance page to server-backed pagination, debounced filtering, cancellation, page reset/clamping, and mutation-triggered reloads.

## 3. Verification And Documentation

- [x] 3.1 Add backend coverage for legacy compatibility, direct resolution, native page bounds, filters, totals, enrichment scope, errors, and metrics.
- [x] 3.2 Add frontend coverage for paged requests, filters, cancellation, page convergence, and mutation refresh behavior.
- [x] 3.3 Run focused tests, compilation/build/static checks, OpenSpec validation, and record the verified outcome in PROJECT_SUMMARY.md.
