## ADDED Requirements

### Requirement: Authorized users can inspect document retrieval health
The system SHALL return a deterministic health summary only for a knowledge base that the caller may read. The result SHALL use stable reason codes: `missing_text_chunks`, `missing_vectors`, `invalid_chunk_content`, `retrieval_store_unavailable`, and `prerequisite_failed`.

#### Scenario: Read-scoped health scan
- **WHEN** an authorized user scans a readable knowledge base
- **THEN** the response contains only that knowledge base's document health rows and aggregate counts

#### Scenario: Unreadable knowledge base
- **WHEN** a caller scans a knowledge base outside their read scope
- **THEN** the request SHALL be rejected without revealing document identifiers, filenames, or reason counts

### Requirement: Repair queueing is operate-scoped and idempotent
The system SHALL require `kb:write` and KB operate scope to enqueue a retrieval repair. Repeated requests for the same KB, document, and repair stage SHALL reuse one durable job and SHALL not reset an active job.

#### Scenario: Authorized repair request
- **WHEN** an operate-authorized user requests repair for a detected unhealthy document
- **THEN** the system queues or reuses one repair job and records a bounded reason code

#### Scenario: Read-only grant
- **WHEN** a read-only member requests repair
- **THEN** the request SHALL be rejected by backend authorization even if a client displays a control
