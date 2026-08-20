## ADDED Requirements

### Requirement: Task-owned duplicate completion
The upload pipeline SHALL determine a task's processing result and automatic-tag target from a persisted document status whose `track_id` or `metadata.task_id` equals that task ID. A status row belonging to another task, including a duplicate zero-chunk placeholder for the same filename or content, MUST NOT cause the current task to fail or select its tag target.

#### Scenario: Current task has a processed document and another task has a duplicate placeholder
- **WHEN** a current upload task has a task-owned processed document with persisted chunks and a newer same-name duplicate placeholder owned by another task has failed with zero chunks
- **THEN** the current task completes using its task-owned document and enqueues automatic tagging for that document

#### Scenario: Current task owns the zero-chunk failure
- **WHEN** the only task-owned document status for an upload task has failed with zero chunks
- **THEN** the upload task remains a hard processing failure and no automatic tag job is enqueued for that zero-chunk document

#### Scenario: Provenance is absent or ambiguous
- **WHEN** no document status can be proven to belong to the current task and same-name status rows belong to other tasks
- **THEN** the pipeline treats the status as pending or retryable and MUST NOT terminally fail or complete the current task from another task's row

### Requirement: Provenance-safe automatic tag recovery
Automatic tag recovery SHALL associate a missing tag job with the document's durable task provenance before applying any legacy filename-based fallback.

#### Scenario: Duplicate placeholder is present during recovery
- **WHEN** a task-owned processed document has no tag job and a same-name duplicate placeholder exists for another task
- **THEN** recovery creates or resumes a tag job for the processed document and associates it with its owning upload task only
