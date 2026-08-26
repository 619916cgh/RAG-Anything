## ADDED Requirements

### Requirement: Stage 3 target and candidate gate
The system SHALL require an explicit non-production target, system temporary working directory, clean detached 40-character candidate revision, local Docker context, loopback-only disposable resources, and matching immutable candidate image identity before any Stage 3 resource is created.

#### Scenario: Unsafe target is supplied
- **WHEN** a target, database identifier, path, Docker context, checkout, revision, image revision, or image digest fails the gate
- **THEN** the coordinator SHALL write sanitized `not-releasable` evidence and SHALL not start the rehearsal

### Requirement: Fixed isolated rehearsal stages
The system SHALL run only a fixed registry consisting of candidate inventory, disposable resource preflight, backup verification and isolated restore validation, migrations, health, role/API and Worker retrieval acceptance, isolated rollback rehearsal, and owned-resource cleanup.

#### Scenario: Complete disposable rehearsal
- **WHEN** every fixed stage succeeds against a disposable target
- **THEN** the coordinator SHALL emit an isolated rehearsal pass without asserting production acceptance

### Requirement: Bounded ordinary failure repair
The system SHALL retry only dependency, fixture, launcher, Compose, browser, and network failure classifications within a finite per-stage attempt budget and total repair-time budget.

#### Scenario: Retryable startup failure recovers
- **WHEN** a Compose startup failure is classified as retryable and succeeds before the budget is exhausted
- **THEN** the evidence SHALL record every attempt and the final passed stage

#### Scenario: Safety failure occurs
- **WHEN** target identity, backup/restore, secret/data integrity, image identity, or rollback validation fails
- **THEN** the coordinator SHALL stop immediately without retrying that stage

### Requirement: Sanitized evidence and owned cleanup
The system SHALL write schema-versioned evidence containing only candidate and artifact hashes, aggregate target attestations, stage outcomes, attempts, durations, repair summaries, and cleanup status. It MUST exclude secrets, DSNs, source content, hostnames, private image references, usernames, and absolute paths.

#### Scenario: Nested failure is recorded
- **WHEN** a stage failure contains a secret or local path in nested detail
- **THEN** the persisted evidence SHALL replace the sensitive value with a stable redaction marker

#### Scenario: Rehearsal terminates
- **WHEN** the rehearsal succeeds or fails after owning disposable resources
- **THEN** the coordinator SHALL clean up only the run-owned resources and SHALL make cleanup failure non-releasable

### Requirement: Offline release qualification boundary
The release workflow SHALL only mark an offline bundle `offline-release-qualified`
after its immutable archives pass a read-only provenance verifier and two
independent archive-only candidate-to-rollback Compose health rehearsals pass.
The verifier SHALL distinguish OCI index descriptor digests from config blob
digests, reject unsafe archive members and unlisted files, and emit only stable
codes, checksums, and sanitized status.

#### Scenario: Offline rehearsal fixture is invalid
- **WHEN** a run-owned bootstrap fixture cannot start Candidate App or either
  clean-room health rehearsal fails
- **THEN** the release record SHALL be `not-qualified`, clean up only its
  manifest-owned resources, and SHALL NOT use locally pre-existing images as
  substitute evidence

### Requirement: Offline v2 provenance and supply-chain qualification
An offline v2 package SHALL preserve byte-identical image archives from its
immutable source package, separately bind Product Candidate, Rollback, and
Package tooling revisions, and retain only sanitized inventory and recovery
evidence. Qualification SHALL require a scanner and a verifiably current local
vulnerability database; scanner/database absence SHALL be recorded as
`scanner_database_unavailable` and SHALL remain not-qualified.

#### Scenario: Local CVE database is unavailable
- **WHEN** the offline scanner has no verifiably current local vulnerability database
- **THEN** the record SHALL retain the scanner and cache status, SHALL NOT claim a current scan, and SHALL remain `not-qualified`
