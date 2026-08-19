import { useEffect, useState } from 'react'
import { tradingApi } from '../lib/api'
import type { AccountSummaryResponse } from '../types'

/**
 * Persistent broker account strip, pinned under the header on every page.
 *
 * Shows the account being traded, cash available to trade, capital currently
 * deployed, and unrealised P&L.
 *
 * Signed figures follow the broker-statement convention: gains green, losses
 * red and wrapped in parentheses rather than carrying a minus sign. Values
 * within half a cent of zero stay neutral, so a flat account doesn't read as a
 * gain and float dust or -0 can't render as a phantom loss.
 */

const usd = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

/** Absolute value, currency-formatted. Sign is carried by colour + brackets. */
function money(value: number): string {
  return usd.format(Math.abs(value ?? 0))
}

function SignedMoney({ value }: { value: number }) {
  const v = value ?? 0
  const isLoss = v < -0.005
  const isGain = v > 0.005
  const tone = isLoss ? 'text-red-500' : isGain ? 'text-green-500' : 'text-[var(--color-fg)]'
  return (
    <span className={`tabular-nums font-medium ${tone}`}>
      {isLoss ? `(${money(v)})` : money(v)}
    </span>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-1.5 flex-shrink-0 whitespace-nowrap">
      <span className="text-[0.65rem] uppercase tracking-widest text-[var(--color-fg-muted)]">
        {label}
      </span>
      {children}
    </div>
  )
}

/** Shell so the bar occupies identical space in every state (no layout shift). */
function Bar({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="sticky top-14 md:top-[60px] z-20 flex-shrink-0
                 bg-[var(--color-surface)] border-b border-[var(--color-border)]
                 transition-colors duration-200"
    >
      <div className="max-w-5xl mx-auto w-full px-4 md:px-6 h-10 flex items-center gap-4 md:gap-6 overflow-x-auto scrollbar-none">
        {children}
      </div>
    </div>
  )
}

export default function AccountBar() {
  const [account, setAccount] = useState<AccountSummaryResponse | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      try {
        const { data } = await tradingApi.getAccount()
        if (!cancelled) setAccount(data)
      } catch {
        // Non-fatal — this strip must never break the page it sits above.
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
      <Bar>
        <div className="h-3 w-28 rounded bg-[var(--color-border)]/60 animate-pulse" />
        <div className="h-3 w-32 rounded bg-[var(--color-border)]/40 animate-pulse" />
        <div className="h-3 w-28 rounded bg-[var(--color-border)]/40 animate-pulse" />
      </Bar>
    )
  }

  if (!account?.connected) {
    return (
      <Bar>
        <span className="flex items-center gap-2 text-xs text-[var(--color-fg-muted)] whitespace-nowrap">
          <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-fg-muted)]" />
          Broker disconnected — balances unavailable
        </span>
      </Bar>
    )
  }

  return (
    <Bar>
      <Field label="Acct">
        <span className="tabular-nums font-medium text-[var(--color-fg)] text-sm">
          {account.account_id || '—'}
        </span>
      </Field>

      <Field label="Available">
        <span className="tabular-nums font-medium text-[var(--color-fg)] text-sm">
          {money(account.buying_power)}
        </span>
      </Field>

      <Field label="In Trade">
        <span className="tabular-nums font-medium text-[var(--color-fg)] text-sm">
          {money(account.gross_position_value)}
        </span>
      </Field>

      <Field label="Unrealised">
        <span className="text-sm">
          <SignedMoney value={account.unrealized_pnl} />
        </span>
      </Field>

      {/* Net liquidation is the least volatile figure — desktop only, keeps the
          mobile strip to the three numbers that actually change intraday. */}
      <div className="hidden sm:flex items-baseline gap-1.5 flex-shrink-0 whitespace-nowrap ml-auto">
        <span className="text-[0.65rem] uppercase tracking-widest text-[var(--color-fg-muted)]">
          Net Liq
        </span>
        <span className="tabular-nums font-medium text-[var(--color-fg)] text-sm">
          {money(account.net_liquidation)}
        </span>
      </div>
    </Bar>
  )
}
