## REMOVED Requirements

### Requirement: Save workflow
**Reason**: Saved DAG definitions are retired.
**Migration**: Workflow definitions are irreversibly removed by the forward database migration.

### Requirement: List and load workflows
**Reason**: The workflow editor is retired.
**Migration**: No workflow listing or loading endpoint remains.

### Requirement: Delete workflow
**Reason**: Workflow tables are dropped globally by the retirement migration.
**Migration**: Individual workflow deletion is no longer available.

### Requirement: Navigation entry point
**Reason**: The application no longer offers a workflow editor.
**Migration**: The `/workflow` route and navigation item are removed.
