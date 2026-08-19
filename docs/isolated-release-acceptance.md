# Isolated Release Acceptance

This procedure is for a disposable staging/pre-production target only. It is not a production migration command and does not replace the PostgreSQL migration release runbook.

## Preconditions

1. Use an isolated database, working directory, containers, and test accounts.
2. Verify the staging backup according to the approved recovery procedure.
3. Do not pass secrets in commands, evidence, logs, or chat. Use the deployment secret mechanism.
4. Run the read-only candidate inventory first:

```powershell
.venv\Scripts\python.exe scripts\release_candidate_inventory.py --root .
```

Do not treat a dirty workspace as one release candidate. Shared assets require the coordinator to serialize their changes.

## Acceptance Command

Use the fixed disposable Compose driver. It creates a unique project, temporary credentials, a pgvector database, mock provider, app and loopback Nginx. It never reads the repository `.env` and always removes only its own Compose project and volumes.

```powershell
.venv\Scripts\python.exe scripts\run_isolated_acceptance.py `
  --non-production --target-id preprod-20260819 `
  --commit <40-character-full-SHA> `
  --working-dir "$env:TEMP\raganything-preprod-20260819"
```

Run this only from a clean detached worktree whose `HEAD` equals `--commit`. The driver records bounded stage outcomes and writes `evidence.json` beneath the temporary run directory. Missing images, migration failures, health failures, role failures, Worker failures, or cleanup failures produce `not-releasable`; no production target is accepted.

The `migration-failure` command must prove that an intentional failure prevents later migrations from running. The Worker command must use a disposable KB and prove that a new upload has non-empty valid chunks, complete PostgreSQL vector coverage, and a retrievable result. A zero-vector document, partial vector coverage, storage outage, cancellation race, or stale claim must fail the stage.

## Evidence Boundary

`isolated-preproduction-pass` establishes only the completed isolated stages. External model providers, video E2E, browser UAT, and production approval remain deferred unless independently evidenced. A failed, skipped, missing, or unsafe stage always writes `not-releasable` evidence.

Production migration still requires the verified backup, `status` and `plan` preflight, manual approval, and the rollback rules in `docs/postgresql-migration-release-runbook.md`.
