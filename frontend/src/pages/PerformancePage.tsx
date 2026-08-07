import { useEffect, useState } from 'react'
import { AlertCircle, BarChart2, TrendingUp } from 'lucide-react'
import { performanceApi } from '../lib/api'
import type { PerformanceResponse, Signal } from '../types'
import Layout from '../components/Layout'
import SignalBadge from '../components/SignalBadge'
import LoadingSpinner from '../components/LoadingSpinner'

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtPct(val?: number | null): string {
  if (val == null) return '—'
  return `${(val * 100).toFixed(1)}%`
}

function fmtReturn(val?: number | null): string {
  if (val == null) return '—'
  const pct = (val * 100).toFixed(1)
  return val >= 0 ? `+${pct}%` : `${pct}%`
}

function returnColor(val?: number | null): string {
  if (val == null) return 'text-[var(--color-fg-muted)]'
  return val >= 0 ? 'text-green-500' : 'text-red-500'
}

// ── Stat card ─────────────────────────────────────────────────────────────────

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="card p-4 flex flex-col gap-1">
      <span className="text-xs text-[var(--color-fg-muted)]">{label}</span>
      <span
        className="text-2xl font-light text-[var(--color-fg)]"
        style={{ fontFamily: 'Fraunces, Georgia, serif' }}
      >
        {value}
      </span>
      {sub && <span className="text-xs text-[var(--color-fg-muted)]">{sub}</span>}
    </div>
  )
}

// ── By-signal table ───────────────────────────────────────────────────────────

function BySignalTable({ rows }: { rows: PerformanceResponse['by_signal'] }) {
  if (!rows || rows.length === 0) return null

  return (
    <div className="card overflow-hidden">
      <div className="px-4 py-3 border-b border-[var(--color-border)]">
        <h3
          className="font-medium text-[var(--color-fg)]"
          style={{ fontFamily: 'Fraunces, Georgia, serif' }}
        >
          By Signal
        </h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--color-border)]">
              <th className="px-4 py-2.5 text-left text-xs text-[var(--color-fg-muted)] font-medium">Signal</th>
              <th className="px-4 py-2.5 text-right text-xs text-[var(--color-fg-muted)] font-medium">Total</th>
              <th className="px-4 py-2.5 text-right text-xs text-[var(--color-fg-muted)] font-medium">Settled</th>
              <th className="px-4 py-2.5 text-right text-xs text-[var(--color-fg-muted)] font-medium">Win Rate</th>
              <th className="px-4 py-2.5 text-right text-xs text-[var(--color-fg-muted)] font-medium">Avg 20d</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.signal} className="border-b border-[var(--color-border)]/50 last:border-0">
                <td className="px-4 py-3">
                  <SignalBadge signal={row.signal as Signal} />
                </td>
                <td className="px-4 py-3 text-right text-[var(--color-fg)] tabular-nums">{row.total}</td>
                <td className="px-4 py-3 text-right text-[var(--color-fg)] tabular-nums">{row.settled}</td>
                <td className="px-4 py-3 text-right tabular-nums">
                  <span className={row.win_rate != null && row.win_rate >= 0.5 ? 'text-green-500' : 'text-[var(--color-fg-muted)]'}>
                    {fmtPct(row.win_rate)}
                  </span>
                </td>
                <td className={`px-4 py-3 text-right tabular-nums ${returnColor(row.avg_return_20d)}`}>
                  {fmtReturn(row.avg_return_20d)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── By-ticker table ───────────────────────────────────────────────────────────

function ByTickerTable({ rows }: { rows: PerformanceResponse['by_ticker'] }) {
  if (!rows || rows.length === 0) return null

  const sorted = [...rows].sort((a, b) => (b.win_rate ?? 0) - (a.win_rate ?? 0))

  return (
    <div className="card overflow-hidden">
      <div className="px-4 py-3 border-b border-[var(--color-border)]">
        <h3
          className="font-medium text-[var(--color-fg)]"
          style={{ fontFamily: 'Fraunces, Georgia, serif' }}
        >
          By Ticker
        </h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--color-border)]">
              <th className="px-4 py-2.5 text-left text-xs text-[var(--color-fg-muted)] font-medium">Ticker</th>
              <th className="px-4 py-2.5 text-right text-xs text-[var(--color-fg-muted)] font-medium">Signals</th>
              <th className="px-4 py-2.5 text-right text-xs text-[var(--color-fg-muted)] font-medium">Settled</th>
              <th className="px-4 py-2.5 text-right text-xs text-[var(--color-fg-muted)] font-medium">Win Rate</th>
              <th className="px-4 py-2.5 text-right text-xs text-[var(--color-fg-muted)] font-medium">Avg 20d</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
              <tr key={row.ticker} className="border-b border-[var(--color-border)]/50 last:border-0">
                <td className="px-4 py-3">
                  <span
                    className="font-semibold text-[var(--color-fg)]"
                    style={{ fontFamily: 'Fraunces, Georgia, serif' }}
                  >
                    {row.ticker}
                  </span>
                </td>
                <td className="px-4 py-3 text-right text-[var(--color-fg)] tabular-nums">{row.total}</td>
                <td className="px-4 py-3 text-right text-[var(--color-fg)] tabular-nums">{row.settled}</td>
                <td className="px-4 py-3 text-right tabular-nums">
                  <span className={row.win_rate != null && row.win_rate >= 0.5 ? 'text-green-500' : 'text-[var(--color-fg-muted)]'}>
                    {fmtPct(row.win_rate)}
                  </span>
                </td>
                <td className={`px-4 py-3 text-right tabular-nums ${returnColor(row.avg_return_20d)}`}>
                  {fmtReturn(row.avg_return_20d)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="w-16 h-16 rounded-2xl bg-brand-500/10 flex items-center justify-center mb-4">
        <BarChart2 className="w-8 h-8 text-brand-500" />
      </div>
      <h3
        className="text-lg font-medium text-[var(--color-fg)] mb-2"
        style={{ fontFamily: 'Fraunces, Georgia, serif' }}
      >
        No performance data yet
      </h3>
      <p className="text-sm text-[var(--color-fg-muted)] max-w-xs">
        Performance metrics will appear once signals have had 20 days to settle.
      </p>
    </div>
  )
}

// ── Performance Page ──────────────────────────────────────────────────────────

export default function PerformancePage() {
  const [data, setData] = useState<PerformanceResponse | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    performanceApi.get()
      .then((res) => setData(res.data))
      .catch((err: unknown) => {
        const msg = (err as { response?: { data?: { detail?: string } } })
          ?.response?.data?.detail
        setError(msg ?? 'Failed to load performance data.')
      })
      .finally(() => setIsLoading(false))
  }, [])

  const hasSettled = data && data.settled_signals > 0

  return (
    <Layout>
      {/* Header */}
      <div className="mb-6">
        <h1
          className="text-2xl font-light text-[var(--color-fg)]"
          style={{ fontFamily: 'Fraunces, Georgia, serif' }}
        >
          Signal Performance
        </h1>
        <p className="text-sm text-[var(--color-fg-muted)] mt-0.5">
          Historical accuracy of AI-generated trading signals
        </p>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <LoadingSpinner size="lg" />
        </div>
      ) : error ? (
        <div className="flex items-center gap-3 px-4 py-3 rounded-xl
                        bg-red-500/10 border border-red-500/20 text-red-500 text-sm">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          {error}
        </div>
      ) : !data || data.total_signals === 0 ? (
        <EmptyState />
      ) : (
        <div className="flex flex-col gap-4">
          {/* Overall stats */}
          <div className="flex flex-col gap-3 sm:grid sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              label="Total Signals"
              value={String(data.total_signals)}
              sub="All time"
            />
            <StatCard
              label="Settled Signals"
              value={String(data.settled_signals)}
              sub="20d+ old"
            />
            <StatCard
              label="Overall Win Rate"
              value={fmtPct(data.overall_win_rate)}
              sub={hasSettled ? 'On settled signals' : 'Pending settlement'}
            />
            <StatCard
              label="Avg 20-day Return"
              value={fmtReturn(data.overall_avg_return_20d)}
              sub="Per signal"
            />
          </div>

          {/* No settled signals note */}
          {!hasSettled && (
            <div className="flex items-center gap-3 px-4 py-3 rounded-xl
                            bg-yellow-500/10 border border-yellow-500/20 text-yellow-600 dark:text-yellow-400 text-sm">
              <TrendingUp className="w-4 h-4 flex-shrink-0" />
              Win rate and return metrics will appear once signals have settled (20+ days old).
            </div>
          )}

          {/* By signal */}
          <BySignalTable rows={data.by_signal} />

          {/* By ticker */}
          <ByTickerTable rows={data.by_ticker} />
        </div>
      )}
    </Layout>
  )
}
