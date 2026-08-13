import test from 'node:test'
import assert from 'node:assert/strict'
import { formatPublicDemoMarkdown, isCompactEntity, parseDemoDisplayMarker } from './publicDemoMarkdown.js'

test('formats a short fenced entity relationship as one compact relation marker', () => {
  const content = '```\n技师\n```\n—依据→\n```\n文件\n```'
  assert.equal(formatPublicDemoMarkdown(content), '[[demo-relation:技师|依据|文件]]')
  assert.deepEqual(parseDemoDisplayMarker(formatPublicDemoMarkdown(content)), {
    type: 'relation', source: '技师', relation: '依据', target: '文件',
  })
})

test('formats the arrow-only relationship shape emitted by knowledge answers', () => {
  const content = '```\n保养表格\n```\n→\n```\n技师\n```\n：技师根据保养表格进行分工；'
  assert.equal(formatPublicDemoMarkdown(content), '[[demo-relation:保养表格|→|技师]]\n：技师根据保养表格进行分工；')
})

test('formats remaining short fenced entities without changing ordinary code', () => {
  assert.equal(formatPublicDemoMarkdown('```\n剪贴板\n```'), '[[demo-entity:剪贴板]]')
  const source = '```js\nconst answer = 42\nconsole.log(answer)\n```'
  assert.equal(formatPublicDemoMarkdown(source), source)
})

test('accepts CRLF and padded single-line fences while preserving multiline code', () => {
  assert.equal(formatPublicDemoMarkdown('```\r\n  检测平台  \r\n```'), '[[demo-entity:检测平台]]')
  assert.equal(isCompactEntity('检测平台'), true)
  assert.equal(isCompactEntity('line one\nline two'), false)
})

test('recognises only complete public demo display markers', () => {
  assert.equal(parseDemoDisplayMarker('普通文本'), null)
  assert.equal(parseDemoDisplayMarker('[[demo-relation:技师|依据]]'), null)
})
