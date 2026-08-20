## Why

The isolated cloud query benchmark reached its CPU protection threshold at 10 concurrent virtual users while preserving a 100 percent request success rate and substantial memory headroom. Raising the threshold would hide saturation rather than increase capacity, so the application needs evidence-led hotspot analysis and a narrowly scoped optimization before another capacity measurement.

## What Changes

- Add a repeatable, isolated process-level CPU profiling mode for the mock-backed query stack, with no production data, configuration, model endpoint, or runtime state access.
- Correlate sampled application stacks with request-level SSE timings and existing resource observations to identify the dominant query-path CPU cost.
- Implement only an evidence-backed single-instance query-path optimization and preserve existing session, knowledge-base, WebSocket, and rate-limit semantics.
- Add focused regression tests and compare the optimized 5- and 10-user stages with the recorded baseline under the same CPU, memory, mock-provider, and stop-rule configuration.
- Add one user-authorized, bounded 20-user diagnostic stage after a recorded CPU-gate breach. The breach remains a failed capacity stage; the diagnostic result is not capacity-acceptance evidence.
- Add one user-authorized `30 -> 40 -> 50` diagnostic ladder. Each rung is a fresh isolated run, is allowed only after the preceding rung's recovery and healthy production probes, and remains non-acceptance evidence.
- Report an unchanged or lower capacity boundary when the evidence does not demonstrate improvement; do not claim 20/35/50-user capacity without executing those stages.

## Capabilities

### New Capabilities

- `isolated-query-capacity-optimization`: Safe profiling, targeted optimization, and comparable isolated capacity evidence for the single-instance SSE query path.

### Modified Capabilities

- None.

## Impact

- Affects the isolated cloud performance runner, workload driver, resource evidence, and the specific backend query-path component identified by profiling. The authorized diagnostic stage remains test-only and leaves production unchanged.
- Adds test-only profiling controls and focused behavioral/performance regression coverage; production deployment settings, worker count, external model configuration, and database schema remain unchanged.
