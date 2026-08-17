function parseTimestamp(iso) {
  if (!iso || typeof iso !== 'string') return ''
  // Reject version-like strings (for example "0") that Date would turn into a date.
  if (!/[-T]/.test(iso)) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : d
}

/** Format an ISO timestamp as zh-CN date and time in the viewer's local timezone. */
export function formatDate(iso) {
  const d = parseTimestamp(iso)
  if (!d) return ''
  return d.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

/** Format an ISO timestamp as a local clock time, including seconds. */
export function formatTime(iso) {
  const d = parseTimestamp(iso)
  if (!d) return ''
  return d.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}
