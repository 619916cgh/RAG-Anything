import assert from 'node:assert/strict'
import test from 'node:test'
import {
  getKnowledgeBaseDisplayName,
  isOpaqueKnowledgeBaseName,
  UNKNOWN_KNOWLEDGE_BASE_NAME,
} from './kbDisplayName.js'

test('recognizes only 32-character hexadecimal KB identifiers as opaque', () => {
  assert.equal(isOpaqueKnowledgeBaseName('0123456789abcdef0123456789ABCDEF'), true)
  assert.equal(isOpaqueKnowledgeBaseName('0123456789abcdef0123456789abcdeg'), false)
  assert.equal(isOpaqueKnowledgeBaseName('a'.repeat(31)), false)
})

test('uses a KB display name and never falls back to an opaque internal name', () => {
  assert.equal(getKnowledgeBaseDisplayName({ name: 'kb-1', label: '课程资料' }), '课程资料')
  assert.equal(
    getKnowledgeBaseDisplayName({ name: '0123456789abcdef0123456789abcdef', label: '0123456789abcdef0123456789abcdef' }),
    UNKNOWN_KNOWLEDGE_BASE_NAME,
  )
  assert.equal(
    getKnowledgeBaseDisplayName({ kb_name: '0123456789abcdef0123456789abcdef' }),
    UNKNOWN_KNOWLEDGE_BASE_NAME,
  )
})
