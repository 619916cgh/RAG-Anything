## Context

The repository already contains a fail-closed manifest migration runner, a reusable CI release gate, durable upload claims, `document_quality.evaluate_content_readiness()`, and an idempotent `document_repair_jobs` queue. These components are individually tested but do not currently produce one isolated Worker-to-retrieval evidence record. A dirty working tree also cannot be treated as one release candidate.

## Goals / Non-Goals

**Goals:**

- Make PostgreSQL-backed text/vector retrieval readiness the authoritative prerequisite for an upload task's `completed` result.
- Provide read-scoped health inspection and write-scoped, idempotent repair queueing without disclosing cross-KB document data.
- Provide a non-production acceptance command that composes existing migration, container, API, and Worker checks into sanitized evidence.
- Report release-candidate ownership without changing the worktree.

**Non-Goals:**

- Redis/WebSocket multi-instance transport, browser UAT automation, production migration execution, automatic rollback, real cloud-model repair, new parser rollout, and a health-dashboard UI.
- Treating graph, tag, or optional multimodal enrichment failure as a text/vector ingestion failure.

## Decisions

### PostgreSQL-strict readiness is the terminal upload authority

`evaluate_content_readiness()` gains an explicit strict mode. In strict mode it requires the PostgreSQL document status, non-empty valid text chunks, and complete vector coverage from the KB-bound vector table. Read failure, an unknown vector table, or an incomplete artifact becomes a stable recoverable readiness failure. JSON/NanoVectorDB remains a compatibility read path only outside strict production/pre-production verification.

The Worker invokes the evaluator once after durable background work drains and before publishing completion. The existing task claim/generation is still the fence: a stale Worker cannot overwrite cancellation, retry, or a newer terminal result. Graph/tag failures remain a document `degraded` condition and use the existing repair lifecycle.

### Repair queue reuses the existing durable job table

The existing `document_repair_jobs` unique `(kb_name, doc_id, stage)` contract is extended with stable readiness stages. A health scan builds content-free reason/count results from authoritative storage. A repair request requires the caller's normal `kb:write` permission plus KB `operate` scope; it enqueues or reuses one job and never deletes/rebuilds a whole KB automatically.

This avoids a schema migration unless existing durable fields prove insufficient. Historical migrations remain immutable.

### Acceptance is command-driven and isolated

The runner requires `--non-production`, an explicit isolated target identifier, and an isolated working directory. It writes a JSON evidence manifest containing revision, manifest checksum, stages, durations, assertion outcomes, and sanitized failure classes. Any failed or skipped required stage produces a non-release result. It reuses the migration runner and existing Compose/HTTP checks; external-provider, video, and browser profiles are separately marked not-run rather than claimed as accepted.

### Dirty-worktree inventory is read-only

The inventory reads Git status and active OpenSpec roots, classifies paths as owned/shared/unowned/generated-candidate, and reports coordination requirements. It never stages, commits, deletes, moves, checks out, or resets files. `PROJECT_SUMMARY.md`, migration manifests, lockfiles, and deployment resources are reported as shared serialized assets.

## Risks / Trade-offs

- [Readiness query adds a final database round trip] -> It runs once per task and prevents false success; bounded counts and sanitized details are recorded.
- [Legacy file-backed deployments cannot satisfy strict PG readiness] -> Strict mode is opt-in to pre-production/production and fails closed; compatibility mode remains explicit.
- [Repair cannot regenerate every root cause automatically] -> Queue only approved stages and preserve an operator-visible reason/error rather than deleting data.
- [Acceptance depends on environment credentials and model availability] -> Evidence distinguishes not-run/environment-blocked from pass; neither can yield a release recommendation.
- [Dirty workspace ownership may be ambiguous] -> Inventory reports ambiguity rather than inferring a commit boundary.

## Migration Plan

1. Add specs and focused unit/PG integration tests before changing completion behavior.
2. Deploy first to the isolated pre-production profile with strict readiness enabled and an empty, disposable KB.
3. Run fresh/upgrade/repeat/intentional-failure migration checks, then Worker-to-retrieval acceptance; preserve only sanitized evidence.
4. On readiness regressions, disable strict runtime enforcement, retain failed task evidence, and use the existing retry/repair paths. Do not edit migration history or apply anything to production without verified backup and manual approval.

## Open Questions

- None for the first implementation slice. Real-provider, video, and browser acceptance remain separately reported environment work.
