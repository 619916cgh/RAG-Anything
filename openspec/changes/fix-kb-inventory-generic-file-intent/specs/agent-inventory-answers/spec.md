## MODIFIED Requirements

### Requirement: Deterministic inventory answers
The system SHALL recognize high-confidence Chinese knowledge-base inventory questions and answer them from the authorized aggregate inventory without invoking retrieval, a model profile, quota acquisition, RAG, or an LLM. Explicit file-format questions SHALL filter the aggregate by that format. Generic inventory nouns including `文件`, `资料`, and `文档` SHALL return the all-type aggregate and its non-empty type breakdown. The system SHALL preserve ordinary RAG handling for document-content count questions.

#### Scenario: Authorized generic inventory question
- **WHEN** an authorized caller asks a generic knowledge-base file-count question
- **THEN** the service SHALL save the user and deterministic assistant messages, emit compatible SSE `agent_info`, `token`, and `done` events, and return the all-type aggregate without citations

#### Scenario: Explicit file-format inventory question
- **WHEN** an authorized caller asks for a specific recognized file format such as video, PDF, Word/doc/docx, spreadsheet, presentation, image, or audio
- **THEN** the service SHALL return only that format's aggregate inventory

#### Scenario: Document-content count question
- **WHEN** a caller asks a count question about items inside a video or document without a knowledge-base inventory object
- **THEN** the request SHALL continue through the ordinary RAG path
