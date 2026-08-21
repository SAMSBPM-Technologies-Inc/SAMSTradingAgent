import { useEffect, useRef, useState, useCallback } from 'react'
import { flushSync } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import {
  AlertCircle,
  ArrowRight,
  ChevronDown,
  ChevronUp,
  Clock,
  Minus,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  TrendingDown,
  TrendingUp,
} from 'lucide-react'
import { watchlistApi, analyzeApi } from '../lib/api'
import { useToast } from '../lib/toast-context'
import { relativeTime } from '../lib/format'
import type { Signal, Trigger, WatchlistItem, WatchlistSetupCounts } from '../types'
import Layout from '../components/Layout'
import SignalBadge from '../components/SignalBadge'
import ConvictionBadge from '../components/ConvictionBadge'
import LoadingSpinner from '../components/LoadingSpinner'

// ── Filters ───────────────────────────────────────────────────────────────────
//
// One bar mixes two axes deliberately: the verdict (BUY/HOLD/SELL, "is this a
// good business at this price") and the setup (DIP/PROFIT, "is now the moment").
// They were separate pages answering the same question about the same tickers.

type Filter = 'ALL' | Signal | 'ENTRY' | 'EXIT_ALERT'

const SETUP_FILTERS: Filter[] = ['ENTRY', 'EXIT_ALERT']

const FILTER_LABEL: Record<Filter, string> = {
  ALL: 'All',
  ENTRY: 'Dip entry',
  EXIT_ALERT: 'Take profit',
  BUY: 'Buy',
  HOLD: 'Hold',
  SELL: 'Sell',
}

function matchesFilter(item: WatchlistItem, f: Filter): boolean {
  if (f === 'ALL') return true
  if (f === 'ENTRY' || f === 'EXIT_ALERT') return item.trigger === f
  return item.signal === f
}

function FilterBar({ active, onChange, counts }: {
  active: Filter
  onChange: (f: Filter) => void
  counts: Record<Filter, number>
}) {
  const options: Filter[] = ['ALL', 'ENTRY', 'EXIT_ALERT', 'BUY', 'HOLD', 'SELL']
  return (
    <div className="flex items-center gap-1 flex-wrap">
      {options.map((f) => {
        const isSetup = SETUP_FILTERS.includes(f)
        return (
          <button
            key={f}
            onClick={() => onChange(f)}
            className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
              active === f
                ? isSetup
                  ? f === 'ENTRY' ? 'bg-green-600 text-white' : 'bg-amber-500 text-white'
                  : 'bg-brand-500 text-white'
                : isSetup && counts[f] > 0
                  ? f === 'ENTRY'
                    ? 'bg-green-500/10 text-green-600 dark:text-green-400 hover:bg-green-500/20'
                    : 'bg-amber-500/10 text-amber-600 dark:text-amber-400 hover:bg-amber-500/20'
                  : 'bg-[var(--color-border)]/50 text-[var(--color-fg-muted)] hover:text-[var(--color-fg)]'
            }`}
          >
            {FILTER_LABEL[f]}
            <span className={`ml-1.5 tabular-nums ${active === f ? 'opacity-80' : 'opacity-60'}`}>
              {counts[f]}
            </span>
          </button>
        )
      })}
    </div>
  )
}

// ── Setup badge ───────────────────────────────────────────────────────────────

function SetupBadge({ trigger }: { trigger: Trigger }) {
  if (trigger === 'ENTRY') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold
                       bg-green-500/15 text-green-600 dark:text-green-400 whitespace-nowrap">
        <TrendingDown className="w-3 h-3" />
        DIP ENTRY
      </span>
    )
  }
  if (trigger === 'EXIT_ALERT') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold
                       bg-amber-500/15 text-amber-600 dark:text-amber-400 whitespace-nowrap">
        <TrendingUp className="w-3 h-3" />
        TAKE PROFIT
      </span>
    )
  }
  if (trigger === 'PENDING') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium
                       bg-[var(--color-border)]/60 text-[var(--color-fg-muted)] whitespace-nowrap">
        <Clock className="w-3 h-3" />
        PENDING
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 text-[11px] text-[var(--color-fg-muted)]">
      <Minus className="w-3 h-3" />
    </span>
  )
}

// ── Indicator bar (from the old radar cards) ─────────────────────────────────

function IndicatorBar({ label, value, danger, format }: {
  label: string
  value?: number
  /** Which end of 0–100 is the danger zone. */
  danger: 'low' | 'high'
  format?: (v: number) => string
}) {
  if (value == null) return null
  const pct = Math.min(100, Math.max(0, value))

  const barColor = danger === 'high'
    ? pct > 75 ? 'bg-red-500' : pct > 50 ? 'bg-amber-400' : 'bg-green-500'
    : pct < 25 ? 'bg-brand-500' : pct < 50 ? 'bg-amber-400' : 'bg-green-500'

  return (
    <div className="space-y-0.5">
      <div className="flex justify-between text-xs">
        <span className="text-[var(--color-fg-muted)]">{label}</span>
        <span className="font-medium text-[var(--color-fg)] tabular-nums">
          {format ? format(value) : value.toFixed(1)}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-[var(--color-border)] overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

// ── Expanded row detail ───────────────────────────────────────────────────────

function RowDetail({ item }: { item: WatchlistItem }) {
  const hasIndicators = item.rsi_14 != null || item.stoch_rsi != null || item.bb_pct != null

  return (
    <div className="px-4 py-4 bg-[var(--color-bg)] border-b border-[var(--color-border)]">
      {!hasIndicators ? (
        <p className="text-xs text-[var(--color-fg-muted)]">
          No indicator data yet — analysis is still running in the background.
        </p>
      ) : (
        <div className="grid sm:grid-cols-2 gap-x-8 gap-y-3">
          <div className="space-y-2">
            <IndicatorBar label="RSI-14" value={item.rsi_14} danger="high" />
            <IndicatorBar
              label="Stoch RSI"
              value={item.stoch_rsi != null ? item.stoch_rsi * 100 : undefined}
              danger="high"
              format={(v) => `${v.toFixed(0)}%`}
            />
            <IndicatorBar
              label="BB Position"
              value={item.bb_pct != null ? item.bb_pct * 100 : undefined}
              danger="high"
              format={(v) => `${v.toFixed(0)}%`}
            />
          </div>

          <div className="space-y-2 text-xs">
            {item.pct_from_ma20 != null && (
              <div className="flex justify-between">
                <span className="text-[var(--color-fg-muted)]">Distance from MA-20</span>
                <span className={`font-medium tabular-nums ${
                  item.pct_from_ma20 >= 0 ? 'text-amber-500' : 'text-green-500'
                }`}>
                  {item.pct_from_ma20 > 0 ? '+' : ''}{item.pct_from_ma20.toFixed(1)}%
                </span>
              </div>
            )}
            {item.volume_anomaly != null && (
              <div className="flex justify-between">
                <span className="text-[var(--color-fg-muted)]">Volume vs avg</span>
                <span className={`font-medium tabular-nums ${
                  item.volume_anomaly >= 1.2 ? 'text-green-500' : 'text-[var(--color-fg)]'
                }`}>
                  {item.volume_anomaly.toFixed(2)}x
                </span>
              </div>
            )}
            {item.price_target != null && (
              <div className="flex justify-between">
                <span className="text-[var(--color-fg-muted)]">Price target</span>
                <span className="font-medium tabular-nums text-[var(--color-fg)]">
                  ${item.price_target.toFixed(2)}
                </span>
              </div>
            )}
            {item.computed_at && (
              <div className="flex justify-between">
                <span className="text-[var(--color-fg-muted)]">Indicators computed</span>
                <span className="text-[var(--color-fg-muted)]">{relativeTime(item.computed_at)}</span>
              </div>
            )}
            {item.thesis && (
              <p className="text-[var(--color-fg-muted)] leading-relaxed pt-1 lg:hidden">
                {item.thesis}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Watchlist row ─────────────────────────────────────────────────────────────

function WatchlistRow({ item, expanded, onToggle, onRemove }: {
  item: WatchlistItem
  expanded: boolean
  onToggle: () => void
  onRemove: (t: string) => void
}) {
  const navigate = useNavigate()
  const [removing] = useState(false)
  const scorePct = Math.round(item.score * 100)

  const handleRemove = (e: React.MouseEvent) => {
    e.stopPropagation()
    onRemove(item.ticker)
  }

  const accent =
    item.trigger === 'ENTRY' ? 'border-l-2 border-l-green-500'
    : item.trigger === 'EXIT_ALERT' ? 'border-l-2 border-l-amber-500'
    : 'border-l-2 border-l-transparent'

  return (
    <>
      <div
        onClick={onToggle}
        className={`flex items-center gap-3 pl-3 pr-4 py-3 border-b border-[var(--color-border)]
                    hover:bg-[var(--color-bg)] transition-colors group cursor-pointer ${accent}`}
      >
        {/* Ticker */}
        <button
          onClick={(e) => { e.stopPropagation(); navigate(`/ticker/${item.ticker}`) }}
          className="font-semibold text-sm text-[var(--color-fg)] w-14 flex-shrink-0 text-left hover:text-brand-500 transition-colors"
          style={{ fontFamily: 'Archivo, system-ui, sans-serif' }}
        >
          {item.ticker}
        </button>

        {/* Signal */}
        <div className="w-20 flex-shrink-0">
          <SignalBadge signal={item.signal} />
        </div>

        {/* Score bar + number */}
        <div className="flex items-center gap-1.5 w-16 sm:w-24 flex-shrink-0">
          <div className="flex-1 h-1.5 rounded-sm bg-[var(--color-border)] overflow-hidden hidden sm:block">
            <div
              className="h-full transition-all duration-500"
              style={{ width: `${scorePct}%`, background: '#f2600c', borderRadius: '2px' }}
            />
          </div>
          <span className="text-xs tabular-nums text-[var(--color-fg-muted)] w-6 text-right">{scorePct}</span>
        </div>

        {/* Price + change */}
        <div className="flex items-baseline gap-1 flex-shrink-0 min-w-0">
          {item.current_price != null ? (
            <>
              <span className="text-sm tabular-nums font-medium text-[var(--color-fg)]">
                ${item.current_price.toFixed(2)}
              </span>
              {item.day_change_pct != null && (
                <span className={`text-xs tabular-nums ${item.day_change_pct >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                  {item.day_change_pct >= 0 ? '+' : ''}{item.day_change_pct.toFixed(2)}%
                </span>
              )}
            </>
          ) : (
            <span className="text-xs text-[var(--color-fg-muted)]">—</span>
          )}
        </div>

        {/* Setup */}
        <div className="w-28 flex-shrink-0 hidden sm:block">
          <SetupBadge trigger={item.trigger} />
        </div>

        {/* Conviction */}
        <div className="hidden md:block flex-shrink-0">
          {item.conviction
            ? <ConvictionBadge conviction={item.conviction} />
            : <span className="text-xs text-[var(--color-fg-muted)]">—</span>
          }
        </div>

        {/* Thesis snippet */}
        {item.thesis && (
          <p className="hidden lg:block flex-1 text-xs text-[var(--color-fg-muted)] truncate min-w-0">
            {item.thesis}
          </p>
        )}

        {/* Actions */}
        <div className="flex items-center gap-1 ml-auto flex-shrink-0">
          <button
            onClick={(e) => { e.stopPropagation(); navigate(`/ticker/${item.ticker}`) }}
            className="hidden sm:flex items-center gap-1 px-2 py-1 rounded-lg text-xs text-brand-500 hover:bg-brand-500/10 transition-colors opacity-0 group-hover:opacity-100"
            title="View analysis"
          >
            View <ArrowRight className="w-3 h-3" />
          </button>
          <button
            onClick={handleRemove}
            disabled={removing}
            className="p-1.5 rounded-lg text-[var(--color-fg-muted)] hover:text-red-500 hover:bg-red-500/10 transition-colors"
            title="Remove from watchlist"
          >
            {removing
              ? <LoadingSpinner size="sm" />
              : <Trash2 className="w-3.5 h-3.5" />
            }
          </button>
          <span className="text-[var(--color-fg-muted)]" title={expanded ? 'Hide indicators' : 'Show indicators'}>
            {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </span>
        </div>
      </div>

      {expanded && <RowDetail item={item} />}
    </>
  )
}

// ── Skeleton row ──────────────────────────────────────────────────────────────

function SkeletonRow() {
  return (
    <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--color-border)] animate-pulse">
      <div className="h-4 w-14 rounded bg-[var(--color-border)]" />
      <div className="h-5 w-12 rounded-full bg-[var(--color-border)]" />
      <div className="h-3 flex-1 max-w-24 rounded bg-[var(--color-border)]" />
      <div className="h-4 w-16 rounded bg-[var(--color-border)] ml-auto" />
    </div>
  )
}

// ── Add ticker input with autocomplete ───────────────────────────────────────

function AddTickerForm({ onAdded }: { onAdded: () => void }) {
  const [value, setValue] = useState('')
  const [suggestions, setSuggestions] = useState<{ symbol: string; name: string }[]>([])
  const [isSearching, setIsSearching] = useState(false)
  const [isAdding, setIsAdding] = useState(false)
  const [analyzingTicker, setAnalyzingTicker] = useState<string | null>(null)
  const [activeIdx, setActiveIdx] = useState(-1)
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const search = useCallback((q: string) => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (!q || q.length < 1) { setSuggestions([]); setOpen(false); return }
    debounceRef.current = setTimeout(async () => {
      setIsSearching(true)
      try {
        const res = await analyzeApi.search(q)
        setSuggestions(res.data)
        setOpen(res.data.length > 0)
        setActiveIdx(-1)
      } catch {
        setSuggestions([])
        setOpen(false)
      } finally {
        setIsSearching(false)
      }
    }, 300)
  }, [])

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const selectSuggestion = (symbol: string) => {
    setValue(symbol)
    setSuggestions([])
    setOpen(false)
    inputRef.current?.focus()
  }

  const addTicker = async (ticker: string) => {
    const t = ticker.trim().toUpperCase()
    if (!t) return
    flushSync(() => { setIsAdding(true); setError(null) })
    try {
      await watchlistApi.add(t)
      setValue('')
      setSuggestions([])
      setOpen(false)
      onAdded()
      inputRef.current?.focus()
      setAnalyzingTicker(t)
      analyzeApi.get(t, true)
        .then(() => onAdded())
        .catch(() => {})
        .finally(() => setAnalyzingTicker(null))
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setError(msg ?? 'Failed to add ticker.')
    } finally {
      setIsAdding(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!open) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIdx((i) => Math.min(i + 1, suggestions.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx((i) => Math.max(i - 1, -1))
    } else if (e.key === 'Enter' && activeIdx >= 0) {
      e.preventDefault()
      selectSuggestion(suggestions[activeIdx].symbol)
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <div ref={containerRef} className="flex flex-col gap-2">
      <div className="flex gap-2">
        <div className="relative flex-1">
          <div className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-fg-muted)]">
            {isSearching ? <LoadingSpinner size="sm" /> : <Search className="w-4 h-4" />}
          </div>
          <input
            ref={inputRef}
            type="text"
            value={value}
            onChange={(e) => {
              const v = e.target.value
              setValue(v)
              setError(null)
              search(v)
            }}
            onKeyDown={handleKeyDown}
            onFocus={() => suggestions.length > 0 && setOpen(true)}
            placeholder="Search ticker or company name…"
            maxLength={20}
            className="input pl-9"
            disabled={isAdding}
            autoComplete="off"
          />
          {open && suggestions.length > 0 && (
            <div className="absolute z-50 top-full mt-1 w-full rounded-xl border border-[var(--color-border)]
                            bg-[var(--color-surface)] shadow-lg overflow-hidden">
              {suggestions.map((s, i) => (
                <button
                  key={s.symbol}
                  type="button"
                  onMouseDown={(e) => { e.preventDefault(); selectSuggestion(s.symbol) }}
                  className={`flex items-center gap-3 w-full px-4 py-2.5 text-left transition-colors
                    ${i === activeIdx
                      ? 'bg-brand-500/10 text-[var(--color-fg)]'
                      : 'hover:bg-[var(--color-bg)] text-[var(--color-fg)]'}`}
                >
                  <span className="font-semibold text-sm w-16 flex-shrink-0 text-brand-500">{s.symbol}</span>
                  <span className="text-sm text-[var(--color-fg-muted)] truncate">{s.name}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={() => addTicker(value)}
          disabled={isAdding || !value.trim()}
          className="btn-primary flex-shrink-0 px-4"
        >
          {isAdding ? <LoadingSpinner size="sm" /> : <Plus className="w-4 h-4" />}
          <span className="hidden sm:inline">{isAdding ? 'Adding…' : 'Add'}</span>
        </button>
      </div>

      {analyzingTicker && (
        <div className="flex items-center gap-3 px-4 py-3 rounded-xl
                        bg-brand-500/10 border border-brand-500/30 text-brand-500">
          <LoadingSpinner size="sm" />
          <span className="text-sm font-medium">
            Analysing <strong>{analyzingTicker}</strong> — takes 5–10 seconds…
          </span>
        </div>
      )}
      {error && (
        <div className="flex items-center gap-2 text-red-500 text-xs">
          <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
          {error}
        </div>
      )}
    </div>
  )
}

// ── Criteria legend ───────────────────────────────────────────────────────────

function CriteriaLegend() {
  const [show, setShow] = useState(false)
  return (
    <div className="mb-6">
      <button
        onClick={() => setShow((v) => !v)}
        className="flex items-center gap-2 text-xs text-[var(--color-fg-muted)] hover:text-[var(--color-fg)] transition-colors"
      >
        {show ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
        How setups are detected
      </button>

      {show && (
        <div className="card grid sm:grid-cols-2 gap-4 text-xs text-[var(--color-fg-muted)] mt-3">
          <div>
            <div className="flex items-center gap-1.5 font-semibold text-green-600 dark:text-green-400 mb-2">
              <TrendingDown className="w-3.5 h-3.5" /> Dip entry (all must hold)
            </div>
            <ul className="space-y-1">
              <li>RSI-14 ≤ 45 — not yet overbought</li>
              <li>Stochastic RSI ≤ 20% — oversold</li>
              <li>Bollinger Band position ≤ 35% — near lower band</li>
            </ul>
          </div>
          <div>
            <div className="flex items-center gap-1.5 font-semibold text-amber-600 dark:text-amber-400 mb-2">
              <TrendingUp className="w-3.5 h-3.5" /> Take profit (either fires)
            </div>
            <ul className="space-y-1">
              <li>RSI-14 ≥ 70 — overbought territory</li>
              <li>Bollinger Band position ≥ 90% — near upper band</li>
            </ul>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Sorting ───────────────────────────────────────────────────────────────────
//
// A watchlist you cannot order by score or by today's move is a list, not a
// table. Default stays insertion order so the view does not reshuffle itself
// under anyone who was not asking for that.

type SortField = 'ticker' | 'score' | 'day_change_pct'
type SortState = { field: SortField; dir: 'asc' | 'desc' } | null

function SortHeader({ field, sort, onSort, className = '', children }: {
  field: SortField
  sort: SortState
  onSort: (s: SortState) => void
  className?: string
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
      aria-label={`Sort by ${field}`}
      className={`flex-shrink-0 flex items-center gap-1 text-left uppercase tracking-widest
                  transition-colors hover:text-[var(--color-fg)]
                  ${active ? 'text-[var(--color-fg)]' : ''} ${className}`}
    >
      {children}
      {active && (sort!.dir === 'desc'
        ? <ChevronDown className="w-3 h-3" />
        : <ChevronUp className="w-3 h-3" />)}
    </button>
  )
}

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

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="w-16 h-16 rounded-2xl bg-brand-500/10 flex items-center justify-center mb-4">
        <TrendingUp className="w-8 h-8 text-brand-500" />
      </div>
      <h3
        className="text-lg font-medium text-[var(--color-fg)] mb-2"
        style={{ fontFamily: 'Fraunces, Georgia, serif' }}
      >
        Your watchlist is empty
      </h3>
      <p className="text-sm text-[var(--color-fg-muted)] max-w-xs">
        Add tickers above to get AI-powered signals and dip-buy timing.
      </p>
    </div>
  )
}

// ── Dashboard Page ────────────────────────────────────────────────────────────

const EMPTY_SETUPS: WatchlistSetupCounts = { entry: 0, exit_alert: 0, neutral: 0, pending: 0 }

export default function DashboardPage() {
  const { toast, toastWithUndo } = useToast()
  const [items, setItems] = useState<WatchlistItem[]>([])
  const [setups, setSetups] = useState<WatchlistSetupCounts>(EMPTY_SETUPS)
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<Filter>('ALL')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<string | null>(null)
  const [sort, setSort] = useState<SortState>(null)

  const fetchWatchlist = useCallback(async (showSpinner = false) => {
    if (showSpinner) setIsRefreshing(true)
    setError(null)
    try {
      const res = await watchlistApi.get()
      const data = res.data
      setItems(Array.isArray(data) ? data : (data.items ?? []))
      setSetups(Array.isArray(data) ? EMPTY_SETUPS : (data.setups ?? EMPTY_SETUPS))
      setLastUpdated(new Date().toISOString())
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setError(msg ?? 'Failed to load watchlist.')
    } finally {
      setIsLoading(false)
      setIsRefreshing(false)
    }
  }, [])

  useEffect(() => { fetchWatchlist() }, [fetchWatchlist])

  /**
   * Remove optimistically, but hold the DELETE for the length of the undo
   * window. Previously the request fired on click with no confirmation and no
   * way back — a mis-tap silently destroyed a watchlist entry.
   */
  const handleRemove = (ticker: string) => {
    const snapshot = items
    setItems((prev) => prev.filter((i) => i.ticker !== ticker))

    toastWithUndo(
      `Removed ${ticker}`,
      async () => {
        try {
          await watchlistApi.remove(ticker)
        } catch {
          toast(`Could not remove ${ticker}.`, 'error')
          setItems(snapshot)
        }
      },
      () => setItems(snapshot),
    )
  }

  const counts: Record<Filter, number> = {
    ALL: items.length,
    ENTRY: setups.entry,
    EXIT_ALERT: setups.exit_alert,
    BUY: items.filter((i) => i.signal === 'BUY').length,
    HOLD: items.filter((i) => i.signal === 'HOLD').length,
    SELL: items.filter((i) => i.signal === 'SELL').length,
  }

  const filtered = sortItems(items.filter((i) => matchesFilter(i, filter)), sort)

  const actionable = setups.entry + setups.exit_alert

  return (
    <Layout>
      {/* Page header */}
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3 mb-6">
        <div>
          <h1
            className="text-2xl font-light text-[var(--color-fg)]"
            style={{ fontFamily: 'Fraunces, Georgia, serif' }}
          >
            Your Watchlist
          </h1>
          {!isLoading && (
            <p className="text-sm text-[var(--color-fg-muted)] mt-0.5">
              {items.length} {items.length === 1 ? 'ticker' : 'tickers'} tracked
              {actionable > 0 && (
                <>
                  {' · '}
                  <span className="text-[var(--color-fg)] font-medium">
                    {actionable} {actionable === 1 ? 'setup' : 'setups'} live
                  </span>
                </>
              )}
            </p>
          )}
        </div>

        <div className="flex items-center gap-2 flex-shrink-0">
          {lastUpdated && (
            <span className="text-xs text-[var(--color-fg-muted)]">
              Updated {relativeTime(lastUpdated)}
            </span>
          )}
          <button
            onClick={() => fetchWatchlist(true)}
            disabled={isRefreshing || isLoading}
            className="btn-secondary flex items-center gap-1.5"
          >
            <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
            {isRefreshing ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
      </div>

      {/* Add ticker */}
      <div className="mb-4">
        <AddTickerForm onAdded={fetchWatchlist} />
      </div>

      <CriteriaLegend />

      {/* Error */}
      {error && (
        <div className="flex items-center gap-3 px-4 py-3 rounded-xl
                        bg-red-500/10 border border-red-500/20 text-red-500 text-sm mb-6">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          {error}
        </div>
      )}

      {/* Content */}
      {isLoading ? (
        <div className="card overflow-hidden p-0">
          {[...Array(4)].map((_, i) => <SkeletonRow key={i} />)}
        </div>
      ) : items.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="card overflow-hidden p-0">
          {/* Filter bar */}
          <div className="px-4 py-3 border-b border-[var(--color-border)]">
            <FilterBar active={filter} onChange={setFilter} counts={counts} />
          </div>

          {/* Column headers — must mirror WatchlistRow layout exactly */}
          <div className="hidden sm:flex items-center gap-3 pl-3 pr-4 py-2 border-b border-[var(--color-border)] text-[0.65rem] uppercase tracking-widest text-[var(--color-fg-muted)] select-none border-l-2 border-l-transparent">
            <SortHeader field="ticker" sort={sort} onSort={setSort} className="w-14">Ticker</SortHeader>
            <span className="w-20 flex-shrink-0">Signal</span>
            <SortHeader field="score" sort={sort} onSort={setSort} className="w-24">Score</SortHeader>
            <SortHeader field="day_change_pct" sort={sort} onSort={setSort}>Price</SortHeader>
            <span className="w-28 flex-shrink-0">Setup</span>
            <span className="hidden md:block flex-shrink-0">Conviction</span>
          </div>

          {filtered.length === 0 ? (
            <div className="px-4 py-10 text-center text-sm text-[var(--color-fg-muted)]">
              {filter === 'ENTRY'
                ? 'No dip-buy setups right now. Add more tickers or wait for a pullback.'
                : filter === 'EXIT_ALERT'
                  ? 'Nothing overbought on your watchlist.'
                  : `No ${FILTER_LABEL[filter].toLowerCase()} signals in your watchlist.`}
            </div>
          ) : (
            filtered.map((item) => (
              <WatchlistRow
                key={item.ticker}
                item={item}
                expanded={expanded === item.ticker}
                onToggle={() => setExpanded((cur) => (cur === item.ticker ? null : item.ticker))}
                onRemove={handleRemove}
              />
            ))
          )}
        </div>
      )}
    </Layout>
  )
}
