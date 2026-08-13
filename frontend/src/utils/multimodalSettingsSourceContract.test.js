import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = relativePath => readFileSync(new URL(relativePath, import.meta.url), 'utf8')

test('knowledge upload no longer exposes multimodal processing choices', () => {
  const page = source('../pages/KnowledgeDetailPage.jsx')

  assert.doesNotMatch(page, /setMultimodal|effectiveIngestion|multimodal=/)
  assert.doesNotMatch(page, /enable_image|enable_table|enable_equation/)
  assert.doesNotMatch(page, /URL 导入|文件夹导入|粘贴内容|uploadFolder|uploadUrl|uploadContent/)
  assert.doesNotMatch(page, /const \[chunkingStrategy, setChunkingStrategy\]/)
  assert.match(page, /effectiveChunkingStrategy/)
  assert.match(page, /effectiveChunkingSource/)
  assert.match(page, /const \[temporaryChunkingStrategy, setTemporaryChunkingStrategy\] = useState\(''\)/)
  assert.match(page, /const \[showTemporaryChunkingOverride, setShowTemporaryChunkingOverride\] = useState\(false\)/)
  assert.match(page, /showTemporaryChunkingOverride \? \(/)
  assert.match(page, /value=\{displayedChunkingStrategy\}/)
  assert.match(page, /const submittedOverride = temporaryChunkingStrategy/)
  assert.match(page, /api\.uploadFile\(target\.file, submittedOverride\)/)
  assert.match(page, /api\.uploadFiles\(\s*pendingFiles\.map\(item => item\.file\),\s*submittedOverride,/)
  assert.match(page, /clearSubmittedTemporaryOverride\(submittedOverride\)/)
  assert.match(page, /setTemporaryChunkingStrategy\(''\)/)
  assert.match(page, /aria-controls="temporary-chunking-override"/)
})

test('personal ingestion settings no longer render or persist multimodal fields', () => {
  const page = source('../pages/PreferencesPage.jsx')

  assert.doesNotMatch(page, /preferences-toggle-list/)
  assert.doesNotMatch(page, /FIELD_LABELS\.(enable_image|enable_table|enable_equation)/)
  assert.match(page, /FIXED_INGESTION_FIELDS = new Set\(\['enable_image', 'enable_table', 'enable_equation'\]\)/)
  assert.match(page, /Object\.entries\(rawValues\)\.filter\(\(\[field\]\) => !FIXED_INGESTION_FIELDS\.has\(field\)\)/)
})

test('remaining frontend upload helpers force multimodal processing on', () => {
  const api = source('./api.js')

  assert.match(api, /function setFixedMultimodalUploadParams\(params\)/)
  assert.match(api, /params\.set\('enable_image', 'true'\)/)
  assert.match(api, /params\.set\('enable_table', 'true'\)/)
  assert.match(api, /params\.set\('enable_equation', 'true'\)/)
  assert.equal((api.match(/setFixedMultimodalUploadParams\(params\)/g) || []).length, 3)
  assert.doesNotMatch(api, /uploadFolder:|uploadUrl:|uploadContent:|\/upload\/(folder|url|content)/)
})
