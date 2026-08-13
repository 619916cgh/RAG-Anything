import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

const sourceRoot = path.resolve(import.meta.dirname, '..')
const readSource = relative => fs.readFileSync(path.join(sourceRoot, relative), 'utf8')

test('normal agent chat formats only completed successful assistant answers', () => {
  const page = readSource('pages/AgentChatPage.jsx')
  assert.match(page, /m\.done && !m\.error && !m\.cancelled \? formatCompleteAgentRelationMarkdown\(m\.content\) : m\.content/)
  assert.match(page, /m\.content \+ content/)
  assert.match(page, /<textarea[\s\S]*value=\{editContent\}/)
})

test('normal agent chat uses its own safe relation component and styles', () => {
  const page = readSource('pages/AgentChatPage.jsx')
  const css = readSource('index.css')
  assert.match(page, /parseAgentRelationMarker\(value\)/)
  assert.match(page, /className="agent-chat-relation"/)
  assert.doesNotMatch(page, /public-demo-relation/)
  assert.match(css, /\.agent-chat-relation \{/) 
  assert.doesNotMatch(page, /rehypeRaw/)
  assert.doesNotMatch(page, /dangerouslySetInnerHTML/)
})
