## ADDED Requirements

### Requirement: Completed agent relations render compactly
The authenticated agent chat SHALL render a complete, bounded fenced source-relation-target structure as one compact relationship row after an assistant answer has completed. The row MUST display source, relation, and target as text and MUST wrap without horizontal overflow.

#### Scenario: Completed knowledge-graph relation
- **WHEN** a completed assistant answer contains a valid fenced source entity, a non-empty relation arrow segment, and a valid fenced target entity
- **THEN** the authenticated chat renders one compact relationship row in source-relation-target order

#### Scenario: Stream reaches terminal completion
- **WHEN** the final target fence arrives and the assistant message receives its terminal completion event
- **THEN** the same answer changes from ordinary streamed Markdown to the compact relationship row without changing the stored message content

### Requirement: Code and incomplete content remain unchanged
The authenticated agent chat MUST leave ordinary Markdown code and incomplete relation-shaped content unchanged.

#### Scenario: Ordinary short code block
- **WHEN** an answer contains an isolated fenced short code block or a fenced block with a language identifier
- **THEN** the chat renders it through the existing code-block renderer

#### Scenario: Incomplete or malformed relation
- **WHEN** a streamed, cancelled, failed, or completed answer lacks a complete valid source-relation-target structure, or any field is empty, multiline, too long, or contains marker delimiters
- **THEN** the chat renders the original Markdown without a compact relationship row

### Requirement: Relation display is presentation-only
The relation display transformation SHALL be limited to completed assistant-message presentation.

#### Scenario: Existing chat behavior
- **WHEN** a user streams, views, edits, retries, saves, or reloads a normal agent conversation
- **THEN** the original message text, SSE payload, persistence, citations, and media behavior remain unchanged
