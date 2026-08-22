import { useState } from 'react'
import { AlertCircle, RefreshCw, Wallet } from 'lucide-react'
import { tradingApi } from '../lib/api'
import { relativeTime } from '../lib/format'
import type { HoldingsResponse } from '../types'
import Layout from '../components/Layout'
import LoadingSpinner from '../components/LoadingSpinner'

/**
 * Holdings straight from the broker, fetched only when asked for.
 *
 * Deliberately not loaded on mount: each fetch costs a broker round-trip, and
 * unlike the watchlist this is not something you want re-polling in the
 * background. The user decides when the number matters.
 *
 * P&L follows the broker-statement convention used across the app — gains
 * green, losses red in parentheses, exact zero neutral.
 */

const usd = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

function money(value: number | null | undefined): string {
  if (value == null) return '—'
  return usd.format(Math.abs(value))
}

function SignedMoney({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="text-[var(--color-fg-muted)]">—</span>
  const isLoss = value < -0.005
  const isGain = value > 0.005
  const tone = isLoss ? 'text-red-500' : isGain ? 'text-green-500' : 'text-[var(--color-fg)]'
  return (
    <span className={`tabular-nums ${tone}`}>
      {isLoss ? `(${money(value)})` : money(value)}
    </span>
  )
}

/**
 * Last fetch, held at module scope so it survives this component unmounting as
 * the user navigates between pages — otherwise every trip to another tab threw
 * the result away and forced a fresh broker round-trip on return.
 *
 * Deliberately in memory rather than sessionStorage: a browser refresh should
 * clear it. Holdings move, and presenting a stale snapshot as current after a
 * reload is worse than showing the empty state and letting the user ask again.
 */
let cachedData: HoldingsResponse | null = null
let cachedAt: Date | null = null

export default function HoldingsPage() {
  // Seed from the module cache so returning to this page shows what was already
  // fetched instead of resetting to the empty state.
  const [data, setData] = useState<HoldingsResponse | null>(cachedData)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fetchedAt, setFetchedAt] = useState<Date | null>(cachedAt)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const { data } = await tradingApi.getHoldings()
      const now = new Date()
      setData(data)
      setFetchedAt(now)
      cachedData = data
      cachedAt = now
    } catch {
      // Keep whatever was already on screen — a failed refresh should not wipe
      // a snapshot the user still finds useful.
      setError('Could not reach the broker. Check the connection and try again.')
    } finally {
      setLoading(false)
    }
  }

  const totalPnl = (data?.holdings ?? []).reduce(
    (sum, h) => sum + (h.unrealized_pnl ?? 0),
    0,
  )

  return (
    <Layout>
      <div className="flex items-start justify-between gap-4 mb-6">
        <div>
          <h1
            className="text-2xl font-light text-[var(--color-fg)]"
            style={{ fontFamily: 'Fraunces, Georgia, serif' }}
          >
            Holdings
          </h1>
          <p className="text-sm text-[var(--color-fg-muted)] mt-0.5">
            {fetchedAt
              ? `As of ${fetchedAt.toLocaleTimeString()} · ${relativeTime(fetchedAt)}`
              : 'Live positions, fetched on demand'}
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium
                     bg-brand-500 text-white hover:opacity-90 disabled:opacity-60
                     transition-opacity flex-shrink-0"
        >
          {loading ? <LoadingSpinner size="sm" /> : <RefreshCw className="w-4 h-4" />}
          {data ? 'Refresh' : 'Load holdings'}
        </button>
      </div>

      {error && (
        <div role="alert" className="flex items-center gap-3 px-4 py-3 rounded-xl mb-6
                        bg-red-500/10 border border-red-500/20 text-red-500 text-sm">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          {error}
        </div>
      )}

      {/* Nothing fetched yet — say so plainly rather than showing an empty table */}
      {!data && !loading && !error && (
        <div className="card p-10 text-center">
          <Wallet className="w-8 h-8 mx-auto text-[var(--color-fg-muted)] mb-3" />
          <p className="text-sm text-[var(--color-fg-muted)]">
            Holdings aren&rsquo;t loaded automatically.
            <br />
            Select <span className="text-[var(--color-fg)]">Load holdings</span> to
            fetch them from your broker.
          </p>
        </div>
      )}

      {data && !data.connected && (
        <div className="card p-10 text-center text-sm text-[var(--color-fg-muted)]">
          Broker disconnected — holdings unavailable.
        </div>
      )}

      {data?.connected && data.holdings.length === 0 && (
        <div className="card p-10 text-center text-sm text-[var(--color-fg-muted)]">
          No open positions in {data.account_id || 'this account'}.
        </div>
      )}

      {data?.connected && data.holdings.length > 0 && (
        <div className="card overflow-hidden p-0">
          <div className="flex items-center justify-between gap-3 px-4 py-3
                          border-b border-[var(--color-border)] flex-wrap">
            <span className="text-[0.65rem] uppercase tracking-widest text-[var(--color-fg-muted)]">
              Account {data.account_id || '—'} · {data.holdings.length}{' '}
              {data.holdings.length === 1 ? 'position' : 'positions'}
            </span>
            <span className="text-sm">
              <span className="text-[var(--color-fg-muted)] mr-2">Unrealised</span>
              <SignedMoney value={totalPnl} />
            </span>
          </div>

          {/* Header — must mirror the row layout below */}
          <div className="hidden sm:flex items-center gap-3 px-4 py-2
                          border-b border-[var(--color-border)] text-[0.65rem]
                          uppercase tracking-widest text-[var(--color-fg-muted)] select-none">
            <span className="w-16 flex-shrink-0">Ticker</span>
            <span className="w-24 flex-shrink-0 text-right">Qty</span>
            <span className="w-28 flex-shrink-0 text-right">Avg cost</span>
            <span className="flex-1 text-right">Market value</span>
            <span className="w-32 flex-shrink-0 text-right">Unrealised</span>
          </div>

          {data.holdings.map((h) => (
            <div
              key={h.ticker}
              className="flex items-center gap-3 px-4 py-3 border-b border-[var(--color-border)]
                         last:border-b-0 hover:bg-[var(--color-bg)] transition-colors"
            >
              <span
                className="w-16 flex-shrink-0 font-semibold text-sm text-[var(--color-fg)]"
                style={{ fontFamily: 'Archivo, system-ui, sans-serif' }}
              >
                {h.ticker}
              </span>
              <span className="w-24 flex-shrink-0 text-right text-sm tabular-nums text-[var(--color-fg)]">
                {h.qty.toLocaleString()}
              </span>
              <span className="w-28 flex-shrink-0 text-right text-sm tabular-nums text-[var(--color-fg-muted)]">
                {money(h.avg_cost)}
              </span>
              <span className="flex-1 text-right text-sm tabular-nums text-[var(--color-fg)]">
                {money(h.market_value)}
              </span>
              <span className="w-32 flex-shrink-0 text-right text-sm">
                <SignedMoney value={h.unrealized_pnl} />
              </span>
            </div>
          ))}

          <div className="flex items-center justify-between px-4 py-3
                          border-t border-[var(--color-border)] text-sm">
            <span className="text-[0.65rem] uppercase tracking-widest text-[var(--color-fg-muted)]">
              Total market value
            </span>
            <span className="tabular-nums font-medium text-[var(--color-fg)]">
              {money(data.total_market_value)}
            </span>
          </div>
        </div>
      )}
    </Layout>
  )
}
