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

Provide seven commands that return success only when their isolated checks pass: four migration commands (fresh, upgrade, repeat, intentional-failure), five-role authenticated API, Worker upload-to-retrieval, and cleanup. The runner records stage outcome and bounded failure classification but not command lines or output.

```powershell
.venv\Scripts\python.exe scripts\run_isolated_release_acceptance.py `
  --non-production --target-id staging-20260812 `
  --working-dir D:\raganything-staging-acceptance `
  --repo-root C:\Users\98014\知元 `
  --health-url http://127.0.0.1:8000/api/health `
  --stage-command "migration-fresh=.venv\Scripts\python.exe tests\test_pg_migration_fresh_integration.py" `
  --stage-command "migration-upgrade=.venv\Scripts\python.exe tests\test_pg_migration_upgrade_integration.py" `
  --stage-command "migration-repeat=.venv\Scripts\python.exe tests\test_pg_migration_repeat_integration.py" `
  --stage-command "migration-failure=.venv\Scripts\python.exe tests\test_pg_migration_failure_integration.py" `
  --stage-command "roles=.venv\Scripts\python.exe tests\test_pg_authenticated_api_integration.py" `
  --stage-command "worker=.venv\Scripts\python.exe scripts\kb_regression_suite.py" `
  --cleanup-command ".venv\Scripts\python.exe scripts\cleanup_acceptance_namespace.py" `
  --evidence D:\raganything-staging-acceptance\evidence.json
```

`--working-dir` identifies only the isolated target and must include an isolation marker. `--repo-root` is the reviewed source checkout containing the migration manifest and is the directory used to execute the supplied checks. The runner executes migration, health, five-role, and Worker checks in order; after any required stage fails, later stages are recorded as skipped. It always executes the explicit cleanup command last; cleanup failure also makes the evidence not releasable.

The `migration-failure` command must prove that an intentional failure prevents later migrations from running. The Worker command must use a disposable KB and prove that a new upload has non-empty valid chunks, complete PostgreSQL vector coverage, and a retrievable result. A zero-vector document, partial vector coverage, storage outage, cancellation race, or stale claim must fail the stage.

## Evidence Boundary

`isolated-preproduction-pass` establishes only the completed isolated stages. External model providers, video E2E, browser UAT, and production approval remain deferred unless independently evidenced. A failed, skipped, missing, or unsafe stage always writes `not-releasable` evidence.

Production migration still requires the verified backup, `status` and `plan` preflight, manual approval, and the rollback rules in `docs/postgresql-migration-release-runbook.md`.
