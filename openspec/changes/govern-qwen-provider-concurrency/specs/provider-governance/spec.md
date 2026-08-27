## ADDED Requirements

### Requirement: Provider policy is private, validated, and fingerprinted
The system SHALL resolve each outbound LLM/VLM call to an immutable server-side provider profile fingerprint and a validated private governance policy. The initial Qwen policy SHALL default to `concurrency_limit=40` and `queue_timeout_seconds=10`; RPM/TPM SHALL remain unconfigured until controlled quota evidence is recorded. Governance fields MUST NOT appear in public model/profile/settings responses.

#### Scenario: Default Qwen policy
- **WHEN** a Qwen profile has no private override and no verified RPM/TPM record
- **THEN** the server uses concurrency 40 and queue timeout 10, leaves RPM/TPM unenforced, and returns no private policy fields to clients

#### Scenario: Invalid policy is rejected
- **WHEN** a private policy contains a non-positive concurrency, an invalid timeout, or retry values outside configured bounds
- **THEN** profile activation fails with a sanitized configuration error and no provider call is started

#### Scenario: Fingerprint changes create a separate governor
- **WHEN** provider, model, capability, or policy version changes
- **THEN** the canonical fingerprint changes and calls do not consume leases from the previous profile

### Requirement: Provider leases are durable and atomic across instances
The system SHALL enforce the profile concurrency limit with PostgreSQL-backed leases that are atomic across workers and app instances. Leases SHALL have an expiry/TTL, owner-checked heartbeat, idempotent release, and recovery of expired rows. An in-process semaphore MUST NOT be the provider-wide enforcement mechanism.

#### Scenario: Two app instances share one cap
- **WHEN** two instances concurrently acquire leases for the same fingerprint at the configured limit
- **THEN** the combined active leases never exceed that limit

#### Scenario: Expired lease is reclaimed
- **WHEN** a worker stops heartbeating and its lease TTL elapses
- **THEN** a later acquisition reclaims the expired lease and the stale owner cannot release or heartbeat it as current

#### Scenario: Cancellation releases ownership
- **WHEN** a request is cancelled while holding a provider lease
- **THEN** the lease is released or becomes reclaimable immediately, and no slot remains permanently occupied

### Requirement: Admission is bounded, prioritized, cancellable, and FIFO within priority
The governor SHALL queue calls that cannot acquire a lease immediately up to a finite configured queue capacity, order them by interactive-query priority before upload/background priority and FIFO sequence within each priority, and enforce the profile queue timeout. A timed-out or full queue SHALL return the uniform `provider_busy` outcome; a cancelled call SHALL leave no waiter row. Non-streaming HTTP callers SHALL receive a sanitized 429 response with code `provider_busy`; an already accepted SSE caller SHALL receive an allowlisted error event with the same code and then stream termination.

#### Scenario: Query precedes background work
- **WHEN** a query and a background model task wait for the same free slot
- **THEN** the query is admitted first regardless of enqueue time

#### Scenario: FIFO within query priority
- **WHEN** two query calls wait for capacity in sequence
- **THEN** the earlier waiter is admitted first

#### Scenario: Queue timeout
- **WHEN** a call waits longer than 10 seconds without capacity
- **THEN** it ends with `provider_busy`, increments the redacted rejection metric, and does not start an outbound request

#### Scenario: Queue cancellation
- **WHEN** the client disconnects or cancels while waiting
- **THEN** the waiter is removed or marked cancelled and a later waiter can use the next available slot

#### Scenario: Queue capacity is full
- **WHEN** a new call arrives after the finite waiter capacity is exhausted
- **THEN** it receives the sanitized `provider_busy` outcome immediately and no waiter row is created

### Requirement: Each outbound call is governed independently
The system SHALL acquire and release a provider lease around each actual LLM/VLM network call, including calls from agent, RAG/rerank/citation repair, contextual, VLM/image, and agentic paths. The SSE lifetime MUST NOT hold a provider slot. Query-local `MAX_ASYNC` SHALL be capped at the provider limit without changing the stored user quota.

#### Scenario: Multiple calls in one SSE query
- **WHEN** a query performs retrieval followed by two sequential model calls
- **THEN** each network call obtains its own lease and the slot is available between calls

#### Scenario: Fan-out is capped
- **WHEN** a query requests a `MAX_ASYNC` greater than the provider concurrency limit
- **THEN** effective fan-out is the provider limit and no more than that many provider calls are started

#### Scenario: All known entry points are wrapped
- **WHEN** the model-entry inventory test runs
- **THEN** every registered LLM/VLM construction path is injected with the governor wrapper

### Requirement: Retry policy is pre-first-token and bounded
The wrapper SHALL retry at most the configured number of attempts only before the first streamed token for 429, 408, 409, timeouts, and confirmed 503 responses. It SHALL honor a valid bounded `Retry-After` or use capped jittered exponential backoff. Authentication, parameter, and other 4xx failures SHALL NOT be retried, and no failure after the first token SHALL be retried.

#### Scenario: Eligible 429 with Retry-After
- **WHEN** a non-streaming-started call receives a 429 with a legal `Retry-After` below the configured maximum
- **THEN** the wrapper waits no longer than that bounded delay and retries within the attempt limit

#### Scenario: Retry reacquires a lease
- **WHEN** an eligible failure occurs before the first token and a retry is scheduled
- **THEN** the failed attempt releases its lease before backoff and the retry acquires a fresh lease

#### Scenario: Invalid Retry-After is capped
- **WHEN** `Retry-After` is missing, malformed, negative, or above the configured maximum
- **THEN** the wrapper uses capped jittered backoff and never waits beyond the configured maximum

#### Scenario: Streaming failure is terminal
- **WHEN** a provider error occurs after the first token has been emitted
- **THEN** the wrapper does not retry and releases the lease with a streamed-failure outcome

#### Scenario: Non-retryable 4xx
- **WHEN** authentication or parameter validation returns a 4xx response
- **THEN** the wrapper fails once without retrying

#### Scenario: Cancellation interrupts backoff
- **WHEN** a caller is cancelled while an eligible retry is sleeping
- **THEN** backoff stops, no duplicate outbound call starts, and all lease/waiter state is released

### Requirement: Circuit breaker limits repeated provider failure
The system SHALL maintain circuit state per provider fingerprint with closed, open, and half-open states. After the configured failure threshold it SHALL reject new calls while open, permit at most one probe after cooldown, and close only after a successful probe.

#### Scenario: Circuit opens
- **WHEN** the configured rolling/consecutive failure threshold is reached
- **THEN** the fingerprint circuit opens and new calls receive a sanitized unavailable/busy outcome without contacting Qwen

#### Scenario: Single half-open probe
- **WHEN** the open cooldown expires and multiple calls arrive
- **THEN** exactly one call is admitted as the half-open probe and the others remain rejected or queued

#### Scenario: Successful probe closes circuit
- **WHEN** the half-open probe succeeds before streaming begins
- **THEN** the circuit returns to closed and subsequent calls may be admitted

### Requirement: Metrics and logs are low-cardinality and redacted
The system SHALL expose aggregate provider metrics for active calls, queue wait, rejects/cancellations/timeouts, outcomes (success/429/timeout/5xx), retries and reasons, circuit state, call/first-token latency, and usage reservation/settlement only when upstream usage is returned. Labels and logs MUST exclude query text, answer/token content, secrets, raw endpoints, and user identifiers.

#### Scenario: Metric labels are sanitized
- **WHEN** provider metrics are scraped after a call
- **THEN** labels contain only the documented provider/capability/fingerprint-hash/priority/outcome fields and no sensitive values

#### Scenario: Usage absent
- **WHEN** the upstream response contains no usage data
- **THEN** TPM reservation/settlement is marked unconfigured or unknown and no estimated token gate is enforced

### Requirement: Real-Qwen acceptance is isolated and staged
The system SHALL provide an acceptance procedure using disposable App/PostgreSQL/Redis/Nginx resources, 50 synthetic users, an isolated knowledge base, and a restricted key. Stages SHALL run strictly `10 -> 20 -> 30 -> 40 -> 50`, stop at the first hard failure, and record SSE ordering, TTFT P95 <= 5 seconds, full-answer P95 <= 15 seconds, bounded queue wait, provider/error/retry outcomes, resource/restart/pool health, ten-minute recovery, 120 health samples, and cleanup. Passing 50 VU SHALL be scoped to the measured model, quota, prompt, KB, and topology.

#### Scenario: Failed rung stops ladder
- **WHEN** any stage has a hard error, unbounded queue growth, resource breach, or P95 violation
- **THEN** later stages do not run and the report classifies the failure domain

#### Scenario: Passing 50 VU is scoped
- **WHEN** all five stages pass under one controlled profile and quota
- **THEN** the result is recorded as profile-specific capacity evidence and does not authorize other models or production traffic
