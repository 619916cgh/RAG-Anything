## ADDED Requirements

### Requirement: Detail reads propagate cancellation
The detail-page document-summary and statistics requests SHALL receive the active caller `AbortSignal`, and an aborted caller SHALL stop awaiting obsolete work.

#### Scenario: Search cancellation reaches both requests
- **WHEN** a detail-page search is superseded before document and statistics responses complete
- **THEN** both underlying fetch calls SHALL observe the caller signal
- **AND** the superseded result SHALL not update page state or caches

### Requirement: Shared requests protect surviving consumers
The shared prefetch layer SHALL track active consumers and SHALL abort the underlying request only after the last pending consumer releases it.

#### Scenario: One consumer aborts
- **WHEN** one of two consumers aborts while a shared request is pending
- **THEN** that consumer SHALL reject with an abort error
- **AND** the underlying request SHALL remain active for the surviving consumer

#### Scenario: All consumers abort
- **WHEN** every pending consumer releases a shared request before it settles
- **THEN** the underlying request SHALL be aborted
- **AND** the in-flight entry SHALL be removed without poisoning a later request

### Requirement: Aborted work cannot populate scoped caches
The detail cache SHALL commit only successful results whose auth generation, KB, page, page size, query, and invalidation generation still match the request context.

#### Scenario: Aborted or invalidated response settles
- **WHEN** a request is aborted, fails, or settles after its cache scope is invalidated
- **THEN** no document page or statistics cache entry SHALL be written

### Requirement: Detail reads do not perform global terminal cleanup
Reading paginated document summaries SHALL not delete terminal task rows globally as a side effect.

#### Scenario: Ordinary paginated page read
- **WHEN** an authorized user reads or searches a document page
- **THEN** the route SHALL query visible runtime tasks without invoking global terminal cleanup
- **AND** legacy full-list cleanup behavior SHALL remain unchanged

### Requirement: Authorization precedes cancellable data work
The detail endpoint SHALL complete object-level KB authorization before starting document, task, tag-health, or statistics reads.

#### Scenario: Unauthorized request
- **WHEN** a caller lacks read access to the requested KB
- **THEN** the endpoint SHALL return 403
- **AND** no cancellable data query or enrichment SHALL be started
