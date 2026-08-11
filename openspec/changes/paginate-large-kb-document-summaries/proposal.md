## Why

The knowledge-base detail page currently retrieves every document summary, computes tag health for every row, and then filters and paginates in the browser. This makes initial load, refresh, and filename search scale linearly with the total document count and becomes impractical for large knowledge bases.

## What Changes

- Add a paginated, server-side searchable document-summary API for knowledge-base detail views.
- Keep the existing full-list document API unchanged for compatibility with current callers.
- Query PostgreSQL summary data with server-side display-name normalization, duplicate handling, exact totals, stable ordering, and page slicing.
- Return only the page's tag health and upload-task overlays while preserving the existing document-row contract.
- Migrate the detail page to page-keyed document caching, debounced server-side search, cancellation of stale requests, and server-provided pagination metadata.

## Capabilities

### New Capabilities
- `knowledge-base-document-summary-pagination`: Authorized users can browse and search large knowledge-base document summaries without transferring the entire document list.

### Modified Capabilities
- `document-list-deduplication`: The displayed deduplicated document set gains a stable, paginated summary representation while preserving legacy full-list behavior.

## Impact

- Backend: `raganything/routers/knowledge.py`, `raganything/services/kb_service.py`, document-tag and upload-status lookups.
- Frontend: `frontend/src/utils/api.js`, document-detail cache, and `frontend/src/pages/KnowledgeDetailPage.jsx`.
- Tests: document list contracts, authorization matrix, frontend API/cache/page interactions, and PostgreSQL performance measurement.
