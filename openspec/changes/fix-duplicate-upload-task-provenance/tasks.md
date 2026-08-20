## 1. Task-Owned Document Resolution

- [x] 1.1 Add a shared provenance-aware document-status selector for upload completion, preserving only an unambiguous legacy fallback.
- [x] 1.2 Pass the upload task ID through final document resolution and prevent other-task duplicate placeholders from determining readiness or tagging.
- [x] 1.3 Make the Worker final JSON status check task-aware and defer to the service resolver when no owned row is visible.

## 2. Tag Recovery

- [x] 2.1 Make missing-tag reconciliation associate upload tasks from durable document provenance before legacy filename matching.

## 3. Verification

- [x] 3.1 Add focused regression tests for mixed task-owned processed and foreign duplicate zero-chunk statuses, current-task hard failure, and ambiguous provenance deferral.
- [x] 3.2 Add a completion-path regression proving the task-owned document is used for readiness and automatic tag enqueueing.
- [x] 3.3 Run focused backend tests, static compilation, OpenSpec validation, and the project-summary check.
