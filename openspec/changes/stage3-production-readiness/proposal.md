## Why

The existing isolated acceptance driver validates migrations, application health, roles, and Worker retrieval, but it does not bind all candidate identities, exercise backup recovery, rehearse isolated rollback, or bound ordinary environment repairs. Stage 3 makes those checks one fail-closed, operator-runnable rehearsal without authorizing production actions.

## What Changes

- Add a fixed, non-production-only Stage 3 readiness coordinator and schema-versioned sanitized evidence manifest.
- Bind an isolated target, clean detached candidate, Compose configuration, and service image revisions/digests before starting disposable resources.
- Rehearse backup verification, isolated restore, semantic aggregate validation, and disposable rollback alongside the existing Compose acceptance profile.
- Add a finite repair budget for allowlisted dependency, fixture, launcher, Compose, browser, and network failures; safety failures never retry.
- Document the rehearsal boundary and update the project summary with the recorded result.

## Capabilities

### New Capabilities
- `stage3-production-readiness`: Fixed isolated readiness orchestration, safety gates, repair budget, recovery rehearsal, rollback rehearsal, and sanitized evidence.

### Modified Capabilities
- `platform-deployment-and-ops`: Add the Stage 3 isolated rehearsal requirement and explicitly exclude it from production deployment, migration, and data operations.

## Impact

Affected systems are the acceptance scripts, release backup helpers, disposable Compose fixtures, focused operational tests, OpenSpec artifacts, and project status documentation. The change adds no production migration, external provider call, persistent production backup, deployment, or production data operation.
