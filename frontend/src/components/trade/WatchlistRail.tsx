import { useCallback, useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronUp, Plus, RefreshCw, Search, X } from 'lucide-react'
import { analyzeApi, watchlistApi } from '../../lib/api'
import { relativeTime } from '../../lib/format'
import type { Signal, WatchlistItem, WatchlistSetupCounts } from '../../types'
import LoadingSpinner from '../LoadingSpinner'

/**
 * Left rail of the Trade screen: the whole watchlist at a glance.
 *
 * This replaces the old Dashboard table, which needed a full page width to say
 * what fits here in 246px. Two marks carry what used to be a "Setup" column and
 * a "Held" column, and their shapes are deliberately different rather than two
 * colours of the same dot — a round dot is a *timing trigger* the engine spotted,
 * a square is a *position you own*. One is an opinion, the other is a fact, and
 * colour alone would not separate them for a red-green colourblind reader.
 */

export type RailFilter = 'ALL' | 'ENTRY' | 'BUY' | 'EXIT_ALERT'

const FILTER_LABEL: Record<RailFilter, string> = {
  ALL: 'All',
  ENTRY: 'Entry',
  BUY: 'Buy',
  EXIT_ALERT: 'Exit',
}

function matches(item: WatchlistItem, f: RailFilter): boolean {
  if (f === 'ALL') return true
  if (f === 'BUY') return item.signal === 'BUY'
  return item.trigger === f
}

const SIGNAL_TONE: Record<Signal | 'PENDING', { bg: string; fg: string }> = {
  BUY: { bg: 'var(--tint-buy)', fg: 'var(--accent-buy)' },
  SELL: { bg: 'var(--tint-sell)', fg: 'var(--accent-sell)' },
  HOLD: { bg: 'var(--tint-hold)', fg: 'var(--accent-hold)' },
  PENDING: { bg: 'var(--color-hover)', fg: 'var(--color-fg-muted)' },
}

// ── Sorting ───────────────────────────────────────────────────────────────────
//
// Kept from the Dashboard table it replaces. Default stays insertion order so
// the rail does not reshuffle itself under anyone who was not asking for that.

type SortField = 'ticker' | 'current_price' | 'day_change_pct' | 'score'
type SortState = { field: SortField; dir: 'asc' | 'desc' } | null

function sortItems(items: WatchlistItem[], sort: SortState): WatchlistItem[] {
  if (!sort) return items
  const { field, dir } = sort
  const factor = dir === 'asc' ? 1 : -1
  return [...items].sort((a, b) => {
    if (field === 'ticker') return a.ticker.localeCompare(b.ticker) * factor
    // Missing values sort last in both directions — a ticker with no price yet
    // is not "the worst performer", it is simply unknown.
    const av = a[field], bv = b[field]
    if (av == null && bv == null) return 0
    if (av == null) return 1
    if (bv == null) return -1
    return (av - bv) * factor
  })
}

function SortHeader({ field, sort, onSort, align = 'right', children }: {
  field: SortField
  sort: SortState
  onSort: (s: SortState) => void
  align?: 'left' | 'right'
  children: React.ReactNode
}) {
  const active = sort?.field === field
  return (
    <button
      onClick={() => {
        // Three-state cycle: descending → ascending → unsorted. Without the
        // third state there is no way back to the original order.
        if (!active) onSort({ field, dir: 'desc' })
        else if (sort!.dir === 'desc') onSort({ field, dir: 'asc' })
        else onSort(null)
      }}
      aria-label={`Sort by ${field.replace('_', ' ')}${
        active ? `, currently ${sort!.dir === 'desc' ? 'descending' : 'ascending'}` : ''
      }`}
      className={`flex items-center gap-0.5 uppercase tracking-[0.1em] transition-colors
                  hover:text-[var(--color-fg)] focus:outline-none focus-visible:ring-1
                  focus-visible:ring-brand-500 ${align === 'right' ? 'justify-end' : ''}
                  ${active ? 'text-[var(--color-fg)]' : ''}`}
    >
      {children}
      <span aria-hidden="true">
        {active && (sort!.dir === 'desc'
          ? <ChevronDown className="h-2.5 w-2.5" />
          : <ChevronUp className="h-2.5 w-2.5" />)}
      </span>
    </button>
  )
}

// ── Add ticker ────────────────────────────────────────────────────────────────

function AddTicker({ onAdded, onClose }: { onAdded: (t: string) => void; onClose: () => void }) {
  const [value, setValue] = useState('')
  const [suggestions, setSuggestions] = useState<{ symbol: string; name: string }[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => { inputRef.current?.focus() }, [])

  const search = useCallback((q: string) => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (!q.trim()) { setSuggestions([]); return }
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await analyzeApi.search(q)
        setSuggestions(res.data.slice(0, 5))
      } catch {
        setSuggestions([])
      }
    }, 300)
  }, [])

  const add = async (ticker: string) => {
    const t = ticker.trim().toUpperCase()
    if (!t || busy) return
    setBusy(true)
    setError(null)
    try {
      await watchlistApi.add(t)
      onAdded(t)
      onClose()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Failed to add ticker.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex gap-1.5">
        <input
          ref={inputRef}
          value={value}
          onChange={(e) => { setValue(e.target.value); setError(null); search(e.target.value) }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') add(value)
            else if (e.key === 'Escape') onClose()
          }}
          placeholder="Ticker or company"
          maxLength={20}
          autoComplete="off"
          aria-label="Add a ticker to the watchlist"
          className="h-7 min-w-0 flex-1 rounded-md border border-[var(--color-border)] bg-[var(--color-bg)]
                     px-2 text-[12px] text-[var(--color-fg)] outline-none focus:border-brand-500"
        />
        <button
          onClick={() => add(value)}
          disabled={busy || !value.trim()}
          className="grid h-7 w-7 flex-shrink-0 place-items-center rounded-md bg-brand-500 text-white
                     disabled:opacity-40"
          aria-label="Add ticker"
        >
          {busy ? <LoadingSpinner size="sm" /> : <Plus className="h-3.5 w-3.5" aria-hidden="true" />}
        </button>
        <button
          onClick={onClose}
          className="grid h-7 w-7 flex-shrink-0 place-items-center rounded-md border
                     border-[var(--color-border)] text-[var(--color-fg-muted)] hover:bg-[var(--color-hover)]"
          aria-label="Cancel adding a ticker"
        >
          <X className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      </div>

      {suggestions.length > 0 && (
        <div className="overflow-hidden rounded-md border border-[var(--color-border)]">
          {suggestions.map((s) => (
            <button
              key={s.symbol}
              onClick={() => add(s.symbol)}
              className="flex w-full items-center gap-2 border-b border-[var(--color-border)] px-2 py-1.5
                         text-left last:border-b-0 hover:bg-[var(--color-hover)]"
            >
              <span className="num w-12 flex-shrink-0 text-[11.5px] font-semibold text-brand-500">
                {s.symbol}
              </span>
              <span className="truncate text-[11px] text-[var(--color-fg-muted)]">{s.name}</span>
            </button>
          ))}
        </div>
      )}

      {error && <p className="text-[10.5px] text-[var(--accent-sell)]">{error}</p>}
    </div>
  )
}

// ── Rail ──────────────────────────────────────────────────────────────────────

interface WatchlistRailProps {
  items: WatchlistItem[]
  setups: WatchlistSetupCounts
  loading: boolean
  selected: string | null
  heldTickers: Set<string>
  lastUpdated: string | null
  onSelect: (ticker: string) => void
  onRefresh: () => void
  onAdded: (ticker: string) => void
}

export default function WatchlistRail({
  items,
  setups,
  loading,
  selected,
  heldTickers,
  lastUpdated,
  onSelect,
  onRefresh,
  onAdded,
}: WatchlistRailProps) {
  const [filter, setFilter] = useState<RailFilter>('ALL')
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<SortState>(null)
  const [adding, setAdding] = useState(false)

  const counts: Record<RailFilter, number> = {
    ALL: items.length,
    ENTRY: setups.entry,
    BUY: items.filter((i) => i.signal === 'BUY').length,
    EXIT_ALERT: setups.exit_alert,
  }

  const q = query.trim().toUpperCase()
  const rows = sortItems(
    items.filter((i) => matches(i, filter) && (!q || i.ticker.includes(q))),
    sort,
  )

  return (
    <aside className="flex min-h-0 flex-col border-r border-[var(--color-border)] bg-[var(--color-surface)]">
      <div className="flex flex-col gap-1.5 border-b border-[var(--color-border)] p-2">
        {adding ? (
          <AddTicker onAdded={onAdded} onClose={() => setAdding(false)} />
        ) : (
          <>
            <div className="flex gap-1.5">
              <div className="relative min-w-0 flex-1">
                <Search
                  aria-hidden="true"
                  className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-[var(--color-fg-muted)]"
                />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Filter watchlist"
                  aria-label="Filter watchlist"
                  className="h-7 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg)]
                             pl-7 pr-2 text-[12px] text-[var(--color-fg)] outline-none focus:border-brand-500"
                />
              </div>
              <button
                onClick={() => setAdding(true)}
                aria-label="Add a ticker to the watchlist"
                className="grid h-7 w-7 flex-shrink-0 place-items-center rounded-md border
                           border-[var(--color-border)] text-[var(--color-fg-muted)]
                           hover:bg-[var(--color-hover)] hover:text-[var(--color-fg)]"
              >
                <Plus className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
              <button
                onClick={onRefresh}
                disabled={loading}
                title={lastUpdated ? `Updated ${relativeTime(lastUpdated)}` : 'Refresh watchlist'}
                aria-label="Refresh watchlist"
                className="grid h-7 w-7 flex-shrink-0 place-items-center rounded-md border
                           border-[var(--color-border)] text-[var(--color-fg-muted)]
                           hover:bg-[var(--color-hover)] hover:text-[var(--color-fg)] disabled:opacity-40"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" />
              </button>
            </div>

            <div className="flex gap-1">
              {(['ALL', 'ENTRY', 'BUY', 'EXIT_ALERT'] as RailFilter[]).map((f) => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  aria-pressed={filter === f}
                  className="chip flex-1 px-1.5"
                >
                  {FILTER_LABEL[f]}
                  <span className="num ml-1 opacity-55">{counts[f]}</span>
                </button>
              ))}
            </div>
          </>
        )}
      </div>

      <div
        className="grid h-[22px] items-center gap-0 border-b border-[var(--color-border)] px-2.5
                   text-[9.5px] uppercase tracking-[0.1em] text-[var(--color-fg-muted)]"
        style={{ gridTemplateColumns: '1fr 62px 46px 34px' }}
      >
        <SortHeader field="ticker" sort={sort} onSort={setSort} align="left">Symbol</SortHeader>
        <SortHeader field="current_price" sort={sort} onSort={setSort}>Last</SortHeader>
        <SortHeader field="day_change_pct" sort={sort} onSort={setSort}>Chg</SortHeader>
        <SortHeader field="score" sort={sort} onSort={setSort}>Scr</SortHeader>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading && items.length === 0 ? (
          [...Array(8)].map((_, i) => (
            <div key={i} className="flex animate-pulse items-center gap-2 px-2.5 py-2">
              <div className="h-3 w-10 rounded bg-[var(--color-border)]" />
              <div className="h-3 w-8 rounded bg-[var(--color-border)]/60" />
              <div className="ml-auto h-3 w-10 rounded bg-[var(--color-border)]/40" />
            </div>
          ))
        ) : rows.length === 0 ? (
          <p className="px-3 py-6 text-center text-[11px] leading-relaxed text-[var(--color-fg-muted)]">
            {items.length === 0
              ? 'Your watchlist is empty. Add a ticker to get signals and dip-buy timing.'
              : filter === 'ENTRY'
                ? 'No dip-buy setups right now.'
                : filter === 'EXIT_ALERT'
                  ? 'Nothing overbought on your watchlist.'
                  : 'Nothing matches that filter.'}
          </p>
        ) : (
          rows.map((r) => {
            const isSel = r.ticker === selected
            const held = heldTickers.has(r.ticker)
            const tone = SIGNAL_TONE[r.signal]
            const chg = r.day_change_pct
            return (
              <button
                key={r.ticker}
                onClick={() => onSelect(r.ticker)}
                aria-current={isSel ? 'true' : undefined}
                className={`grid w-full items-center gap-0 border-b border-[var(--color-border)] py-[5px]
                            pl-2 pr-2.5 text-left transition-colors hover:bg-[var(--color-hover)]
                            focus:outline-none focus-visible:bg-[var(--color-hover)]
                            ${isSel ? 'bg-[var(--color-hover)]' : ''}`}
                style={{
                  gridTemplateColumns: '1fr 62px 46px 34px',
                  borderLeft: `2px solid ${isSel ? '#f2600c' : 'transparent'}`,
                }}
              >
                <span className="flex min-w-0 items-center gap-1.5">
                  {/* Round dot = timing trigger the engine spotted. */}
                  <span
                    aria-hidden="true"
                    className="h-[5px] w-[5px] flex-shrink-0 rounded-full"
                    style={{
                      background: r.trigger === 'ENTRY' ? 'var(--accent-buy)'
                        : r.trigger === 'EXIT_ALERT' ? 'var(--accent-sell)'
                          : 'transparent',
                    }}
                  />
                  <span className="num truncate text-[12px] font-semibold text-[var(--color-fg)]">
                    {r.ticker}
                  </span>
                  {/* Square = a position you actually hold. Different shape, not
                      just a different colour — see the note at the top. */}
                  {held && (
                    <span
                      aria-hidden="true"
                      className="h-1.5 w-1.5 flex-shrink-0 rounded-[2px] bg-brand-500"
                    />
                  )}
                  <span
                    className="flex-shrink-0 rounded px-1 py-px text-[9px] font-bold leading-[1.4]"
                    style={{ background: tone.bg, color: tone.fg }}
                  >
                    {r.signal}
                  </span>
                  <span className="sr-only">
                    {r.trigger === 'ENTRY' ? ', entry setup' : r.trigger === 'EXIT_ALERT' ? ', exit alert' : ''}
                    {held ? ', held' : ''}
                  </span>
                </span>

                <span className="num text-right text-[12px] text-[var(--color-fg)]">
                  {r.current_price != null ? r.current_price.toFixed(2) : '—'}
                </span>
                <span
                  className="num text-right text-[11.5px]"
                  style={{
                    color: chg == null ? 'var(--color-fg-muted)'
                      : chg >= 0 ? 'var(--accent-buy)' : 'var(--accent-sell)',
                  }}
                >
                  {chg != null ? `${chg >= 0 ? '+' : ''}${chg.toFixed(1)}` : '—'}
                </span>
                <span className="num text-right text-[11.5px] text-[var(--color-fg-muted)]">
                  {Math.round(r.score * 100)}
                </span>
              </button>
            )
          })
        )}
      </div>

      <div className="flex flex-wrap gap-x-3 gap-y-1 border-t border-[var(--color-border)] px-2.5 py-2
                      text-[10px] text-[var(--color-fg-muted)]">
        <span className="flex items-center gap-1">
          <span aria-hidden="true" className="h-[5px] w-[5px] rounded-full bg-[var(--accent-buy)]" />
          Entry setup
        </span>
        <span className="flex items-center gap-1">
          <span aria-hidden="true" className="h-[5px] w-[5px] rounded-full bg-[var(--accent-sell)]" />
          Exit alert
        </span>
        <span className="flex items-center gap-1">
          <span aria-hidden="true" className="h-1.5 w-1.5 rounded-[2px] bg-brand-500" />
          Held
        </span>
      </div>
    </aside>
  )
}
