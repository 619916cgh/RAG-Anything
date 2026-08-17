## 1. Inventory Contract

- [x] 1.1 Extract a reusable, de-duplicated knowledge-base inventory aggregator with file-type and retrieval/tag state counts.
- [x] 1.2 Add the authorized read-only `GET /knowledge/inventory` endpoint without exposing document identities or paths.
- [x] 1.3 Preserve retrieval readiness in document summaries when automatic tagging is pending or failed.

## 2. Deterministic Agent Answers

- [x] 2.1 Add high-confidence Chinese knowledge-base inventory intent recognition that excludes document-content count questions.
- [x] 2.2 Stream and persist deterministic inventory answers with compatible SSE completion metadata, bypassing RAG and LLM calls.

## 3. User Interface

- [x] 3.1 Update document-list status presentation to show retrievable content and tag enrichment independently.

## 4. Verification And Documentation

- [x] 4.1 Add focused inventory aggregation, API authorization, agent routing/SSE, and frontend status regression coverage.
- [x] 4.2 Run focused validation, update the project summary, and record the controlled production recovery verification boundary.
