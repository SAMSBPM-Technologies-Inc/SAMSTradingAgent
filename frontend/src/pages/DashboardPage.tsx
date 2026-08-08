import { useEffect, useRef, useState, useCallback } from 'react'
import { flushSync } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { AlertCircle, ArrowRight, Plus, Search, Trash2, TrendingUp } from 'lucide-react'
import { watchlistApi, analyzeApi } from '../lib/api'
import type { Signal, WatchlistItem } from '../types'
import Layout from '../components/Layout'
import SignalBadge from '../components/SignalBadge'
import ConvictionBadge from '../components/ConvictionBadge'
import LoadingSpinner from '../components/LoadingSpinner'

// ── Filter bar ────────────────────────────────────────────────────────────────

type Filter = 'ALL' | Signal

function FilterBar({ active, onChange, counts }: {
  active: Filter
  onChange: (f: Filter) => void
  counts: Record<Filter, number>
}) {
  const options: Filter[] = ['ALL', 'BUY', 'HOLD', 'SELL']
  return (
    <div className="flex items-center gap-1 flex-wrap">
      {options.map((f) => (
        <button
          key={f}
          onClick={() => onChange(f)}
          className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
            active === f
              ? 'bg-brand-500 text-white'
              : 'bg-[var(--color-border)]/50 text-[var(--color-fg-muted)] hover:text-[var(--color-fg)]'
          }`}
        >
          {f}
          <span className={`ml-1.5 tabular-nums ${active === f ? 'opacity-80' : 'opacity-60'}`}>
            {counts[f]}
          </span>
        </button>
      ))}
    </div>
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

// ── Watchlist row ─────────────────────────────────────────────────────────────

function WatchlistRow({ item, onRemove }: { item: WatchlistItem; onRemove: (t: string) => void }) {
  const navigate = useNavigate()
  const [removing, setRemoving] = useState(false)
  const scorePct = Math.round(item.score * 100)

  const handleRemove = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (removing) return
    setRemoving(true)
    try {
      await watchlistApi.remove(item.ticker)
      onRemove(item.ticker)
    } catch {
      setRemoving(false)
    }
  }

  return (
    <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--color-border)] hover:bg-[var(--color-bg)] transition-colors group">
      {/* Ticker */}
      <button
        onClick={() => navigate(`/ticker/${item.ticker}`)}
        className="font-semibold text-sm text-[var(--color-fg)] w-14 flex-shrink-0 text-left hover:text-brand-500 transition-colors"
        style={{ fontFamily: 'Fraunces, Georgia, serif' }}
      >
        {item.ticker}
      </button>

      {/* Signal */}
      <div className="flex-shrink-0">
        <SignalBadge signal={item.signal} />
      </div>

      {/* Score bar + number */}
      <div className="flex items-center gap-2 w-28 flex-shrink-0">
        <div className="flex-1 h-1.5 rounded-full bg-[var(--color-border)] overflow-hidden">
          <div
            className="h-full rounded-full bg-gradient-to-r from-brand-500 to-brand-600 transition-all duration-500"
            style={{ width: `${scorePct}%` }}
          />
        </div>
        <span className="text-xs tabular-nums text-[var(--color-fg-muted)] w-6 text-right">{scorePct}</span>
      </div>

      {/* Price + change */}
      <div className="hidden sm:flex items-baseline gap-1.5 flex-shrink-0 w-28">
        {item.current_price != null ? (
          <>
            <span className="text-sm tabular-nums text-[var(--color-fg)]">
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
          onClick={() => navigate(`/ticker/${item.ticker}`)}
          className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs text-brand-500 hover:bg-brand-500/10 transition-colors opacity-0 group-hover:opacity-100"
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
      </div>
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
        Add tickers above to get AI-powered signal analysis.
      </p>
    </div>
  )
}

// ── Dashboard Page ────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const [items, setItems] = useState<WatchlistItem[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<Filter>('ALL')

  const fetchWatchlist = async () => {
    setError(null)
    try {
      const res = await watchlistApi.get()
      const data = res.data
      setItems(Array.isArray(data) ? data : (data.items ?? []))
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setError(msg ?? 'Failed to load watchlist.')
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => { fetchWatchlist() }, [])

  const handleRemove = (ticker: string) => {
    setItems((prev) => prev.filter((i) => i.ticker !== ticker))
  }

  const counts: Record<Filter, number> = {
    ALL: items.length,
    BUY: items.filter((i) => i.signal === 'BUY').length,
    HOLD: items.filter((i) => i.signal === 'HOLD').length,
    SELL: items.filter((i) => i.signal === 'SELL').length,
  }

  const filtered = filter === 'ALL' ? items : items.filter((i) => i.signal === filter)

  return (
    <Layout>
      {/* Page header */}
      <div className="flex items-center justify-between mb-6">
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
            </p>
          )}
        </div>
      </div>

      {/* Add ticker */}
      <div className="mb-6">
        <AddTickerForm onAdded={fetchWatchlist} />
      </div>

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
          {/* Filter + column headers */}
          <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-[var(--color-border)] flex-wrap gap-y-2">
            <FilterBar active={filter} onChange={setFilter} counts={counts} />
            {/* Column labels */}
            <div className="hidden sm:flex items-center gap-3 text-[0.65rem] uppercase tracking-widest text-[var(--color-fg-muted)] select-none">
              <span className="w-14">Ticker</span>
              <span className="w-12">Signal</span>
              <span className="w-28">Score</span>
              <span className="w-28">Price</span>
              <span className="hidden md:block">Conviction</span>
            </div>
          </div>

          {filtered.length === 0 ? (
            <div className="px-4 py-10 text-center text-sm text-[var(--color-fg-muted)]">
              No {filter} signals in your watchlist.
            </div>
          ) : (
            filtered.map((item) => (
              <WatchlistRow key={item.ticker} item={item} onRemove={handleRemove} />
            ))
          )}
        </div>
      )}
    </Layout>
  )
}
