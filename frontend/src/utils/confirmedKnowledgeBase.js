export function getKnowledgeBaseItems(response) {
  return Array.isArray(response?.knowledge_bases) ? response.knowledge_bases : []
}

export function getConfirmedKnowledgeBase(response, kbName) {
  if (!kbName) return null
  return getKnowledgeBaseItems(response).find(item => item?.name === kbName) || null
}

export function isKnowledgeBaseConfirmed(response, kbName) {
  return getConfirmedKnowledgeBase(response, kbName) !== null
}
