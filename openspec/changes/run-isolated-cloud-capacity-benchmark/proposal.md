## Why

The existing performance harness proves only a low-resource, direct-App mock smoke: it is Windows-only, creates one identity, and omits Nginx and Marker. The current cloud host now has sufficient isolated headroom to measure the single-host query and upload paths, but doing so safely requires a Linux-native, manifest-owned test stack and measurable stop conditions.

## What Changes

- Add a Linux-native runner for manifest-owned, loopback-only, mock-backed performance runs using locked existing images and disposable credentials, databases, volumes, and work directories.
- Add a full-stack isolated Compose profile with bounded app, PostgreSQL, Redis, Marker, Nginx, and mock-provider resources, logging, PID limits, and ownership labels.
- Extend bootstrap, workload drivers, reporting, and collection for independent virtual-user identities, staged SSE query load, request-level timing evidence, continuous resource samples, and threshold-triggered stop/recovery behavior.
- Add an upload readiness gate with unique text and PDF fixtures; do not run upload throughput tests until a unique upload reaches retrieval-ready state and duplicate behavior is classified.
- Record redacted cloud-run results separately from real-model, production-data, browser, and multi-instance conclusions.

## Capabilities

### New Capabilities
- `isolated-cloud-capacity-benchmark`: Runs and reports bounded, disposable cloud-host performance measurements without accessing production data or external model providers.

### Modified Capabilities
- None.

## Impact

- Affected test tooling: `tests/perf/`, `scripts/`, and isolated Compose configuration.
- Affected operational evidence: `PROJECT_SUMMARY.md` and redacted temporary performance reports.
- No production application API, production configuration, Docker volumes, database, uploads, indexes, or external model endpoints are changed or used.
