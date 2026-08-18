## Why

The existing provider-free performance harness proves only a small query path and
the new metrics smoke. It cannot reproducibly bootstrap its own workload,
collect a complete SSE evidence set, or distinguish a test-stack configuration
failure from an upload/Worker regression. The low-resource host also needs a
separate, explicitly non-capacity execution path.

## What Changes

- Make the isolated mock environment self-contained for visual and text
  embedding preflight, generated identities, KB/Agent bootstrap, and
  redacted evidence capture.
- Add a resource-capped Compose smoke profile and phased query/SSE execution
  that stops on health, restart, memory, or error thresholds.
- Diagnose and cover the disposable text upload terminal-state gate before
  attempting upload/Worker evidence.
- Produce a report that separates low-resource smoke, mock query load,
  upload/Worker, Nginx, and real-provider/production conclusions.

## Capabilities

### New Capabilities
- `isolated-performance-runtime-evidence`: Repeatable, disposable runtime
  evidence for the mock-backed query, SSE, metrics, and upload paths.

### Modified Capabilities
- None.

## Impact

Affected areas include `tests/perf/`, the performance runner and collector,
focused tests, and the project performance report. No production deployment,
existing PostgreSQL, `.env`, real model endpoint, or public port is in scope.
