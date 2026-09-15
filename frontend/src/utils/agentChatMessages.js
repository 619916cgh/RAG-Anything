export function mapThreadMessages(threadId, messages = []) {
  return messages.map((message, index) => ({
    ...message,
    id: `${threadId}-${index}`,
    thinking: [],
    thinkingDone: true,
    done: true,
    imageUrl: message.imageUrl || message.image_preview || '',
  }))
}

export function shouldShowAgentProvenance(agent) {
  return agent?.include_references !== false
}
