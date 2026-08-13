## Why

Normal agent answers can contain knowledge-graph entities and relations as adjacent fenced blocks. Rendering those blocks independently consumes unnecessary vertical space and obscures their connection, while broadly compacting code blocks would damage legitimate code answers.

## What Changes

- Add a completed-answer display transformation for strict fenced entity-relation-entity patterns in the authenticated agent chat.
- Render recognized relations as compact, accessible inline relationship rows using the authenticated chat's existing visual system.
- Preserve all ordinary and incomplete Markdown code blocks, streamed buffers, stored message text, editing behavior, citations, and media behavior.

## Capabilities

### New Capabilities
- `agent-relation-display`: Safe compact rendering of complete knowledge-graph relation structures in authenticated agent answers.

### Modified Capabilities

- `answer-format-spec`: The existing relationship section can be presented as a compact relationship row without changing answer content.

## Impact

- Affects `frontend/src/pages/AgentChatPage.jsx`, a frontend-only Markdown utility, scoped authenticated-chat styles, and unit/source-contract tests.
- Does not change APIs, SSE payloads, conversation persistence, retrieval, prompt templates, knowledge-base data, or authorization.
