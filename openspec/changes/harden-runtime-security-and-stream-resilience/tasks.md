## 1. Account and WebSocket Security

- [x] 1.1 Enforce current-target hierarchy from locked actor and target rows for user update and archive operations.
- [x] 1.2 Retain token JTI in WebSocket sessions and revalidate it for receive and delivery.
- [x] 1.3 Replace ordinary task broadcast with owner-directed, projected delivery and add a monitor-authorized stream.
- [x] 1.4 Add repository, API, and WebSocket regression coverage for hierarchy, revocation, and two-user isolation.

## 2. Worker and Deployment Reliability

- [x] 2.1 Start upload Workers in OS process groups and centralize tree termination across cancellation, timeout, and deletion paths.
- [x] 2.2 Use `/api/live` for image healthchecks, remove the Compose app host mapping, and update release probing.
- [x] 2.3 Add unit/contract tests for termination construction and liveness/readiness/port behavior.

## 3. Migration and Monitoring Operations

- [x] 3.1 Add validated transaction-body extraction and same-session advisory-lock migration execution.
- [x] 3.2 Preserve supported PostgreSQL TLS and connection URL options without diagnostic disclosure.
- [x] 3.3 Add runner tests for lock/no-op, rollback, unsupported SQL, failure history, and URL options.
- [x] 3.4 Add credential-free Prometheus scrape inventory and static rule/config validation.

## 4. Interactive and Legacy Readiness Behavior

- [x] 4.1 Add PATCH to CORS and additive accepted/heartbeat events before slow agent query acquisition.
- [x] 4.2 Add shared browser SSE first-event and idle deadlines while retaining caller cancellation.
- [x] 4.3 Add a scoped, read-only legacy readiness preview with authoritative evidence and reason counts.
- [x] 4.4 Add backend and frontend regression tests for CORS, streaming deadlines, and no-write readiness previews.

## 5. Validation and Handoff

- [x] 5.1 Run focused backend/frontend/ops tests, compilation, strict OpenSpec validation, and scoped diff checks.
- [x] 5.2 Record the project-summary increment for its current owner without modifying unrelated dirty summary content.
- [x] 5.3 Record blocked external acceptance: Docker, Windows process tree, isolated PostgreSQL concurrency/TLS, Prometheus staging, and production backup-gated work.
