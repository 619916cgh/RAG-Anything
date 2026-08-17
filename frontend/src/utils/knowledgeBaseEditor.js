export function getKnowledgeBaseEditCapabilities(kb) {
  const capabilities = kb?.capabilities || {}
  return {
    rename: capabilities.rename === true,
  }
}

export function canEditKnowledgeBase(kb) {
  const capabilities = getKnowledgeBaseEditCapabilities(kb)
  return capabilities.rename
}

export function getKnowledgeBaseEditorTabs(kb) {
  const capabilities = getKnowledgeBaseEditCapabilities(kb)
  return capabilities.rename ? [{ id: 'details', label: '基本信息' }] : []
}
