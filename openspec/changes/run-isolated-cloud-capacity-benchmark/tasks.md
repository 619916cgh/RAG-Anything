## 1. Linux Isolation Runner

- [x] 1.1 Add a Linux-native manifest-backed runner with immutable image resolution, temporary run directory, loopback-port, host-headroom, production-probe, container/volume/network ownership, and scoped-cleanup preflights.
- [x] 1.2 Add focused tests for Linux runner input rejection, manifest ownership, and cleanup target selection.

## 2. Full-Stack Isolated Profile

- [x] 2.1 Add a fixed-image full-stack Compose profile for mock-provider, PostgreSQL, Redis, migrate, app, Marker, and Nginx with explicit resource, PID, log, network, and ownership constraints.
- [x] 2.2 Add fixed text and PDF fixtures plus configuration validation tests that prohibit source/production mounts and non-loopback ports.

## 3. Workload and Evidence

- [x] 3.1 Extend bootstrap for distinct staged virtual-user identities, retrieval-ready fixture seeding/verification, and session-capable agents.
- [x] 3.2 Add JSON data-type aware staged SSE workload execution with redacted request NDJSON, rate-limit mode separation, percentiles, executable threshold stops, and recovery sampling.
- [x] 3.3 Extend continuous resource collection and reporting for full-stack services, host disk, PostgreSQL, Redis, queue age, and metrics snapshots.
- [x] 3.4 Add unique text/PDF upload workload support and enforce the retrieval-ready/duplicate diagnostic gate before upload concurrency.

## 4. Verification

- [x] 4.1 Run focused unit/contract tests, static checks, and rendered Compose validation with generated temporary inputs.
- [x] 4.2 Run one Linux isolated full-stack smoke with fixed mock models, verify ownership cleanup, and preserve only a redacted report.

## 5. Cloud Measurement

- [x] 5.1 Run cold/hot query baselines and the `5/10/20/35/50` query staircase with stop conditions and a recovery period (stopped at 10 concurrent users by the configured CPU threshold; recovery verified).
- [x] 5.2 Run the text upload diagnostic; only if retrieval-ready, run separate text/PDF upload stages and soak measurements.
- [x] 5.3 Produce a layered capacity report, update `PROJECT_SUMMARY.md`, and record all unmeasured boundaries.
