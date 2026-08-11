## ADDED Requirements

### Requirement: Authorized paginated document summaries
The system SHALL expose `GET /api/knowledge/document-summaries` for a knowledge base authorized by the same object-level read dependency as the legacy document list. The endpoint SHALL accept a one-based `page`, `page_size` from 1 through 100, and an optional `q` no longer than 200 characters.

#### Scenario: Authorized reader requests a page
- **WHEN** a user with access to a knowledge base requests page 2 with `page_size=50`
- **THEN** the response SHALL contain at most 50 document rows and the exact post-filter total
- **AND** the response SHALL include `page`, `page_size`, `total_pages`, `has_next`, `has_prev`, and normalized `q`

#### Scenario: Unauthorized request is rejected before data reads
- **WHEN** a user without access requests document summaries for a knowledge base
- **THEN** the endpoint SHALL return 403 before loading document status, upload task, or tag-health data

#### Scenario: Invalid pagination or query is rejected
- **WHEN** a caller provides an invalid page, page size, or query longer than 200 characters
- **THEN** the endpoint SHALL return validation error 422

### Requirement: Server-side complete document search and ordering
The paginated endpoint SHALL apply case-insensitive containment matching against normalized display filenames before calculating the total and slicing the page. It SHALL sort results by update time descending with full document ID ascending as the deterministic tie-breaker.

#### Scenario: Search matches a document outside the first unfiltered page
- **WHEN** a matching document would not occur on the first unfiltered page
- **THEN** a first-page query containing its filename fragment SHALL return that document

#### Scenario: Display-name duplicates and missing paths remain safe
- **WHEN** multiple status rows share a normalized non-empty filename
- **THEN** only the latest row SHALL be included in the paginated result
- **AND** rows without a filename SHALL remain distinct by document ID

### Requirement: Page-bounded enrichment
The paginated endpoint SHALL preserve the legacy document row fields for returned rows and SHALL calculate tag health and durable upload-task overlays only for task or document IDs represented by the selected page.

#### Scenario: Large result set returns one enriched page
- **WHEN** a knowledge base contains 1,000 matching document summaries and page size is 10
- **THEN** the endpoint SHALL serialize no more than 10 document rows
- **AND** tag health SHALL be requested only for persisted documents in that page

### Requirement: Legacy full-list compatibility
The system SHALL preserve the behavior and response shape of `GET /api/knowledge/documents`; pagination and search parameters SHALL be implemented only on the new summary endpoint.

#### Scenario: Existing caller uses legacy document list
- **WHEN** a caller requests the legacy document-list endpoint
- **THEN** it SHALL receive the existing full-list `{documents, total}` contract
