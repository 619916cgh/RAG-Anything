## Context

The repository contains a mock-backed direct-query smoke profile. It is Windows-only, mounts source files into a prebuilt image, creates one identity, and does not drive Locust stages or the full Nginx/Marker path. The cloud host has 8 vCPU, approximately 31 GiB RAM, low current load, and sufficient disk for a disposable stack, while production containers remain running.

## Goals / Non-Goals

**Goals:**
- Run reproducible, isolated query and upload performance workloads on Linux with fixed mock-provider timing.
- Protect production data and live services through loopback-only networking, image pinning, unique labels, temporary credentials, separate volumes, bounded resources, and scoped cleanup.
- Produce request-level SSE timings and continuous, redacted resource evidence that can support explicit single-host capacity boundaries.

**Non-Goals:**
- Measure external model latency, production data retrieval quality, browser behavior, multi-instance scaling, or public-endpoint capacity.
- Modify production application settings, limits, Docker volumes, or database records.
- Run upload throughput before the retrieval-ready diagnostic gate passes.

## Decisions

### Linux-owned runner and manifest

Use a POSIX shell runner plus existing Python helpers. It SHALL resolve and record the exact pre-existing image digest, generate a run ID below the Linux temporary directory, require loopback ports, and label every created resource. This avoids the Windows-only Docker context restriction and prevents a source-mounted checkout from changing the tested image.

The alternative of invoking the current PowerShell runner remotely is rejected because it requires `desktop-linux` and cannot verify Linux cleanup ownership.

### Full-stack Compose override using existing images

Create a dedicated profile with mock-provider, PostgreSQL, Redis, migrate, app, Marker, and Nginx. It SHALL use existing image references only, expose only Nginx on loopback, and use disposable named volumes. App, database, Redis, Marker, mock, and Nginx SHALL have explicit CPU, memory, PID, and bounded-log limits.

The alternative of reusing the build-based Compose file is rejected because a build changes the tested artifact, consumes unpredictable disk, and lacks ownership controls.

### Workload and identity model

Bootstrap SHALL create a distinct disposable identity, KB, agent, and seeded retrieval-ready fixture per virtual user. The SSE driver SHALL create a session for each identity, then reuse it during the stage. It SHALL emit redacted NDJSON including TTFB, TTFT, complete duration, event ordering, HTTP class, and bounded error category; percentile reporting is calculated from that evidence.

The alternative of shared credentials or `retrieval_only` is rejected because it does not exercise session persistence and can exhaust the current credential queue.

### Rate-limit and retrieval gates

The harness SHALL run two explicitly labelled query modes: an enforced-limit mode that records 429s as protection behavior, and an isolated application-capacity mode that uses only a documented test-stack override for the source-address limiter. It SHALL never mutate the production limiter or treat 429s as application saturation. Before either query matrix, every seeded fixture SHALL reach retrieval-ready state and a single query SHALL record non-empty retrieval evidence; otherwise the matrix is skipped.

### Readiness gates and stop control

Query stages are `1`, `5`, `10`, `20`, `35`, and `50` virtual users, with a two-minute ramp and ten-minute steady interval after single-user cold and hot baselines. The controller SHALL stop a stage on any owned-container OOM/restart, production health regression, or configured error/resource threshold, then collect a ten-minute recovery period.

The initial locked thresholds are: host available memory at least 8 GiB and free disk at least 20 GiB; any owned service RSS above 80 percent of its limit or CPU above 85 percent for three consecutive samples; any 5xx or timeout rate above 1 percent; unexpected 429s in application-capacity mode; queue oldest age above 120 seconds; and a twelve-minute maximum stage. Recovery requires no owned restart/OOM, production probes healthy, and host memory/disk gates restored for ten minutes.

Upload uses unique content and names. It SHALL not begin its concurrency matrix until a text diagnostic records both `retrieval_ready` and expected same-KB duplicate classification. Text and PDF workloads are separate.

### Evidence and cleanup

The collector SHALL sample every five seconds while load is active: load-generator and per-service CPU/RSS/network/block I/O/restart, host memory/load/disk, PostgreSQL connections/activity/locks, Redis memory/commands, queue state/age, and selected metrics counters/histograms. Collection commands have bounded timeouts and unavailable observations are preserved. The only production probes are read-only Docker status/restart/health inspection for the named production services and loopback `GET /api/live` and `GET /api/ready`, with fixed timeouts; arbitrary URLs and production credentials are prohibited.

Before cleanup, the manifest records exact container, volume, and network IDs. Each resource is inspected for matching project label, run-id label, and manifest membership. Credentials are removed and the entire temporary run directory is deleted only after the sanitized report has been copied out.

## Risks / Trade-offs

- [Production load can change during the run] -> Reserve resource headroom, gate every stage on production health and stop immediately on regression.
- [Mock timing omits provider variability] -> Report mock parameters and explicitly exclude real-model capacity claims.
- [Worker readiness can fail independently of HTTP acceptance] -> Enforce the retrieval-ready gate before upload throughput.
- [The host has no swap] -> Apply memory/PID caps and stop before host memory pressure.
- [The server has no retained local backup after authorized cleanup] -> The run uses only disposable resources and never accesses production data.

## Migration Plan

Add test-only tooling and focused tests. Execute the runner only after code-level verification and a final cloud gate. Failed or completed runs remove only resources carrying the generated run label; production resources are never part of cleanup. Removing the new test files reverts the capability without a data migration.

## Open Questions

- Whether the text diagnostic reaches `retrieval_ready` under the bounded full-stack Worker profile.
- Whether the existing current image contains all tools required for the Nginx and PDF fixture path; the Linux preflight will report this before load begins.
