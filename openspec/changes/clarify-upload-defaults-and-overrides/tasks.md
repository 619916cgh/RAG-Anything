## 1. Frontend state and interaction

- [x] 1.1 Split KB effective/default state from the upload panel's empty temporary override; clear the override when switching KBs.
- [x] 1.2 Replace the always-visible upload selector with an effective-strategy summary, source label, accessible temporary override toggle, selector, and reset behavior.
- [x] 1.3 Pass only the captured non-empty override to single/batch upload calls; clear and collapse after resolved requests while retaining it on rejection.

## 2. Backend batch snapshot integrity

- [x] 2.1 Keep the batch request strategy immutable and use a per-file resolved strategy for task metadata, queue payloads, and response fields.
- [x] 2.2 Add regression coverage for two-file batches without a request strategy and preserve existing KB/personal precedence tests.

## 3. Contract tests and documentation

- [x] 3.1 Update frontend source contracts for the collapsed override UI, effective source summary, and reset lifecycle.
- [ ] 3.2 Run focused frontend/backend tests, syntax checks, Vite build, OpenSpec strict validation, and scoped diff checks. (focused tests, syntax, strict validation, and diff checks pass; Vite build timed out without output)
- [x] 3.3 Update `PROJECT_SUMMARY.md` with the new UI semantics, batch fix, and verification boundaries.
