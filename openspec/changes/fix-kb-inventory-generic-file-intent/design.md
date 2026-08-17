## Context

The inventory branch intentionally avoids RAG and the LLM for high-confidence count prompts. Its current ordered type patterns include generic Chinese inventory nouns in the Word-document bucket, so a video-only KB produces a valid but semantically incorrect zero-valued subset.

## Goals / Non-Goals

**Goals:**

- Route generic count wording to the existing all-type aggregate.
- Keep explicit file-format filters deterministic and preserve the content-question exclusion.
- Release without data migration or historical-document processing.

**Non-Goals:**

- Change the inventory response schema, RBAC, document-state semantics, RAG retrieval, or video processing.

## Decisions

- Treat `文件`, `资料`, and generic `文档` as all-type inventory nouns. They describe stock, not a file format.
- Retain the `document` type only for explicit `word`, `doc`, or `docx` wording. Video remains first in the ordered patterns, so “视频文件” remains a video request.
- Assert behavior through the public detector and streaming route using a video-only fixture. This proves both the classification and the user-visible template while retaining the no-RAG/LLM contract.
- Correct the project summary entry rather than modifying storage code: the existing document-summary path already calls `kb_dir()` before querying PostgreSQL.

## Risks / Trade-offs

- [A user means only text documents by saying “文档”] → The deterministic response returns all types with an explicit type breakdown; an explicit Word/doc/docx query retains document filtering.
- [Generic wording regresses content questions] → Tests retain “视频中有多少个零件” on the RAG path.
- [Fast-release gate rejects the candidate] → Stop at the gate; do not bypass it or alter runtime images, migrations, or cloud data.
