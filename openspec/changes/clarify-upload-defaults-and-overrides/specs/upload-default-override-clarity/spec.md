## ADDED Requirements

### Requirement: Upload UI distinguishes persistent defaults from one-time overrides
The knowledge-base detail page SHALL present the KB ingestion form as long-term upload defaults and SHALL present the effective strategy in the upload panel without rendering a strategy selector by default. A writer SHALL be able to explicitly expand a one-time override control.

#### Scenario: Normal upload inherits the effective default
- **WHEN** a writer opens the upload panel without enabling a temporary override
- **THEN** the panel shows the effective strategy and its source, and the upload request omits `chunking_strategy`

#### Scenario: Writer enables a one-time override
- **WHEN** a writer activates the temporary override control and selects a strategy
- **THEN** the next single-file or batch submission sends that strategy without changing the KB ingestion defaults

### Requirement: One-time overrides have explicit lifecycle
The client SHALL apply a temporary strategy only to the next explicit submit action, SHALL clear and collapse it after the upload request resolves, and SHALL retain it when the request rejects.

#### Scenario: Accepted batch clears the override
- **WHEN** a batch upload request resolves after the server accepts it
- **THEN** the temporary strategy is cleared before a later submission and the panel returns to the effective default summary

#### Scenario: Rejected request retains the override
- **WHEN** a single-file or batch upload request rejects
- **THEN** the selected temporary strategy remains available for retry

### Requirement: Batch snapshots retain their original override layer
The batch upload route SHALL resolve every file from the same immutable request override and SHALL not reuse an earlier file's effective strategy as a request override for a later file.

#### Scenario: Batch without a strategy parameter
- **WHEN** a batch upload omits `chunking_strategy`
- **THEN** every file snapshot resolves from the KB and personal defaults without a request-level strategy override
