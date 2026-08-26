## ADDED Requirements

### Requirement: Stage 3 isolated readiness rehearsal
The deployment workflow SHALL provide a fixed Stage 3 rehearsal for a disposable non-production candidate that proves its completed backup/restore, migration, health, authorization, Worker retrieval, rollback, and cleanup stages with sanitized evidence. This rehearsal SHALL NOT deploy, migrate, back up, restore, or modify production resources.

#### Scenario: Isolated rehearsal evidence is complete
- **WHEN** the Stage 3 coordinator reports success
- **THEN** its evidence SHALL identify the immutable candidate by hash and state the deferred production, real-provider, browser, and other unexecuted acceptance boundaries
