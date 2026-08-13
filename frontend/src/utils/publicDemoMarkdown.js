const COMPACT_RELATION = /```[^\n]*\n([^\n]+)\n```\s*\n\s*[—-]\s*([^\n→]+?)\s*[→>]\s*\n\s*```[^\n]*\n([^\n]+)\n```/g
const COMPACT_ARROW_RELATION = /```[^\n]*\n([^\n]+)\n```\s*\n\s*(?:[—-]\s*)?→\s*\n\s*```[^\n]*\n([^\n]+)\n```/g
const SINGLE_LINE_CODE_BLOCK = /```[^\r\n]*\r?\n\s*([^\r\n]+?)\s*\r?\n\s*```/g

export const isCompactEntity = value => {
  const text = String(value || '').trim()
  return text.length > 0 && text.length <= 96 && !/[\r\n`{}<>|]/.test(text)
}

const entityMarker = value => `[[demo-entity:${value.trim()}]]`

export const formatPublicDemoMarkdown = content => String(content || '').replace(/\r\n?/g, '\n')
  .replace(COMPACT_RELATION, (match, source, relation, target) => {
    if (!isCompactEntity(source) || !isCompactEntity(target)) return match
    const label = relation.trim()
    return label ? `[[demo-relation:${source.trim()}|${label}|${target.trim()}]]` : match
  })
  .replace(COMPACT_ARROW_RELATION, (match, source, target) => {
    if (!isCompactEntity(source) || !isCompactEntity(target)) return match
    return `[[demo-relation:${source.trim()}|→|${target.trim()}]]`
  })
  .replace(SINGLE_LINE_CODE_BLOCK, (match, entity) => isCompactEntity(entity) ? entityMarker(entity) : match)

export const parseDemoDisplayMarker = value => {
  if (typeof value !== 'string') return null
  const relation = value.match(/^\[\[demo-relation:([^|\]]+)\|([^|\]]+)\|([^\]]+)\]\]$/)
  if (relation) return { type: 'relation', source: relation[1], relation: relation[2], target: relation[3] }
  const entity = value.match(/^\[\[demo-entity:([^\]]+)\]\]$/)
  return entity ? { type: 'entity', value: entity[1] } : null
}
