## Why

Several independent production boundaries are currently incomplete: account hierarchy checks do not protect every target-account mutation, established WebSocket sessions do not retain revocation identity, and Worker, container, migration, and streaming lifecycles can leave unsafe or misleading states. These defects affect authorization, data integrity, availability, and user-visible recovery, so they require a coordinated but explicitly non-workflow change.

## What Changes

- Enforce target-account hierarchy in repository transactions for updates and archival operations, using the persisted actor identity rather than a router-provided role.
- Bind WebSocket session snapshots to token revocation identity and replace all-user task broadcasts with owner-directed, projected events; monitor events remain a separately authorized surface.
- Separate container liveness from readiness, remove the application host-port mapping, and terminate every upload Worker process group rather than just the immediate Python process.
- Make manifest migrations execute under a stable PostgreSQL advisory lock and write successful history atomically with migration SQL. Preserve immutable historical migration files through a validated runtime transaction wrapper.
- Add CORS PATCH support and bounded SSE first-event/idle handling with backward-compatible `accepted` and `heartbeat` events.
- Add a read-only, RBAC-protected preview for legacy document-readiness candidates. This change does not backfill historical data.
- Add deployable Prometheus scrape inventory and validation artifacts. Compacting the currently user-modified project summary is deliberately deferred to its owner.

## Capabilities

### New Capabilities
- `target-account-hierarchy`: Transactional protection of higher-privileged target accounts.
- `scoped-revocable-websocket-events`: Revocable WebSocket sessions and owner-scoped task event delivery.
- `worker-process-tree-recovery`: Cross-platform upload Worker process-group termination.
- `atomic-manifest-migrations`: Locked, transactional manifest migration execution and connection-option preservation.
- `interactive-stream-resilience`: Bounded SSE startup and idle behavior with compatible progress events.
- `legacy-document-readiness-preview`: Read-only evidence-based discovery of legacy readiness candidates.
- `prometheus-deployment-inventory`: Scrape ownership and deploy-time monitoring validation.

### Modified Capabilities
- `admin-user-crud`: User mutation and archival authorization honors the target account's current role.
- `auth-hardening`: Established WebSocket sessions must fail closed after token revocation.
- `background-task-lifecycle`: Cancellation, timeout, and deletion reclaim the Worker process tree before cleanup.
- `platform-deployment-and-ops`: Container liveness, readiness, and externally exposed ports have distinct contracts.

## Impact

Affected areas are the auth repository and router, WebSocket service and upload event emitters, upload Worker lifecycle, FastAPI CORS, agent streaming client/server, Docker and fast-release resources, PostgreSQL migration runner, Prometheus deployment resources, and focused backend/frontend/ops tests. No workflow file API, database migration, historical data write, cloud release, or production operation is included.
