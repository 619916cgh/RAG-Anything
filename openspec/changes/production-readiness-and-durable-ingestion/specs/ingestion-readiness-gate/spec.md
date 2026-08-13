## ADDED Requirements

### Requirement: Completed uploads have durable retrieval artifacts
For a PostgreSQL-backed strict readiness check, an upload task SHALL be marked `completed` only when the target document has non-empty valid text chunks and every expected chunk has a vector in the KB-bound PostgreSQL vector table. The check SHALL be fenced by the active task ownership state.

#### Scenario: Complete text and vector coverage
- **WHEN** a Worker finishes a document whose expected chunks and vectors are present in authoritative PostgreSQL storage
- **THEN** the task may be marked `completed` and the readiness result records matching expected, text, and vector counts

#### Scenario: Text exists but vectors are incomplete
- **WHEN** a Worker finishes a document with missing or zero vector coverage
- **THEN** the task SHALL not be marked `completed` and SHALL receive the recoverable `retrieval_not_ready` outcome with bounded reason/count fields

#### Scenario: Authoritative storage is unavailable
- **WHEN** strict readiness cannot read the document or KB vector table from PostgreSQL
- **THEN** the task SHALL fail closed as recoverable and SHALL NOT use JSON or NanoVectorDB fallback as success evidence

### Requirement: Optional enrichment is reported independently
Graph, tag, and optional multimodal processing failures SHALL be represented as document health degradation when text/vector readiness is complete and SHALL NOT convert a retrieval-ready upload into a failed ingestion task.

#### Scenario: Graph enrichment fails after vectors persist
- **WHEN** durable text and vector readiness succeeds but graph enrichment fails
- **THEN** the upload remains completed and the document health is `degraded` with a repairable stage

## MODIFIED Requirements

### Requirement: Worker subprocess correctly reports all failures
The document processing subprocess (`process_worker.py`) SHALL exit non-zero when durable retrieval readiness fails. A failed optional enrichment stage alone SHALL not make the subprocess fail when text/vector readiness succeeds.

#### Scenario: Retrieval readiness fails
- **WHEN** the Worker completes parsing but the terminal strict readiness check is not ready
- **THEN** it SHALL emit a structured retryable readiness failure and exit non-zero

#### Scenario: Optional enrichment fails after readiness succeeds
- **WHEN** graph or tag enrichment fails after text/vector readiness succeeds
- **THEN** the Worker may exit zero and the durable document health SHALL remain degraded
