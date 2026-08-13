## MODIFIED Requirements

### Requirement: Authorized paginated document summaries
The system SHALL expose `GET /api/knowledge/document-summaries` for an authorized knowledge base. It SHALL preserve the existing pagination, normalized query, exact totals, row fields, and authorization behavior while allowing obsolete detail-page reads to be cancelled without triggering unrelated global task cleanup.

#### Scenario: Authorized reader requests a page
- **WHEN** a user with access to a knowledge base requests a page
- **THEN** the response SHALL contain the requested bounded page and exact pagination metadata
- **AND** the read path SHALL not perform global terminal-task cleanup

#### Scenario: Unauthorized request is rejected before data reads
- **WHEN** a user without access requests document summaries for a knowledge base
- **THEN** the endpoint SHALL return 403 before loading document status, upload task, or tag-health data

#### Scenario: Invalid pagination or query is rejected
- **WHEN** a caller provides an invalid page, page size, or query longer than 200 characters
- **THEN** the endpoint SHALL return validation error 422
