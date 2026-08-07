import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertCircle, Plus, TrendingUp } from 'lucide-react'
import { watchlistApi } from '../lib/api'
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

// ── Add ticker input ──────────────────────────────────────────────────────────

function AddTickerForm({ onAdded }: { onAdded: () => void }) {
  const [value, setValue] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const ticker = value.trim().toUpperCase()
    if (!ticker) return

    setIsLoading(true)
    setError(null)
    try {
      await watchlistApi.add(ticker)
      setValue('')
      onAdded()
      inputRef.current?.focus()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setError(msg ?? 'Failed to add ticker. Please try again.')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2">
      <div className="flex gap-2">
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={(e) => {
            setValue(e.target.value.toUpperCase())
            setError(null)
          }}
          placeholder="Add ticker (e.g. AAPL)"
          maxLength={10}
          className="input flex-1"
          disabled={isLoading}
        />
        <button
          type="submit"
          disabled={isLoading || !value.trim()}
          className="btn-primary flex-shrink-0 px-4"
        >
          {isLoading ? <LoadingSpinner size="sm" /> : <Plus className="w-4 h-4" />}
          <span className="hidden sm:inline">Add</span>
        </button>
      </div>
      {error && (
        <div className="flex items-center gap-2 text-red-500 text-xs">
          <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
          {error}
        </div>
      )}
    </form>
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
