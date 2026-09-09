import { useEffect, useState } from 'react'
import { AlertTriangle, BookOpen, ExternalLink, FileText, Image as ImageIcon, MapPin, Video } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useControlledMediaSource, useControlledMediaState } from './ControlledMedia'
import VideoSegmentPlayer from './VideoSegmentPlayer'
import { controlledMediaUrl } from '../utils/controlledMedia'
import {
  bboxStyle, formatProvenanceBBox, formatProvenanceRange, normalizeProvenanceItems,
  provenanceChunkHref, provenanceLocatorLabels,
} from '../utils/provenancePresentation'

const itemClass = 'rounded-lg border border-cloud-200 dark:border-sky-800/30 bg-white/70 dark:bg-sky-950/20 px-3 py-2.5'

function text(value) {
  return typeof value === 'string' ? value.trim() : ''
}

function MediaPreview({ media, mediaResolver, alt, className = '', video = false }) {
  const [failed, setFailed] = useState(false)
  const controlledSource = useControlledMediaSource(mediaResolver ? null : media || null)
  const source = mediaResolver ? mediaResolver(media) : controlledSource
  if (!source || failed) {
    return <div className="flex min-h-16 items-center justify-center gap-1.5 rounded border border-cloud-200 dark:border-sky-800/30 bg-cloud-50 dark:bg-sky-900/20 px-2 text-2xs text-ink-muted dark:text-cloud-500" role="status"><AlertTriangle size={13} aria-hidden="true" />{failed ? '媒体预览不可用' : '媒体需要授权后显示'}</div>
  }
  if (video) {
    return <video className={'max-h-48 w-full rounded bg-black object-contain ' + className} controls preload="metadata" src={source} onError={() => setFailed(true)} aria-label={alt} />
  }
  return <img className={'max-h-48 w-full rounded object-contain ' + className} src={source} alt={alt} loading="lazy" onError={() => setFailed(true)} />
}

function PagePreview({ image, mediaResolver }) {
  const [dimensions, setDimensions] = useState(null)
  const [failed, setFailed] = useState(false)
  const preview = image?.pagePreview
  const protectedPreviewUrl = controlledMediaUrl(preview)
  const controlledState = useControlledMediaState(mediaResolver || !protectedPreviewUrl ? null : preview)
  const resolvedSource = mediaResolver ? mediaResolver(preview) : controlledState.source
  const source = typeof resolvedSource === 'string' ? resolvedSource : ''
  const isControlledPreview = Boolean(preview && source && (mediaResolver || protectedPreviewUrl))
  const overlay = isControlledPreview && !failed
    ? bboxStyle(image?.bbox, image?.bboxCoordinateSystem, dimensions)
    : null
  const coordinateLabel = image?.bboxCoordinateSystem?.type
    || image?.bboxCoordinateSystem?.units
    || image?.bboxCoordinateSystem?.unit

  useEffect(() => {
    setDimensions(null)
    setFailed(false)
  }, [preview?.media_id, preview?.media_url, preview?.url, source])

  if (!image?.bbox) return null
  if (!isControlledPreview || failed) {
    return <p className="text-2xs text-ink-muted dark:text-cloud-500">图片位置：页内图片 · 坐标 {formatProvenanceBBox(image.bbox)}{coordinateLabel ? ' · ' + coordinateLabel : ''}</p>
  }
  return (
    <div className="mt-2">
      <div className="flex justify-center overflow-hidden rounded border border-cloud-200 bg-cloud-50 dark:border-sky-800/30 dark:bg-sky-900/20">
        <div className="relative inline-block max-w-full">
          <img
            src={source}
            alt="资料页预览"
            className="block h-auto max-h-56 max-w-full"
            loading="lazy"
            onLoad={event => setDimensions({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })}
            onError={() => setFailed(true)}
          />
          {overlay && <span className="pointer-events-none absolute border-2 border-coral-500 bg-coral-400/15" style={overlay} aria-label="图片位置高亮" />}
        </div>
      </div>
      <p className="mt-1 text-2xs text-ink-muted dark:text-cloud-500">{overlay ? '图片位置：' + formatProvenanceBBox(image.bbox) : '图片位置：页内图片 · 坐标 ' + formatProvenanceBBox(image.bbox)}{coordinateLabel ? ' · ' + coordinateLabel : ''}</p>
    </div>
  )
}

function MediaDetails({ item, mediaResolver }) {
  const image = item.image
  if (!image) return null
  const media = { ...image, media_id: image.media_id || item.mediaId, kb: image.kb || image.media_kb }
  const isVideo = item.modality === 'video' || String(media.mime || '').toLowerCase().startsWith('video/')
  const caption = text(image.caption || image.description || image.alt || image.metadata?.caption || image.metadata?.description)
  const metadata = image.metadata && typeof image.metadata === 'object'
    ? Object.entries(image.metadata)
        .filter(([, value]) => ['string', 'number', 'boolean'].includes(typeof value) && String(value).trim())
        .slice(0, 4)
    : []
  return (
    <div className="mt-2 space-y-2">
      {media.media_id || media.media_url || media.url ? <MediaPreview media={media} mediaResolver={mediaResolver} alt={caption || (isVideo ? '引用视频' : '引用图片')} video={isVideo} /> : null}
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-2xs text-ink-muted dark:text-cloud-500">
        {image.elementId && <span>元素 {image.elementId}</span>}
        {image.figureLabel && <span>{image.figureLabel}</span>}
        {caption && <span className="max-w-full break-words">{caption}</span>}
        {metadata.map(([key, value]) => <span className="max-w-full break-words" key={key}>{key}: {String(value)}</span>)}
      </div>
      <PagePreview image={image} mediaResolver={mediaResolver} />
      {!image.bbox && item.page != null && <p className="text-2xs text-ink-muted dark:text-cloud-500">图片位置：第 {item.page} 页</p>}
    </div>
  )
}

function CitationTitle({ item, href, index }) {
  const title = item.documentName || '未命名资料'
  const content = href
    ? <Link to={href} className="inline-flex min-w-0 break-words items-center gap-1 font-medium text-sky-600 hover:text-sky-700 hover:underline dark:text-sky-400 dark:hover:text-sky-300" title="打开切块详情">{title}<ExternalLink size={11} aria-hidden="true" /></Link>
    : <span className="break-words font-medium text-ink-body dark:text-cloud-300">{title}</span>
  return <div className="flex min-w-0 items-start gap-2"><span className="mt-0.5 inline-grid h-5 w-5 shrink-0 place-items-center rounded-full bg-sky-50 text-2xs font-semibold text-sky-600 dark:bg-sky-900/40 dark:text-sky-300">{index + 1}</span><div className="min-w-0 flex-1">{content}</div></div>
}

export function ProvenanceItem({ item, index, kbName = '', mediaResolver, publicMode = false }) {
  const href = !publicMode ? provenanceChunkHref(kbName, item.documentId, item.chunkId) : ''
  const firstSegment = item.videoSegments[0]
  const mediaId = item.mediaId || firstSegment?.media_id || item.image?.media_id
  const segments = item.videoSegments.map(segment => ({
    ...segment,
    media_id: segment.media_id || mediaId,
    media_kb: segment.media_kb || item.raw?.media_kb || item.raw?.kb || item.image?.media_kb,
    media_url: segment.media_url || item.raw?.media_url || item.image?.media_url,
    document_name: segment.document_name || item.documentName,
  }))
  const hasPlayableVideo = segments.some(segment => (
    mediaResolver ? Boolean(segment.media_url || segment.url) : Boolean(segment.media_id && (segment.media_kb || segment.kb))
  ))
  const locatorLabel = provenanceLocatorLabels[item.locatorStatus] || provenanceLocatorLabels.unavailable
  return (
    <article
      className={itemClass}
      data-testid="citation-block"
      data-citation-id={item.citationId}
      data-citation-media-id={mediaId || undefined}
      data-video-segment-id={firstSegment?.segment_id || undefined}
      data-locator-status={item.locatorStatus}
    >
      <CitationTitle item={item} href={href} index={index} />
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5 pl-7 text-2xs text-ink-muted dark:text-cloud-500">
        {item.page != null && <span className="inline-flex items-center gap-1"><FileText size={11} aria-hidden="true" />第 {item.page} 页</span>}
        {item.sectionPath.length > 0 && <span className="max-w-full break-words">· {item.sectionPath.join(' / ')}</span>}
        <span className={'inline-flex items-center gap-1 ' + (item.locatorStatus === 'unavailable' ? 'text-amber-600 dark:text-amber-400' : 'text-sage-600 dark:text-sage-400')}><MapPin size={11} aria-hidden="true" />{locatorLabel}</span>
        {item.chunkId && <span className="font-mono">· 切块 {item.chunkId}</span>}
        {item.similarityScore != null && <span>· 相似度 {(Math.max(0, Math.min(1, item.similarityScore)) * 100).toFixed(1)}%</span>}
      </div>
      {item.excerpt && <p className="mt-2 whitespace-pre-wrap break-words pl-7 text-xs leading-relaxed text-ink-body dark:text-cloud-300">{item.excerpt}</p>}
      {segments.length > 0 && (
        <div className="mt-2 border-t border-cloud-200 pt-2 dark:border-sky-800/30">
          <div className="mb-1 flex items-center gap-1 pl-7 text-2xs font-medium text-ink-muted dark:text-cloud-500"><Video size={11} aria-hidden="true" />视频时间</div>
          {publicMode
            ? <div className="pl-7"><MediaPreview media={segments[0]} mediaResolver={mediaResolver} alt={item.documentName || '引用视频'} video /></div>
            : hasPlayableVideo
              ? <VideoSegmentPlayer segments={segments} resolveSource={mediaResolver} />
              : <p className="pl-7 text-2xs text-ink-muted dark:text-cloud-500">视频预览不可用，时间范围仍可核对。</p>}
          <div className="mt-1 flex flex-wrap gap-1.5 pl-7 text-2xs text-ink-muted dark:text-cloud-500">
            {segments.map((segment, segmentIndex) => <span key={segment.segment_id || segmentIndex}>{formatProvenanceRange(segment.start_ms ?? segment.start_ts, segment.end_ms ?? segment.end_ts)}</span>)}
          </div>
        </div>
      )}
      {item.image && (
        <div className="mt-2 border-t border-cloud-200 pt-2 pl-7 dark:border-sky-800/30">
          <div className="mb-1 flex items-center gap-1 text-2xs font-medium text-ink-muted dark:text-cloud-500"><ImageIcon size={11} aria-hidden="true" />图片位置</div>
          <MediaDetails item={item} mediaResolver={mediaResolver} />
        </div>
      )}
      {item.locatorStatus === 'unavailable' && !item.excerpt && !item.image && !segments.length && <p className="mt-2 flex items-center gap-1 pl-7 text-2xs text-amber-600 dark:text-amber-400"><AlertTriangle size={11} aria-hidden="true" />暂无法定位到页码或媒体位置</p>}
    </article>
  )
}

export default function ProvenanceList({
  citations = [], sources = [], media = [], images = [], similarImages = [], kbName = '', mediaResolver,
  publicMode = false, className = '', showHeading = true, heading = '参考来源',
}) {
  const items = normalizeProvenanceItems({ citations, sources, media, images, similarImages })
  if (items.length === 0) return null
  return (
    <section className={'mt-3 space-y-2 border-t border-cloud-200 pt-3 dark:border-sky-800/30 ' + className} aria-label="溯源引用">
      {showHeading && <div className="flex items-center gap-1 text-2xs font-medium text-ink-muted dark:text-cloud-500"><BookOpen size={11} aria-hidden="true" />{heading}<span className="rounded-full bg-sky-50 px-1.5 py-0.5 text-[10px] text-sky-600 dark:bg-sky-900/40 dark:text-sky-300">{items.length} 项</span></div>}
      <div className="space-y-2">
        {items.map((item, index) => <ProvenanceItem key={item.citationId + '-' + (item.chunkId || item.mediaId || index)} item={item} index={index} kbName={kbName} mediaResolver={mediaResolver} publicMode={publicMode} />)}
      </div>
    </section>
  )
}
