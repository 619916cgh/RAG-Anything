## ADDED Requirements

### Requirement: Worker process groups are reclaimed on terminal control paths
The document processing lifecycle SHALL reclaim the complete Worker process group on cancellation, timeout, and KB deletion before durable cleanup reports completion.

#### Scenario: KB deletion interrupts active processing
- **WHEN** a knowledge base is deleted while an upload Worker is active
- **THEN** the Worker process group is terminated and awaited before its task is removed
