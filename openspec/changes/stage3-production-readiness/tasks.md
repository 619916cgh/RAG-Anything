## 1. Coordinator and safety gates

- [x] 1.1 Implement the fixed Stage 3 coordinator CLI and schema-versioned evidence model.
- [x] 1.2 Implement target, candidate checkout, Docker context, database identity, image revision/digest, temporary path, and production-marker gates.
- [x] 1.3 Implement the allowlisted stage registry, bounded retry/repair budget, hard-stop classifications, and owned-resource cleanup.

## 2. Recovery and rehearsal composition

- [x] 2.1 Compose release backup verify, isolated restore, and aggregate inventory validation using disposable PostgreSQL/assets only.
- [x] 2.2 Compose existing migration, health, five-role/API, and Worker-to-retrieval acceptance stages with explicit stage ordering and skip semantics.
- [x] 2.3 Add disposable rollback identity/health gate and hard-stop semantics without invoking production release scripts.

## 3. Evidence and tests

- [x] 3.1 Add recursive evidence redaction and contract tests for secrets, DSNs, paths, source content, hostnames, and private image references.
- [x] 3.2 Add unit tests for all safety gates, retry budget accounting, hard stops, backup/restore mismatch, rollback failure, and cleanup ownership/idempotence.
- [x] 3.3 Add Compose/acceptance contract coverage and run focused tests, static compilation, strict OpenSpec validation, and diff checks.

## 4. Isolated rehearsal and closeout

- [ ] 4.1 Run one complete rehearsal from a clean detached candidate with disposable Compose/PG resources where environment access is available.
- [x] 4.2 Record environment blockers and deferred provider/browser/video/production boundaries without weakening gates.
- [x] 4.3 Update `PROJECT_SUMMARY.md` with candidate identity, rehearsal evidence, repair budget usage, cleanup result, and verification boundaries.
