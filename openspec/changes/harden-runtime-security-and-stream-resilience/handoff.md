# Project Summary Increment And Acceptance Boundary

Do not merge this text into `PROJECT_SUMMARY.md` until its current dirty-worktree
owner coordinates the update.

## Summary increment

- Account update and archive transactions now lock the actor and target rows,
  derive their persisted roles, reject mutations of a higher-role target, and
  retain the final-super-admin guard.
- WebSocket sessions retain `token_jti` and fail closed on revocation, account
  lifecycle, or generation changes. Ordinary task events are owner-directed
  and projected; monitoring uses a separate `monitor:read` endpoint.
- Upload Worker creation uses an OS process group/session. Cancellation,
  watchdog timeout, and KB deletion use one tree-reap helper.
- Image liveness checks use `/api/live`, the Compose app service has no host
  port mapping, and remote app health probing runs inside the app container.
- Manifest migrations validate an in-memory transaction body and execute the
  advisory lock, SQL, and applied history insert in one psql transaction.
- Agent streams send `accepted` before query-core acquisition and heartbeats
  while it is pending. Browser SSE enforces first-event and idle deadlines.
- `GET /knowledge/legacy-readiness-preview` is read-only and only reports
  evidence-backed candidates within existing KB access scope.

## Not accepted here

- No Docker runtime test with PostgreSQL temporarily unavailable was run.
- No Windows process-tree observation was run.
- No isolated PostgreSQL competition, rollback, or private-CA TLS acceptance
  was run.
- No Prometheus staging scrape or Alertmanager drill was run.
- No database migration, legacy-readiness backfill, deployment, or production
  backup-gated action was run.
