const COMPLETE_FENCED_RELATION = /```[^\r\n]*\r?\n([^\r\n]+)\r?\n```\s*\r?\n\s*((?:—\s*)?[^\r\n]*?)\s*→\s*\r?\n\s*```[^\r\n]*\r?\n([^\r\n]+)\r?\n```/g

export const isCompactAgentRelationField = value => {
  const text = String(value || '').trim()
  return text.length > 0 && text.length <= 96 && !/[\r\n`{}<>\[\]|]/.test(text)
}

const relationMarker = (source, relation, target) => `[[agent-relation:${source}|${relation}|${target}]]`

export const formatCompleteAgentRelationMarkdown = content => String(content || '').replace(/\r\n?/g, '\n')
  .replace(COMPLETE_FENCED_RELATION, (match, source, relation, target) => {
    const normalizedSource = source.trim()
    const rawRelation = relation.trim()
    const normalizedRelation = rawRelation === '' ? '→' : rawRelation.replace(/^—\s*/, '').trim()
    const normalizedTarget = target.trim()
    if (!isCompactAgentRelationField(normalizedSource) ||
      !isCompactAgentRelationField(normalizedRelation) ||
      !isCompactAgentRelationField(normalizedTarget)) return match
    return relationMarker(normalizedSource, normalizedRelation, normalizedTarget)
  })

export const parseAgentRelationMarker = value => {
  if (typeof value !== 'string') return null
  const match = value.match(/^\[\[agent-relation:([^|\]]+)\|([^|\]]+)\|([^|\]]+)\]\]$/)
  if (!match) return null
  const [, source, relation, target] = match
  if (!isCompactAgentRelationField(source) ||
    !isCompactAgentRelationField(relation) ||
    !isCompactAgentRelationField(target)) return null
  return { source, relation, target }
}
