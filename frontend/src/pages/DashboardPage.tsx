import { useEffect, useRef, useState, useCallback } from 'react'
import { flushSync } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { AlertCircle, Plus, Search, TrendingUp } from 'lucide-react'
import { watchlistApi, analyzeApi } from '../lib/api'
import type { WatchlistItem } from '../types'
import Layout from '../components/Layout'
import SignalBadge from '../components/SignalBadge'
import ConvictionBadge from '../components/ConvictionBadge'
import LoadingSpinner from '../components/LoadingSpinner'

// ── Score bar ─────────────────────────────────────────────────────────────────

function ScoreBar({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-[var(--color-border)] overflow-hidden">
        <div
          className="h-full rounded-full bg-gradient-to-r from-brand-500 to-brand-600 transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs font-medium text-[var(--color-fg-muted)] w-8 text-right tabular-nums">
        {pct}
      </span>
    </div>
  )
}

// ── Skeleton card ─────────────────────────────────────────────────────────────

function SkeletonCard() {
  return (
    <div className="card p-4 animate-pulse">
      <div className="flex items-start justify-between mb-3">
        <div className="h-6 w-20 rounded-lg bg-[var(--color-border)]" />
        <div className="h-5 w-12 rounded-full bg-[var(--color-border)]" />
      </div>
      <div className="h-4 w-16 rounded-lg bg-[var(--color-border)] mb-3" />
      <div className="h-1.5 rounded-full bg-[var(--color-border)] mb-4" />
      <div className="h-3 w-full rounded bg-[var(--color-border)] mb-1.5" />
      <div className="h-3 w-3/4 rounded bg-[var(--color-border)]" />
    </div>
  )
}

// ── Watchlist card ────────────────────────────────────────────────────────────

function WatchlistCard({ item }: { item: WatchlistItem }) {
  const navigate = useNavigate()

  return (
    <button
      onClick={() => navigate(`/ticker/${item.ticker}`)}
      className="card p-4 text-left w-full hover:border-brand-500/40 hover:shadow-brand-sm
                 active:scale-[0.98] transition-all duration-200 focus:outline-none
                 focus:ring-2 focus:ring-brand-500/50"
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <div>
          <span
            className="block text-xl font-semibold text-[var(--color-fg)] leading-none mb-1"
            style={{ fontFamily: 'Fraunces, Georgia, serif' }}
          >
            {item.ticker}
          </span>
          {item.conviction && <ConvictionBadge conviction={item.conviction} />}
        </div>
        <SignalBadge signal={item.signal} />
      </div>

      {/* Score bar */}
      <div className="mb-3">
        <div className="flex justify-between mb-1">
          <span className="text-xs text-[var(--color-fg-muted)]">Score</span>
          <span className="text-xs text-[var(--color-fg-muted)]">
            {Math.round(item.confidence * 100)}% confidence
          </span>
        </div>
        <ScoreBar score={item.score} />
      </div>

      {/* Price target */}
      {item.price_target && (
        <div className="flex items-center gap-1.5 mb-2">
          <TrendingUp className="w-3.5 h-3.5 text-brand-500 flex-shrink-0" />
          <span className="text-xs text-[var(--color-fg-muted)]">
            Target: <span className="text-[var(--color-fg)] font-medium">${item.price_target.toFixed(2)}</span>
          </span>
        </div>
      )}

      {/* Thesis preview */}
      {item.thesis && (
        <p className="text-xs text-[var(--color-fg-muted)] line-clamp-2 leading-relaxed">
          {item.thesis}
        </p>
      )}

      {/* Footer timestamp */}
      <div className="mt-3 pt-2 border-t border-[var(--color-border)]">
        <span className="text-[0.65rem] text-[var(--color-fg-muted)]">
          Updated {new Date(item.generated_at).toLocaleDateString()}
        </span>
      </div>
    </button>
  )
}

// ── Add ticker input with autocomplete ───────────────────────────────────────

function AddTickerForm({ onAdded }: { onAdded: () => void }) {
  const [value, setValue] = useState('')
  const [suggestions, setSuggestions] = useState<{ symbol: string; name: string }[]>([])
  const [isSearching, setIsSearching] = useState(false)
  const [isAdding, setIsAdding] = useState(false)
  const [activeIdx, setActiveIdx] = useState(-1)
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  // Debounced Finnhub search
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

  // Close dropdown on outside click
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
      // Trigger full analysis pipeline (5-10s) — keeps busy state visible
      await analyzeApi.get(t, true)
      setValue('')
      setSuggestions([])
      setOpen(false)
      onAdded()
      inputRef.current?.focus()
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
          {/* Search icon / spinner */}
          <div className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-fg-muted)]">
            {isSearching
              ? <LoadingSpinner size="sm" />
              : <Search className="w-4 h-4" />}
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

          {/* Dropdown */}
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
                  <span className="font-semibold text-sm w-16 flex-shrink-0 text-brand-500">
                    {s.symbol}
                  </span>
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

      {isAdding && (
        <div className="flex items-center gap-3 px-4 py-3 rounded-xl
                        bg-brand-500/10 border border-brand-500/30 text-brand-500">
          <LoadingSpinner size="sm" />
          <span className="text-sm font-medium">
            Fetching &amp; analysing <strong>{value.trim().toUpperCase()}</strong> — this may take 5–10 seconds…
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
        Add tickers to your watchlist above to get AI-powered signal analysis.
      </p>
    </div>
  )
}

// ── Dashboard Page ────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const [items, setItems] = useState<WatchlistItem[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchWatchlist = async () => {
    setError(null)
    try {
      const res = await watchlistApi.get()
      const data = res.data
      // Support both array and { items: [] } response shapes
      setItems(Array.isArray(data) ? data : (data.items ?? []))
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setError(msg ?? 'Failed to load watchlist.')
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    fetchWatchlist()
  }, [])

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
        <div className="flex flex-col gap-3 sm:grid sm:grid-cols-2">
          {[...Array(4)].map((_, i) => <SkeletonCard key={i} />)}
        </div>
      ) : items.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="flex flex-col gap-3 sm:grid sm:grid-cols-2">
          {items.map((item) => (
            <WatchlistCard key={item.ticker} item={item} />
          ))}
        </div>
      )}
    </Layout>
  )
}
