export const UNKNOWN_GRAPH_ENTITY_NAME = '未命名实体'

export function getGraphNodeDisplayName(node) {
  const label = typeof node?.label === 'string' ? node.label.trim() : ''
  return label || UNKNOWN_GRAPH_ENTITY_NAME
}

export function getGraphConnectionDisplayName(nodes, entityId) {
  return getGraphNodeDisplayName((nodes || []).find(node => node?.id === entityId))
}
