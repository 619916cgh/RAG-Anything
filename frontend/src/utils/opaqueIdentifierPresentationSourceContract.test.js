import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'

const sourceRoot = path.resolve(import.meta.dirname, '..')
const page = relative => fs.readFileSync(path.join(sourceRoot, relative), 'utf8')

test('user-facing agent and share surfaces use safe KB display names', () => {
  const agents = page('pages/AgentsPage.jsx')
  const chat = page('pages/AgentChatPage.jsx')
  const shares = page('pages/DemoSharesPage.jsx')

  assert.doesNotMatch(agents, /ID:\s*\{agent\.id\}/)
  assert.match(agents, /getKnowledgeBaseDisplayName\(agent\)/)
  assert.match(chat, /getKnowledgeBaseDisplayName\(agent\)/)
  assert.match(shares, /getKnowledgeBaseDisplayName\(share\)/)
  assert.doesNotMatch(shares, /<strong>\{share\.agent_id\}/)
})

test('knowledge and graph fallbacks do not render internal identifiers', () => {
  const knowledge = page('pages/KnowledgePage.jsx')
  const graph = page('pages/KnowledgeDetailPage.jsx')

  assert.match(knowledge, /getKnowledgeBaseDisplayName\(deleteTarget\)/)
  assert.match(graph, /getGraphNodeDisplayName\(d\)/)
  assert.match(graph, /getGraphConnectionDisplayName\(graph\.nodes, c\.other\)/)
  assert.doesNotMatch(graph, /node = \{ id: e\.name, label: e\.name/)
})
