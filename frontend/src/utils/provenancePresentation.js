const LOCATOR_STATUSES = new Set(['exact', 'page', 'document', 'unavailable'])

function nonEmptyString(value) {
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}

function firstNonEmpty(...values) {
  for (const value of values) {
    const text = nonEmptyString(value)
    if (text) return text
  }
  return ''
}

function finiteNumber(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function positiveNumber(value) {
  const number = finiteNumber(value)
  return number != null && number > 0 ? number : null
}

function positiveInteger(value) {
  const number = finiteNumber(value)
  return number != null && number >= 1 ? Math.trunc(number) : null
}

function normalizePage(value, legacyPageIndex, pageIndexTrusted = false) {
  const explicit = positiveInteger(value)
  if (explicit != null) return explicit

  // A bare page_idx is ambiguous across legacy parsers. Convert it only when
  // the producer explicitly declares the index trustworthy and zero-based.
  if (!pageIndexTrusted) return null
  const index = finiteNumber(legacyPageIndex)
  return index != null && index >= 0 ? Math.trunc(index) + 1 : null
}

function normalizeSectionPath(value) {
  if (Array.isArray(value)) {
    return value.map(nonEmptyString).filter(Boolean)
  }
  const text = nonEmptyString(value)
  return text ? [text] : []
}

function normalizeBBox(value, coordinateSystem = null) {
  if (Array.isArray(value) && value.length >= 4) {
    const [first, second, third, fourth] = value.slice(0, 4).map(finiteNumber)
    if (![first, second, third, fourth].every(item => item != null)) return null
    const order = Array.isArray(coordinateSystem?.order)
      ? coordinateSystem.order.map(item => String(item).toLowerCase()).join(',')
      : ''
    const isEdges = order === 'left,bottom,right,top' || order === 'left,top,right,bottom'
    return isEdges
      ? { x: first, y: second, width: third - first, height: fourth - second }
      : { x: first, y: second, width: third, height: fourth }
  }
  if (!value || typeof value !== 'object') return null
  const x = finiteNumber(value.x ?? value.left)
  const y = finiteNumber(value.y ?? value.top)
  let width = finiteNumber(value.width)
  let height = finiteNumber(value.height)
  const right = finiteNumber(value.right)
  const bottom = finiteNumber(value.bottom)
  if (width == null && x != null && right != null) width = right - x
  if (height == null && y != null && bottom != null) height = bottom - y
  return [x, y, width, height].every(item => item != null)
    ? { x, y, width, height }
    : null
}

function normalizeCoordinateSystem(value) {
  if (!value || typeof value !== 'object') {
    const name = nonEmptyString(value)
    return name ? { type: name } : null
  }
  const type = nonEmptyString(value.type || value.name || value.units || value.unit || value.kind)
  const width = finiteNumber(value.width ?? value.page_width ?? value.image_width)
  const height = finiteNumber(value.height ?? value.page_height ?? value.image_height)
  return { ...value, ...(type ? { type } : {}), ...(width != null ? { width } : {}), ...(height != null ? { height } : {}) }
}

function coordinateKind(coordinateSystem) {
  const label = firstNonEmpty(
    coordinateSystem?.type,
    coordinateSystem?.units,
    coordinateSystem?.unit,
    coordinateSystem?.kind,
    coordinateSystem?.name,
  ).toLowerCase()
  if (!label) return ''
  if (label.includes('norm') || label.includes('relative') || label.includes('ratio')) return 'normalized'
  if (label.includes('pixel') || label === 'px' || label.includes('pdf point') || label === 'point' || label === 'points' || label === 'pt') return 'absolute'
  return ''
}

function coordinateOrigin(coordinateSystem) {
  const value = nonEmptyString(coordinateSystem?.origin)
    .toLowerCase()
    .replace(/[\s_]+/g, '-')
  if (['top-left', 'upper-left', 'left-top'].includes(value)) return 'top-left'
  if (['bottom-left', 'lower-left', 'left-bottom'].includes(value)) return 'bottom-left'
  return ''
}

function coordinateDimensions(coordinateSystem) {
  return {
    width: positiveNumber(coordinateSystem?.width ?? coordinateSystem?.page_width ?? coordinateSystem?.image_width),
    height: positiveNumber(coordinateSystem?.height ?? coordinateSystem?.page_height ?? coordinateSystem?.image_height),
  }
}

function validBBox(value) {
  if (!value || typeof value !== 'object') return null
  const x = finiteNumber(value.x)
  const y = finiteNumber(value.y)
  const width = positiveNumber(value.width)
  const height = positiveNumber(value.height)
  return x != null && y != null && width != null && height != null
    ? { x, y, width, height }
    : null
}

export function hasCompleteBBoxCoordinateSystem(bbox, coordinateSystem) {
  const box = validBBox(bbox)
  const kind = coordinateKind(coordinateSystem)
  const origin = coordinateOrigin(coordinateSystem)
  if (!box || !kind || !origin) return false
  if (kind === 'normalized') return true
  const { width, height } = coordinateDimensions(coordinateSystem)
  return width != null && height != null
}

function normalizeMedia(value, parent = {}) {
  if (!value || typeof value !== 'object') return null
  const mediaId = nonEmptyString(value.media_id || value.id || parent.media_id)
  const kb = nonEmptyString(value.kb || value.media_kb || parent.kb || parent.media_kb)
  const mediaUrl = firstNonEmpty(value.media_url, value.url, value.src, parent.media_url, parent.url)
  const mime = firstNonEmpty(value.mime, value.mime_type, value.content_type, parent.mime, parent.mime_type)
  const metadata = value.metadata && typeof value.metadata === 'object' ? value.metadata
    : value.meta && typeof value.meta === 'object' ? value.meta
      : null
  const result = {
    ...value,
    ...(mediaId ? { media_id: mediaId } : {}),
    ...(kb ? { kb, media_kb: kb } : {}),
    ...(mediaUrl ? { media_url: mediaUrl } : {}),
    ...(mime ? { mime } : {}),
    ...(metadata ? { metadata } : {}),
  }
  return mediaId || kb || mediaUrl || mime || metadata ? result : null
}

function mediaFromCitation(citation, nestedImage) {
  const image = nestedImage && typeof nestedImage === 'object' ? nestedImage : null
  const citationType = firstNonEmpty(citation?.modality, citation?.original_type, citation?.media_type).toLowerCase()
  const mime = firstNonEmpty(citation?.mime, citation?.mime_type, citation?.content_type).toLowerCase()
  const isImage = citationType === 'image' || citationType === 'figure' || mime.startsWith('image/')
  const candidate = image ? { ...citation, ...image } : (isImage ? citation : null)
  if (!candidate) return null
  return normalizeMedia(candidate, citation)
}

function normalizeVideoSegments(citation) {
  const values = []
  if (Array.isArray(citation?.video_segments)) values.push(...citation.video_segments)
  if (citation?.video_segment && typeof citation.video_segment === 'object') values.push(citation.video_segment)
  const citationType = firstNonEmpty(citation?.modality, citation?.original_type, citation?.media_type).toLowerCase()
  const citationMime = firstNonEmpty(citation?.mime, citation?.mime_type, citation?.content_type).toLowerCase()
  if (!values.length && (citationType === 'video' || citationMime.startsWith('video/')) && (citation.start_ms != null || citation.end_ms != null || citation.start_ts != null || citation.end_ts != null)) {
    values.push(citation)
  }
  const seen = new Set()
  return values
    .filter(segment => segment && typeof segment === 'object')
    .map(segment => {
      const mediaId = firstNonEmpty(segment.media_id, segment.id_media, citation.media_id)
      const mediaKb = firstNonEmpty(segment.media_kb, segment.kb, citation.media_kb, citation.kb)
      const mediaUrl = firstNonEmpty(segment.media_url, segment.url, segment.src, citation.media_url, citation.url)
      const segmentId = firstNonEmpty(segment.segment_id, segment.segmentId, segment.id)
      const startMs = finiteNumber(segment.start_ms ?? segment.startMs ?? segment.start_ts ?? segment.start)
      const endMs = finiteNumber(segment.end_ms ?? segment.endMs ?? segment.end_ts ?? segment.end)
      return {
        ...segment,
        ...(mediaId ? { media_id: mediaId } : {}),
        ...(mediaKb ? { media_kb: mediaKb, kb: mediaKb } : {}),
        ...(mediaUrl ? { media_url: mediaUrl } : {}),
        ...(segmentId ? { segment_id: segmentId } : {}),
        ...(startMs != null ? { start_ms: startMs } : {}),
        ...(endMs != null ? { end_ms: endMs } : {}),
      }
    })
    .filter(segment => {
      const key = segment.segment_id || `${segment.media_id || ''}:${segment.start_ms ?? segment.start_ts ?? ''}:${segment.end_ms ?? segment.end_ts ?? ''}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
}

function statusFor({ locatorStatus, page, documentName, image, videoSegments }) {
  if (LOCATOR_STATUSES.has(locatorStatus)) return locatorStatus
  if (image?.pagePreview && hasCompleteBBoxCoordinateSystem(image.bbox, image.bboxCoordinateSystem)) return 'exact'
  if (image?.bbox || page != null || videoSegments.some(segment => segment.start_ms != null || segment.end_ms != null)) return 'page'
  if (documentName) return 'document'
  return 'unavailable'
}

export function normalizeProvenanceCitation(citation, index = 0) {
  if (!citation || typeof citation !== 'object') return null
  const nestedImage = citation.image || citation.image_provenance || citation.image_metadata || citation.figure
    || (citation.media && typeof citation.media === 'object' && !String(citation.media.mime || citation.media.mime_type || '').toLowerCase().startsWith('video/') ? citation.media : null)
  const image = mediaFromCitation(citation, nestedImage)
  const pagePreviewValue = image && (image.page_preview || image.pagePreview || image.page_preview_media)
    ? (image.page_preview || image.pagePreview || image.page_preview_media)
    : image && (image.page_preview_url || image.page_media_url)
      ? { media_url: image.page_preview_url || image.page_media_url, media_id: image.page_preview_media_id, kb: image.kb || image.media_kb }
      : null
  const pagePreviewRaw = typeof pagePreviewValue === 'string'
    ? { media_url: pagePreviewValue, kb: image?.kb || image?.media_kb }
    : pagePreviewValue
  const bboxCoordinateSystem = image
    ? normalizeCoordinateSystem(
        image.bbox_coordinate_system || image.coordinate_system || image.metadata?.bbox_coordinate_system,
      )
    : null
  const normalizedImage = image
    ? {
        ...image,
        elementId: nonEmptyString(image.element_id || image.elementId || image.metadata?.element_id),
        figureLabel: nonEmptyString(image.figure_label || image.figure || image.label || image.metadata?.figure_label),
        metadata: image.metadata && typeof image.metadata === 'object'
          ? image.metadata
          : image.meta && typeof image.meta === 'object' ? image.meta : null,
        bbox: normalizeBBox(image.bbox || image.metadata?.bbox, bboxCoordinateSystem),
        bboxCoordinateSystem,
        pagePreview: normalizeMedia(pagePreviewRaw, image),
      }
    : null
  const videoSegments = normalizeVideoSegments(citation)
  const documentName = firstNonEmpty(
    citation.document_name, citation.source_title, citation.source_name, citation.title,
    citation.name, citation.file_name, citation.filename, citation.source,
  )
  const documentId = firstNonEmpty(citation.document_id, citation.doc_id, citation.full_doc_id)
  const chunkId = firstNonEmpty(citation.chunk_id, citation.chunkId)
  const filePath = firstNonEmpty(citation.file_path, citation.filePath)
  const page = normalizePage(
    citation.page ?? citation.page_number ?? citation.page_no ?? image?.page ?? image?.metadata?.page,
    citation.page_idx ?? image?.page_idx ?? image?.metadata?.page_idx,
    citation.page_idx_trusted === true || citation.page_index_base === 0
      || image?.page_idx_trusted === true || image?.page_index_base === 0,
  )
  const sectionPath = normalizeSectionPath(citation.section_path ?? citation.section)
  const excerpt = firstNonEmpty(citation.excerpt, citation.text, citation.content, citation.preview)
  const citationType = firstNonEmpty(citation.modality, citation.original_type, citation.media_type).toLowerCase()
  const citationMime = firstNonEmpty(citation.mime, citation.mime_type, citation.content_type).toLowerCase()
  const modality = citationType || (videoSegments.length || citationMime.startsWith('video/') ? 'video' : normalizedImage || citationMime.startsWith('image/') ? 'image' : 'text')
  const citationId = nonEmptyString(citation.citation_id || citation.citationId || citation.id) || `citation-${index + 1}`
  const locatorStatus = statusFor({
    locatorStatus: nonEmptyString(citation.locator_status),
    page, documentName, image: normalizedImage, videoSegments,
  })

  return {
    raw: citation,
    citationId,
    documentId,
    documentName,
    chunkId,
    filePath,
    excerpt,
    page,
    sectionPath,
    modality,
    locatorStatus,
    similarityScore: finiteNumber(citation.similarity_score ?? citation.score ?? citation.similarity),
    image: normalizedImage,
    videoSegments,
    mediaId: firstNonEmpty(citation.media_id, normalizedImage?.media_id, videoSegments[0]?.media_id),
    sourceIndex: positiveInteger(citation.index),
  }
}

export function normalizeProvenanceItems({ citations = [], sources = [], media = [], images = [], similarImages = [] } = {}) {
  const result = []
  const seen = new Set()
  const append = (value, index) => {
    const item = normalizeProvenanceCitation(value, result.length || index)
    if (!item) return
    const key = item.citationId !== `citation-${result.length + 1}`
      ? `id:${item.citationId}`
      : `${item.documentName}|${item.documentId}|${item.chunkId}|${item.mediaId}|${item.page}|${item.excerpt}`
    if (seen.has(key)) return
    seen.add(key)
    result.push(item)
  }

  if (Array.isArray(citations)) citations.forEach(append)
  if (Array.isArray(sources)) {
    sources.forEach((source, index) => {
      if (!source || typeof source !== 'object') return
      append({
        ...source,
        document_name: source.document_name || source.name || source.title,
        excerpt: source.excerpt || source.text || source.content,
        page: source.page,
        locator_status: source.locator_status,
      }, index)
    })
  }
  const mediaItems = []
  if (Array.isArray(media)) mediaItems.push(...media)
  if (Array.isArray(images)) mediaItems.push(...images)
  if (Array.isArray(similarImages)) mediaItems.push(...similarImages)
  if (mediaItems.length) {
    mediaItems.forEach((item, index) => {
      if (!item || typeof item !== 'object') return
      const mime = String(item.mime || item.mime_type || item.content_type || '').toLowerCase()
      const modality = item.modality || (mime.startsWith('video/') ? 'video' : 'image')
      append({
        ...item,
        modality,
        document_name: item.document_name || item.name || item.caption || item.entity_name,
        image: modality === 'image' ? item : undefined,
        video_segment: modality === 'video' && (item.start_ms != null || item.end_ms != null || item.start_ts != null || item.end_ts != null) ? item : undefined,
        similarity_score: item.similarity_score ?? item.score ?? item.similarity,
      }, index)
    })
  }
  return result
}

export function formatProvenanceTime(value) {
  const milliseconds = finiteNumber(value)
  if (milliseconds == null) return ''
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000))
  return `${Math.floor(totalSeconds / 60)}:${String(totalSeconds % 60).padStart(2, '0')}`
}

export function formatProvenanceRange(start, end) {
  const startText = formatProvenanceTime(start)
  const endText = formatProvenanceTime(end)
  if (!startText && !endText) return ''
  return (startText || '0:00') + ' - ' + (endText || '—')
}

export function formatProvenanceBBox(bbox) {
  if (!bbox) return ''
  return '[' + [bbox.x, bbox.y, bbox.width, bbox.height].map(value => {
    const number = finiteNumber(value)
    return number == null ? '' : Number(number.toFixed(2))
  }).join(', ') + ']'
}

export function bboxStyle(bbox, coordinateSystem, dimensions) {
  const box = validBBox(bbox)
  const previewWidth = positiveNumber(dimensions?.width)
  const previewHeight = positiveNumber(dimensions?.height)
  if (!box || !previewWidth || !previewHeight || !hasCompleteBBoxCoordinateSystem(box, coordinateSystem)) return null

  const kind = coordinateKind(coordinateSystem)
  const origin = coordinateOrigin(coordinateSystem)
  const sourceDimensions = kind === 'normalized'
    ? { width: 1, height: 1 }
    : coordinateDimensions(coordinateSystem)
  const { width: sourceWidth, height: sourceHeight } = sourceDimensions
  if (!sourceWidth || !sourceHeight) return null

  // A full-page raster may use a different DPI, but it must preserve the page
  // aspect ratio. A mismatch means the preview could be cropped or unrelated.
  if (kind === 'absolute') {
    const sourceRatio = sourceWidth / sourceHeight
    const previewRatio = previewWidth / previewHeight
    if (Math.abs(sourceRatio - previewRatio) / sourceRatio > 0.02) return null
  }

  const epsilon = Math.max(sourceWidth, sourceHeight) * 1e-6
  if (
    box.x < -epsilon || box.y < -epsilon
    || box.x + box.width > sourceWidth + epsilon
    || box.y + box.height > sourceHeight + epsilon
  ) return null

  const left = Math.max(0, Math.min(1, box.x / sourceWidth))
  const topValue = origin === 'bottom-left'
    ? (sourceHeight - box.y - box.height) / sourceHeight
    : box.y / sourceHeight
  const top = Math.max(0, Math.min(1, topValue))
  const right = Math.max(left, Math.min(1, (box.x + box.width) / sourceWidth))
  const bottom = Math.max(top, Math.min(1, top + box.height / sourceHeight))
  if (right <= left || bottom <= top) return null

  const percent = value => `${Number((value * 100).toFixed(6))}%`
  return {
    left: percent(left),
    top: percent(top),
    width: percent(right - left),
    height: percent(bottom - top),
  }
}

export function provenanceChunkHref(kbName, documentId, chunkId) {
  if (!nonEmptyString(kbName) || !nonEmptyString(documentId) || !nonEmptyString(chunkId)) return ''
  return `/knowledge/${encodeURIComponent(kbName)}/documents/${encodeURIComponent(documentId)}/chunks/${encodeURIComponent(chunkId)}`
}

export const provenanceLocatorLabels = Object.freeze({
  exact: '精确定位',
  page: '页码定位',
  document: '资料定位',
  unavailable: '定位不可用',
})
