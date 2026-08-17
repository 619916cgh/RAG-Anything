## Why

The deterministic inventory answer treats generic Chinese words such as "文件" and "资料" as the `document` file type. A video-only knowledge base therefore answers that it has zero documents when the user asks for its total file count.

## What Changes

- Classify unqualified knowledge-base count prompts using "文件"、"资料"、"文档" as all-type inventory requests.
- Retain file-type filtering only for explicit formats, including video, PDF, Word/doc/docx, spreadsheets, presentations, images, and audio.
- Add regression coverage for generic prompts over a video-only inventory and preserve RAG handling for content-count questions.
- Correct the project summary diagnosis: the existing `kb_dir()` mapping already resolves logical knowledge-base names to LightRAG workspaces.

## Capabilities

### New Capabilities

- `generic-kb-inventory-intent`: Deterministic handling for generic Chinese knowledge-base file-count prompts.

### Modified Capabilities

- `agent-inventory-answers`: Generic inventory wording returns an all-type aggregate instead of a document-format subset.

## Impact

- `raganything/routers/agent.py` intent recognition and `tests/test_agent_inventory_answers.py`.
- No API shape, database schema, uploaded document, Worker, video index, or frontend change.
