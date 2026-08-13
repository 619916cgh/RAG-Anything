import test from 'node:test'
import assert from 'node:assert/strict'
import { formatCompleteAgentRelationMarkdown, parseAgentRelationMarker } from './agentRelationMarkdown.js'

const relation = '```\n设备\n```\n—依赖→\n```\n工艺卡\n```'

test('formats a complete fenced relation without changing its field order', () => {
  const formatted = formatCompleteAgentRelationMarkdown(relation)
  assert.equal(formatted, '[[agent-relation:设备|依赖|工艺卡]]')
  assert.deepEqual(parseAgentRelationMarker(formatted), { source: '设备', relation: '依赖', target: '工艺卡' })
})

test('accepts CRLF, fence language labels, and arrow-only relations', () => {
  const content = '```entity\r\n  保养表格 \r\n```\r\n→\r\n```entity\r\n 技师\r\n```'
  assert.equal(formatCompleteAgentRelationMarkdown(content), '[[agent-relation:保养表格|→|技师]]')
})

test('keeps ordinary short, language-tagged, inline, and unrelated code unchanged', () => {
  const examples = [
    '```\nfoo\n```',
    '```js\nconst x = 1\n```',
    'Use `ABC` as the identifier.',
    '```\n设备\n```\n```\n工艺卡\n```',
  ]
  examples.forEach(content => assert.equal(formatCompleteAgentRelationMarkdown(content), content))
})

test('keeps incomplete streamed relation buffers unchanged until the target fence closes', () => {
  const partials = [
    '```\n设备\n```',
    '```\n设备\n```\n—依赖→',
    '```\n设备\n```\n—依赖→\n```\n工艺卡',
  ]
  partials.forEach(content => assert.equal(formatCompleteAgentRelationMarkdown(content), content))
  assert.equal(formatCompleteAgentRelationMarkdown(relation), '[[agent-relation:设备|依赖|工艺卡]]')
})

test('fails closed for empty, unsafe, and oversized relation fields', () => {
  const unsafe = [
    '```\n设备\n```\n—→\n```\n工艺卡\n```',
    '```\n设备|零件\n```\n—依赖→\n```\n工艺卡\n```',
    '```\n设备\n```\n—依赖|引用→\n```\n工艺卡\n```',
    `\`\`\`\n${'a'.repeat(97)}\n\`\`\`\n—依赖→\n\`\`\`\n工艺卡\n\`\`\``,
  ]
  unsafe.forEach(content => {
    assert.equal(formatCompleteAgentRelationMarkdown(content), content)
    assert.equal(parseAgentRelationMarker(formatCompleteAgentRelationMarkdown(content)), null)
  })
})

test('parses only a complete and field-safe agent relation marker', () => {
  assert.equal(parseAgentRelationMarker('ordinary text'), null)
  assert.equal(parseAgentRelationMarker('[[agent-relation:设备|依赖]]'), null)
  assert.equal(parseAgentRelationMarker('[[agent-relation:设备|依赖|工艺卡|extra]]'), null)
  assert.equal(parseAgentRelationMarker('[[agent-relation:设备|依赖|工艺[卡]]'), null)
})
