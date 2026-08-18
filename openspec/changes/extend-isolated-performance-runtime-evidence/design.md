## Context

The existing isolated performance harness can start a mock-backed query stack,
but its workload preparation, resource limits, SSE evidence, upload terminal
state, and cleanup guarantees are incomplete. The available Windows host has
approximately 16 GiB physical memory and is not a capacity-test target. It
must therefore run only a disposable, resource-capped evidence profile.

The test profile SHALL never consume repository `.env` values, existing
PostgreSQL/Redis state, real model endpoints, real users, or production
resources. Its only externally reachable application port is loopback. Query,
Nginx, and upload/Worker runs are separate phases so resource and failure
attribution remains meaningful.

## Goals / Non-Goals

**Goals:**

- Make one low-resource mock profile reproducible from a generated run
  directory, including identities, knowledge base, agent, fixture, manifest,
  raw observations, and cleanup inventory.
- Collect one logical SSE outcome per request, preserving request-to-token
  TTFT, complete wall time, event sequence, error classification, metrics, and
  resource snapshots.
- Establish a truthful upload terminal-state diagnostic gate using unique
  content before any upload concurrency result is reported.
- Enforce host/container limits and stop conditions that prevent an unsafe
  run from becoming a host-impacting workload.

**Non-Goals:**

- Establishing 5--50 user capacity, production SLOs, browser performance,
  multi-instance behavior, or real model latency/cost.
- Changing product duplicate-document, indexing, Worker, or rate-limit
  semantics to make a benchmark pass.
- Using Nginx or Marker in the direct query profile; those are optional,
  separately bounded smoke phases only.

## Decisions

### Standalone, labelled Compose project

The performance Compose file is invoked alone with a cryptographically random
run ID and project name `ragperf-<run-id>`. It has no `env_file`, fixed
container name, repository data bind mount, or public port. The runner creates
a temporary run directory and generated environment file, then writes a
redacted manifest containing Docker context, project name, labels, image
digest, source revision, mock settings, and allocated limits.

This avoids Compose merge inheritance from the production file and gives
cleanup an exact ownership proof. Cleanup SHALL enumerate only resources in
the manifest whose `com.docker.compose.project` label still matches, then run
project-scoped `down --volumes --remove-orphans`; it SHALL never prune shared
Docker resources.

### Resource-capped low-resource profile

The direct query profile contains only mock-provider, app, PostgreSQL, Redis,
and migrate. It sets explicit CPU and memory limits per long-running service,
a finite Docker log size, a loopback application port, one test user, and a
short phase duration. The runner rejects a non-default Docker context, a host
that does not meet its documented free memory/disk floor, a non-loopback port,
or a request for more than one concurrent query user.

Sampling uses a fixed cadence. A restart, readiness loss, stop marker,
container memory limit breach, or configured consecutive error-rate breach
ends the phase with a non-success status, followed by a 60-second recovery
sample before cleanup. This is preferred to using the full-harness gate because
the latter correctly rejects this host but cannot establish low-resource
runtime evidence.

### Deterministic mock and bootstrap contract

The mock provider implements model discovery, text and visual embeddings, and
OpenAI-compatible streamed/non-streamed chat with fixed delay, token count,
token interval, and explicit failure injection. The Compose environment sets
both text and visual embedding host/model/key/dimension values to this mock.

The bootstrap tool logs in with the generated temporary administrator,
provisions one isolated knowledge base, agent, and distinct temporary query
identity, then verifies both the API response and provider preflight. It stores
only credentials and raw identifiers in the temporary run root. Metrics labels
and reports use no raw identifier, question, file name, token, or pathname.

### SSE observations are the single source of query results

The query driver measures monotonic time immediately before opening the stream.
It emits exactly one outcome record and one load-tool request statistic for
each logical attempt. It records response status, first event, `accepted`,
first non-empty `token`, `done`, token count, complete wall time, and a bounded
error class. TTFT means request start through the first non-empty token; TTFB
is retained as a separate diagnostic. The server-reported `done.elapsed` is
not substituted for client wall time.

Each run writes redacted NDJSON under its temporary root. The report derives
P50/P95/P99 from those observations and separately reports all HTTP, timeout,
SSE, parser, and provider failure categories. This avoids duplicated HTTP/SSE
statistics and makes the semantics reviewable.

### Upload terminal-state diagnostic before load

The upload tool generates a new text fixture per run whose contents and name
are not reused. It records the HTTP acceptance, task/document reference,
Worker claim, provider preflight, index/chunk evidence, and terminal database
state through scoped read-only inspection. Only the repository's documented
retrieval-ready terminal state counts as success. Duplicate, preflight,
parsing, indexing/retrieval-store, timeout, and unknown terminal failures are
reported separately.

The diagnostic then uploads the identical content only once more to the same
isolated KB to prove the duplicate classification. It does not disable or
weaken duplicate protection. Any product defect discovered by this gate is a
separate change; this change only records it and prevents upload throughput
claims until it is resolved.

### Optional edge and provider boundaries

Nginx, Marker, and upload Worker are never silently included in direct query
load. Nginx may run as a single-request proxy smoke after the direct phase,
with its own resource limits and a proof that app has no host port. Real model
testing requires separate disposable credentials, an approved budget, and an
explicitly configured endpoint; absent all three it remains unexecuted.

## Risks / Trade-offs

- [Resource limits make failures more likely than on a capacity host] -> label
  every result as low-resource mock evidence, collect limits in the manifest,
  and do not extrapolate capacity.
- [Bootstrap/API drift can block the test stack] -> fail before load and retain
  only redacted diagnostics, rather than falling back to manual credentials or
  external providers.
- [A Worker failure can be confused with HTTP upload success] -> require a
  terminal-state gate and separate outcomes before reporting upload rates.
- [Collector commands can fail while the app is healthy] -> report that metric
  as unavailable with command/error class; never invent a zero value.
- [Cleanup could target shared Docker resources] -> require both manifest
  membership and exact Compose project labels before deleting anything.

## Migration Plan

1. Add profile, bootstrap/driver, collector, and contract tests without
   changing production Compose or runtime settings.
2. Run static/focused tests, Compose configuration validation, then one
   bounded direct-query execution on the current host.
3. Run the upload terminal-state diagnostic only after direct-query cleanup;
   record failure as a gate rather than modifying product behavior.
4. Keep generated evidence in the system temporary directory and clean the
   manifest-owned Docker resources. Rollback is removal of these test-only
   files; no production migration or data rollback exists.

## Open Questions

- The exact retrieval-ready `uploaded_files` terminal state and the minimal
  indexed fixture query must be confirmed from implementation during apply.
- Nginx and Marker single-request smoke are conditional on the measured host
  headroom after direct-query cleanup; they are not prerequisites for query
  evidence.
