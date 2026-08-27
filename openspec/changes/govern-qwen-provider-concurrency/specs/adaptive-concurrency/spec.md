## MODIFIED Requirements

### Requirement: Effective concurrency combines personal quota with global limits
The system SHALL resolve a user's saved query concurrency against platform, provider-governor, and worker hard limits and enforce the resulting effective quota through durable user leases. The provider governor SHALL remain an outer, immutable constraint shared across workers and instances; `MAX_ASYNC` SHALL be treated only as a query-local fan-out bound and SHALL be capped by the provider limit. A user's request MUST NOT mutate the stored personal quota or provider policy.

#### Scenario: Provider cap lowers available user concurrency
- **WHEN** the provider governor or another hard limit is lower than a user's saved quota or query-local `MAX_ASYNC`
- **THEN** the resolver reports the lower effective limit and constraint source, while leaving the stored user quota unchanged

#### Scenario: User leases remain distinct
- **WHEN** a query enters retrieval under a user quota and later makes a provider call
- **THEN** the user query lease remains enforced independently and the provider lease is acquired only for the outbound model call

#### Scenario: Governor is shared across instances
- **WHEN** two app instances resolve the same provider profile concurrently
- **THEN** both use the same durable provider limit and cannot replace it with process-local semaphores or per-instance counters
