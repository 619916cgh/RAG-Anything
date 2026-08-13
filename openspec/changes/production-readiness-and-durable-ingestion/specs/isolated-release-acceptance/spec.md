## ADDED Requirements

### Requirement: Isolated acceptance produces sanitized evidence
The system SHALL provide an operator command that runs only with an explicit non-production confirmation, isolated target identifier, and isolated working directory. It SHALL produce structured sanitized evidence for each stage and SHALL never include secrets, source content, raw DSNs, or absolute workspace paths.

#### Scenario: Isolated acceptance succeeds
- **WHEN** every required pre-production stage passes
- **THEN** the command writes evidence containing revision, migration-manifest checksum, stage outcomes, and durations with a non-production release recommendation

#### Scenario: Required stage fails or is skipped
- **WHEN** a required migration, health, authorization, or Worker readiness stage fails or is skipped
- **THEN** the command SHALL return failure and SHALL not emit a releasable recommendation

### Requirement: Acceptance rejects unsafe targets
The acceptance command SHALL reject a missing isolation confirmation, a non-isolated working directory, or a target identifier that matches production markers configured by the operator.

#### Scenario: Missing non-production confirmation
- **WHEN** an operator omits the explicit non-production flag
- **THEN** the command SHALL fail before invoking migrations, containers, or uploads
