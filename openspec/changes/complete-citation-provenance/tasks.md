## 1. Schema And Repository

- [x] 1.1 Add migration 038 and manifest entry with current-row uniqueness on KB, document, chunk, and provenance version, plus query-history citation persistence.
- [x] 1.2 Implement atomic provenance upsert, batched lookup, strict public DTO construction, and legacy read degradation.
- [x] 1.3 Add focused migration and repository tests for fresh/upgrade/repeat, concurrent hash replacement, duplicate names, query-history round-trip, and deep redaction.

## 2. Ingestion And Lifecycle

- [x] 2.1 Preserve trustworthy ODL page, element, bbox, coordinate-system, section, and media metadata through chunk creation.
- [x] 2.2 Compute full source SHA-256 and persist text, image, and video provenance for new uploads only.
- [x] 2.3 Make new provenance writes and mutation cleanup fail closed while retaining precise legacy table-missing compatibility.
- [x] 2.4 Scope new video asset and segment identity to KB/document and cover retry and cross-owner isolation.

## 3. Query And Delivery

- [x] 3.1 Register native, RRF, Graph, tag-scoped, standard, ReAct, and CoT hits in a request provenance sink keyed by document/chunk identity.
- [x] 3.2 Filter citations to valid source numbers actually present in the final answer, preserving first-use order and removing duplicates.
- [x] 3.3 Return the same unified citations in Agent terminal branches, SSE done, assistant messages, query history, and conversation reload.
- [x] 3.4 Normalize AutoRepair citations and deliver Public Demo citations through share-scoped URLs, including explicit empty terminal arrays.

## 4. Frontend

- [x] 4.1 Add reusable provenance presentation utilities and components for document, page, section, excerpt, locator, and legacy states.
- [x] 4.2 Integrate AgentChat and Public Demo with controlled image/video media, start-time seek, chunk links, and safe degradation.
- [ ] 4.3 Render bbox highlights only with a valid page preview and coordinate transform, and verify desktop/mobile layout behavior.

## 5. Verification And Closure

- [x] 5.1 Run focused backend provenance, ingestion, query, Agent, AutoRepair, Demo, video, and migration tests plus compilation and diff checks.
- [x] 5.2 Run the full relevant frontend test suite and production Vite build.
- [x] 5.3 Validate migration fresh/upgrade/repeat/failure/recovery and provenance concurrency in an isolated PostgreSQL environment without applying 038 to the existing database.
- [ ] 5.4 Run one real new-upload Worker + PostgreSQL + browser acceptance for PDF, image document, and video across desktop/mobile, or record exact environment blockers without upgrading weaker evidence.
- [ ] 5.5 Strict-validate OpenSpec, update PROJECT_SUMMARY.md with evidence boundaries, and create a task-only local commit without production deployment.
