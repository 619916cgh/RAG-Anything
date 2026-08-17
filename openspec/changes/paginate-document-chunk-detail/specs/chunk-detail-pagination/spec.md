## ADDED Requirements

### Requirement: Authorized paginated chunk reads
The system SHALL allow an authorized reader to request a bounded page from `GET /api/knowledge/documents/{doc_id}/chunks` using `page`, `page_size`, optional `q`, and optional `tag_id`. Paged reads SHALL return stable `chunk_order_index, chunk_id` ordering, page-only `chunks`, `page`, `page_size`, `total`, `total_tokens`, `total_pages`, `has_next`, `document_total`, and `document_total_tokens`.

#### Scenario: First page of a large document
- **WHEN** an authorized reader requests page 1 with page size 25 for a 400-chunk document
- **THEN** the response contains no more than 25 chunk DTOs and exact document and filtered totals

#### Scenario: Paged filter matches visible chunk fields
- **WHEN** a reader supplies `q` that matches a chunk's content, ID, modal entity name, original type, or page index
- **THEN** the response includes that chunk in the filtered result and applies the same filter to rows and totals

#### Scenario: Paged tag filter
- **WHEN** a reader supplies a tag ID that is assigned to three chunks in the document
- **THEN** the response contains only those three chunks across its pages and reports a filtered total of three

#### Scenario: Invalid page arguments
- **WHEN** a reader supplies a page below 1 or a page size outside 1 through 100
- **THEN** the endpoint returns HTTP 422

### Requirement: Page-bounded authoritative work
For a PostgreSQL-backed knowledge base, a paged chunk read SHALL resolve the requested document directly and query only its requested page before loading tags and video metadata. A PostgreSQL query failure SHALL not be represented as an empty successful result.

#### Scenario: Large document page enrichment
- **WHEN** an authorized reader requests one page of a 400-chunk document
- **THEN** tag and video enrichment receive only that page's chunk IDs

#### Scenario: Full document ID
- **WHEN** an authorized reader supplies an exact document ID
- **THEN** the route does not hydrate the knowledge base's complete document-status catalog to resolve it

### Requirement: Chunk read observability
The system SHALL emit bounded metrics for paged chunk reads covering core acquisition, document-status resolution, chunk query, tag enrichment, video enrichment, serialization, response size, and total outcome.

#### Scenario: Paged request completes
- **WHEN** a paged chunk request succeeds or fails
- **THEN** the recorded measurements use only fixed phase and outcome labels and contain no KB name, document ID, or content
