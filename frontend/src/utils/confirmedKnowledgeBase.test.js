import assert from 'node:assert/strict'
import test from 'node:test'

import { getConfirmedKnowledgeBase, getKnowledgeBaseItems, isKnowledgeBaseConfirmed } from './confirmedKnowledgeBase.js'

test('knowledge base confirmation accepts only exact names from the current list', () => {
  const response = { knowledge_bases: [{ name: 'course-a' }, { name: 'course-b' }] }
  assert.equal(isKnowledgeBaseConfirmed(response, 'course-a'), true)
  assert.equal(isKnowledgeBaseConfirmed(response, 'course'), false)
  assert.equal(isKnowledgeBaseConfirmed(response, ''), false)
})

test('knowledge base confirmation fails closed for malformed or empty lists', () => {
  assert.deepEqual(getKnowledgeBaseItems(null), [])
  assert.deepEqual(getKnowledgeBaseItems({ knowledge_bases: null }), [])
  assert.equal(isKnowledgeBaseConfirmed({ knowledge_bases: [] }, 'course-a'), false)
})

test('confirmed knowledge base returns the exact server capability projection', () => {
  const knowledgeBase = { name: 'course-a', capabilities: { read: true, operate: false } }
  assert.equal(getConfirmedKnowledgeBase({ knowledge_bases: [knowledgeBase] }, 'course-a'), knowledgeBase)
  assert.equal(getConfirmedKnowledgeBase({ knowledge_bases: [knowledgeBase] }, 'course-b'), null)
})
