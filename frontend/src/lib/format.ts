/**
 * Shared formatting helpers.
 *
 * Relative time lived as a private copy inside the old Alpha Radar page, and a
 * second, differently-worded implementation appeared in HoldingsPage. Two
 * spellings of the same idea ("7m ago" vs "7 min ago") read as inconsistency,
 * so this is the single definition every page uses.
 */

/**
 * Compact age of a timestamp: "just now", "7m ago", "3h ago", "2d ago".
 *
 * Accepts an ISO string (what the API returns) or a Date (what a local fetch
 * records). Returns "—" for anything unparseable rather than "NaNm ago".
 */
export function relativeTime(value: string | Date | null | undefined): string {
  if (value == null) return '—'

  const then = value instanceof Date ? value : new Date(value)
  const ms = then.getTime()
  if (Number.isNaN(ms)) return '—'

  // A future timestamp means clock skew between browser and server, not a
  // negative age — clamp rather than render "-3m ago".
  const diff = Math.max(0, Date.now() - ms)

  const m = Math.floor(diff / 60_000)
  if (m < 1) return 'just now'
  if (m < 60) return `${m}m ago`

  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`

  return `${Math.floor(h / 24)}d ago`
}
