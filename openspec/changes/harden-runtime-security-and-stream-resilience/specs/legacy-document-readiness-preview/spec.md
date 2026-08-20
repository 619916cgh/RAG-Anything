## ADDED Requirements

### Requirement: Legacy readiness candidates can be inspected without mutation
The system SHALL provide an authorized, read-only preview of legacy documents missing `content_ready`. A candidate SHALL be included only when it is terminal, has matching authoritative persisted chunk evidence, passes strict PostgreSQL readiness evaluation, and has no failure evidence.

#### Scenario: Verified legacy document
- **WHEN** an authorized caller previews a KB containing a completed legacy document with verified chunks and readiness
- **THEN** the preview returns its stable document ID and reason code without changing metadata or queuing repair

#### Scenario: Incomplete or failed legacy document
- **WHEN** a record has missing chunks, non-terminal status, or failure evidence
- **THEN** the preview excludes it and reports the applicable aggregate exclusion reason

#### Scenario: Caller lacks KB scope
- **WHEN** an unauthorized caller requests a KB preview
- **THEN** the endpoint rejects the request without revealing candidate data
