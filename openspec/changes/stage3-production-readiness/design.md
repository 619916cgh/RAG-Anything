## Context

`scripts/run_isolated_acceptance.py` already owns a disposable local Compose profile, while `scripts/ops/release_ops.py` provides secret-safe backup, verification, restore, and aggregate validation. Neither establishes a single identity-bound recovery and rollback rehearsal with bounded ordinary-environment repair. The repository worktree is concurrently dirty, so the coordinator must never use it as a candidate.

## Goals / Non-Goals

**Goals:**
- Provide one fixed stage registry for a clean detached, immutable non-production candidate.
- Fail closed before mutation for target, image, backup/restore, secret/data-integrity, and rollback gates.
- Record only sanitized, aggregate evidence and tear down only owned disposable resources.

**Non-Goals:**
- Production deployment, production migration, production backup/restore, production data operations, real-provider acceptance, or replacement of the established fast-release workflow.

## Decisions

- The Stage 3 CLI is a new coordinator rather than an extension of the generic command runner. It invokes a fixed set of Python functions and the existing isolated acceptance driver; callers cannot provide shell commands.
- Preflight accepts a candidate checkout, full SHA, app image, expected image digest, target identifier, isolated database name, and temporary working directory. It requires loopback-local Docker and computes evidence-safe hashes rather than storing names, paths, DSNs, or secrets.
- A per-stage retry wrapper accepts only ordinary classified failures and stops after a default of two attempts or ten minutes total repair time. It exposes strict lower-only CLI limits. Safety classifications are terminal.
- The recovery rehearsal calls `release_ops` only with generated fixture config, a disposable PostgreSQL target, and a fake runner in unit tests. The complete Docker rehearsal uses the existing acceptance driver and records its result as one fixed stage.
- Isolated rollback means teardown and verification of only the generated Compose project and restoration of an explicitly created disposable snapshot. It never invokes `deploy.ps1`, remote-release, Docker pruning, or an unlabelled resource removal.

## Risks / Trade-offs

- [Docker or fixture availability can block a full rehearsal] -> classify the failure, use the finite repair budget, and preserve `environment_blocked` evidence rather than weakening a required stage.
- [Backup tooling requires PostgreSQL client credentials] -> unit-test it with injected runners and reserve real backup/restore for the isolated Compose fixture only.
- [Evidence itself can leak values] -> recursively sanitize all strings before writing and test nested payloads.
- [A shared dirty worktree can be mistaken for a candidate] -> require a separate clean detached candidate checkout before the driver is invoked.

## Migration Plan

1. Add the OpenSpec contract, coordinator, tests, and documentation.
2. Validate focused tests and strict OpenSpec checks.
3. Create or select a clean detached candidate with a revision-labelled image, then run the fixed disposable rehearsal.
4. On any safety failure, keep the sanitized evidence and stop. On ordinary environment failures, retry only within the configured budget. No production rollback exists in this change.

## Open Questions

- None. A missing local candidate image or fixture is an `environment_blocked` rehearsal outcome, not permission to use a production target.
