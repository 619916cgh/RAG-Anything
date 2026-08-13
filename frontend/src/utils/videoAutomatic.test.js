import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

const root = path.resolve(import.meta.dirname, '..', '..', '..')

test('video processing is automatic and has no client toggle', () => {
  const api = fs.readFileSync(path.join(root, 'frontend', 'src', 'utils', 'api.js'), 'utf8')
  const pages = [
    'frontend/src/pages/KnowledgeDetailPage.jsx',
    'frontend/src/pages/PreferencesPage.jsx',
    'frontend/src/pages/AdminPlatformPage.jsx',
  ].map(file => fs.readFileSync(path.join(root, file), 'utf8'))

  assert.doesNotMatch(api, /enable_video/)
  for (const source of pages) {
    assert.doesNotMatch(source, /enable_video/)
    assert.doesNotMatch(source, /处理视频|启用视频处理/)
  }
})
