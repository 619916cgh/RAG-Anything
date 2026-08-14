## ADDED Requirements

### Requirement: Commit-only release staging
The fast release command SHALL require a full 40-character Git commit SHA and construct its release payload with `git archive` from that exact revision rather than from the caller's working tree. The payload MUST exclude environment files and persistent runtime directories. The command SHALL record the commit SHA, payload SHA-256, configured runtime-base image ID, and resulting app and Nginx image IDs in a sanitized release manifest.

#### Scenario: Dirty local workspace
- **WHEN** uncommitted changes exist locally and a full commit SHA is supplied
- **THEN** the release payload contains only files from the requested commit.

### Requirement: Fast release eligibility gate
The fast release command MUST reject candidates that modify a Dockerfile, dependency manifest or lockfile, Node runtime or frontend lockfile, operating-system package input, parser-model manifest, Compose or runtime configuration, migration or migration manifest, or release tooling relative to the configured runtime-base revision. The rejection MUST identify the disallowed changed paths and MUST not contact the production switch routine.

#### Scenario: Migration changes are included
- **WHEN** a requested commit changes a file under `migrations/` or the migration manifest
- **THEN** the fast release exits before upload and reports that a controlled migration release is required.

### Requirement: Capacity and concurrency protection
Before uploading or building, the remote release routine SHALL acquire a host-local exclusive lock, reject an active build or release, and verify a configured minimum free-space threshold. It MUST fail closed without invoking automatic cleanup and MUST NOT modify volumes, `.env`, uploads, indexes, outputs, model caches, or non-release services.

#### Scenario: Another release holds the lock
- **WHEN** another release owns the host release lock
- **THEN** the command exits before upload or container replacement and identifies the lock conflict.

### Requirement: Verified rollout and rollback
The remote release routine SHALL verify the uploaded payload checksum, perform an application import smoke test, preserve immutable references to the active app and Nginx images, switch only app before Nginx using `--no-deps --no-build --force-recreate`, and require direct and reverse-proxy HTTP 200 plus zero app restarts through the configured stability window. It MUST restore the preserved images and verify their health when a required post-switch check fails. The routine MUST NOT invoke `migrate`, set `MIGRATION_BACKUP_ACKNOWLEDGED`, or prune images.

#### Scenario: Candidate import fails
- **WHEN** the candidate application import smoke test fails
- **THEN** no running application or Nginx container is replaced.

#### Scenario: App health fails after switch
- **WHEN** the candidate app fails the direct health check after replacement
- **THEN** the routine restores the preserved app and Nginx images and reports the failed health evidence.
