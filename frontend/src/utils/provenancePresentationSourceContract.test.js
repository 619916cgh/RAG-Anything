import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const component = readFileSync(new URL('../components/ProvenanceList.jsx', import.meta.url), 'utf8')

test('bbox overlay is isolated to a controlled full-page preview', () => {
  const thumbnailStart = component.indexOf('function MediaPreview')
  const pagePreviewStart = component.indexOf('function PagePreview')
  const mediaDetailsStart = component.indexOf('function MediaDetails')
  assert.ok(thumbnailStart >= 0 && pagePreviewStart > thumbnailStart && mediaDetailsStart > pagePreviewStart)

  const thumbnailSource = component.slice(thumbnailStart, pagePreviewStart)
  const pagePreviewSource = component.slice(pagePreviewStart, mediaDetailsStart)
  assert.doesNotMatch(thumbnailSource, /bboxStyle|图片位置高亮/)
  assert.match(pagePreviewSource, /controlledMediaUrl\(preview\)/)
  assert.match(pagePreviewSource, /bboxStyle\(image\?\.bbox, image\?\.bboxCoordinateSystem, dimensions\)/)
  assert.match(pagePreviewSource, /overlay && <span[^>]+aria-label="图片位置高亮"/)
})

test('page preview failures and incomplete transforms retain an explicit page-level fallback', () => {
  assert.match(component, /图片位置：页内图片 · 坐标/)
  assert.match(component, /overlay \? '图片位置：'/)
  assert.match(component, /onError=\{\(\) => setFailed\(true\)\}/)
})
