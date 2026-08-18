## Why

The isolated query performance run cannot enable `ENABLE_METRICS` because
`prometheus-fastapi-instrumentator==7.1.0` assumes every request route has a
`.path`. Current FastAPI retains `_IncludedRouter` objects that can match a
request but do not expose that attribute, so a normal `/api/...` request
crashes during metrics handler resolution. This blocks trustworthy
application-side performance evidence.

## What Changes

- Add a narrow route-name compatibility adapter for FastAPI included routers
  when `ENABLE_METRICS=true`; it must preserve template paths for HTTP metric
  labels instead of treating `/api/...` routes as untemplated.
- Preserve `ENABLE_METRICS`, `METRICS_PATH`, the default `/metrics` endpoint,
  existing instrumentator options, and the
  `rag_agent_query_phase_duration_seconds` Histogram with its current labels.
- Add focused regression coverage for enabled and disabled metrics, default
  and custom metrics paths, a normal included `/api/...` request, and a route
  with a path parameter.
- Keep metrics opt-in and its existing endpoint exposure semantics. Do not add
  request bodies, credentials, raw paths, user/KB/document identifiers, or
  exception text to metric labels.
- Validate the implementation against the lockfile's FastAPI and
  `prometheus-fastapi-instrumentator` versions; do not broaden this change to
  an unverified dependency upgrade or downgrade.

## Capabilities

### New Capabilities
- `runtime-metrics-instrumentation`: Safe opt-in Prometheus metrics exposure
  for the running FastAPI application and its registered routers.

### Modified Capabilities
- None.

## Impact

Affected areas are `server.py`, focused backend tests, and the isolated
performance environment validation path. The public metrics endpoint, metric
names, environment-variable names, status grouping, untemplated-route
protection, and existing scrape configuration remain compatible.
