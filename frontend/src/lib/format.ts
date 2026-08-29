/**
 * Shared formatting helpers.
 *
 * Relative time lived as a private copy inside the old Alpha Radar page, and a
 * second, differently-worded implementation appeared in HoldingsPage. Two
 * spellings of the same idea ("7m ago" vs "7 min ago") read as inconsistency,
 * so this is the single definition every page uses.
 */

/**
 * Parse a timestamp the API returned.
 *
 * The backend writes UTC, but the datetimes come back out of MongoDB tz-naive,
 * so the JSON often carries no offset — and `new Date('2026-08-25T18:04:00')`
 * reads that as *local* time, shifting every timestamp by the viewer's UTC
 * offset. A datetime with no zone designator is UTC, because UTC is the only
 * thing the backend writes. Returns null for anything unparseable so callers
 * can render "—" rather than "Invalid Date".
 */
export function parseTimestamp(value: string | Date | null | undefined): Date | null {
  if (value == null) return null

  let d: Date
  if (value instanceof Date) {
    d = value
  } else {
    // Space-separated forms fail outright in Safari; normalise before parsing.
    const s = value.trim().replace(' ', 'T')
    const hasTime = /\d{2}:\d{2}/.test(s)
    const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(s)
    d = new Date(hasTime && !hasZone ? `${s}Z` : s)
  }
  return Number.isNaN(d.getTime()) ? null : d
}

/**
 * Everything with a timestamp renders in Toronto time, not the viewer's.
 *
 * A trading record is read against the session it happened in, so the zone
 * has to be a property of the data rather than of where the laptop is: the
 * same order must not be dated 25 Aug at a desk and 26 Aug on a trip. Toronto
 * is US market time, so an order stamped 9:31 AM is one minute into the open
 * wherever it is read.
 */
export const DISPLAY_TZ = 'America/Toronto'

const DATE_FMT = new Intl.DateTimeFormat('en-US', {
  month: 'short', day: 'numeric', year: 'numeric', timeZone: DISPLAY_TZ,
})
const TIME_FMT = new Intl.DateTimeFormat('en-US', {
  hour: 'numeric', minute: '2-digit', timeZone: DISPLAY_TZ,
})

/** Calendar date in Toronto: "Aug 25, 2026". */
export function formatDate(value: string | Date | null | undefined): string {
  const d = parseTimestamp(value)
  return d ? DATE_FMT.format(d) : '—'
}

/** Clock time in Toronto: "2:04 PM". Label the column "(ET)" where shown. */
export function formatTime(value: string | Date | null | undefined): string {
  const d = parseTimestamp(value)
  return d ? TIME_FMT.format(d) : '—'
}

// en-CA renders as yyyy-mm-dd, the exact format `<input type="date">` uses —
// so a date-range filter can compare this against its own value as strings,
// in Toronto's calendar day rather than the browser's.
const DATE_KEY_FMT = new Intl.DateTimeFormat('en-CA', {
  year: 'numeric', month: '2-digit', day: '2-digit', timeZone: DISPLAY_TZ,
})

const DATETIME_FMT = new Intl.DateTimeFormat('en-US', {
  month: 'short', day: 'numeric', year: 'numeric',
  hour: 'numeric', minute: '2-digit', timeZone: DISPLAY_TZ,
})
const DATETIME_NO_YEAR_FMT = new Intl.DateTimeFormat('en-US', {
  month: 'short', day: 'numeric',
  hour: 'numeric', minute: '2-digit', timeZone: DISPLAY_TZ,
})

/**
 * A precise moment: "Aug 29, 2026, 2:04 PM".
 *
 * Use this wherever a record is a *thing that happened* rather than a day it
 * happened on. A closed trade dated only "Aug 29" cannot be told apart from
 * another closed forty minutes earlier, and a fill stamped only "2:04 PM"
 * could be from yesterday — either half alone is ambiguous exactly when the
 * reader is checking something recent, which is when they usually are.
 */
export function formatDateTime(value: string | Date | null | undefined): string {
  const d = parseTimestamp(value)
  return d ? DATETIME_FMT.format(d) : '—'
}

/**
 * The same moment, dropping the year when it is the current one:
 * "Aug 29, 2:04 PM", but "Aug 29, 2025, 2:04 PM" for anything older.
 *
 * For dense surfaces — the activity log's left column — where the full form
 * does not fit. The year is only omitted when it cannot be misread: a record
 * from a previous year keeps it, so shortening never costs correctness. The
 * comparison is made in Toronto's calendar, not the browser's, for the same
 * reason every other timestamp here is.
 */
export function formatDateTimeShort(value: string | Date | null | undefined): string {
  const d = parseTimestamp(value)
  if (!d) return '—'
  const thisYear = DATE_KEY_FMT.format(new Date()).slice(0, 4)
  const thatYear = DATE_KEY_FMT.format(d).slice(0, 4)
  return (thatYear === thisYear ? DATETIME_NO_YEAR_FMT : DATETIME_FMT).format(d)
}

/** Toronto calendar day as "yyyy-mm-dd", for range comparisons. Null if unparseable. */
export function dateKey(value: string | Date | null | undefined): string | null {
  const d = parseTimestamp(value)
  return d ? DATE_KEY_FMT.format(d) : null
}

/**
 * Compact age of a timestamp: "just now", "7m ago", "3h ago", "2d ago".
 *
 * Accepts an ISO string (what the API returns) or a Date (what a local fetch
 * records). Returns "—" for anything unparseable rather than "NaNm ago".
 */
export function relativeTime(value: string | Date | null | undefined): string {
  const then = parseTimestamp(value)
  if (!then) return '—'
  const ms = then.getTime()

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
