// Shared chunking-option helpers for the personal settings page and the
// knowledge-base upload panel.  The backend catalog is an array of
// {id,name,description,cost,cost_level} items, while the upload selector
// (getChunkingStrategyOptions) consumes an object keyed by strategy id, so
// the catalog is normalized here once.

// Minimal usable set when the options request fails on the personal settings
// page (matches the platform defaults docling / recursive).
export const MINIMAL_CHUNKING_STRATEGY_IDS = ['recursive', 'fixed_size']

const BUILTIN_STRATEGY_IDS = ['fixed_size', 'recursive', 'sentence', 'structure', 'semantic', 'agentic']
const RETIRED_PARSER_IDS = new Set(['paddleocr', 'marker'])

export function isRetiredParserId(value) {
  return typeof value === 'string' && RETIRED_PARSER_IDS.has(value.trim().toLowerCase())
}

export function canonicalChunkingStrategyId(value) {
  return value === 'fixed' ? 'fixed_size' : value
}

export function normalizeChunkingStrategyCatalog(catalog) {
  const result = {}
  if (Array.isArray(catalog)) {
    for (const item of catalog) {
      if (item && item.id) result[canonicalChunkingStrategyId(item.id)] = item
    }
  } else if (catalog && typeof catalog === 'object') {
    for (const [id, meta] of Object.entries(catalog)) {
      result[canonicalChunkingStrategyId(id)] = meta || {}
    }
  }
  return result
}

// Built-in six-strategy object used by the upload panel when the catalog
// request fails, so the selector never stays stuck on a loading state.
export function fallbackChunkingStrategyCatalog() {
  return normalizeChunkingStrategyCatalog(
    BUILTIN_STRATEGY_IDS.map(id => ({ id })),
  )
}

// Fallback parser options: the current effective parser plus docling.
export function fallbackParserOptions(currentParser) {
  const normalizedCurrent = typeof currentParser === 'string' ? currentParser.trim() : ''
  const ids = [normalizedCurrent || 'docling', 'docling']
  const seen = new Set()
  return ids
    .filter(id => { if (seen.has(id)) return false; seen.add(id); return true })
    .filter(id => !isRetiredParserId(id))
    .map(id => ({
      id,
      name: id,
      available: true,
    }))
}

// Resolve the parser option list for a select. Retired ids are removed even
// from stale catalogs; only a missing catalog falls back.
export function resolveParserOptions(catalog, currentParser) {
  if (!Array.isArray(catalog)) return fallbackParserOptions(currentParser)
  return catalog.filter(item => !isRetiredParserId(item?.id))
}

// Resolve canonical chunking strategy ids for a select.  A present catalog is
// canonicalized as-is; only a missing catalog falls back to the minimal set.
export function resolveChunkingStrategyIds(catalog) {
  const items = Array.isArray(catalog) ? catalog : MINIMAL_CHUNKING_STRATEGY_IDS.map(id => ({ id }))
  const seen = new Set()
  const result = []
  for (const item of items) {
    if (!item || !item.id) continue
    const id = canonicalChunkingStrategyId(item.id)
    if (seen.has(id)) continue
    seen.add(id)
    result.push({ id, name: item.name || item.id })
  }
  return result
}
