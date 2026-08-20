## Context

The application is a FastAPI modular monolith with PostgreSQL as authoritative state, subprocess Workers for ingestion, and browser SSE/WebSocket clients. Existing security/session primitives and historical manifest migrations must remain compatible. The worktree has unrelated project-summary changes, so this change does not edit that file.

## Goals / Non-Goals

**Goals:**
- Close higher-role account mutation and post-revocation WebSocket delivery gaps.
- Make upload termination, container health, and migration execution fail safely.
- Give interactive clients bounded, visible recovery when streaming stalls.
- Identify but never mutate legacy readiness data without a separately approved repair.

**Non-Goals:**
- Workflow file changes, new database schema, historical data backfill, production migration, deployment, or redesigning query-token WebSocket authentication.

## Decisions

- The auth repository receives `actor_id`, locks the target row, reads the actor's persisted role in that transaction, and applies `can_assign_role(actor, target_current)` to every sensitive mutation. This prevents direct repository callers and stale router claims from bypassing policy. Same-level management remains allowed to preserve existing hierarchy semantics.
- WebSocket session snapshots include `token_jti`; session validation is reused before both receive and send. Normal task messages require `owner_user_id` and use a new directed sender. Events lacking an owner are suppressed for ordinary clients. A separate monitor endpoint uses `monitor:read` and projected fields only.
- Worker creation starts an OS process group/session. All cancellation, timeout, and KB deletion paths use one helper: POSIX sends signals to `killpg`; Windows uses `taskkill /T` against the group root. Cleanup waits for process exit before deleting task residue.
- Docker healthchecks call `/api/live`; `/api/ready` remains the dependency probe and `/api/health` retains compatibility. Compose removes the app host mapping; release probes run inside the app container or Docker network.
- The migration runner keeps immutable migration files unchanged. It validates that each file has at most one outer `BEGIN/COMMIT` and no non-transactional DDL, removes that outer wrapper in memory, then executes the body plus `applied` history write in one `psql` transaction with `pg_advisory_xact_lock`. A concurrent waiter rechecks history under the lock and no-ops if already applied. Failures roll back SQL; a separate sanitized failure record is diagnostic only.
- SSE retains existing event types and adds ignorable `accepted` and `heartbeat` events. The browser composes caller cancellation with a private AbortController, resets a 20-second first-event timer and 45-second idle timer after every parsed data event, and throws distinct timeout errors.
- Readiness preview uses authoritative PostgreSQL/readiness checks and returns only stable IDs and reason codes within the caller's KB scope. It performs no repair or metadata write.

## Risks / Trade-offs

- [Windows task tree behavior differs from POSIX] -> unit-test platform command construction and require Windows container/host acceptance before release.
- [Historical migration syntax cannot always be transaction-wrapped] -> reject unsupported transaction boundaries or concurrent DDL instead of guessing.
- [Ownerless legacy task events are dropped] -> prefer confidentiality over inferred ownership; expose aggregate monitoring only to monitor-authorized users.
- [SSE heartbeat adds client events] -> use additive event types that existing consumers ignore.
- [Prometheus deployment ownership varies by environment] -> provide inventory/config validation but do not inject secrets or deploy monitoring in this change.

## Migration Plan

1. Merge source and focused tests with no schema/data writes.
2. Validate container, process-tree, isolated PostgreSQL concurrency, and monitoring staging separately.
3. Release only through the existing committed-release workflow. Roll back source/image if needed; no historical migration is applied by this change.

## Open Questions

- Actual historical readiness backfill remains a separate approved change requiring a verified backup and controlled PostgreSQL target.
- Replacing query-token WebSocket authentication with tickets remains a residual security improvement outside this scope.
