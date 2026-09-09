import assert from 'node:assert/strict'
import test from 'node:test'
import {
  bboxStyle,
  formatProvenanceBBox,
  formatProvenanceRange,
  hasCompleteBBoxCoordinateSystem,
  normalizeProvenanceCitation,
  normalizeProvenanceItems,
  provenanceChunkHref,
} from './provenancePresentation.js'

test('does not guess a page from an untrusted legacy page index', () => {
  const citation = normalizeProvenanceCitation({
    index: 2,
    document_name: '设备手册.pdf',
    excerpt: '先断开主电源，再检查端子。',
    page_idx: 3,
    section_path: ['维护', '断电'],
    document_id: 'doc-1',
    chunk_id: 'chunk-2',
  })

  assert.equal(citation.documentName, '设备手册.pdf')
  assert.equal(citation.excerpt, '先断开主电源，再检查端子。')
  assert.equal(citation.page, null)
  assert.equal(citation.sourceIndex, 2)
  assert.deepEqual(citation.sectionPath, ['维护', '断电'])
  assert.equal(citation.locatorStatus, 'document')
})

test('converts an explicitly trusted zero-based page index', () => {
  const citation = normalizeProvenanceCitation({
    document_name: '设备手册.pdf',
    page_idx: 3,
    page_index_base: 0,
  })
  assert.equal(citation.page, 4)
  assert.equal(citation.locatorStatus, 'page')
})

test('keeps explicit one-based pages unchanged', () => {
  const citation = normalizeProvenanceCitation({ document_name: 'guide.pdf', page: 7, page_idx: 1 })
  assert.equal(citation.page, 7)
})

test('normalizes image metadata and bounding boxes from nested image data', () => {
  const citation = normalizeProvenanceCitation({
    document_name: '装配图.pdf',
    image: {
      media_id: 'image-1234567890123456',
      kb: 'kb-a',
      caption: '主轴装配示意图',
      element_id: 'figure-3',
      figure_label: '图 3',
      page: 2,
      bbox: { left: 120, top: 80, right: 420, bottom: 280 },
      bbox_coordinate_system: { type: 'pixel', width: 800, height: 600 },
      metadata: { detector: 'layout', confidence: 0.98 },
    },
  })

  assert.equal(citation.modality, 'image')
  assert.equal(citation.page, 2)
  assert.equal(citation.image.elementId, 'figure-3')
  assert.equal(citation.image.figureLabel, '图 3')
  assert.deepEqual(citation.image.bbox, { x: 120, y: 80, width: 300, height: 200 })
  assert.deepEqual(citation.image.metadata, { detector: 'layout', confidence: 0.98 })
  assert.equal(formatProvenanceBBox(citation.image.bbox), '[120, 80, 300, 200]')
})

test('normalizes and deduplicates legacy video_segments', () => {
  const citation = normalizeProvenanceCitation({
    document_name: '安全培训.mp4',
    media_id: 'video-1234567890123456',
    media_kb: 'training',
    media_url: '/api/knowledge/media/video-1234567890123456?kb=training',
    video_segments: [
      { segment_id: 'segment-1', start_ms: 12000, end_ms: 24500 },
      { segment_id: 'segment-1', start_ms: 12000, end_ms: 24500 },
      { segment_id: 'segment-2', start_ms: 65000, end_ms: 71000 },
    ],
  })

  assert.equal(citation.modality, 'video')
  assert.equal(citation.videoSegments.length, 2)
  assert.equal(citation.videoSegments[0].media_id, 'video-1234567890123456')
  assert.equal(citation.videoSegments[0].media_kb, 'training')
  assert.equal(formatProvenanceRange(12000, 24500), '0:12 - 0:24')
  assert.equal(formatProvenanceRange(65000, 71000), '1:05 - 1:11')
})

test('retains incomplete citations with an unavailable locator', () => {
  const citation = normalizeProvenanceCitation({})
  assert.equal(citation.documentName, '')
  assert.equal(citation.excerpt, '')
  assert.equal(citation.locatorStatus, 'unavailable')
  assert.deepEqual(citation.videoSegments, [])
})

test('combines citations, sources, images, and similar images without empty inputs failing', () => {
  const items = normalizeProvenanceItems({
    citations: [{ citation_id: 'citation-a', document_name: 'A.pdf', excerpt: 'A' }],
    sources: [{ citation_id: 'source-b', name: 'B.pdf', text: 'B' }],
    images: [{ media_id: 'image-1234567890123456', kb: 'kb-a', caption: '图 C', mime: 'image/png' }],
    similarImages: [{ media_id: 'image-abcdefghijklmnop', kb: 'kb-a', name: '图 D', score: 0.75 }],
  })

  assert.equal(items.length, 4)
  assert.equal(items[1].documentName, 'B.pdf')
  assert.equal(items[2].modality, 'image')
  assert.equal(items[3].similarityScore, 0.75)
  assert.deepEqual(normalizeProvenanceItems(), [])
})

test('builds safe route links only when every route identifier is present', () => {
  assert.equal(
    provenanceChunkHref('机械 知识库', 'doc/1', 'chunk?2'),
    '/knowledge/%E6%9C%BA%E6%A2%B0%20%E7%9F%A5%E8%AF%86%E5%BA%93/documents/doc%2F1/chunks/chunk%3F2',
  )
  assert.equal(provenanceChunkHref('kb', '', 'chunk'), '')
})

test('maps normalized and absolute bounding boxes to percentage overlays', () => {
  assert.deepEqual(
    bboxStyle(
      { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
      { type: 'normalized', origin: 'top-left' },
      { width: 1200, height: 1600 },
    ),
    { left: '10%', top: '20%', width: '30%', height: '40%' },
  )
  assert.deepEqual(
    bboxStyle(
      { x: 100, y: 50, width: 200, height: 100 },
      { type: 'pixel', origin: 'top-left', width: 1000, height: 500 },
      { width: 2000, height: 1000 },
    ),
    { left: '10%', top: '10%', width: '20%', height: '20%' },
  )
  assert.deepEqual(
    bboxStyle(
      { x: 100, y: 50, width: 200, height: 100 },
      { units: 'PDF points', origin: 'bottom-left', width: 1000, height: 500 },
      { width: 2000, height: 1000 },
    ),
    { left: '10%', top: '70%', width: '20%', height: '20%' },
  )
})

test('requires an explicit complete coordinate transform before drawing a bbox', () => {
  const tinyBox = { x: 0.1, y: 0.2, width: 0.3, height: 0.4 }
  const absoluteBox = { x: 100, y: 50, width: 200, height: 100 }

  assert.equal(hasCompleteBBoxCoordinateSystem(tinyBox, null), false)
  assert.equal(hasCompleteBBoxCoordinateSystem(tinyBox, { type: 'normalized' }), false)
  assert.equal(hasCompleteBBoxCoordinateSystem(tinyBox, { type: 'normalized', origin: 'top-left' }), true)
  assert.equal(
    hasCompleteBBoxCoordinateSystem(absoluteBox, { type: 'pixel', origin: 'top-left', width: 1000 }),
    false,
  )
  assert.equal(
    hasCompleteBBoxCoordinateSystem(absoluteBox, { type: 'unknown-grid', origin: 'top-left', width: 1000, height: 500 }),
    false,
  )

  // Numeric values in the 0..1 range are not enough to infer normalized units.
  assert.equal(bboxStyle(tinyBox, null, { width: 1200, height: 1600 }), null)
  // Preview dimensions cannot substitute for missing source-coordinate bounds.
  assert.equal(
    bboxStyle(absoluteBox, { type: 'pixel', origin: 'top-left' }, { width: 1000, height: 500 }),
    null,
  )
  // The overlay waits for the full-page preview to load and expose dimensions.
  assert.equal(
    bboxStyle(absoluteBox, { type: 'pixel', origin: 'top-left', width: 1000, height: 500 }, null),
    null,
  )
})

test('rejects cropped, unsupported-origin, and out-of-bounds page transforms', () => {
  const bbox = { x: 100, y: 50, width: 200, height: 100 }
  const coordinateSystem = { type: 'pixel', origin: 'top-left', width: 1000, height: 500 }

  assert.equal(bboxStyle(bbox, coordinateSystem, { width: 1000, height: 1000 }), null)
  assert.equal(
    bboxStyle(bbox, { ...coordinateSystem, origin: 'top-right' }, { width: 2000, height: 1000 }),
    null,
  )
  assert.equal(
    bboxStyle({ x: 900, y: 50, width: 200, height: 100 }, coordinateSystem, { width: 2000, height: 1000 }),
    null,
  )
})
