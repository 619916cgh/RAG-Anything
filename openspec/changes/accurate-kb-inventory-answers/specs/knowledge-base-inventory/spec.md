## ADDED Requirements

### Requirement: Authorized callers can retrieve knowledge-base inventory
The system SHALL provide `GET /knowledge/inventory` for a knowledge base authorized by the existing KB access dependency. The response SHALL contain aggregate counts only and SHALL not disclose document names, local paths, or document content.

#### Scenario: Inventory contains type and state aggregates
- **WHEN** an authorized caller requests inventory for a knowledge base containing completed, in-progress, tag-pending, and failed documents of multiple file types
- **THEN** the response includes the total plus per-type counts for retrievable, content-processing, tag-processing, and failed documents

#### Scenario: Unauthorized knowledge base remains hidden
- **WHEN** a caller requests inventory for a knowledge base they cannot read
- **THEN** the endpoint applies the existing KB access behavior and returns no inventory data

### Requirement: Inventory distinguishes retrieval readiness from enrichment
The inventory SHALL count a document with durable content and chunks as retrievable even when automatic tagging is pending, running, or retrying. It SHALL report that enrichment state separately.

#### Scenario: Tags are pending after content persistence
- **WHEN** a completed document has `content_ready=true` and an unfinished tag job
- **THEN** it is counted as retrievable and tag-processing, not as content-processing

#### Scenario: Content ingestion is unfinished
- **WHEN** a document has not persisted retrievable content
- **THEN** it is counted as content-processing or failed according to its durable task/document state and is not counted as retrievable
