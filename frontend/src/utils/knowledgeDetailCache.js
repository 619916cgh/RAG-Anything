import { api } from './api.js'

const CACHE_VERSION = 1
const CACHE_PREFIX = 'raganything:kb-detail:v1:'
const cache = new Map()
const listeners = new Map()
const inFlight = new Map()

const snapshotKey = (userId, kbName) => `${CACHE_PREFIX}${String(userId || '')}:${encodeURIComponent(kbName || '')}`

function validSnapshot(value, userId, kbName) {
  return value
    && value.version === CACHE_VERSION
    && String(value.userId) === String(userId)
    && value.kbName === kbName
    && (Array.isArray(value.docs) || value.docs === null)
    && (value.stats === null || (typeof value.stats === 'object' && !Array.isArray(value.stats)))
    && Number.isFinite(value.updatedAt)
}

function notify(key) {
  listeners.get(key)?.forEach(listener => listener())
}

function persist(key, value) {
  cache.set(key, value)
  try { sessionStorage.setItem(key, JSON.stringify(value)) } catch {}
  notify(key)
  return value
}

export function readKnowledgeDetailSnapshot(userId, kbName) {
  const key = snapshotKey(userId, kbName)
  try {
    const serialized = sessionStorage.getItem(key)
    if (serialized === null) {
      cache.delete(key)
      return null
    }
    const parsed = JSON.parse(serialized)
    if (validSnapshot(parsed, userId, kbName)) {
      cache.set(key, parsed)
      return parsed
    }
    cache.delete(key)
  } catch {}
  const memoryValue = cache.get(key)
  return validSnapshot(memoryValue, userId, kbName) ? memoryValue : null
}

export function subscribeKnowledgeDetailSnapshot(userId, kbName, listener) {
  const key = snapshotKey(userId, kbName)
  const bucket = listeners.get(key) || new Set()
  bucket.add(listener)
  listeners.set(key, bucket)
  return () => {
    bucket.delete(listener)
    if (bucket.size === 0) listeners.delete(key)
  }
}

export function seedKnowledgeDetailStats(userId, kbName, stats) {
  if (!userId || !kbName || !stats || typeof stats !== 'object' || stats.unavailable === true) return null
  const key = snapshotKey(userId, kbName)
  const previous = readKnowledgeDetailSnapshot(userId, kbName)
  if (previous?.stats) return previous
  return persist(key, {
    version: CACHE_VERSION,
    userId: String(userId),
    kbName,
    docs: previous?.docs ?? null,
    stats,
    updatedAt: Date.now(),
  })
}

export function invalidateKnowledgeDetailSnapshot(userId, kbName) {
  const key = snapshotKey(userId, kbName)
  cache.delete(key)
  try { sessionStorage.removeItem(key) } catch {}
  notify(key)
}

export function updateKnowledgeDetailSnapshot(userId, kbName, patch) {
  if (!userId || !kbName || !patch || typeof patch !== 'object') return null
  const previous = readKnowledgeDetailSnapshot(userId, kbName)
  const docs = Array.isArray(patch.docs) || patch.docs === null ? patch.docs : previous?.docs ?? null
  const stats = patch.stats && typeof patch.stats === 'object' ? patch.stats : previous?.stats ?? null
  if (docs === null && stats === null) return null
  return persist(snapshotKey(userId, kbName), {
    version: CACHE_VERSION,
    userId: String(userId),
    kbName,
    docs,
    stats,
    updatedAt: Date.now(),
  })
}

export async function refreshKnowledgeDetailSnapshot(userId, kbName, { signal } = {}) {
  if (!userId || !kbName) return { docs: null, stats: null, docsError: null, statsError: null }
  const key = snapshotKey(userId, kbName)
  if (inFlight.has(key)) return inFlight.get(key)

  const refresh = (async () => {
    const previous = readKnowledgeDetailSnapshot(userId, kbName)
    const [documentsResult, statsResult] = await Promise.allSettled([
      api.getDocuments({ kb: kbName, signal }),
      api.getStats({ kb: kbName, signal }),
    ])
    const docs = documentsResult.status === 'fulfilled'
      ? (documentsResult.value.documents || [])
      : previous?.docs ?? null
    const stats = statsResult.status === 'fulfilled'
      ? statsResult.value
      : previous?.stats ?? null
    const docsError = documentsResult.status === 'rejected' ? documentsResult.reason : null
    const statsError = statsResult.status === 'rejected' ? statsResult.reason : null

    if (docs !== null || stats !== null) {
      updateKnowledgeDetailSnapshot(userId, kbName, { docs, stats })
    }
    return { docs, stats, docsError, statsError }
  })()

  inFlight.set(key, refresh)
  try { return await refresh } finally { inFlight.delete(key) }
}
