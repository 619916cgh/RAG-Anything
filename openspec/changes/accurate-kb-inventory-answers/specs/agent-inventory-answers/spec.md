## ADDED Requirements

### Requirement: Agent answers knowledge-base inventory questions deterministically
The agent streaming query endpoint SHALL detect high-confidence Chinese questions about the number of knowledge-base documents or recognized file types and SHALL answer from the authorized inventory service without invoking retrieval or an LLM.

#### Scenario: Video count question
- **WHEN** a user asks an agent “知识库中有多少个视频”
- **THEN** the stream returns the inventory total and state breakdown for video documents from the agent's authorized knowledge base

#### Scenario: General document count question
- **WHEN** a user asks an agent “资料库共有多少文档”
- **THEN** the stream returns the total document inventory and per-type state breakdown

#### Scenario: Content question remains semantic retrieval
- **WHEN** a user asks “视频中有多少个零件”
- **THEN** the endpoint does not treat the question as inventory and continues through the existing RAG query path

### Requirement: Inventory answers preserve conversation streaming semantics
The deterministic inventory branch SHALL persist the user question and generated answer in the agent conversation and SHALL emit compatible token and done SSE events without fabricating retrieval citations.

#### Scenario: Completed inventory answer
- **WHEN** an inventory question is successfully answered
- **THEN** the stream persists both messages and emits the normal completion event with inventory metadata
