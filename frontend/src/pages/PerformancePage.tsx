import { useEffect, useState } from 'react'
import { AlertCircle, BarChart2, CheckCircle2, Clock, TrendingUp, XCircle } from 'lucide-react'
import { performanceApi } from '../lib/api'
import type { PerformanceResponse, Signal, SignalRecord } from '../types'
import Layout from '../components/Layout'
import SignalBadge from '../components/SignalBadge'
import ConvictionBadge from '../components/ConvictionBadge'
import LoadingSpinner from '../components/LoadingSpinner'
import type { Conviction } from '../types'

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

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    })
  } catch {
    return iso
  }
}

function fmtScore(score?: number | null): string {
  if (score == null) return '—'
  return `${Math.round(score)}%`
}

function fmtPrice(val?: number | null): string {
  if (val == null) return '—'
  return `$${val.toFixed(2)}`
}

// ── Stat card ─────────────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  sub,
  valueClass,
}: {
  label: string
  value: string
  sub?: string
  valueClass?: string
}) {
  return (
    <div className="card p-4 flex flex-col gap-1">
      <span className="text-xs text-[var(--color-fg-muted)]">{label}</span>
      <span
        className={`text-2xl font-light ${valueClass ?? 'text-[var(--color-fg)]'}`}
        style={{ fontFamily: 'Fraunces, Georgia, serif' }}
      >
        {value}
      </span>
      {sub && <span className="text-xs text-[var(--color-fg-muted)]">{sub}</span>}
    </div>
  )
}

// ── Signal accuracy cards (Section 2) ─────────────────────────────────────────

const SIGNAL_ORDER: Signal[] = ['BUY', 'HOLD', 'SELL']

function SignalAccuracyCard({ row }: { row: PerformanceResponse['by_signal'][number] }) {
  const pending = row.settled === 0
  const winPct = row.win_rate != null ? row.win_rate * 100 : 0

  return (
    <div className="card p-5 flex flex-col gap-3">
      {/* Signal badge */}
      <SignalBadge signal={row.signal as Signal} />

      {/* Win rate */}
      {pending ? (
        <div className="flex flex-col gap-1">
          <span
            className="text-2xl font-light text-[var(--color-fg-muted)]"
            style={{ fontFamily: 'Fraunces, Georgia, serif' }}
          >
            Pending
          </span>
          <div className="h-1.5 rounded-full bg-[var(--color-border)] overflow-hidden">
            <div className="h-full w-0 bg-green-500 rounded-full" />
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-1">
          <span
            className="text-2xl font-light text-[var(--color-fg)]"
            style={{ fontFamily: 'Fraunces, Georgia, serif' }}
          >
            {fmtPct(row.win_rate)}
          </span>
          <div className="h-1.5 rounded-full bg-[var(--color-border)] overflow-hidden">
            <div
              className="h-full bg-green-500 rounded-full transition-all duration-500"
              style={{ width: `${winPct}%` }}
            />
          </div>
        </div>
      )}

      {/* Counts & avg return */}
      <div className="flex flex-col gap-0.5">
        <span className="text-xs text-[var(--color-fg-muted)] tabular-nums">
          {row.settled} of {row.total} settled
        </span>
        <span className={`text-sm font-medium tabular-nums ${returnColor(row.avg_return_20d)}`}>
          Avg 20d: {fmtReturn(row.avg_return_20d)}
        </span>
      </div>
    </div>
  )
}

// ── Recent signal history table (Section 3) ────────────────────────────────────

function OutcomeCell({ rec }: { rec: SignalRecord }) {
  if (rec.return_20d == null) {
    return <span className="text-[var(--color-fg-muted)] text-xs">— Pending</span>
  }
  if (rec.was_correct) {
    return (
      <span className="inline-flex items-center gap-1 text-green-500 text-xs font-medium">
        <CheckCircle2 className="w-3.5 h-3.5" />
        Correct
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 text-red-500 text-xs font-medium">
      <XCircle className="w-3.5 h-3.5" />
      Wrong
    </span>
  )
}

function SignalHistoryTable({ records }: { records: SignalRecord[] }) {
  const displayed = records.slice(0, 50)

  if (displayed.length === 0) {
    return (
      <div className="card p-8 flex flex-col items-center gap-2 text-center">
        <Clock className="w-6 h-6 text-[var(--color-fg-muted)]" />
        <p className="text-sm text-[var(--color-fg-muted)]">No signal history yet.</p>
      </div>
    )
  }

  return (
    <div className="card overflow-hidden">
      <div className="px-4 py-3 border-b border-[var(--color-border)]">
        <h3
          className="font-medium text-[var(--color-fg)]"
          style={{ fontFamily: 'Fraunces, Georgia, serif' }}
        >
          Recent Signal History
        </h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--color-border)]">
              <th className="px-4 py-2.5 text-left text-xs text-[var(--color-fg-muted)] font-medium">Date</th>
              <th className="px-4 py-2.5 text-left text-xs text-[var(--color-fg-muted)] font-medium">Ticker</th>
              <th className="px-4 py-2.5 text-left text-xs text-[var(--color-fg-muted)] font-medium">Signal</th>
              <th className="px-4 py-2.5 text-right text-xs text-[var(--color-fg-muted)] font-medium">Score</th>
              <th className="px-4 py-2.5 text-left text-xs text-[var(--color-fg-muted)] font-medium">Conviction</th>
              <th className="px-4 py-2.5 text-right text-xs text-[var(--color-fg-muted)] font-medium">Entry Price</th>
              <th className="px-4 py-2.5 text-right text-xs text-[var(--color-fg-muted)] font-medium">20d Return</th>
              <th className="px-4 py-2.5 text-left text-xs text-[var(--color-fg-muted)] font-medium">Outcome</th>
            </tr>
          </thead>
          <tbody>
            {displayed.map((rec, i) => (
              <tr
                key={`${rec.ticker}-${rec.generated_at}-${i}`}
                className="border-b border-[var(--color-border)]/50 last:border-0"
              >
                <td className="px-4 py-3 text-xs text-[var(--color-fg-muted)] tabular-nums whitespace-nowrap">
                  {fmtDate(rec.generated_at)}
                </td>
                <td className="px-4 py-3">
                  <span
                    className="font-semibold text-[var(--color-fg)]"
                    style={{ fontFamily: 'Fraunces, Georgia, serif' }}
                  >
                    {rec.ticker}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <SignalBadge signal={rec.signal} />
                </td>
                <td className="px-4 py-3 text-right text-[var(--color-fg)] tabular-nums">
                  {fmtScore(rec.score)}
                </td>
                <td className="px-4 py-3">
                  {rec.conviction ? (
                    <ConvictionBadge conviction={rec.conviction as Conviction} />
                  ) : (
                    <span className="text-[var(--color-fg-muted)]">—</span>
                  )}
                </td>
                <td className="px-4 py-3 text-right tabular-nums text-[var(--color-fg)]">
                  {fmtPrice(rec.price_at_signal)}
                </td>
                <td className={`px-4 py-3 text-right tabular-nums ${returnColor(rec.return_20d)}`}>
                  {rec.return_20d != null ? fmtReturn(rec.return_20d) : (
                    <span className="text-[var(--color-fg-muted)]">Pending</span>
                  )}
                </td>
                <td className="px-4 py-3">
                  <OutcomeCell rec={rec} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── By-ticker table (Section 4) ───────────────────────────────────────────────

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
                  <span
                    className={
                      row.win_rate != null && row.win_rate >= 0.5
                        ? 'text-green-500'
                        : 'text-[var(--color-fg-muted)]'
                    }
                  >
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
        Add tickers to your watchlist and run analyses. Performance metrics appear once signals
        have had 20 trading days (~28 calendar days) to settle.
      </p>
    </div>
  )
}

// ── Performance Page ──────────────────────────────────────────────────────────

export default function PerformancePage() {
  const [data, setData] = useState<PerformanceResponse | null>(null)
  const [signalHistory, setSignalHistory] = useState<SignalRecord[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([performanceApi.get(), performanceApi.signals()])
      .then(([perfRes, sigRes]) => {
        setData(perfRes.data as PerformanceResponse)
        setSignalHistory(sigRes.data)
      })
      .catch((err: unknown) => {
        const msg = (err as { response?: { data?: { detail?: string } } })
          ?.response?.data?.detail
        setError(msg ?? 'Failed to load performance data.')
      })
      .finally(() => setIsLoading(false))
  }, [])

  const hasSettled = data && data.settled_signals > 0
  const isPending = data && data.total_signals > 0 && data.settled_signals === 0

  // Order by_signal cards as BUY / HOLD / SELL
  const orderedBySignal = data
    ? SIGNAL_ORDER.map(
        (sig) =>
          data.by_signal.find((r) => r.signal === sig) ?? {
            signal: sig,
            total: 0,
            settled: 0,
            correct: 0,
            win_rate: undefined,
            avg_return_20d: undefined,
          }
      )
    : []

  return (
    <Layout>
      {/* Header */}
      <div className="mb-6">
        <h1
          className="text-2xl font-light text-[var(--color-fg)]"
          style={{ fontFamily: 'Fraunces, Georgia, serif' }}
        >
          Signal Accuracy Dashboard
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
        <div
          className="flex items-center gap-3 px-4 py-3 rounded-xl
                      bg-red-500/10 border border-red-500/20 text-red-500 text-sm"
        >
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          {error}
        </div>
      ) : !data || data.total_signals === 0 ? (
        <EmptyState />
      ) : (
        <div className="flex flex-col gap-6">
          {/* ── Section 1: Overview stats ─────────────────────────────────── */}
          <div className="flex flex-col gap-3 sm:grid sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Total Signals" value={String(data.total_signals)} sub="All time" />
            <StatCard
              label="Settled Signals"
              value={String(data.settled_signals)}
              sub="20d+ old"
            />
            <StatCard
              label="Overall Win Rate"
              value={fmtPct(data.overall_win_rate)}
              sub={hasSettled ? 'On settled signals' : 'Pending settlement'}
              valueClass={
                data.overall_win_rate != null && data.overall_win_rate >= 0.5
                  ? 'text-green-500'
                  : 'text-[var(--color-fg)]'
              }
            />
            <StatCard
              label="Avg 20-day Return"
              value={fmtReturn(data.overall_avg_return_20d)}
              sub="Per signal"
              valueClass={returnColor(data.overall_avg_return_20d)}
            />
          </div>

          {/* Pending info banner */}
          {isPending && (
            <div
              className="flex items-center gap-3 px-4 py-3 rounded-xl
                          bg-yellow-500/10 border border-yellow-500/20
                          text-yellow-600 dark:text-yellow-400 text-sm"
            >
              <TrendingUp className="w-4 h-4 flex-shrink-0" />
              {data.total_signals} signal{data.total_signals !== 1 ? 's are' : ' is'} tracking —
              win rate and returns appear after 20 trading days (~28 calendar days). Check back
              soon.
            </div>
          )}

          {/* ── Section 2: Signal type accuracy ───────────────────────────── */}
          <div>
            <h2
              className="text-sm font-medium text-[var(--color-fg-muted)] mb-3 uppercase tracking-wide"
            >
              By Signal Type
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {orderedBySignal.map((row) => (
                <SignalAccuracyCard key={row.signal} row={row} />
              ))}
            </div>
          </div>

          {/* ── Section 3: Recent signal history table ────────────────────── */}
          <div>
            <h2
              className="text-sm font-medium text-[var(--color-fg-muted)] mb-3 uppercase tracking-wide"
            >
              Signal History
            </h2>
            <SignalHistoryTable records={signalHistory} />
          </div>

          {/* ── Section 4: By ticker table ────────────────────────────────── */}
          {data.by_ticker && data.by_ticker.length > 0 && (
            <div>
              <h2
                className="text-sm font-medium text-[var(--color-fg-muted)] mb-3 uppercase tracking-wide"
              >
                By Ticker
              </h2>
              <ByTickerTable rows={data.by_ticker} />
            </div>
          )}
        </div>
      )}
    </Layout>
  )
}
