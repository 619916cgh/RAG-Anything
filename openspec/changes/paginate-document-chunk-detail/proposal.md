## Why

Opening a document with hundreds of chunks currently loads, enriches, serializes, and transfers every chunk before the first page can render. The document-summary page is already paginated, but the document-chunk page remains a full-read path and can take more than ten seconds on large documents.

## What Changes

- Add an opt-in, server-paginated document-chunk read mode with exact filtered totals, stable ordering, search, and tag filtering.
- Make the chunk route load the requested document status directly and enrich only the current page of chunks.
- Update the chunk maintenance page to request and render server pages, including cancellation, page reset, and out-of-range recovery behavior.
- Add bounded, low-cardinality timing and response-size observability for the chunk read path.
- Preserve the existing no-pagination full-response contract for legacy callers.

## Capabilities

### New Capabilities
- `chunk-detail-pagination`: Authorized readers can load a bounded, filterable page of a document's chunks without fetching the complete document.

### Modified Capabilities
- `chunk-detail-view`: Preserve the legacy full chunk response while allowing the chunk detail UI to use the paginated read contract.

## Impact

- Backend route and persisted PostgreSQL chunk reader in `raganything/routers/knowledge.py` and `raganything/services/kb_chunk_repo.py`.
- Existing frontend API client and `DocumentChunksPage` state lifecycle.
- Backend and frontend regression coverage plus `PROJECT_SUMMARY.md`.
- No schema migration, Redis dependency, permission-model change, or deployment configuration change.
