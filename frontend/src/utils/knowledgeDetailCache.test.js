import assert from 'node:assert/strict'
import test from 'node:test'
import {
  invalidateKnowledgeDetailSnapshot,
  readKnowledgeDetailSnapshot,
  seedKnowledgeDetailStats,
  updateKnowledgeDetailSnapshot,
} from './knowledgeDetailCache.js'

function memoryStorage() {
  const values = new Map()
  return {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: key => values.delete(key),
    clear: () => values.clear(),
  }
}

test('seeds and isolates detail statistics by user and knowledge base', () => {
  const original = globalThis.sessionStorage
  globalThis.sessionStorage = memoryStorage()
  try {
    seedKnowledgeDetailStats(1, 'course-a', { documents: 3 })
    assert.deepEqual(readKnowledgeDetailSnapshot(1, 'course-a')?.stats, { documents: 3 })
    assert.equal(readKnowledgeDetailSnapshot(2, 'course-a'), null)
    assert.equal(readKnowledgeDetailSnapshot(1, 'course-b'), null)
  } finally {
    globalThis.sessionStorage = original
  }
})

test('invalidating a detail snapshot removes the cached value', () => {
  const original = globalThis.sessionStorage
  globalThis.sessionStorage = memoryStorage()
  try {
    seedKnowledgeDetailStats(1, 'course-a', { documents: 3 })
    invalidateKnowledgeDetailSnapshot(1, 'course-a')
    assert.equal(readKnowledgeDetailSnapshot(1, 'course-a'), null)
  } finally {
    globalThis.sessionStorage = original
  }
})

test('updates document data without replacing the seeded statistics', () => {
  const original = globalThis.sessionStorage
  globalThis.sessionStorage = memoryStorage()
  try {
    seedKnowledgeDetailStats(3, 'course-c', { documents: 1, entities: 2 })
    updateKnowledgeDetailSnapshot(3, 'course-c', { docs: [{ id: 'doc-1', file: 'lesson.pdf' }] })
    const snapshot = readKnowledgeDetailSnapshot(3, 'course-c')
    assert.deepEqual(snapshot?.docs, [{ id: 'doc-1', file: 'lesson.pdf' }])
    assert.deepEqual(snapshot?.stats, { documents: 1, entities: 2 })
    assert.ok(Number.isFinite(snapshot?.updatedAt))
  } finally {
    globalThis.sessionStorage = original
  }
})

test('clearing session storage also drops the in-memory snapshot', () => {
  const original = globalThis.sessionStorage
  globalThis.sessionStorage = memoryStorage()
  try {
    seedKnowledgeDetailStats(4, 'course-d', { documents: 2 })
    globalThis.sessionStorage.clear()
    assert.equal(readKnowledgeDetailSnapshot(4, 'course-d'), null)
  } finally {
    globalThis.sessionStorage = original
  }
})
