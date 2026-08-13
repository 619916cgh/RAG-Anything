import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { controlledDemoMediaUrl, readDemoToken, streamPublicDemo } from './publicDemoClient.js'
import { formatPublicDemoMarkdown } from './publicDemoMarkdown.js'

const sourceRoot = path.resolve(import.meta.dirname, '..')
const readSource = relative => fs.readFileSync(path.join(sourceRoot, relative), 'utf8')

test('readDemoToken accepts a fragment token without retaining URL syntax', () => {
  const token = 'a'.repeat(43)
  assert.equal(readDemoToken(`#${token}`), token)
  assert.equal(readDemoToken(`?token=${token}`), '')
})

test('readDemoToken rejects missing and malformed fragments', () => {
  assert.equal(readDemoToken(''), '')
  assert.equal(readDemoToken('#short'), '')
  assert.equal(readDemoToken(`#${'a'.repeat(32)}?kb=private`), '')
})

test('controlledDemoMediaUrl accepts only a same-origin, granted demo preview', () => {
  const shareId = 'share_123'
  const origin = 'https://demo.example.test'
  assert.equal(
    controlledDemoMediaUrl(shareId, `/api/demo/${shareId}/media/media_456?grant=short-lived`, origin),
    `/api/demo/${shareId}/media/media_456?grant=short-lived`,
  )
  assert.equal(controlledDemoMediaUrl(shareId, 'https://storage.example.test/file.png?grant=x', origin), '')
  assert.equal(controlledDemoMediaUrl(shareId, '/api/documents/download?grant=x', origin), '')
  assert.equal(controlledDemoMediaUrl(shareId, `/api/demo/${shareId}/media/media_456`, origin), '')
})

test('streamPublicDemo parses CRLF and multi-line SSE events without sending credentials', async () => {
  const originalFetch = globalThis.fetch
  const encoder = new TextEncoder()
  const events = []
  let options
  globalThis.fetch = async (_url, requestOptions) => {
    options = requestOptions
    return new Response(new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode('data: {"type":"token",\r\n'))
        controller.enqueue(encoder.encode('data: "content":"回答"}\r\n\r\ndata: {"type":"done"}\r\n\r\n'))
        controller.close()
      },
    }), { status: 200 })
  }
  try {
    await streamPublicDemo('share_123', 'a'.repeat(43), '问题', { onEvent: event => events.push(event) })
  } finally {
    globalThis.fetch = originalFetch
  }
  assert.equal(options.credentials, 'omit')
  assert.equal(options.headers['X-Demo-Token'], 'a'.repeat(43))
  assert.deepEqual(events, [{ type: 'token', content: '回答' }, { type: 'done' }])
})

test('public demo route is isolated and renders only safe stream sources', () => {
  const entry = readSource('main.jsx')
  const page = readSource('pages/PublicDemoPage.jsx')
  assert.match(entry, /Route path="\/demo\/:shareId" element={<PublicDemoPage \/>}/)
  assert.match(entry, /if \(!window\.location\.pathname\.startsWith\('\/demo\/'\)\)/)
  assert.match(page, /sources: eventData\.sources \|\| \[\]/)
  assert.match(page, /controlledDemoMediaUrl\(shareId, media\?\.url\)/)
  assert.match(page, /<ReactMarkdown components=\{demoMarkdown\}>\{formatPublicDemoMarkdown\(message\.content\)\}<\/ReactMarkdown>/)
  assert.equal(formatPublicDemoMarkdown('```\n技师\n```\n—依据→\n```\n文件\n```'), '[[demo-relation:技师|依据|文件]]')
  assert.doesNotMatch(page, /rehypeRaw/)
  assert.doesNotMatch(page, /src=\{media\.url\}/)
})

test('public demo keeps the composer fixed and sends on Enter without breaking IME input', () => {
  const page = readSource('pages/PublicDemoPage.jsx')
  const css = readSource('index.css')
  assert.match(page, /event\.key !== 'Enter' \|\| event\.shiftKey \|\| event\.nativeEvent\.isComposing \|\| event\.keyCode === 229/)
  assert.match(page, /onKeyDown=\{sendOnEnter\}/)
  assert.match(css, /\.public-demo-composer \{ position: fixed;/)
  assert.match(css, /padding-bottom: calc\(76px \+ env\(safe-area-inset-bottom\)\)/)
})

test('public demo pauses auto-follow when the visitor scrolls away from the bottom', () => {
  const page = readSource('pages/PublicDemoPage.jsx')
  assert.match(page, /followOutputRef\.current = atBottom/)
  assert.match(page, /if \(followOutputRef\.current\) scrollToBottom\('auto'\)/)
  assert.match(page, /className="public-demo-scroll-button"/)
  assert.match(page, /onScroll=\{handleFeedScroll\}/)
})

test('public demo uses a compact two-level header for the knowledge context', () => {
  const page = readSource('pages/PublicDemoPage.jsx')
  const css = readSource('index.css')
  assert.match(page, /className="public-demo-header-main"/)
  assert.match(page, /className="public-demo-settings" aria-label="知识库设置"/)
  assert.match(page, /新上传默认/)
  assert.match(css, /\.public-demo-header-main \{/) 
  assert.match(css, /\.public-demo-settings \{/) 
})

test('public demo groups sources and controlled media in an accessible evidence disclosure', () => {
  const page = readSource('pages/PublicDemoPage.jsx')
  assert.match(page, /<details className="public-demo-evidence">/)
  assert.match(page, /<summary><Database size=\{14\} \/> 依据与资料/)
  assert.match(page, /controlledDemoMediaUrl\(shareId, media\?\.url\)/)
  assert.doesNotMatch(page, /src=\{media\.url\}/)
})
