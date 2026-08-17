## Context

The existing chunk endpoint uses a cached KB core but still hydrates all document status rows, reads every chunk in the target document, and enriches every DTO before returning it. The React page then filters and slices that complete result. PostgreSQL is the production authority; JSON storage remains a compatibility fallback. The existing full endpoint is public API surface and has callers that require its current response shape.

## Goals / Non-Goals

**Goals:**
- Bound the first chunk-page read to at most 100 chunk DTOs and their associated tag/video lookups.
- Preserve the current search and tag-filter semantics, stable chunk ordering, authentication, and no-parameter full response.
- Report low-cardinality phase timing and response bytes without exposing KB, document, or content values in metrics.

**Non-Goals:**
- Redis, document-level cache versions, cache invalidation, schema/index migrations, or changes to chunk mutation permissions.
- A performance guarantee for legacy JSON storage or the existing no-parameter full-read mode.

## Decisions

1. **Explicit opt-in pagination.** The existing endpoint remains a byte-compatible full response when no page, page-size, query, or tag filter is supplied. Any pagination/filter parameter enables paged mode; unspecified page values default to page 1 and 25 rows, with an upper bound of 100.

2. **Native PostgreSQL page query.** A repository query will use one shared filtered predicate for page rows, count, and token sum, ordered by `chunk_order_index, id`. It restricts by workspace and full document ID, then applies `LIMIT/OFFSET`. PostgreSQL failures remain failures; only non-PG/legacy storage can use a correctness-preserving in-memory fallback.

3. **Direct document-status resolution.** Exact document IDs use `_load_doc_status_by_id`. A bounded PG prefix resolver retains the current unique-short-ID behavior; missing and ambiguous IDs continue returning 404. The normal full-ID path must not hydrate the KB's complete status catalog.

4. **Unchanged filter semantics.** Query matching remains case-insensitive containment across content, chunk ID, modal entity name, original type, and page index. Metadata-derived matches are calculated from the resolved document status and merged with the persisted-content predicate. A tag filter uses the same assignment predicate for rows and aggregates. The filtered `total` and `total_tokens` are separate from `document_total` and `document_total_tokens` used by the page header.

5. **Page-bounded enrichment and frontend lifecycle.** Tags and video metadata are fetched only for returned rows. The frontend owns query/page state, debounces the query, aborts superseded requests, resets to page 1 for a new filter or page size, and reloads after mutations rather than editing an assumed-complete local array. If a response makes the requested page invalid, the frontend requests the returned last valid page.

6. **Endpoint observability.** The route records total and named phases for core acquisition, document status, chunk query, tag enrichment, video enrichment, serialization, and response size. Metric labels are fixed bounded names and outcome only.

## Risks / Trade-offs

- [Metadata filtering needs data not stored in the chunk table] -> derive it from the single document status and preserve the existing filter fields.
- [Offset pages can move during a concurrent mutation] -> use stable ordering, return accurate metadata, and make the frontend reload after a successful mutation.
- [Legacy integrations expect full responses] -> retain the no-parameter route behavior and test it separately.
- [A backend paged query may hide a storage failure as empty data] -> restrict fallback to non-PG storage and propagate PG errors.

## Migration Plan

1. Release the compatible endpoint and frontend together with no migration.
2. Observe paged-route duration and response size; compare with the existing full mode only in controlled tests.
3. Roll back by reverting application/frontend source. No data, cache, or migration rollback is required.

## Open Questions

- Redis remains intentionally deferred until page-level production metrics demonstrate a remaining hot-read bottleneck.
