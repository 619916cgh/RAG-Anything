import assert from 'node:assert/strict'
import test from 'node:test'
import {
  advanceKnowledgeDetailAuthGeneration,
  api,
  getCurrentKB,
  setCurrentKB,
  streamSSE,
} from './api.js'

test('knowledge-base metadata mutations invalidate the global list cache', async t => {
  const originalFetch = globalThis.fetch
  const originalLocalStorage = globalThis.localStorage
  const calls = []
  globalThis.localStorage = { getItem: () => null }
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options })
    if (String(url).includes('/metadata')) return jsonResponse({ label: '新名称' })
    return jsonResponse({ knowledge_bases: [{ name: `kb-${calls.length}` }] })
  }
  t.after(() => { globalThis.fetch = originalFetch; globalThis.localStorage = originalLocalStorage })

  await api.listKBs({ force: true })
  await api.updateKBMetadata('知识库 A', { display_name: '新名称', expected_updated_at: '2026-08-07T00:00:00+00:00' })
  await api.listKBs()

  assert.equal(calls[1].url, '/api/kb/%E7%9F%A5%E8%AF%86%E5%BA%93%20A/metadata')
  assert.equal(calls[1].options.method, 'PATCH')
  assert.equal(calls.filter(call => call.url === '/api/kb/list').length, 2)
})

test('streams authenticated terminal SSE events without reading past done', async t => {
  const originalFetch = globalThis.fetch
  const originalLocalStorage = globalThis.localStorage
  const encoder = new TextEncoder()
  let reads = 0
  let cancelled = false
  globalThis.localStorage = { getItem: () => JSON.stringify({ token: 'token-1' }) }
  let requestHeaders
  globalThis.fetch = async (_url, options) => {
    requestHeaders = options.headers
    return ({
    ok: true,
    status: 200,
    body: { getReader: () => ({
      read: async () => {
        reads += 1
        return reads === 1
          ? { done: false, value: encoder.encode('data: {"type":"done"}\r\n') }
          : { done: true }
      },
      cancel: async () => { cancelled = true },
      releaseLock: () => {},
    }) },
    })
  }
  t.after(() => { globalThis.fetch = originalFetch; globalThis.localStorage = originalLocalStorage })
  const events = []
  await streamSSE('/api/agents/a/query/stream', { body: '{}', onEvent: event => events.push(event) })
  assert.equal(events[0].type, 'done')
  assert.equal(reads, 1)
  assert.equal(cancelled, true)
  assert.equal(requestHeaders.Authorization, 'Bearer token-1')
})

test('retries one unauthorized API request after a single-flight refresh', async t => {
  const originalFetch = globalThis.fetch
  const originalLocalStorage = globalThis.localStorage
  const values = new Map([
    ['raganything_auth', JSON.stringify({
      token: 'expired-access',
      refreshToken: 'refresh-old',
      user: { id: 1 },
    })],
  ])
  globalThis.localStorage = {
    getItem: key => values.get(key) || null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: key => values.delete(key),
  }
  const calls = []
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options })
    if (String(url) === '/api/auth/refresh') {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          access_token: 'fresh-access',
          refresh_token: 'refresh-new',
          user: { id: 1, role: { name: 'student', permissions: [] } },
        }),
      }
    }
    if (calls.filter(call => call.url === '/api/auth/me').length === 1) {
      return { ok: false, status: 401, statusText: 'Unauthorized' }
    }
    return jsonResponse({ status: 'ok', user: { id: 1 } })
  }
  t.after(() => {
    globalThis.fetch = originalFetch
    globalThis.localStorage = originalLocalStorage
  })

  const result = await api.getMe()

  assert.deepEqual(result, { status: 'ok', user: { id: 1 } })
  assert.equal(calls.filter(call => call.url === '/api/auth/refresh').length, 1)
  assert.equal(calls.filter(call => call.url === '/api/auth/me').length, 2)
  assert.equal(calls[2].options.headers.Authorization, 'Bearer fresh-access')
  assert.equal(JSON.parse(values.get('raganything_auth')).refreshToken, 'refresh-new')
})

function jsonResponse(value) {
  return {
    ok: true,
    status: 200,
    statusText: 'OK',
    text: async () => JSON.stringify(value),
  }
}

test('loads every tag page with offsets and de-duplicates stable tag ids', async t => {
  const originalFetch = globalThis.fetch
  const originalLocalStorage = globalThis.localStorage
  const calls = []
  globalThis.localStorage = { getItem: () => null }
  globalThis.fetch = async url => {
    calls.push(String(url))
    if (calls.length === 1) {
      return jsonResponse({
        tags: Array.from({ length: 200 }, (_value, index) => ({
          id: index + 1,
          name: `tag-${index + 1}`,
        })),
      })
    }
    return jsonResponse({
      tags: [{ id: 200, name: 'tag-200' }, { id: 201, name: 'tag-201' }],
    })
  }
  t.after(() => {
    globalThis.fetch = originalFetch
    globalThis.localStorage = originalLocalStorage
  })

  const result = await api.listAllKnowledgeTags({ kb: 'demo', query: 'gear' })

  assert.equal(result.tags.length, 201)
  assert.match(calls[0], /limit=200&offset=0$/)
  assert.match(calls[1], /limit=200&offset=200$/)
  assert.match(calls[0], /q=gear/)
})

test('explicit KB detail reads encode the target without changing ambient currentKB', async t => {
  const originalFetch = globalThis.fetch
  const originalLocalStorage = globalThis.localStorage
  const calls = []
  globalThis.localStorage = { getItem: () => null }
  globalThis.fetch = async url => {
    calls.push(String(url))
    return jsonResponse({ documents: [] })
  }
  t.after(() => {
    globalThis.fetch = originalFetch
    globalThis.localStorage = originalLocalStorage
  })

  setCurrentKB('ambient-kb')
  await api.getDocumentsForKB('目标 KB/2')

  assert.equal(getCurrentKB(), 'ambient-kb')
  assert.equal(calls.length, 1)
  assert.equal(calls[0], '/api/knowledge/documents?kb=%E7%9B%AE%E6%A0%87%20KB%2F2')
})

test('document summary requests encode KB, page, size and literal search terms', async t => {
  const originalFetch = globalThis.fetch
  const originalLocalStorage = globalThis.localStorage
  globalThis.localStorage = { getItem: () => null }
  let calledUrl = ''
  globalThis.fetch = async url => {
    calledUrl = String(url)
    return jsonResponse({ documents: [], total: 0, page: 1, page_size: 50, total_pages: 1 })
  }
  t.after(() => {
    globalThis.fetch = originalFetch
    globalThis.localStorage = originalLocalStorage
  })

  await api.getDocumentSummariesForKB('\u77e5\u8bc6\u5e93 KB/2', { page: 2, pageSize: 50, q: '\u4e2d\u6587 & report' })
  assert.equal(
    calledUrl,
    '/api/knowledge/document-summaries?kb=%E7%9F%A5%E8%AF%86%E5%BA%93+KB%2F2&page=2&page_size=50&q=%E4%B8%AD%E6%96%87+%26+report',
  )
})

test('detail prefetch shares in-flight document, statistics, and inventory requests', async t => {
  const originalFetch = globalThis.fetch
  const originalLocalStorage = globalThis.localStorage
  const calls = []
  globalThis.localStorage = { getItem: () => null }
  globalThis.fetch = async url => {
    calls.push(String(url))
    await Promise.resolve()
    return String(url).includes('/document-summaries')
      ? jsonResponse({ documents: [{ id: 'doc-1' }] })
      : jsonResponse({ documents: 1, entities: 2, relations: 3, chunks: 4 })
  }
  t.after(() => {
    api.clearKnowledgeDetailCache()
    globalThis.fetch = originalFetch
    globalThis.localStorage = originalLocalStorage
  })

  api.clearKnowledgeDetailCache()
  const first = api.prefetchKnowledgeDetail('manuals')
  const second = api.prefetchKnowledgeDetail('manuals')

  const [result, secondResult] = await Promise.all([first, second])
  assert.equal(calls.length, 3)
  assert.equal(result.documents.status, 'ready')
  assert.deepEqual(secondResult, result)
  assert.deepEqual(result.documents.data, [{ id: 'doc-1' }])
  assert.equal(result.stats.data.documents, 1)
  assert.equal(result.inventory.status, 'ready')
})

test('cancelling one detail consumer does not abort or poison the shared prefetch', async t => {
  const originalFetch = globalThis.fetch
  const originalLocalStorage = globalThis.localStorage
  const calls = []
  let releaseFetches
  const fetchBarrier = new Promise(resolve => { releaseFetches = resolve })
  globalThis.localStorage = { getItem: () => null }
  globalThis.fetch = async url => {
    calls.push(String(url))
    await fetchBarrier
    return String(url).includes('/document-summaries')
      ? jsonResponse({ documents: [{ id: 'doc-1' }] })
      : jsonResponse({ documents: 1, entities: 2, relations: 3, chunks: 4 })
  }
  t.after(() => {
    api.clearKnowledgeDetailCache()
    globalThis.fetch = originalFetch
    globalThis.localStorage = originalLocalStorage
  })

  api.clearKnowledgeDetailCache()
  const controller = new AbortController()
  const cancelledConsumer = api.prefetchKnowledgeDetail('manuals', { signal: controller.signal })
  const survivingConsumer = api.prefetchKnowledgeDetail('manuals')
  controller.abort()
  releaseFetches()

  await assert.rejects(cancelledConsumer, error => error?.name === 'AbortError')
  const result = await survivingConsumer
  assert.equal(calls.length, 3)
  assert.equal(result.documents.status, 'ready')
  assert.equal(api.getCachedKnowledgeDetail('manuals').stats.data.documents, 1)
})

test('cancelling the final detail consumer aborts document, statistics, and inventory fetches without caching an error snapshot', async t => {
  const originalFetch = globalThis.fetch
  const originalLocalStorage = globalThis.localStorage
  const signals = []
  globalThis.localStorage = { getItem: () => null }
  globalThis.fetch = (url, options = {}) => new Promise((_resolve, reject) => {
    signals.push({ url: String(url), signal: options.signal })
    options.signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })), { once: true })
  })
  t.after(() => {
    api.clearKnowledgeDetailCache()
    globalThis.fetch = originalFetch
    globalThis.localStorage = originalLocalStorage
  })

  api.clearKnowledgeDetailCache()
  const controller = new AbortController()
  const request = api.prefetchKnowledgeDetail('manuals', { signal: controller.signal })
  await new Promise(resolve => setTimeout(resolve, 0))
  assert.equal(signals.length, 3)
  controller.abort()
  await assert.rejects(request, error => error?.name === 'AbortError')
  await new Promise(resolve => setTimeout(resolve, 0))
  assert.ok(signals.every(call => call.signal.aborted))
  assert.equal(api.getCachedKnowledgeDetail('manuals'), null)
})

test('a document-page cancellation does not abort statistics shared by another page', async t => {
  const originalFetch = globalThis.fetch
  const originalLocalStorage = globalThis.localStorage
  const requests = []
  globalThis.localStorage = { getItem: () => null }
  globalThis.fetch = (url, options = {}) => new Promise((resolve, reject) => {
    const target = String(url)
    const request = { target, signal: options.signal, resolve }
    requests.push(request)
    options.signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })), { once: true })
  })
  t.after(() => {
    api.clearKnowledgeDetailCache()
    globalThis.fetch = originalFetch
    globalThis.localStorage = originalLocalStorage
  })

  api.clearKnowledgeDetailCache()
  const cancelled = new AbortController()
  const first = api.prefetchKnowledgeDetail('manuals', { page: 1, signal: cancelled.signal })
  const second = api.prefetchKnowledgeDetail('manuals', { page: 2 })
  await new Promise(resolve => setTimeout(resolve, 0))
  const stats = requests.find(request => request.target.includes('/knowledge/stats'))
  assert.equal(requests.filter(request => request.target.includes('/knowledge/stats')).length, 1)
  cancelled.abort()
  assert.equal(stats.signal.aborted, false)
  for (const request of requests) {
    if (request.target.includes('/document-summaries')) {
      if (!request.signal.aborted) request.resolve(jsonResponse({ documents: [] }))
    } else request.resolve(jsonResponse({ documents: 2 }))
  }
  await assert.rejects(first, error => error?.name === 'AbortError')
  const result = await second
  assert.equal(result.stats.status, 'ready')
})

test('upload task deletion and retry cancellation invalidate every cached document page', async t => {
  const originalFetch = globalThis.fetch
  const originalLocalStorage = globalThis.localStorage
  const calls = []
  globalThis.localStorage = { getItem: () => null }
  globalThis.fetch = async (url, options = {}) => {
    const target = String(url)
    calls.push({ target, options })
    if (target.includes('/document-summaries')) return jsonResponse({ documents: [{ id: target }] })
    if (target.includes('/knowledge/stats')) return jsonResponse({ documents: 2 })
    return jsonResponse({ status: 'ok' })
  }
  t.after(() => {
    api.clearKnowledgeDetailCache()
    globalThis.fetch = originalFetch
    globalThis.localStorage = originalLocalStorage
  })

  api.clearKnowledgeDetailCache()
  await api.prefetchKnowledgeDetail('manuals', { page: 1, pageSize: 10 })
  await api.prefetchKnowledgeDetail('manuals', { page: 2, pageSize: 10 })
  await api.deleteUploadTask('task-1', { kb: 'manuals' })
  assert.equal(api.getCachedKnowledgeDetail('manuals', { page: 1, pageSize: 10 }), null)
  assert.equal(api.getCachedKnowledgeDetail('manuals', { page: 2, pageSize: 10 }), null)

  await api.prefetchKnowledgeDetail('manuals', { page: 1, pageSize: 10 })
  await api.cancelUploadRetry('task-1', { kb: 'manuals' })
  assert.equal(api.getCachedKnowledgeDetail('manuals', { page: 1, pageSize: 10 }), null)
  assert.equal(calls.find(call => call.target.includes('/upload/tasks/task-1?kb=manuals'))?.options.method, 'DELETE')
  assert.equal(calls.find(call => call.target.includes('/upload/tasks/task-1/cancel-retry?kb=manuals'))?.options.method, 'POST')
})

test('authentication generation changes clear the knowledge-base list cache', async t => {
  const originalFetch = globalThis.fetch
  const originalLocalStorage = globalThis.localStorage
  let calls = 0
  globalThis.localStorage = { getItem: () => null }
  globalThis.fetch = async () => {
    calls += 1
    return jsonResponse({ knowledge_bases: [{ name: `kb-${calls}` }] })
  }
  t.after(() => {
    advanceKnowledgeDetailAuthGeneration()
    globalThis.fetch = originalFetch
    globalThis.localStorage = originalLocalStorage
  })

  const first = await api.listKBs({ force: true })
  const cached = await api.listKBs()
  assert.equal(calls, 1)
  assert.deepEqual(cached, first)

  advanceKnowledgeDetailAuthGeneration()
  const nextSession = await api.listKBs()
  assert.equal(calls, 2)
  assert.equal(nextSession.knowledge_bases[0].name, 'kb-2')
})

test('a previous authentication session cannot repopulate or clear the current KB list request', async t => {
  const originalFetch = globalThis.fetch
  const originalLocalStorage = globalThis.localStorage
  const pending = []
  globalThis.localStorage = { getItem: () => null }
  globalThis.fetch = () => new Promise(resolve => pending.push(resolve))
  t.after(() => {
    advanceKnowledgeDetailAuthGeneration()
    globalThis.fetch = originalFetch
    globalThis.localStorage = originalLocalStorage
  })

  const previousSession = api.listKBs({ force: true })
  assert.equal(pending.length, 1)

  advanceKnowledgeDetailAuthGeneration()
  const currentSession = api.listKBs()
  assert.equal(pending.length, 2)

  pending[1](jsonResponse({ knowledge_bases: [{ name: 'current-kb' }] }))
  const currentResult = await currentSession
  assert.equal(currentResult.knowledge_bases[0].name, 'current-kb')

  pending[0](jsonResponse({ knowledge_bases: [{ name: 'previous-kb' }] }))
  await previousSession

  const cachedCurrentResult = await api.listKBs()
  assert.equal(pending.length, 2)
  assert.equal(cachedCurrentResult.knowledge_bases[0].name, 'current-kb')
})

test('a forbidden detail refresh evicts cached rows and returns fail-closed resources', async t => {
  const originalFetch = globalThis.fetch
  const originalLocalStorage = globalThis.localStorage
  let forbidden = false
  globalThis.localStorage = { getItem: () => null }
  globalThis.fetch = async url => {
    if (forbidden) {
      return {
        ok: false,
        status: 403,
        statusText: 'Forbidden',
        text: async () => JSON.stringify({ detail: 'forbidden' }),
      }
    }
    return String(url).includes('/document-summaries')
      ? jsonResponse({ documents: [{ id: 'doc-1' }] })
      : jsonResponse({ documents: 1 })
  }
  t.after(() => {
    api.clearKnowledgeDetailCache()
    globalThis.fetch = originalFetch
    globalThis.localStorage = originalLocalStorage
  })

  api.clearKnowledgeDetailCache()
  await api.prefetchKnowledgeDetail('manuals')
  assert.equal(api.getCachedKnowledgeDetail('manuals').documents.data.length, 1)

  forbidden = true
  const denied = await api.prefetchKnowledgeDetail('manuals', { force: true })
  assert.equal(denied.documents.failClosed, true)
  assert.equal(denied.stats.failClosed, true)
  assert.equal(api.getCachedKnowledgeDetail('manuals'), null)
})

test('getGlobalStatsCached caches per current KB and deduplicates concurrent requests', async t => {
  const originalFetch = globalThis.fetch
  const originalLocalStorage = globalThis.localStorage
  const calls = []
  globalThis.localStorage = { getItem: () => null }
  globalThis.fetch = async url => {
    calls.push(String(url))
    return jsonResponse({ documents: calls.length * 10 })
  }
  t.after(() => {
    globalThis.fetch = originalFetch
    globalThis.localStorage = originalLocalStorage
    advanceKnowledgeDetailAuthGeneration()
  })

  advanceKnowledgeDetailAuthGeneration()
  setCurrentKB('demo')
  const [first, second] = await Promise.all([
    api.getGlobalStatsCached(),
    api.getGlobalStatsCached(),
  ])
  assert.equal(calls.length, 1)
  assert.deepEqual(first, { documents: 10 })
  assert.deepEqual(second, { documents: 10 })

  const cached = await api.getGlobalStatsCached()
  assert.equal(calls.length, 1)
  assert.match(calls[0], /kb=demo/)
  assert.deepEqual(cached, { documents: 10 })
})

test('getGlobalStatsCached skips empty early return and refetches after auth generation advance', async t => {
  const originalFetch = globalThis.fetch
  const originalLocalStorage = globalThis.localStorage
  const calls = []
  globalThis.localStorage = { getItem: () => null }
  globalThis.fetch = async url => {
    calls.push(String(url))
    return jsonResponse({ documents: calls.length * 10 })
  }
  t.after(() => {
    globalThis.fetch = originalFetch
    globalThis.localStorage = originalLocalStorage
    advanceKnowledgeDetailAuthGeneration()
  })

  advanceKnowledgeDetailAuthGeneration()
  const empty = await api.getGlobalStatsCached()
  assert.deepEqual(empty, {})
  assert.equal(calls.length, 0)

  setCurrentKB('demo')
  const first = await api.getGlobalStatsCached()
  assert.equal(calls.length, 1)
  assert.deepEqual(first, { documents: 10 })

  advanceKnowledgeDetailAuthGeneration()
  setCurrentKB('demo')
  const second = await api.getGlobalStatsCached()
  assert.equal(calls.length, 2)
  assert.deepEqual(second, { documents: 20 })
})

test('getGlobalStatsCached force refreshes past the cached value', async t => {
  const originalFetch = globalThis.fetch
  const originalLocalStorage = globalThis.localStorage
  const calls = []
  globalThis.localStorage = { getItem: () => null }
  globalThis.fetch = async url => {
    calls.push(String(url))
    return jsonResponse({ documents: calls.length * 10 })
  }
  t.after(() => {
    globalThis.fetch = originalFetch
    globalThis.localStorage = originalLocalStorage
    advanceKnowledgeDetailAuthGeneration()
  })

  advanceKnowledgeDetailAuthGeneration()
  setCurrentKB('demo')
  await api.getGlobalStatsCached()
  const forced = await api.getGlobalStatsCached({ force: true })
  assert.equal(calls.length, 2)
  assert.deepEqual(forced, { documents: 20 })
})
