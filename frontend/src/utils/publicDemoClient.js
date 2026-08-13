const API_BASE = '/api'

export function readDemoToken(hash = globalThis.location?.hash || '') {
  const token = hash.startsWith('#') ? hash.slice(1) : ''
  return /^[A-Za-z0-9_-]{32,256}$/.test(token) ? token : ''
}

export function controlledDemoMediaUrl(shareId, value, origin = globalThis.location?.origin) {
  if (typeof value !== 'string' || !origin) return ''
  try {
    const url = new URL(value, origin)
    const expectedPrefix = `/api/demo/${encodeURIComponent(shareId)}/media/`
    if (url.origin !== origin || !url.pathname.startsWith(expectedPrefix) || !url.searchParams.get('grant')) return ''
    return `${url.pathname}${url.search}`
  } catch {
    return ''
  }
}

function demoHeaders(token, extra = {}) {
  if (!token) throw new Error('演示链接无效或已失效')
  return { 'X-Demo-Token': token, ...extra }
}

async function readError(response, fallback) {
  const body = await response.json().catch(() => ({}))
  return typeof body?.detail === 'string' ? body.detail : fallback
}

export async function loadPublicDemo(shareId, token, signal) {
  const response = await fetch(`${API_BASE}/demo/${encodeURIComponent(shareId)}/bootstrap`, {
    signal, credentials: 'omit',
    headers: demoHeaders(token),
  })
  if (!response.ok) throw new Error(await readError(response, '演示链接无效或已失效'))
  return response.json()
}

export async function streamPublicDemo(shareId, token, query, { signal, onEvent }) {
  const response = await fetch(`${API_BASE}/demo/${encodeURIComponent(shareId)}/query/stream`, {
    method: 'POST', signal, credentials: 'omit',
    headers: demoHeaders(token, { Accept: 'text/event-stream', 'Content-Type': 'application/json' }),
    body: JSON.stringify({ query }),
  })
  if (!response.ok) throw new Error(await readError(response, '问答暂时不可用'))
  if (!response.body) throw new Error('问答连接意外中断，请重试')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const dispatch = (payload) => {
    const dataLines = payload
      .replace(/\r/g, '')
      .split('\n')
      .filter(line => line.startsWith('data:'))
      .map(line => line.slice(5).trimStart())
    if (!dataLines.length) return
    try { onEvent(JSON.parse(dataLines.join('\n'))) } catch { /* malformed SSE is ignored */ }
  }
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const events = buffer.split(/\r?\n\r?\n/)
      buffer = events.pop() || ''
      events.forEach(dispatch)
    }
    buffer += decoder.decode()
    if (buffer.trim()) dispatch(buffer)
  } finally {
    reader.releaseLock()
  }
}
