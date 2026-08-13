## ADDED Requirements

### Requirement: Authenticated chat may compact the relationship section
The authenticated chat interface MAY present a complete, valid relationship structure from the existing relationship section as a compact source-relation-target row. This presentation MUST preserve the underlying answer text and MUST NOT alter the required answer ordering, source citations, or relationship semantics.

#### Scenario: Answer includes a valid relationship structure
- **WHEN** a completed authenticated agent answer contains a complete valid relationship structure
- **THEN** the chat may render that structure as a compact row while preserving the answer's original text for all non-presentation uses
