export const UNKNOWN_KNOWLEDGE_BASE_NAME = '未命名知识库'

export function isOpaqueKnowledgeBaseName(value) {
  return /^[0-9a-f]{32}$/i.test(String(value || '').trim())
}

export function getKnowledgeBaseDisplayName(knowledgeBase) {
  const internalName = String(
    knowledgeBase?.name ?? knowledgeBase?.kb_name ?? ''
  ).trim()
  const displayName = String(
    knowledgeBase?.kb_display_name
    ?? knowledgeBase?.display_name
    ?? knowledgeBase?.label
    ?? ''
  ).trim()

  if (!displayName) return UNKNOWN_KNOWLEDGE_BASE_NAME
  if (displayName === internalName && isOpaqueKnowledgeBaseName(internalName)) {
    return UNKNOWN_KNOWLEDGE_BASE_NAME
  }
  return displayName
}
