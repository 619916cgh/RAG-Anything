## ADDED Requirements

### Requirement: DAG workflow feature retirement
The system SHALL not expose a DAG workflow editor, workflow execution API, workflow execution WebSocket, or workflow-specific permission to application clients.

#### Scenario: Removed route is requested
- **WHEN** a client requests a former `/api/workflows` or `/api/ws/workflow-run/{run_id}` route
- **THEN** the application SHALL not register that route and SHALL return the framework's normal not-found response.

### Requirement: Irreversible workflow data retirement
The system SHALL remove persisted workflow definitions and runs through a forward PostgreSQL migration while preserving the immutable migration history that originally created them.

#### Scenario: Existing database is upgraded
- **WHEN** migration `037_remove_dag_workflow.sql` is applied to a database containing workflow tables and role permission projections
- **THEN** it SHALL remove both workflow permissions, drop workflow runs before workflow definitions, and record successful application in migration history.

#### Scenario: Migration is repeated
- **WHEN** the migration runner is run again after the retirement migration has succeeded
- **THEN** it SHALL schedule no workflow retirement migration and SHALL not recreate workflow records or tables.
