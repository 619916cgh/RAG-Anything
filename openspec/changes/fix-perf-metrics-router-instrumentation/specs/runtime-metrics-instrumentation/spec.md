## ADDED Requirements

### Requirement: Compatible opt-in HTTP instrumentation
When `ENABLE_METRICS=true`, the system SHALL instrument requests to included
FastAPI routers without assuming every matching route object has a `.path`
attribute. It SHALL use a stable route template for handler attribution and
shall preserve the existing status grouping and untemplated-route behavior.

#### Scenario: Included API route is instrumented
- **WHEN** metrics are enabled and a request targets an included `/api` route
- **THEN** the request returns its normal response without an instrumentation
  exception and the HTTP metrics use the route template rather than a raw URL

#### Scenario: Parameterized route has bounded attribution
- **WHEN** metrics are enabled and a request targets an included route with a
  path parameter
- **THEN** the scraped metrics do not contain the concrete parameter value as
  a handler label

### Requirement: Metrics configuration compatibility
The system SHALL preserve `ENABLE_METRICS`, `METRICS_PATH`, the default
`/metrics` path, and exclusion of the configured metrics path from HTTP
request metrics. It SHALL expose no metrics route when metrics are disabled.

#### Scenario: Default path is enabled
- **WHEN** `ENABLE_METRICS=true` and `METRICS_PATH` is unset
- **THEN** `/metrics` returns a Prometheus response and contains the existing
  query phase metric

#### Scenario: Custom path is enabled
- **WHEN** `ENABLE_METRICS=true` and `METRICS_PATH` is configured
- **THEN** the configured path returns a Prometheus response and the default
  path is not additionally registered by this setup

#### Scenario: Metrics remain opt-in
- **WHEN** `ENABLE_METRICS` is disabled
- **THEN** a normal API route remains usable and neither the default nor a
  configured metrics route is exposed

### Requirement: Query timing scrape compatibility
The system SHALL preserve `rag_agent_query_phase_duration_seconds` and its
existing `phase`, `outcome`, `cache_status`, and `channel` labels in the
Prometheus registry.

#### Scenario: Query timing metric is scraped
- **WHEN** metrics are enabled and a content-free query timing observation is
  recorded
- **THEN** the configured metrics response contains the query timing metric
  with its established label schema

### Requirement: Metrics instrumentation safety
The system SHALL not add request bodies, credentials, raw dynamic paths,
user identifiers, knowledge-base identifiers, document identifiers, or
exception text as metric labels. Repeated setup on the same application
instance SHALL not add duplicate metrics routes or middleware.

#### Scenario: Repeated setup is idempotent
- **WHEN** runtime metrics setup is invoked more than once for one FastAPI app
- **THEN** the app exposes one configured metrics route and does not raise a
  duplicate collector or route-registration error
