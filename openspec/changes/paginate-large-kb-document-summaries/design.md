## Context

`GET /knowledge/documents` materializes every document-status summary, calculates every document's tag health, and returns the complete result. `KnowledgeDetailPage` then filters and paginates that array in memory. PostgreSQL-backed document status storage already contains lightweight list fields, but LightRAG's pagination helper cannot apply this application's display-name deduplication, full-library filename search, or runtime-task merge rules.

## Goals / Non-Goals

**Goals:**
- Make the detail page transfer, parse, and render only one document page.
- Preserve the row shape, object-level authorization, deduplication rules, and legacy full-list endpoint.
- Make full-library filename search server-side and cancel stale client requests.
- Meet P95 <= 1 second for an already-warm 10,000-document PostgreSQL dataset with a 50-row page.

**Non-Goals:**
- Changing graph loading, arbitrary document sorting, bulk server-side selection, or legacy JSON storage into a large-scale datastore.
- Adding a potentially blocking production index migration without a measured query plan.

## Decisions

- Add `/knowledge/document-summaries` instead of extending `/knowledge/documents`. Unknown query parameters on the legacy endpoint have no paging behavior today, so changing it could break callers.
- Use one application-owned, parameterized PostgreSQL CTE. It normalizes the final path component and staged prefix, chooses the latest row for each non-empty display name, preserves empty names by ID, filters `q`, counts the post-dedup set, and applies `updated_at DESC NULLS LAST, id ASC` before `LIMIT/OFFSET`.
- Merge the bounded in-memory task set in the same candidate pipeline. Persisted document rows win over same-name synthetic rows; runtime data overlays phase/status on the returned persisted rows. Upload status is looked up in one batch for selected task IDs only.
- Calculate document tag health after the page is selected. This removes the per-document tag aggregation from the full-list read path without weakening its row contract.
- Use an independent document-page cache keyed by auth generation, KB, page, page size, and normalized query. Statistics remain KB-keyed; KB mutations invalidate both cache families.
- Retain the JSON summary fallback for legacy storage. It remains functional but is explicitly outside the 10,000-document performance contract.

## Risks / Trade-offs

- [Exact totals and display-name deduplication still require a database scan] -> keep serialization, tag aggregation, and browser work page-bounded; measure the real plan before introducing an index.
- [Rows can change between page requests while uploads complete] -> stable secondary sort, server totals on every response, and client page clamping provide eventual consistency without claiming snapshot isolation.
- [Changing page data can clear cross-page selections] -> retain selected IDs independently of loaded page rows; rely on existing backend write authorization and ID validation.
- [Runtime tasks differ by process] -> retain current local-process visibility semantics and do not invent cross-worker task aggregation in this change.

## Migration Plan

1. Deploy the additive endpoint and frontend client together while keeping the legacy endpoint live.
2. Run focused tests, a real PostgreSQL 10,000-row benchmark, and browser interaction regression before enabling release acceptance.
3. Roll back by returning the frontend detail loader to the legacy endpoint; no schema migration or persisted data change is introduced.
