import assert from 'node:assert/strict'
import test from 'node:test'
import {
  getGraphConnectionDisplayName,
  getGraphNodeDisplayName,
  UNKNOWN_GRAPH_ENTITY_NAME,
} from './graphPresentation.js'

test('does not expose an internal graph id when the label is absent', () => {
  assert.equal(getGraphNodeDisplayName({ id: '0123456789abcdef0123456789abcdef' }), UNKNOWN_GRAPH_ENTITY_NAME)
  assert.equal(getGraphNodeDisplayName({ id: 'entity-1', label: '发动机' }), '发动机')
  assert.equal(
    getGraphConnectionDisplayName([{ id: 'entity-1', label: '发动机' }], 'missing'),
    UNKNOWN_GRAPH_ENTITY_NAME,
  )
})
