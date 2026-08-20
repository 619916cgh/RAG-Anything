## Context

The upload service starts a worker for each accepted task. LightRAG can emit an additional duplicate placeholder with a failed zero-chunk status when content already exists. Completion verification, the worker's optional JSON verification, and tag reconciliation currently identify documents by filename, which lets a different task's placeholder control the current task.

## Goals / Non-Goals

**Goals:**

- Resolve completion and automatic tagging against the current upload task's persisted document provenance.
- Preserve hard failure when the current task's own document has zero chunks or failed processing.
- Preserve cautious retry behavior when provenance is absent or ambiguous.

**Non-Goals:**

- Changing the public duplicate-upload admission policy.
- Retrying, deleting, or repairing existing production rows in this change.
- Reusing an earlier task's document as a substitute for the current task after a worker has started.

## Decisions

- Use `track_id` and `metadata.task_id` as the authoritative provenance keys. The final resolver accepts a task ID and selects only matching rows before interpreting status or chunk count. This matches the existing snapshot persistence ownership model.
- If no task-owned row exists in PostgreSQL-backed storage, return the established pending/retry signal. Filename-only selection remains only as a carefully constrained legacy fallback where no task-scoped ambiguity exists.
- Pass the task ID into the Worker final check so an unrelated duplicate row cannot cause it to emit a false zero-chunk failure. When no owned JSON row is available, the Worker defers final authority to the service resolver.
- Tag reconciliation must prefer the durable document provenance before any legacy filename/time matching, so recovery does not attach a job to the wrong upload.

## Risks / Trade-offs

- [Older rows have no provenance] -> Preserve a unique, unambiguous legacy fallback and defer ambiguous rows for recovery.
- [Worker and service selectors drift] -> Exercise both paths in focused regression tests using the same mixed-record fixture.
- [Existing failed duplicate rows remain] -> Do not mutate them; they cannot affect a later task after provenance filtering.

## Migration Plan

Deploy as an application-only change. Existing uploads with an unambiguous task-owned document can be completed by normal recovery; no schema migration or production data rewrite is required. Roll back by restoring the previous application image; this change creates no irreversible data mutation.

## Open Questions

- None for this scoped defect repair.
