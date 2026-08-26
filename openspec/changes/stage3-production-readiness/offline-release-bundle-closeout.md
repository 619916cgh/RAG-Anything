# Offline Release Bundle Closeout

2026-08-26 offline closeout extends the completed Stage 3 rehearsal operationally without reopening its completed tasks.

- The bundle generator requires local `desktop-linux` Docker, clean detached full-SHA candidate and rollback checkouts, ancestry, exact OCI revision/digest/platform, and import smoke.
- The run-owned bundle stores no `.env`, secrets, DSNs, endpoints, user data, raw provider payloads, or raw logs. Its `SHA256SUMS` must cover every packaged file.
- Candidate and rollback archives were identity-verified and their archive checksums matched the successful isolated import/health/rollback rehearsal artifacts.
- New-server production deployment, migration apply, backup/restore, provider access, and production data actions remain explicitly outside this closeout. The new server must independently pass verified backup, `status`/`plan`/`verify`, approval, live/ready/health, Worker, monitoring, and synthetic business acceptance.
