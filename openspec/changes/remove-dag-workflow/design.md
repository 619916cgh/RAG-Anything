## Context

The DAG workflow feature has a dedicated React editor, FastAPI endpoints, a WebSocket channel, a Python execution engine, workflow-specific permissions, and two PostgreSQL tables. Migration `006_workflow_manufacturing_pg.sql` also owns unrelated AutoRepair schema and is part of the recorded migration checksum history, so it cannot be changed.

## Goals / Non-Goals

**Goals:**
- Remove all supported DAG workflow entry points and implementation dependencies.
- Delete persisted workflow records with a forward, transaction-safe migration.
- Remove the corresponding runtime permissions from both new and existing roles.
- Leave no executable frontend, backend, test, reset, performance, or current-specification workflow surface.

**Non-Goals:**
- Do not alter GitHub Actions or generic document-processing workflow terminology.
- Do not rewrite historical migration files or archived OpenSpec/audit artifacts.
- Do not deploy or apply the migration to a non-disposable database in this change.

## Decisions

- Add migration `037_remove_dag_workflow.sql` after the concurrently owned `036_provider_governance.sql` manifest entry. It will remove workflow permissions from JSONB role projections, then drop `workflow_runs` before `workflow_definitions`. This preserves migration history while making the removal irreversible in upgraded databases.
- Remove endpoints instead of returning a compatibility response. FastAPI's ordinary route absence returns 404 and avoids preserving a deprecated authorization surface.
- Delete `@xyflow/react` only after removing every consumer and regenerate its lockfile through npm, rather than manually pruning transitive lock entries.
- Treat archival migrations and archived OpenSpec records as immutable evidence. All mutable product documentation and current specs will be corrected to remove claims that the capability exists.

## Risks / Trade-offs

- [Persisted workflow records are irreversibly deleted] → Require the existing migration backup acknowledgement for any production apply; test only with disposable PostgreSQL.
- [Shared dirty migration manifest] → Preserve the existing `036` entry and append only `037` after rereading the current file immediately before editing.
- [Deleting broad router code can affect unrelated admin endpoints] → Use focused route-absence and remaining-admin-route tests plus static import checks.
- [Generated frontend metadata can drift] → Regenerate tracked bundle statistics only through the existing frontend build path, never hand edit it.

## Migration Plan

1. Deploy code that removes the workflow feature together with migration `037`.
2. Before applying to a persistent database, verify a recoverable backup and set the existing runner acknowledgement.
3. Apply the manifest once; the transaction strips stored role permissions and drops workflow records/tables atomically.
4. Re-running the migration runner is a no-op. Rollback requires restoring the verified database backup; there is no in-place data rollback.

## Open Questions

None. The approved scope specifies direct endpoint removal and irreversible data deletion.
