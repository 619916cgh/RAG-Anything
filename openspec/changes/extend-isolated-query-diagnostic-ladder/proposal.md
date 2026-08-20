## Why

The original isolated Profile A (two CPU/three GiB application limit) remains CPU-gated at 10 VU under its standard threshold, while the explicitly authorized 20 and 30 VU diagnostic runs completed successfully without SSE failures. The user has authorized use of additional test-only host capacity, but the existing gate cannot safely be relabelled or relaxed to make the Profile A result pass.

## What Changes

- Create a distinct, test-only Profile B with a four CPU/six GiB application limit, four fixed in-process LLM slots, and a quota-normalized gate, without changing Profile A records, production resources, or production policy.
- Rebaseline Profile B at 1, 5, and 10 VU, then advance through 20, 30, 40, and 50 VU only after the immediately preceding fresh isolated rung satisfies its success, recovery, cleanup, and production-probe gates.
- Permit one explicitly user-authorized direct 50 VU Profile B diagnostic on a fresh isolated stack when ordered rebaseline evidence is unavailable. On the authorized 8C32G host, this diagnostic uses an independent `8 CPU / 24 GiB / MAX_ASYNC=8` application envelope while retaining at least 8 GiB for the host and companion services. This exception retains every normal preflight, SSE, latency, resource, recovery, cleanup, and permitted production-probe gate, records `direct-50-diagnostic` execution mode, and is never admissible as ordered-ladder evidence or authorization for another stage.
- Define quota-normalized CPU and RSS risk limits, fixed mock latency objectives, and hard stops for non-successful queries, OOM, restart, ownership failure, host-resource exhaustion, and production-probe failure.
- Revise only the Profile B mock latency gate after three comparable 20 VU runs showed healthy resources and protocol behavior but a stable TTFT P95 above the initial target; retain all non-latency hard stops.
- Correct the runner's recovery-result attribution so a query-gate exit does not falsely classify healthy recovery sampling as failed; retain a fixed, content-free recovery failure category when recovery itself is incomplete or unhealthy.
- Require a read-only host-capacity preflight, manifest ownership, retrieval readiness with non-empty sources, and per-rung recovery before starting any Profile B stage.
- Produce sanitized Profile B evidence that cannot be combined with Profile A or claimed as real-model, browser, Worker, multi-instance, or production capacity; prohibit deployment and all production configuration or resource-policy changes.

## Capabilities

### New Capabilities

- `isolated-query-diagnostic-escalation`: A bounded, disposable resource-profile rebaseline and 1-to-50 VU ladder that measures the authorized test-only envelope without changing Profile A or production capacity acceptance.

### Modified Capabilities

- None.

## Impact

The change is limited to the isolated performance runner, its manifest/resource evidence, test-only workload configuration, focused contract tests, OpenSpec artifacts, and the coordinator-owned project record. It does not alter application APIs, authentication, rate limits, Docker production resources, database schema, deployment configuration, or production data.
