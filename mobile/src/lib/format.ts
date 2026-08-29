/**
 * Shared formatting helpers — the phone counterpart of the web
 * `frontend/src/lib/format.ts`. Keep the two spellings in step: a timestamp
 * that reads differently on the two clients reads as a bug in the data.
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
 * has to be a property of the data rather than of where the phone is: the
 * same order must not be dated 25 Aug at home and 26 Aug on a trip. Toronto
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

/** Clock time in Toronto: "2:04 PM". Label it "ET" where shown. */
export function formatTime(value: string | Date | null | undefined): string {
  const d = parseTimestamp(value)
  return d ? TIME_FMT.format(d) : '—'
}

const DATETIME_FMT = new Intl.DateTimeFormat('en-US', {
  month: 'short', day: 'numeric', year: 'numeric',
  hour: 'numeric', minute: '2-digit', timeZone: DISPLAY_TZ,
})

/**
 * A precise moment: "Aug 29, 2026, 2:04 PM". Mirrors the web helper.
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
