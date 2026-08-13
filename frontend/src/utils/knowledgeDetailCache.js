export const KNOWLEDGE_DETAIL_CACHE_TTL_MS = 30_000
export const KNOWLEDGE_DETAIL_CACHE_MAX_ENTRIES = 20

function requireKBName(kbName) {
  if (typeof kbName !== 'string' || !kbName) {
    throw new TypeError('A non-empty KB name is required')
  }
  return kbName
}

/**
 * Build an unambiguous key for an authenticated knowledge-base detail read.
 * The scope is deliberately part of the key so a later login cannot reuse
 * data fetched under an earlier authentication generation.
 */
export function normalizeDocumentPageQuery({ page = 1, pageSize = 10, q = '' } = {}) {
  const normalizedPage = Number.isInteger(Number(page)) && Number(page) > 0 ? Number(page) : 1
  const normalizedPageSize = Number.isInteger(Number(pageSize)) && Number(pageSize) > 0
    ? Number(pageSize)
    : 10
  return {
    page: normalizedPage,
    pageSize: normalizedPageSize,
    q: String(q || '').trim().toLowerCase(),
  }
}

export function knowledgeDetailCacheKey(authGeneration, kbName, pageQuery) {
  const normalized = normalizeDocumentPageQuery(pageQuery)
  return JSON.stringify([
    authGeneration,
    requireKBName(kbName),
    normalized.page,
    normalized.pageSize,
    normalized.q,
  ])
}

/**
 * Small, dependency-free cache for document-summary and statistic payloads.
 *
 * Entries are intentionally memory-only. Callers change the authentication
 * generation on login/logout/expiry; doing so clears both resolved and
 * in-flight data. `read()` retains expired data so a page can render it as
 * stale while it starts a refresh, but `load()` only reuses fresh entries.
 */
export function createKnowledgeDetailCache({
  now = () => Date.now(),
  ttlMs = KNOWLEDGE_DETAIL_CACHE_TTL_MS,
  maxEntries = KNOWLEDGE_DETAIL_CACHE_MAX_ENTRIES,
  authGeneration = 0,
} = {}) {
  if (!Number.isFinite(ttlMs) || ttlMs < 0) {
    throw new TypeError('ttlMs must be a non-negative finite number')
  }
  if (!Number.isInteger(maxEntries) || maxEntries < 1) {
    throw new TypeError('maxEntries must be a positive integer')
  }
  if (typeof now !== 'function') {
    throw new TypeError('now must be a function')
  }

  let activeGeneration = authGeneration
  let invalidationEpoch = 0
  const entries = new Map()
  const inFlight = new Map()
  const leasedInFlight = new Map()
  const keyRevisions = new Map()

  const currentKey = (kbName, pageQuery) => knowledgeDetailCacheKey(activeGeneration, kbName, pageQuery)

  const revisionFor = key => keyRevisions.get(key) || 0

  const touch = (key, entry) => {
    entries.delete(key)
    entries.set(key, entry)
    while (entries.size > maxEntries) {
      const oldestKey = entries.keys().next().value
      entries.delete(oldestKey)
    }
  }

  const read = (kbName, pageQuery) => {
    const key = currentKey(kbName, pageQuery)
    const entry = entries.get(key)
    if (!entry) return null

    touch(key, entry)
    const ageMs = Math.max(0, Number(now()) - entry.cachedAt)
    return {
      value: entry.value,
      cachedAt: entry.cachedAt,
      ageMs,
      fresh: ageMs <= ttlMs,
    }
  }

  const invalidate = (kbName, pageQuery) => {
    const key = currentKey(kbName, pageQuery)
    inFlight.get(key)?.controller?.abort()
    leasedInFlight.get(key)?.controller?.abort()
    entries.delete(key)
    inFlight.delete(key)
    leasedInFlight.delete(key)
    keyRevisions.set(key, revisionFor(key) + 1)
  }

  const invalidateKB = kbName => {
    const normalizedName = requireKBName(kbName)
    for (const key of new Set([...entries.keys(), ...inFlight.keys(), ...leasedInFlight.keys(), ...keyRevisions.keys()])) {
      try {
        if (JSON.parse(key)[1] !== normalizedName) continue
      } catch {
        continue
      }
      inFlight.get(key)?.controller?.abort()
      leasedInFlight.get(key)?.controller?.abort()
      entries.delete(key)
      inFlight.delete(key)
      leasedInFlight.delete(key)
      keyRevisions.set(key, revisionFor(key) + 1)
    }
  }

  const invalidateAll = () => {
    invalidationEpoch += 1
    for (const flight of inFlight.values()) flight.controller?.abort()
    for (const flight of leasedInFlight.values()) flight.controller?.abort()
    entries.clear()
    inFlight.clear()
    leasedInFlight.clear()
    keyRevisions.clear()
  }

  const setAuthGeneration = generation => {
    if (Object.is(activeGeneration, generation)) return false
    activeGeneration = generation
    invalidateAll()
    return true
  }

  const load = (kbName, loader, {
    force = false,
    shouldCache = () => true,
    ...pageQuery
  } = {}) => {
    const key = currentKey(kbName, pageQuery)
    if (typeof loader !== 'function') {
      throw new TypeError('loader must be a function')
    }
    if (typeof shouldCache !== 'function') {
      throw new TypeError('shouldCache must be a function')
    }

    const snapshot = read(kbName, pageQuery)
    if (!force && snapshot?.fresh) return Promise.resolve(snapshot.value)

    const existing = inFlight.get(key)
    if (existing) return existing.promise

    const requestEpoch = invalidationEpoch
    const requestRevision = revisionFor(key)
    const requestGeneration = activeGeneration
    let request
    request = Promise.resolve()
      .then(() => loader({ kbName, authGeneration: requestGeneration }))
      .then(value => {
        const activeRequest = inFlight.get(key)
        if (
          activeRequest?.promise === request
          && invalidationEpoch === requestEpoch
          && revisionFor(key) === requestRevision
          && Object.is(activeGeneration, requestGeneration)
          && shouldCache(value)
        ) {
          touch(key, { value, cachedAt: Number(now()) })
        }
        return value
      })
      .finally(() => {
        if (inFlight.get(key)?.promise === request) {
          inFlight.delete(key)
        }
      })

    inFlight.set(key, { promise: request })
    return request
  }

  const acquire = (kbName, loader, { signal, ...options } = {}) => {
    if (signal?.aborted) return Promise.reject(Object.assign(new Error('请求已取消'), { name: 'AbortError' }))
    const key = currentKey(kbName, options)
    const force = Boolean(options.force)
    const snapshot = read(kbName, options)
    if (!force && snapshot?.fresh) return Promise.resolve(snapshot.value)
    let flight = leasedInFlight.get(key)
    if (!flight) {
      const controller = new AbortController()
      const requestEpoch = invalidationEpoch
      const requestRevision = revisionFor(key)
      const requestGeneration = activeGeneration
      let request
      request = Promise.resolve()
        .then(() => loader({ kbName, authGeneration: requestGeneration, signal: controller.signal }))
        .then(value => {
          const activeRequest = leasedInFlight.get(key)
          if (
            activeRequest?.promise === request
            && invalidationEpoch === requestEpoch
            && revisionFor(key) === requestRevision
            && Object.is(activeGeneration, requestGeneration)
            && (typeof options.shouldCache !== 'function' || options.shouldCache(value))
          ) touch(key, { value, cachedAt: Number(now()) })
          return value
        })
        .finally(() => {
          flight.settled = true
          if (leasedInFlight.get(key)?.promise === request) leasedInFlight.delete(key)
        })
      flight = { promise: request, controller, consumers: 0, settled: false }
      leasedInFlight.set(key, flight)
    }
    flight.consumers += 1
    let released = false
    const release = () => {
      if (released) return
      released = true
      flight.consumers = Math.max(0, flight.consumers - 1)
      if (!flight.settled && flight.consumers === 0) flight.controller.abort()
    }
    return new Promise((resolve, reject) => {
      const onAbort = () => { release(); reject(Object.assign(new Error('请求已取消'), { name: 'AbortError' })) }
      signal?.addEventListener('abort', onAbort, { once: true })
      flight.promise.then(resolve, reject).finally(() => {
        signal?.removeEventListener('abort', onAbort)
        release()
      })
    })
  }

  return {
    read,
    load,
    acquire,
    invalidate,
    invalidateKB,
    invalidateAll,
    setAuthGeneration,
    getAuthGeneration: () => activeGeneration,
    get size() {
      return entries.size
    },
    get inFlightSize() {
      return inFlight.size + leasedInFlight.size
    },
  }
}

export const knowledgeDetailCache = createKnowledgeDetailCache()
