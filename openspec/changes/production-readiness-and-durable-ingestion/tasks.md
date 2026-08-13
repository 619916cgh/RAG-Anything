## 1. Release Boundary Inventory

- [x] 1.1 Add a read-only release-candidate inventory command that maps dirty paths to active OpenSpec ownership and shared serialized assets.
- [x] 1.2 Add unit coverage proving inventory classification never invokes a mutating Git or filesystem operation.

## 2. Retrieval Readiness Contract

- [x] 2.1 Extend the content-readiness evaluator with PostgreSQL-strict authoritative checks and stable bounded failure reasons.
- [x] 2.2 Wire strict readiness into Worker terminal handling and fenced task completion without changing optional enrichment into an ingestion failure.
- [x] 2.3 Add focused readiness, cancellation, retry, and stale-owner regression tests.

## 3. Knowledge-Base Health and Repair

- [x] 3.1 Add read-scoped retrieval-health inspection and operate-scoped, idempotent repair queue APIs using existing repair persistence.
- [x] 3.2 Add backend tests for five-role/scope denial, no cross-KB disclosure, deterministic reason codes, and duplicate repair requests.

## 4. Isolated Pre-Production Acceptance

- [x] 4.1 Add an isolated acceptance runner and sanitized JSON evidence schema that refuses unsafe/non-production targets before mutation.
- [ ] 4.2 Compose migration fresh/upgrade/repeat/intentional-failure, health, role API, and Worker-to-retrieval checks using existing tools and isolated fixtures.
- [x] 4.3 Add tests for evidence redaction, failure/skip non-release outcomes, target guards, and cleanup behavior.
- [x] 4.4 Document the pre-production procedure, evidence taxonomy, rollback boundary, and explicitly deferred provider/video/browser/production acceptance.

## 5. Validation and Closeout

- [x] 5.1 Run focused backend tests, static compilation, OpenSpec strict validation, and scoped diff checks.
- [ ] 5.2 Run the isolated pre-production acceptance profile where environment access is available; record environment blockers separately from source failures.
- [x] 5.3 Update `PROJECT_SUMMARY.md` with current facts, verification boundary, release-candidate inventory result, and this task record.
