## 1. Backend and authorization retirement

- [x] 1.1 Remove workflow endpoints, executor integration, and workflow-only WebSocket state without changing remaining admin endpoints.
- [x] 1.2 Remove workflow permission constants and default-role projections.
- [x] 1.3 Remove legacy workflow directory initialization and workflow-only reset/performance handling.

## 2. Database retirement

- [x] 2.1 Add and register a forward migration that strips stored workflow permissions and drops workflow data tables in dependency order.
- [x] 2.2 Add focused migration and route/permission absence regression coverage.

## 3. Frontend retirement

- [x] 3.1 Delete workflow route, editor components, navigation, permissions UI, and related tests.
- [x] 3.2 Remove the unused React Flow dependency and regenerate the frontend lock/build metadata.

## 4. Specifications and documentation

- [x] 4.1 Remove current workflow OpenSpec specs and update mutable product, architecture, RBAC, and collaboration documentation.
- [x] 4.2 Update PROJECT_SUMMARY.md with the retirement fact, verification result, and production boundary.

## 5. Verification

- [x] 5.1 Run focused backend, migration, frontend, and static removal checks.
- [x] 5.2 Run frontend build, OpenSpec strict validation, summary check, and diff hygiene checks.
