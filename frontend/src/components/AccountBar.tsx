import { Link } from 'react-router-dom'
import { AlertTriangle } from 'lucide-react'
import { useSystemStatus } from '../lib/system-status'
import { useTradingSettings } from '../lib/trading-context'

/**
 * Persistent broker account strip, pinned under the header on every screen.
 *
 * Shows the account being traded, cash available to trade, capital currently
 * deployed, and unrealised P&L.
 *
 * Signed figures follow the broker-statement convention: gains green, losses
 * red and wrapped in parentheses rather than carrying a minus sign. Values
 * within half a cent of zero stay neutral, so a flat account doesn't read as a
 * gain and float dust or -0 can't render as a phantom loss.
 *
 * The 1.7 redesign takes it full-bleed at 34px to match the header rather than
 * inheriting the old page width cap — it belongs to the chrome, not to the
 * screen underneath, and the Trade screen has no width cap to inherit.
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

function signedTone(v: number): string {
  if (v < -0.005) return 'var(--accent-sell)'
  if (v > 0.005) return 'var(--accent-buy)'
  return 'var(--color-fg)'
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-shrink-0 items-baseline gap-1.5 whitespace-nowrap">
      <span className="text-[10px] uppercase tracking-[0.11em] text-[var(--color-fg-muted)]">
        {label}
      </span>
      {children}
    </div>
  )
}

function Value({ children, color }: { children: React.ReactNode; color?: string }) {
  return (
    <span className="num text-[12.5px] font-semibold" style={{ color: color ?? 'var(--color-fg)' }}>
      {children}
    </span>
  )
}

/** Shell so the bar occupies identical space in every state (no layout shift). */
function Bar({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="scrollbar-none sticky top-12 z-20 flex h-[34px] flex-shrink-0 items-center gap-5
                 overflow-x-auto border-b border-[var(--color-border)] bg-[var(--color-surface)] px-3.5"
    >
      {children}
    </div>
  )
}

/**
 * A degraded-inputs chip, and nothing at all when everything is working.
 *
 * Deliberately silent in the nominal case. A green dot that is always green
 * teaches people to stop seeing the strip it lives in, and the strip is where
 * the account balances are — the last place worth training someone to ignore.
 *
 * It never says "not trading" outside market hours: the pipeline is not
 * scheduled then, and the summary it renders is composed on the server, which
 * knows the market clock.
 */
function InputsChip() {
  const { status } = useSystemStatus()
  if (!status || status.overall === 'ok') return null

  const halted = status.overall === 'halted'
  return (
    <Link
      to="/status"
      title={status.summary}
      className="ml-auto flex flex-shrink-0 items-center gap-1.5 whitespace-nowrap rounded
                 px-1.5 py-0.5 text-[10.5px] font-semibold"
      style={{
        background: halted ? 'var(--tint-sell)' : 'var(--tint-hold)',
        color: halted ? 'var(--accent-sell)' : 'var(--accent-hold)',
      }}
    >
      <AlertTriangle className="h-3 w-3" aria-hidden="true" />
      {halted ? 'Trading paused' : 'Inputs degraded'}
    </Link>
  )
}

export default function AccountBar() {
  // Reads the shared copy rather than fetching and polling its own. The order
  // ticket sizes from the same object, so the equity shown here and the equity
  // an order is sized against cannot drift apart.
  const { account, accountLoading: loading } = useTradingSettings()

  if (loading) {
    return (
      <Bar>
        <div className="h-2.5 w-28 animate-pulse rounded bg-[var(--color-border)]/60" />
        <div className="h-2.5 w-32 animate-pulse rounded bg-[var(--color-border)]/40" />
        <div className="h-2.5 w-28 animate-pulse rounded bg-[var(--color-border)]/40" />
      </Bar>
    )
  }

  if (!account?.connected) {
    return (
      <Bar>
        <span className="flex flex-shrink-0 items-center gap-2 whitespace-nowrap text-[11px] text-[var(--color-fg-muted)]">
          <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-[var(--color-fg-muted)]" />
          Broker disconnected — balances unavailable
        </span>
        <InputsChip />
      </Bar>
    )
  }

  return (
    <Bar>
      <span className="flex flex-shrink-0 items-center gap-1.5 whitespace-nowrap text-[11px] text-[var(--color-fg-muted)]">
        <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-[var(--accent-buy)]" />
        IBKR
      </span>

      <Field label="Acct"><Value>{account.account_id || '—'}</Value></Field>
      <Field label="Available"><Value>{money(account.buying_power)}</Value></Field>
      <Field label="In trade"><Value>{money(account.gross_position_value)}</Value></Field>
      <Field label="Unrealised">
        <Value color={signedTone(account.unrealized_pnl)}>
          {account.unrealized_pnl < -0.005
            ? `(${money(account.unrealized_pnl)})`
            : money(account.unrealized_pnl)}
        </Value>
      </Field>

      {/* Net liquidation is the least volatile figure — it drops out first on a
          narrow viewport, keeping the strip to the numbers that move intraday. */}
      <InputsChip />

      <div className="ml-auto hidden flex-shrink-0 items-baseline gap-1.5 whitespace-nowrap min-[1000px]:flex">
        <span className="text-[10px] uppercase tracking-[0.11em] text-[var(--color-fg-muted)]">Net liq</span>
        <Value>{money(account.net_liquidation)}</Value>
      </div>
    </Bar>
  )
}
