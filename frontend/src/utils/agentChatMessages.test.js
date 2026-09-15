import assert from 'node:assert/strict'
import test from 'node:test'

import { mapThreadMessages } from './agentChatMessages.js'

test('restores a persisted query image preview as the message image URL', () => {
  const messages = [{
    msg_id: 17,
    role: 'user',
    content: '这是什么？',
    image_preview: 'data:image/jpeg;base64,preview',
  }]

  const mapped = mapThreadMessages('thread-1', messages)

  assert.equal(mapped[0].id, 'thread-1-0')
  assert.equal(mapped[0].imageUrl, 'data:image/jpeg;base64,preview')
  assert.equal(mapped[0].done, true)
  assert.deepEqual(mapped[0].thinking, [])
})

test('preserves an existing image URL over the persisted preview', () => {
  const mapped = mapThreadMessages('thread-1', [{
    role: 'user',
    content: '',
    imageUrl: 'blob:existing-preview',
    image_preview: 'data:image/jpeg;base64,preview',
  }])

  assert.equal(mapped[0].imageUrl, 'blob:existing-preview')
})
