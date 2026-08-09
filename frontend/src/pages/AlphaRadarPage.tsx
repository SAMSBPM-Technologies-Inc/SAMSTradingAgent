import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  Crosshair,
  Minus,
  Plus,
  RefreshCw,
  Trash2,
  TrendingDown,
  TrendingUp,
  X,
} from 'lucide-react'
import { analyzeApi, radarApi, watchlistApi } from '../lib/api'
import type { DipBuyCandidate, DipBuyScanResponse } from '../types'
import LoadingSpinner from '../components/LoadingSpinner'
import Layout from '../components/Layout'

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(n?: number, decimals = 1) {
  if (n == null) return '—'
  return n.toFixed(decimals)
}

function fmtPrice(n?: number) {
  if (n == null) return '—'
  return `$${n.toFixed(2)}`
}

function relativeTime(iso: string) {
  const diff = Date.now() - new Date(iso).getTime()
  const m = Math.floor(diff / 60000)
  if (m < 1) return 'just now'
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

// ── Indicator bar ─────────────────────────────────────────────────────────────

interface IndicatorBarProps {
  label: string
  value?: number
  min: number
  max: number
  danger: 'low' | 'high'   // which end is the danger zone
  format?: (v: number) => string
}

function IndicatorBar({ label, value, min, max, danger, format }: IndicatorBarProps) {
  if (value == null) return null
  const pct = Math.min(100, Math.max(0, ((value - min) / (max - min)) * 100))

  // Color logic: for dip-buy entries (danger=low = low is good / high is bad)
  let barColor = 'bg-green-500'
  if (danger === 'high') {
    // High value is dangerous (overbought)
    barColor = pct > 75 ? 'bg-red-500' : pct > 50 ? 'bg-amber-400' : 'bg-green-500'
  } else {
    // Low value is dangerous (oversold — what we want for entry)
    barColor = pct < 25 ? 'bg-brand-500' : pct < 50 ? 'bg-amber-400' : 'bg-green-500'
  }

  return (
    <div className="space-y-0.5">
      <div className="flex justify-between text-xs">
        <span className="text-[var(--color-fg-muted)]">{label}</span>
        <span className="font-medium text-[var(--color-fg)]">
          {format ? format(value) : fmt(value)}
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

// ── Candidate card ────────────────────────────────────────────────────────────

function EntryCard({ c, onNavigate, onRemove }: { c: DipBuyCandidate; onNavigate: (t: string) => void; onRemove: (t: string) => void }) {
  const [removing, setRemoving] = useState(false)
  const distLabel =
    c.pct_from_ma20 != null
      ? `${c.pct_from_ma20 > 0 ? '+' : ''}${c.pct_from_ma20.toFixed(1)}% from MA-20`
      : null

  const handleRemove = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (removing) return
    setRemoving(true)
    try {
      await watchlistApi.remove(c.ticker)
      onRemove(c.ticker)
    } catch {
      setRemoving(false)
    }
  }

  return (
    <div
      className="card border-l-4 border-l-green-500 cursor-pointer hover:shadow-brand-sm transition-all duration-200"
      onClick={() => onNavigate(c.ticker)}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-bold text-lg text-[var(--color-fg)]" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
              {c.ticker}
            </span>
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-green-500/15 text-green-600 dark:text-green-400">
              <TrendingDown className="w-3 h-3" />
              DIP ENTRY
            </span>
          </div>
          <div className="text-[var(--color-fg-muted)] text-sm mt-0.5">{fmtPrice(c.current_price)}</div>
        </div>
        <div className="flex items-start gap-2">
          <div className="text-right">
            <div className="text-xs text-[var(--color-fg-muted)]">{relativeTime(c.computed_at)}</div>
            {distLabel && (
              <div className="text-xs text-[var(--color-fg-muted)] mt-0.5">{distLabel}</div>
            )}
          </div>
          <button
            onClick={handleRemove}
            disabled={removing}
            className="p-1 rounded-lg text-[var(--color-fg-muted)] hover:text-red-500 hover:bg-red-500/10 transition-colors flex-shrink-0"
            title="Remove from watchlist"
          >
            {removing ? <LoadingSpinner size="sm" /> : <Trash2 className="w-3.5 h-3.5" />}
          </button>
        </div>
      </div>

      {/* Indicators */}
      <div className="space-y-2 mb-3">
        <IndicatorBar label="RSI-14" value={c.rsi_14} min={0} max={100} danger="high" />
        <IndicatorBar
          label="Stoch RSI"
          value={c.stoch_rsi != null ? c.stoch_rsi * 100 : undefined}
          min={0} max={100} danger="high"
          format={(v) => `${v.toFixed(0)}%`}
        />
        <IndicatorBar
          label="BB Position"
          value={c.bb_pct != null ? c.bb_pct * 100 : undefined}
          min={0} max={100} danger="high"
          format={(v) => `${v.toFixed(0)}%`}
        />
      </div>

      {/* Volume */}
      {c.volume_anomaly != null && (
        <div className="flex items-center justify-between text-xs border-t border-[var(--color-border)] pt-2">
          <span className="text-[var(--color-fg-muted)]">Volume vs avg</span>
          <span className={`font-medium ${c.volume_anomaly >= 1.2 ? 'text-green-500' : 'text-[var(--color-fg-muted)]'}`}>
            {c.volume_anomaly.toFixed(2)}x
          </span>
        </div>
      )}

      {/* CTA */}
      <div className="flex items-center gap-1 mt-3 text-xs text-brand-500 font-medium">
        View full analysis <ArrowRight className="w-3 h-3" />
      </div>
    </div>
  )
}

function ExitAlertCard({ c, onNavigate, onRemove }: { c: DipBuyCandidate; onNavigate: (t: string) => void; onRemove: (t: string) => void }) {
  const [removing, setRemoving] = useState(false)
  const distLabel =
    c.pct_from_ma20 != null
      ? `${c.pct_from_ma20 > 0 ? '+' : ''}${c.pct_from_ma20.toFixed(1)}% from MA-20`
      : null

  const handleRemove = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (removing) return
    setRemoving(true)
    try {
      await watchlistApi.remove(c.ticker)
      onRemove(c.ticker)
    } catch {
      setRemoving(false)
    }
  }

  return (
    <div
      className="card border-l-4 border-l-amber-500 cursor-pointer hover:shadow-brand-sm transition-all duration-200"
      onClick={() => onNavigate(c.ticker)}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-bold text-lg text-[var(--color-fg)]" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
              {c.ticker}
            </span>
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-500/15 text-amber-600 dark:text-amber-400">
              <TrendingUp className="w-3 h-3" />
              TAKE PROFIT
            </span>
          </div>
          <div className="text-[var(--color-fg-muted)] text-sm mt-0.5">{fmtPrice(c.current_price)}</div>
        </div>
        <div className="flex items-start gap-2">
          <div className="text-right">
            <div className="text-xs text-[var(--color-fg-muted)]">{relativeTime(c.computed_at)}</div>
            {distLabel && (
              <div className="text-xs font-medium text-amber-500 mt-0.5">{distLabel}</div>
            )}
          </div>
          <button
            onClick={handleRemove}
            disabled={removing}
            className="p-1 rounded-lg text-[var(--color-fg-muted)] hover:text-red-500 hover:bg-red-500/10 transition-colors flex-shrink-0"
            title="Remove from watchlist"
          >
            {removing ? <LoadingSpinner size="sm" /> : <Trash2 className="w-3.5 h-3.5" />}
          </button>
        </div>
      </div>

      {/* Indicators */}
      <div className="space-y-2 mb-3">
        <IndicatorBar label="RSI-14" value={c.rsi_14} min={0} max={100} danger="high" />
        <IndicatorBar
          label="Stoch RSI"
          value={c.stoch_rsi != null ? c.stoch_rsi * 100 : undefined}
          min={0} max={100} danger="high"
          format={(v) => `${v.toFixed(0)}%`}
        />
        <IndicatorBar
          label="BB Position"
          value={c.bb_pct != null ? c.bb_pct * 100 : undefined}
          min={0} max={100} danger="high"
          format={(v) => `${v.toFixed(0)}%`}
        />
      </div>

      {/* Volume */}
      {c.volume_anomaly != null && (
        <div className="flex items-center justify-between text-xs border-t border-[var(--color-border)] pt-2">
          <span className="text-[var(--color-fg-muted)]">Volume vs avg</span>
          <span className={`font-medium ${c.volume_anomaly >= 1.2 ? 'text-amber-500' : 'text-[var(--color-fg-muted)]'}`}>
            {c.volume_anomaly.toFixed(2)}x
          </span>
        </div>
      )}

      {/* CTA */}
      <div className="flex items-center gap-1 mt-3 text-xs text-brand-500 font-medium">
        View full analysis <ArrowRight className="w-3 h-3" />
      </div>
    </div>
  )
}

function NeutralCard({ c, onNavigate, onRemove }: { c: DipBuyCandidate; onNavigate: (t: string) => void; onRemove: (t: string) => void }) {
  const [removing, setRemoving] = useState(false)

  const handleRemove = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (removing) return
    setRemoving(true)
    try {
      await watchlistApi.remove(c.ticker)
      onRemove(c.ticker)
    } catch {
      setRemoving(false)
    }
  }

  return (
    <div
      className="card border-l-4 border-l-[var(--color-border)] cursor-pointer hover:shadow-brand-sm transition-all duration-200"
      onClick={() => onNavigate(c.ticker)}
    >
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-bold text-lg text-[var(--color-fg)]" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
              {c.ticker}
            </span>
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-[var(--color-border)]/60 text-[var(--color-fg-muted)]">
              <Minus className="w-3 h-3" />
              WATCHING
            </span>
          </div>
          <div className="text-[var(--color-fg-muted)] text-sm mt-0.5">{fmtPrice(c.current_price)}</div>
        </div>
        <div className="flex items-start gap-2">
          <div className="text-right">
            <div className="text-xs text-[var(--color-fg-muted)]">{relativeTime(c.computed_at)}</div>
          </div>
          <button
            onClick={handleRemove}
            disabled={removing}
            className="p-1 rounded-lg text-[var(--color-fg-muted)] hover:text-red-500 hover:bg-red-500/10 transition-colors flex-shrink-0"
            title="Remove from watchlist"
          >
            {removing ? <LoadingSpinner size="sm" /> : <Trash2 className="w-3.5 h-3.5" />}
          </button>
        </div>
      </div>

      <div className="space-y-2 mb-3">
        <IndicatorBar label="RSI-14" value={c.rsi_14} min={0} max={100} danger="high" />
        <IndicatorBar
          label="Stoch RSI"
          value={c.stoch_rsi != null ? c.stoch_rsi * 100 : undefined}
          min={0} max={100} danger="high"
          format={(v) => `${v.toFixed(0)}%`}
        />
        <IndicatorBar
          label="BB Position"
          value={c.bb_pct != null ? c.bb_pct * 100 : undefined}
          min={0} max={100} danger="high"
          format={(v) => `${v.toFixed(0)}%`}
        />
      </div>

      <div className="flex items-center gap-1 mt-3 text-xs text-brand-500 font-medium">
        View full analysis <ArrowRight className="w-3 h-3" />
      </div>
    </div>
  )
}

function PendingCard({ ticker, onNavigate, onRemove }: { ticker: string; onNavigate: (t: string) => void; onRemove: (t: string) => void }) {
  const [removing, setRemoving] = useState(false)

  const handleRemove = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (removing) return
    setRemoving(true)
    try {
      await watchlistApi.remove(ticker)
      onRemove(ticker)
    } catch {
      setRemoving(false)
    }
  }

  return (
    <div
      className="card border-l-4 border-l-[var(--color-border)] flex items-center justify-between cursor-pointer hover:shadow-brand-sm transition-all duration-200"
      onClick={() => onNavigate(ticker)}
    >
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-[var(--color-border)]/60">
          <Clock className="w-4 h-4 text-[var(--color-fg-muted)]" />
        </div>
        <div>
          <div className="font-bold text-[var(--color-fg)]" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
            {ticker}
          </div>
          <div className="text-xs text-[var(--color-fg-muted)]">Awaiting data</div>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <button
          onClick={handleRemove}
          disabled={removing}
          className="p-1 rounded-lg text-[var(--color-fg-muted)] hover:text-red-500 hover:bg-red-500/10 transition-colors"
          title="Remove from watchlist"
        >
          {removing ? <LoadingSpinner size="sm" /> : <Trash2 className="w-3.5 h-3.5" />}
        </button>
        <ArrowRight className="w-4 h-4 text-[var(--color-fg-muted)]" />
      </div>
    </div>
  )
}

// ── Add ticker form ───────────────────────────────────────────────────────────

interface AddTickerFormProps {
  onAdded: (ticker: string) => void
}

function AddTickerForm({ onAdded }: AddTickerFormProps) {
  const [query, setQuery] = useState('')
  const [suggestions, setSuggestions] = useState<{ symbol: string; name: string }[]>([])
  const [selectedTicker, setSelectedTicker] = useState('')
  const [focusedIdx, setFocusedIdx] = useState(-1)
  const [status, setStatus] = useState<'idle' | 'adding' | 'done' | 'error'>('idle')
  const [errorMsg, setErrorMsg] = useState('')
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const search = useCallback(async (q: string) => {
    if (q.length < 1) { setSuggestions([]); return }
    try {
      const res = await analyzeApi.search(q)
      setSuggestions(res.data.slice(0, 6))
    } catch {
      setSuggestions([])
    }
  }, [])

  const handleInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value.toUpperCase()
    setQuery(val)
    setSelectedTicker('')
    setFocusedIdx(-1)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => search(val), 300)
  }

  const pickSuggestion = (s: { symbol: string; name: string }) => {
    setQuery(s.symbol)
    setSelectedTicker(s.symbol)
    setSuggestions([])
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (suggestions.length === 0) return
    if (e.key === 'ArrowDown') { e.preventDefault(); setFocusedIdx(i => Math.min(i + 1, suggestions.length - 1)) }
    if (e.key === 'ArrowUp') { e.preventDefault(); setFocusedIdx(i => Math.max(i - 1, 0)) }
    if (e.key === 'Enter' && focusedIdx >= 0) { e.preventDefault(); pickSuggestion(suggestions[focusedIdx]) }
    if (e.key === 'Escape') setSuggestions([])
  }

  const handleAdd = async () => {
    const ticker = (selectedTicker || query).trim().toUpperCase()
    if (!ticker) return
    setStatus('adding')
    setErrorMsg('')
    try {
      await watchlistApi.add(ticker)
      setStatus('done')
      setQuery('')
      setSelectedTicker('')
      onAdded(ticker)
      setTimeout(() => setStatus('idle'), 2500)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to add ticker'
      setErrorMsg(msg)
      setStatus('error')
      setTimeout(() => setStatus('idle'), 3000)
    }
  }

  return (
    <div className="card">
      <h3 className="text-sm font-semibold text-[var(--color-fg)] mb-3">Add ticker to radar</h3>
      <div className="relative flex gap-2">
        <div className="relative flex-1">
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            placeholder="Search ticker (e.g. NVDA)"
            className="input w-full pr-8"
            disabled={status === 'adding'}
          />
          {query && (
            <button
              onClick={() => { setQuery(''); setSelectedTicker(''); setSuggestions([]) }}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--color-fg-muted)] hover:text-[var(--color-fg)]"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}

          {/* Suggestions dropdown */}
          {suggestions.length > 0 && (
            <div className="absolute top-full left-0 right-0 mt-1 z-20 card !p-1 shadow-lg border border-[var(--color-border)]">
              {suggestions.map((s, i) => (
                <button
                  key={s.symbol}
                  onMouseDown={(e) => { e.preventDefault(); pickSuggestion(s) }}
                  className={`w-full text-left flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors
                    ${i === focusedIdx ? 'bg-brand-500/10 text-brand-500' : 'hover:bg-[var(--color-border)]/40 text-[var(--color-fg)]'}`}
                >
                  <span className="font-semibold w-16 flex-shrink-0">{s.symbol}</span>
                  <span className="text-[var(--color-fg-muted)] truncate">{s.name}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        <button
          onClick={handleAdd}
          disabled={!query.trim() || status === 'adding' || status === 'done'}
          className="btn-primary flex items-center gap-1.5 px-4 flex-shrink-0"
        >
          {status === 'adding' ? (
            <LoadingSpinner size="sm" />
          ) : status === 'done' ? (
            <CheckCircle2 className="w-4 h-4" />
          ) : (
            <Plus className="w-4 h-4" />
          )}
          {status === 'adding' ? 'Adding…' : status === 'done' ? 'Added!' : 'Add'}
        </button>
      </div>

      {status === 'done' && (
        <p className="text-xs text-green-600 dark:text-green-400 mt-2">
          Ticker added — analysis running in background. Scan again in ~30s.
        </p>
      )}
      {status === 'error' && (
        <p className="text-xs text-red-500 mt-2">{errorMsg}</p>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function AlphaRadarPage() {
  const navigate = useNavigate()
  const [scan, setScan] = useState<DipBuyScanResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [lastScan, setLastScan] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showCriteria, setShowCriteria] = useState(false)

  const runScan = useCallback(async (showSpinner = false) => {
    if (showSpinner) setScanning(true)
    setError(null)
    try {
      const res = await radarApi.scan()
      setScan(res.data)
      setLastScan(new Date().toISOString())
    } catch {
      setError('Scan failed — check your connection.')
    } finally {
      setScanning(false)
      setLoading(false)
    }
  }, [])

  // Initial load
  useEffect(() => { runScan() }, [runScan])

  const handleTickerAdded = () => {
    // Don't auto-rescan — analysis runs in background, user should trigger manually
  }

  const handleRemove = (ticker: string) => {
    if (!scan) return
    setScan({
      ...scan,
      entry_candidates: scan.entry_candidates.filter((c) => c.ticker !== ticker),
      exit_alerts: scan.exit_alerts.filter((c) => c.ticker !== ticker),
      neutral_tickers: scan.neutral_tickers.filter((c) => c.ticker !== ticker),
      unanalyzed_tickers: scan.unanalyzed_tickers.filter((t) => t !== ticker),
      scanned: scan.scanned - 1,
    })
  }

  return (
    <Layout>
      <div className="space-y-6">

        {/* ── Page header ── */}
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2.5 mb-1">
              <div className="flex items-center justify-center w-9 h-9 rounded-xl bg-brand-500/10">
                <Crosshair className="w-5 h-5 text-brand-500" />
              </div>
              <h1
                className="text-2xl font-bold text-[var(--color-fg)]"
                style={{ fontFamily: 'Fraunces, Georgia, serif' }}
              >
                Alpha Radar
              </h1>
            </div>
            <p className="text-sm text-[var(--color-fg-muted)]">
              Scans your watchlist for dip-buy entries and profit-taking alerts.
            </p>
          </div>

          <div className="flex items-center gap-2 flex-shrink-0">
            {lastScan && (
              <span className="text-xs text-[var(--color-fg-muted)]">
                Last scan {relativeTime(lastScan)}
              </span>
            )}
            <button
              onClick={() => runScan(true)}
              disabled={scanning || loading}
              className="btn-secondary flex items-center gap-1.5"
            >
              <RefreshCw className={`w-4 h-4 ${scanning ? 'animate-spin' : ''}`} />
              {scanning ? 'Scanning…' : 'Scan Now'}
            </button>
          </div>
        </div>

        {/* ── Stats strip ── */}
        {scan && (
          <div className="grid grid-cols-4 gap-3">
            <div className="card text-center">
              <div className="text-2xl font-bold text-[var(--color-fg)]" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
                {scan.scanned + scan.unanalyzed_tickers.length}
              </div>
              <div className="text-xs text-[var(--color-fg-muted)] mt-0.5">Watching</div>
            </div>
            <div className="card text-center">
              <div className="text-2xl font-bold text-green-500" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
                {scan.entry_candidates.length}
              </div>
              <div className="text-xs text-[var(--color-fg-muted)] mt-0.5">Entry setups</div>
            </div>
            <div className="card text-center">
              <div className="text-2xl font-bold text-amber-500" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
                {scan.exit_alerts.length}
              </div>
              <div className="text-xs text-[var(--color-fg-muted)] mt-0.5">Exit alerts</div>
            </div>
            <div className="card text-center">
              <div className="text-2xl font-bold text-[var(--color-fg-muted)]" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
                {scan.neutral_tickers.length}
              </div>
              <div className="text-xs text-[var(--color-fg-muted)] mt-0.5">Neutral</div>
            </div>
          </div>
        )}

        {/* ── Criteria legend (collapsible) ── */}
        <button
          onClick={() => setShowCriteria(v => !v)}
          className="flex items-center gap-2 text-xs text-[var(--color-fg-muted)] hover:text-[var(--color-fg)] transition-colors"
        >
          {showCriteria ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          How signals are detected
        </button>

        {showCriteria && (
          <div className="card grid sm:grid-cols-2 gap-4 text-xs text-[var(--color-fg-muted)]">
            <div>
              <div className="flex items-center gap-1.5 font-semibold text-green-600 dark:text-green-400 mb-2">
                <TrendingDown className="w-3.5 h-3.5" /> Entry criteria (all must hold)
              </div>
              <ul className="space-y-1">
                <li>RSI-14 ≤ 45 — not yet overbought</li>
                <li>Stochastic RSI ≤ 20% — oversold</li>
                <li>Bollinger Band position ≤ 35% — near lower band</li>
              </ul>
            </div>
            <div>
              <div className="flex items-center gap-1.5 font-semibold text-amber-600 dark:text-amber-400 mb-2">
                <TrendingUp className="w-3.5 h-3.5" /> Exit alert criteria (either fires)
              </div>
              <ul className="space-y-1">
                <li>RSI-14 ≥ 70 — overbought territory</li>
                <li>Bollinger Band position ≥ 90% — near upper band</li>
              </ul>
            </div>
          </div>
        )}

        {/* ── Add ticker ── */}
        <AddTickerForm onAdded={handleTickerAdded} />

        {/* ── Error ── */}
        {error && (
          <div className="flex items-center gap-2 p-3 rounded-xl bg-red-500/10 text-red-600 dark:text-red-400 text-sm">
            <AlertTriangle className="w-4 h-4 flex-shrink-0" />
            {error}
          </div>
        )}

        {/* ── Loading state ── */}
        {loading && (
          <div className="flex items-center justify-center py-16">
            <LoadingSpinner size="lg" />
          </div>
        )}

        {/* ── Results ── */}
        {!loading && scan && (
          <>
            {/* Entry candidates */}
            <section>
              <div className="flex items-center gap-2 mb-3">
                <h2 className="font-semibold text-[var(--color-fg)]" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
                  Entry Setups
                </h2>
                <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-green-500/15 text-green-600 dark:text-green-400">
                  {scan.entry_candidates.length}
                </span>
              </div>

              {scan.entry_candidates.length === 0 ? (
                <div className="card flex flex-col items-center justify-center py-10 text-center">
                  <Crosshair className="w-8 h-8 text-[var(--color-fg-muted)] mb-2 opacity-40" />
                  <p className="text-sm text-[var(--color-fg-muted)]">No dip-buy setups right now.</p>
                  <p className="text-xs text-[var(--color-fg-muted)] mt-1">Add more tickers or wait for a pullback.</p>
                </div>
              ) : (
                <div className="grid sm:grid-cols-2 gap-3">
                  {scan.entry_candidates.map(c => (
                    <EntryCard key={c.ticker} c={c} onNavigate={(t) => navigate(`/ticker/${t}`)} onRemove={handleRemove} />
                  ))}
                </div>
              )}
            </section>

            {/* Exit alerts */}
            <section>
              <div className="flex items-center gap-2 mb-3">
                <h2 className="font-semibold text-[var(--color-fg)]" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
                  Exit Alerts
                </h2>
                <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-500/15 text-amber-600 dark:text-amber-400">
                  {scan.exit_alerts.length}
                </span>
              </div>

              {scan.exit_alerts.length === 0 ? (
                <div className="card flex flex-col items-center justify-center py-10 text-center">
                  <CheckCircle2 className="w-8 h-8 text-[var(--color-fg-muted)] mb-2 opacity-40" />
                  <p className="text-sm text-[var(--color-fg-muted)]">No overbought signals on your watchlist.</p>
                </div>
              ) : (
                <div className="grid sm:grid-cols-2 gap-3">
                  {scan.exit_alerts.map(c => (
                    <ExitAlertCard key={c.ticker} c={c} onNavigate={(t) => navigate(`/ticker/${t}`)} onRemove={handleRemove} />
                  ))}
                </div>
              )}
            </section>

            {/* Neutral / Watching */}
            {scan.neutral_tickers.length > 0 && (
              <section>
                <div className="flex items-center gap-2 mb-3">
                  <h2 className="font-semibold text-[var(--color-fg)]" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
                    Watching
                  </h2>
                  <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-[var(--color-border)]/60 text-[var(--color-fg-muted)]">
                    {scan.neutral_tickers.length}
                  </span>
                </div>
                <p className="text-xs text-[var(--color-fg-muted)] mb-3">
                  These tickers have data but don't currently meet entry or exit thresholds.
                </p>
                <div className="grid sm:grid-cols-2 gap-3">
                  {scan.neutral_tickers.map(c => (
                    <NeutralCard key={c.ticker} c={c} onNavigate={(t) => navigate(`/ticker/${t}`)} onRemove={handleRemove} />
                  ))}
                </div>
              </section>
            )}

            {/* Unanalyzed / Pending */}
            {scan.unanalyzed_tickers.length > 0 && (
              <section>
                <div className="flex items-center gap-2 mb-3">
                  <h2 className="font-semibold text-[var(--color-fg)]" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
                    Pending Analysis
                  </h2>
                  <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-[var(--color-border)]/60 text-[var(--color-fg-muted)]">
                    {scan.unanalyzed_tickers.length}
                  </span>
                </div>
                <p className="text-xs text-[var(--color-fg-muted)] mb-3">
                  No feature data yet — analysis is still running in the background.
                </p>
                <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  {scan.unanalyzed_tickers.map(ticker => (
                    <PendingCard key={ticker} ticker={ticker} onNavigate={(t) => navigate(`/ticker/${t}`)} onRemove={handleRemove} />
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </div>
    </Layout>
  )
}
