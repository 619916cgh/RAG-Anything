## Context

`AgentChatPage` already renders stored and streamed assistant messages with safe `ReactMarkdown`. Knowledge-graph answers can emit a source entity, a relation arrow, and a target entity in three adjacent fenced Markdown blocks. The public demo currently recognizes a wider set of compact entities, but authenticated chat also supports code explanations and historical code snippets.

## Goals / Non-Goals

**Goals:**
- Compact only a complete, bounded relation structure in completed authenticated assistant answers.
- Keep relation rows readable in the existing light and dark chat themes.
- Preserve the original answer string for streaming, editing, persistence, citations, and retries.

**Non-Goals:**
- Do not compact isolated short fenced blocks, inline code, multiline code, or incomplete streamed output.
- Do not change API payloads, stored conversations, RAG retrieval, model prompts, or public-demo rendering.

## Decisions

- Use a frontend-only pure formatter that replaces only complete fenced `source -> relation -> target` patterns with an internal marker. It validates every field after trimming: one line, 1-96 characters, and no marker delimiters or code-structure characters. This is narrower than the public-demo formatter so short shell, SQL, configuration, and example code remain code.
- Apply the formatter only when `message.done` is true. During streaming, the existing Markdown renderer receives the original buffer, so partial fences and relation markers never flash or alter token rendering. Historical messages use the same completed-message presentation without mutating their stored contents.
- Parse only a complete internal marker in the authenticated chat paragraph renderer and render text-only relation elements with agent-chat-scoped classes. This preserves ReactMarkdown's default raw-HTML safety and existing link, table, code, citation, and media components.
- Keep styles local to the authenticated chat namespace rather than reuse `public-demo-*` classes. The relation row uses the established sky/cloud palette and wrapping rules for the 80%-width chat column.

## Risks / Trade-offs

- [LLM output differs from the strict structure] -> Leave it as ordinary Markdown rather than guess.
- [Relation values are long or malformed] -> Fail closed and leave the original code blocks unchanged.
- [Streaming completion changes visual layout once] -> Defer conversion until terminal completion; this avoids malformed intermediate rendering at the cost of one intentional final reflow.

## Migration Plan

1. Deploy as a frontend-only change with no migration or backend restart requirement beyond the normal rebuilt frontend asset rollout.
2. Roll back by removing the formatter call and relation component; conversation records require no data migration because their original text is never changed.

## Open Questions

- None.
