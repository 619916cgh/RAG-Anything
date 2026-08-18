## Why

The project has query timing metrics and a legacy SSE Locust script, but no
repeatable isolated environment for measuring end-to-end query, upload, and
resource behavior without production data or provider cost.  The existing
script also conflates request timing and duplicate Locust statistics.

## What Changes

- Add a disposable Docker Compose performance profile with isolated storage,
  PostgreSQL, Redis, parser worker, and an OpenAI-compatible mock provider.
- Add deterministic text/PDF fixtures, a phase runner, and sampling tools for
  application, container, database, Redis, disk, and Prometheus data.
- Replace the unsafe defaults in the SSE stress runner with credential-file
  support, end-to-end timing, unique request correlation, and external output
  directories.
- Document query and upload load stages, acceptance limits, evidence, and safe
  cleanup for the dedicated test environment.

## Capabilities

### New Capabilities
- `isolated-performance-benchmarking`: Reproducible, disposable query and
  upload performance tests using mock model providers and resource evidence.

### Modified Capabilities

None.

## Impact

New test-only deployment files, Python benchmark utilities and fixtures, the
existing Locust workload, focused unit tests, and project operational summary.
No production API, database schema, provider configuration, or deployment is
changed.
