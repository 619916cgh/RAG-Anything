## MODIFIED Requirements

### Requirement: API returns document chunks detail

The system SHALL provide an API endpoint `GET /api/knowledge/documents/{doc_id}/chunks` that returns all chunks for a given document, sorted by `chunk_order_index` in ascending order when the caller supplies no pagination or filter parameter. Each chunk in the response SHALL include `chunk_id`, `content`, `tokens`, `chunk_order_index`, `file_path`, `is_multimodal`, `original_type`, `page_idx`, `media_path`, and `media_url`. The endpoint SHALL require authentication and SHALL return 404 if the document does not exist.

#### Scenario: Successful legacy chunks retrieval
- **WHEN** an authenticated user requests `GET /api/knowledge/documents/doc-abc/chunks` without pagination or filter parameters
- **AND** the document has 15 chunks in `doc_status.chunks_list`
- **THEN** the system returns the existing full JSON response containing 15 chunk objects sorted by `chunk_order_index`

#### Scenario: Document not found
- **WHEN** an authenticated user requests chunks for a non-existent document ID
- **THEN** the system returns HTTP 404

#### Scenario: Chunk ID in list but data missing
- **WHEN** a chunk ID in `chunks_list` does not exist in `text_chunks` storage
- **THEN** the system skips that chunk and returns the remaining chunks without error

### Requirement: Text filter for chunk search

The system SHALL provide a text input at the top of the chunk list that filters chunks by content, chunk ID, modal entity name, original type, or page index, using case-insensitive containment. The page SHALL request filters from the server and show the returned filtered count separately from the document-wide count.

#### Scenario: Filter chunks by keyword
- **WHEN** user types "发动机" in the filter input
- **THEN** the page requests the filtered first page and displays only matching chunks with the exact filtered total

#### Scenario: Clear filter
- **WHEN** user clears the filter input
- **THEN** the page requests the unfiltered first page and displays the document-wide chunk count

#### Scenario: Empty filter result
- **WHEN** the filter text matches no chunks
- **THEN** the page displays an empty state message "没有匹配的切块"
