## ADDED Requirements

### Requirement: Document status preserves retrieval readiness during tag enrichment
The document summary response and document-list UI SHALL distinguish content ingestion from automatic tag enrichment. A document with retrievable content and an unfinished tag job SHALL remain visibly retrievable while reporting its tag-processing state.

#### Scenario: Retrievable document waits for automatic tags
- **WHEN** a document has completed content processing but its tag job is pending, running, or retrying
- **THEN** its content status remains completed/retrievable and the UI displays a separate tag-processing indication

#### Scenario: Tag job terminally fails after retrieval succeeds
- **WHEN** a document has retrievable content and its automatic tag job terminally fails
- **THEN** its content remains retrievable and the UI reports the tag failure without presenting the whole document as content-ingestion failed
