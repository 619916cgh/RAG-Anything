## Why

The standalone DAG workflow editor duplicates document and retrieval operations that are maintained through the supported knowledge-base and agent interfaces. Removing it eliminates an unused execution, persistence, and authorization surface, including stored workflow data that must no longer be exposed or retained.

## What Changes

- **BREAKING** Remove all DAG workflow REST and WebSocket endpoints, execution code, frontend editor route, navigation, and its dedicated client dependency.
- **BREAKING** Remove `workflow:read` and `workflow:write` from runtime permission definitions and stored role projections.
- **BREAKING** Add a forward PostgreSQL migration which irreversibly drops workflow definitions and run records after removing their role permissions.
- Remove workflow-only runtime cleanup, reset, performance, test, documentation, and current OpenSpec specification references.
- Preserve historical migration and archived OpenSpec records as immutable audit evidence.

## Capabilities

### New Capabilities

- `workflow-feature-retirement`: Retire the obsolete DAG workflow product surface and persisted state through a forward-compatible database migration.

### Modified Capabilities

- `workflow-execution`: Remove the requirement to execute saved DAG workflows.
- `workflow-persistence`: Remove the requirement to persist workflow definitions and runs.
- `workflow-run-ui`: Remove the workflow execution user interface requirements.

## Impact

Affected areas include the admin router, WebSocket service, RBAC defaults and database role records, PostgreSQL migration manifest, React routing and permissions, frontend dependency lockfile, reset/performance support, tests, current specifications, and product documentation. Existing clients calling the removed endpoints receive the normal FastAPI 404 response.
