## Context

`prometheus-fastapi-instrumentator==7.1.0` resolves a request handler by
walking `app.routes` and reading `route.path`. Current FastAPI represents
included routers as `_IncludedRouter` objects that can match a request but do
not provide that attribute. The application currently contains included
`/api` routers, so metrics middleware crashes before a normal API response is
sent when `ENABLE_METRICS=true`.

The query timing Histogram is already registered independently in the global
Prometheus registry. The failure is HTTP request instrumentation, not query
timing registration. The application must retain its opt-in metrics contract
without adding unbounded or sensitive labels.

## Goals / Non-Goals

**Goals:**
- Expose metrics safely when enabled and permit normal included-router API
  requests to complete.
- Preserve template handler labels, status grouping, excluded metrics paths,
  the default and configured metrics paths, and the query timing Histogram.
- Test the dependency versions pinned for the application runtime.

**Non-Goals:**
- Upgrade or downgrade FastAPI, Starlette, or the instrumentator.
- Change authentication, Nginx exposure, scrape configuration, business
  routes, query timing semantics, or metric label cardinality.
- Make metrics enabled by default.

## Decisions

### Adapt route-name resolution, not router registration order

Install a narrow compatibility adapter around the instrumentator route-name
lookup. When FastAPI route contexts are available, it will resolve the first
matching context and use its template path. It will otherwise use the
instrumentator's existing lookup. The adapter must preserve failures unrelated
to this known route shape.

Moving instrumentation after `include_router()` is rejected because the
instrumentator inspects the final route collection at request time. Skipping
objects without `.path` is rejected because `should_ignore_untemplated=true`
would silently discard HTTP metrics for the application's API routes.

### Keep a small, testable metrics setup boundary

Move metrics setup into a helper that accepts a FastAPI app and reads the
existing environment contract. `server.py` will invoke the helper once. This
allows a minimal FastAPI fixture to test enabled, disabled, default-path and
custom-path behavior without importing lifecycle code that initializes
PostgreSQL and background tasks.

### Preserve bounded labels and existing registry behavior

The adapter returns route templates only, never raw request paths. Existing
`should_group_status_codes`, `should_ignore_untemplated`, excluded handler
paths, in-progress metric settings, and query timing labels remain unchanged.
The setup helper must be idempotent per application instance so reload and
test imports do not duplicate the metrics route or middleware.

## Risks / Trade-offs

- [FastAPI route-context internals change] -> Detect availability and retain
  the third-party fallback; cover the pinned runtime versions with tests.
- [Adapter masks another instrumentation failure] -> Catch only the known
  missing-path shape and let other exceptions surface.
- [Template resolution is wrong] -> Exercise an included route and a route
  with a parameter, and assert no literal parameter value appears in metrics.
- [Repeated setup duplicates metrics] -> Store setup state on the app and
  cover repeated invocation in tests.

## Migration Plan

The change is code-only and backward compatible. Deploy it with the existing
application image build, then verify `/metrics` only where it was already
enabled, a normal `/api` endpoint, and the query phase Histogram. Rollback is
the previous application image; no data migration or volume operation is
needed.

## Open Questions

- None. The pinned runtime dependency combination is the implementation and
  test target; dependency changes require a separate change.
