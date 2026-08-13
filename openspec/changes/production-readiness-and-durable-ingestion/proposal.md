## Why

The application already has a migration runner, asynchronous ingestion, RBAC, and deployment resources, but a successful local test or HTTP response does not prove that a document is searchable after a real PostgreSQL-backed Worker run. Previous incidents have left parsed text with no durable vectors, while the release workflow lacks one operator-runnable, isolated acceptance procedure that proves migration and ingestion outcomes together.

## What Changes

- Add a fail-closed ingestion readiness contract: a new upload is terminally successful only after its required text and vector retrieval artifacts are durably available; incomplete artifacts become a structured recoverable failure rather than a successful task.
- Add an authorized knowledge-base health scan and repair queue for detecting and retrying documents with zero vectors, missing retrieval artifacts, or failed prerequisite processing, with audit records and stable reason codes.
- Add a reusable isolated pre-production acceptance runner that verifies backup acknowledgement, fresh/upgrade/repeat/failure migration behavior, container health, authenticated five-role authorization, and document upload-to-retrieval readiness without exposing secrets or source content.
- Add an evidence format that distinguishes local tests, container smoke, isolated PostgreSQL/Worker acceptance, and production authorization. The runner must not apply migrations to, upload documents to, or otherwise mutate a production target.
- Provide a release-candidate inventory procedure for mapping dirty working-tree paths to active OpenSpec changes and flagging files without an owner; it reports only and never stages, reverts, or commits user changes.

## Capabilities

### New Capabilities
- `ingestion-readiness-gate`: Durable, retrieval-aware success criteria and recoverable failure classification for upload tasks.
- `knowledge-base-health-repair`: RBAC-protected inspection and repair queuing for unhealthy knowledge-base documents.
- `isolated-release-acceptance`: A non-production acceptance runner and evidence contract for release candidates.
- `release-candidate-inventory`: Read-only ownership and release-boundary inventory for a dirty workspace.

### Modified Capabilities
- `upload-failure-detection`: Upload completion must enforce the new retrieval-readiness outcome rather than accepting parse/chunk completion alone.
- `background-task-lifecycle`: Background processing failures that prevent retrieval readiness must be reflected in the durable task result.
- `kb-access-control`: Health inspection and repair actions require backend-enforced knowledge-base scope and role permissions.

## Impact

Affected systems include the upload Worker and task-state services, document health/readiness logic, knowledge and admin routers, PostgreSQL migration/release scripts, focused backend tests, and the operator release runbook. The change adds no production migration by default, does not alter historical documents automatically, and deliberately excludes Redis/WebSocket multi-instance redesign, new parser rollout, and unrelated active OpenSpec changes.
