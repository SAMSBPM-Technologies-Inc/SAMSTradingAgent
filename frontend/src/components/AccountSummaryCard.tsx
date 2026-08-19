import { useEffect, useState } from 'react'
import { Wallet, WifiOff } from 'lucide-react'
import { tradingApi } from '../lib/api'
import type { AccountSummaryResponse } from '../types'

/**
 * Broker account panel — account number, cash available to trade, capital
 * currently deployed, and P&L.
 *
 * Signed figures follow the accounting convention used by broker statements:
 * gains in green, losses in red and wrapped in parentheses rather than carrying
 * a minus sign. Exactly zero stays neutral so a flat account doesn't read as a
 * gain.
 */

const usd = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

/** Absolute value, currency-formatted. Sign is conveyed by colour + brackets. */
function money(value: number): string {
  return usd.format(Math.abs(value ?? 0))
}

function SignedMoney({ value, className = '' }: { value: number; className?: string }) {
  const v = value ?? 0
  // Guard against -0 and float dust rendering as a "loss" of $0.00.
  const isLoss = v < -0.005
  const isGain = v > 0.005
  const tone = isLoss ? 'text-red-500' : isGain ? 'text-green-500' : 'text-[var(--color-fg)]'
  return (
    <span className={`tabular-nums ${tone} ${className}`}>
      {isLoss ? `(${money(v)})` : money(v)}
    </span>
  )
}

function Metric({
  label,
  children,
  hint,
}: {
  label: string
  children: React.ReactNode
  hint?: string
}) {
  return (
    <div className="min-w-0">
      <div className="text-[0.65rem] uppercase tracking-widest text-[var(--color-fg-muted)] whitespace-nowrap">
        {label}
      </div>
      <div className="mt-1 text-lg font-medium truncate">{children}</div>
      {hint && <div className="text-[0.7rem] text-[var(--color-fg-muted)] mt-0.5">{hint}</div>}
    </div>
  )
}

export default function AccountSummaryCard() {
  const [account, setAccount] = useState<AccountSummaryResponse | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      try {
        const { data } = await tradingApi.getAccount()
        if (!cancelled) setAccount(data)
      } catch {
        // Non-fatal: the watchlist below is the primary content of this page,
        // so a broker hiccup must never take the whole dashboard down.
        if (!cancelled) setAccount(null)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    const id = setInterval(load, 30_000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  if (loading) {
    return (
      <div className="card p-4 mb-6">
        <div className="h-4 w-32 rounded bg-[var(--color-border)]/60 animate-pulse" />
        <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-10 rounded bg-[var(--color-border)]/40 animate-pulse" />
          ))}
        </div>
      </div>
    )
  }

  if (!account?.connected) {
    return (
      <div className="card p-4 mb-6 flex items-center gap-3 text-sm text-[var(--color-fg-muted)]">
        <WifiOff className="w-4 h-4 flex-shrink-0" />
        <span>
          Broker disconnected — account balances unavailable.
          {account?.account_id ? ` Last known account ${account.account_id}.` : ''}
        </span>
      </div>
    )
  }

  const totalPnl = (account.unrealized_pnl ?? 0) + (account.realized_pnl ?? 0)

  return (
    <div className="card p-4 mb-6">
      {/* Header: account identity + live state */}
      <div className="flex items-center justify-between gap-3 mb-4">
        <div className="flex items-center gap-2 min-w-0">
          <Wallet className="w-4 h-4 text-[var(--color-fg-muted)] flex-shrink-0" />
          <span className="text-[0.65rem] uppercase tracking-widest text-[var(--color-fg-muted)]">
            Account
          </span>
          <span className="text-sm font-medium tabular-nums text-[var(--color-fg)] truncate">
            {account.account_id || '—'}
          </span>
        </div>
        <span className="flex items-center gap-1.5 text-[0.7rem] text-[var(--color-fg-muted)] flex-shrink-0">
          <span className="w-1.5 h-1.5 rounded-full bg-green-500" />
          Connected
        </span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Metric label="Net Liquidation">
          <span className="tabular-nums text-[var(--color-fg)]">
            {money(account.net_liquidation)}
          </span>
        </Metric>

        <Metric label="Available to Trade" hint={`Cash ${money(account.total_cash)}`}>
          <span className="tabular-nums text-[var(--color-fg)]">
            {money(account.buying_power)}
          </span>
        </Metric>

        <Metric label="Funds in Trade">
          <span className="tabular-nums text-[var(--color-fg)]">
            {money(account.gross_position_value)}
          </span>
        </Metric>

        <Metric label="Total P&L" hint={`Realised ${money(account.realized_pnl)}`}>
          <SignedMoney value={totalPnl} />
        </Metric>
      </div>

      {/* Unrealised broken out — this is the number that moves intraday */}
      <div className="mt-4 pt-3 border-t border-[var(--color-border)] flex items-center justify-between text-sm">
        <span className="text-[var(--color-fg-muted)]">Unrealised P&L</span>
        <SignedMoney value={account.unrealized_pnl} className="font-medium" />
      </div>
    </div>
  )
}
