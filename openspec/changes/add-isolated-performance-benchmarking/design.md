## Context

The checked-in Compose file consumes the production `.env`, uses fixed
container names, and can write existing volumes.  The SSE workload writes
reports into the repository and measures after response headers arrive.  A
performance run must instead be repeatable, isolated, and provider-free.

## Goals / Non-Goals

**Goals:**
- Exercise query SSE and text/PDF upload paths with deterministic OpenAI-style
  chat and embedding responses.
- Produce client latency plus resource, database, Redis, queue, and Prometheus
  evidence outside the worktree.
- Prevent test data, credentials, ports, networks, and volumes from colliding
  with normal deployment resources.

**Non-Goals:**
- No production deployment, external model call, browser benchmark, migration
  change, or claim that mocked timing represents provider performance.

## Decisions

### Dedicated Compose project and mock provider

A `deploy/perf` Compose definition builds an isolated stack and uses a project
name supplied by the runner.  It never imports `.env`; its generated runtime
environment uses new named volumes and a private network.  A compact FastAPI
mock implements `/v1/models`, `/v1/embeddings`, and chat completions with
fixed delay/token settings.  This exercises the existing OpenAI-compatible
adapter without application feature flags.

### External evidence directory

The phase runner creates a unique directory under the operating-system temp
location.  Credentials, raw metrics, logs, Locust reports and cleanup
manifests remain there.  A redacted Markdown summary is the only intended
handoff artifact.

### One request, one Locust statistic

The workload starts its timer before the streaming POST, records a single
custom SSE statistic, and prevents the raw streaming request from being added
to Locust's aggregate statistics.  Credentials are assigned round-robin from
a local runtime-only JSON file; no password defaults exist.

### Host-side resource collection

The collector samples Docker stats, PostgreSQL counters, Redis info, `/metrics`
and disk state at a fixed interval.  Missing optional sources are reported as
unavailable, never fabricated.  Upload queue observations use the dedicated
test database only.

## Risks / Trade-offs

- [The parser image can exceed a small host's capacity] -> gate the runner on
  CPU, memory and disk thresholds before Compose starts.
- [Mock output hides provider latency] -> report mock parameters prominently
  and keep real-provider testing out of scope.
- [Load traffic can persist chat and upload records] -> use only generated
  volumes/database and remove them through an explicit run manifest.
