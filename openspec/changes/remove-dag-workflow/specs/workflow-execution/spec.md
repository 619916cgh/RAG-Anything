## REMOVED Requirements

### Requirement: Run workflow via API
**Reason**: The DAG workflow product is retired.
**Migration**: Use the supported knowledge-base ingestion and agent-query APIs; `/api/workflows/{id}/run` no longer exists.

### Requirement: Node execution in topological order
**Reason**: The DAG execution engine is retired.
**Migration**: No replacement DAG executor is provided.

### Requirement: Real-time status via WebSocket
**Reason**: Workflow runs no longer exist.
**Migration**: `/api/ws/workflow-run/{run_id}` is removed.

### Requirement: Error handling
**Reason**: Workflow execution is retired.
**Migration**: Use error handling provided by the supported API being used.

### Requirement: Run history
**Reason**: Workflow records are deleted by the retirement migration.
**Migration**: No workflow history export or compatibility endpoint is retained.
