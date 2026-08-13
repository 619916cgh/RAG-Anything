import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'

const root = path.resolve(import.meta.dirname, '..')
const read = relative => fs.readFileSync(path.join(root, relative), 'utf8')

test('knowledge detail keeps KB ingestion controls behind global and per-KB write capability', () => {
  const source = read('pages/KnowledgeDetailPage.jsx')
  assert.match(source, /const canOperateKB = kbAccess\.capabilities\?\.operate === true/)
  assert.match(source, /const canManageKB = hasPermission\('kb:write'\) && canOperateKB/)
  assert.match(source, /api\.getKBIngestionSettings\(kbName\)/)
  assert.match(source, /api\.updateKBIngestionSettings\(kbName/)
  assert.match(source, /canManageKB && <section[^>]*aria-labelledby="kb-ingestion-heading"/)
  assert.match(source, /if \(error\?\.status === 403\) void verifyToken\(\)/)
  assert.match(source, /parserOptions\.map\(parser/)
  assert.match(source, /ingestionDraft\.chunking_strategy/)

  const settingsLifecycle = source.slice(
    source.indexOf('const saveKBIngestionSettings'),
    source.indexOf('// 文档/统计核心数据加载'),
  )
  assert.doesNotMatch(settingsLifecycle, /setTemporaryChunkingStrategy|setShowTemporaryChunkingOverride/)
})

test('API client exposes KB ingestion settings endpoints', () => {
  const source = read('utils/api.js')
  assert.match(source, /getKBIngestionSettings: \(kbName\).*\/ingestion-settings/)
  assert.match(source, /updateKBIngestionSettings: \(kbName, data\).*\/ingestion-settings/)
})
