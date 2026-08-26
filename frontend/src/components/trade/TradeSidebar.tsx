import { useState } from 'react'
import { tradingApi } from '../../lib/api'
import { formatTime, relativeTime } from '../../lib/format'
import { useToast } from '../../lib/toast-context'
import { useTradingSettings } from '../../lib/trading-context'
import { SOURCE_LABEL, tradeSource } from '../../lib/trade-source'
import type { AnalyzeResponse, Proposal, TradeRecord } from '../../types'
import LoadingSpinner from '../LoadingSpinner'
import OrderTicket from '../OrderTicket'

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

// ── Approvals ─────────────────────────────────────────────────────────────────

/**
 * Entries the agent wanted to take but was not permitted to take alone.
 *
 * A live-money approval asks for the ticker to be typed back, exactly as the
 * order ticket does. Approving a proposal *is* placing an order — the fact
 * that the agent chose the name rather than the human does not make it a
 * smaller commitment, so it does not get a smaller confirmation.
 */
function ProposalCard({
  proposal,
  onResolved,
}: {
  proposal: Proposal
  onResolved: () => void
}) {
  const { toast } = useToast()
  const [busy, setBusy] = useState(false)
  const [confirmText, setConfirmText] = useState('')

  const isLive = !proposal.is_paper
  const confirmed = !isLive || confirmText.trim().toUpperCase() === proposal.ticker.toUpperCase()

  const approve = async () => {
    if (busy || !confirmed) return
    setBusy(true)
    try {
      const { data } = await tradingApi.approveProposal(proposal.id, isLive)
      if (data.placed) {
        toast(
          `Order placed: ${data.qty} ${data.ticker} at ${usd.format(data.limit_price)}`
          + (data.is_paper ? ' (paper)' : ''),
          'success',
        )
      } else {
        toast(data.reason ?? 'The order was not placed.', 'error')
      }
      onResolved()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast(detail ?? 'Could not approve that proposal.', 'error')
    } finally {
      setBusy(false)
    }
  }

  const decline = async () => {
    if (busy) return
    setBusy(true)
    try {
      await tradingApi.declineProposal(proposal.id)
      toast(`Skipped ${proposal.ticker}.`, 'info')
      onResolved()
    } catch {
      toast('Could not skip that proposal.', 'error')
    } finally {
      setBusy(false)
    }
  }

  const tone = proposal.action === 'SELL'
    ? { bg: 'var(--tint-sell)', fg: 'var(--accent-sell)' }
    : { bg: 'var(--tint-buy)', fg: 'var(--accent-buy)' }

  return (
    <div className="rounded-[7px] border border-[var(--color-border)] bg-[var(--color-bg)] p-2.5">
      <div className="flex items-baseline gap-1.5">
        <span className="num text-[13px] font-semibold">{proposal.ticker}</span>
        <span
          className="rounded px-1 py-px text-[9px] font-bold"
          style={{ background: tone.bg, color: tone.fg }}
        >
          {proposal.action}
        </span>
        {isLive && (
          <span
            className="rounded px-1 py-px text-[9px] font-bold"
            style={{ background: 'var(--tint-sell)', color: 'var(--accent-sell)' }}
          >
            LIVE
          </span>
        )}
        <span className="num ml-auto text-[12px]">
          {proposal.qty} @ {usd.format(proposal.limit_price)}
        </span>
      </div>

      {proposal.reason && (
        <p className="mt-1.5 text-[11px] leading-snug text-[var(--color-fg-muted)]">{proposal.reason}</p>
      )}

      <p className="mt-1 text-[10px] text-[var(--color-fg-muted)]">
        Proposed {relativeTime(proposal.proposed_at)}
        {proposal.conviction ? ` · ${proposal.conviction} conviction` : ''}
        {proposal.stop_loss != null ? ` · stop ${usd.format(proposal.stop_loss)}` : ''}
      </p>

      {isLive && (
        <div className="mt-2">
          <label
            htmlFor={`confirm-${proposal.id}`}
            className="mb-1 block text-[10.5px] text-[var(--accent-sell)]"
          >
            Type <strong>{proposal.ticker}</strong> to approve a live order
          </label>
          <input
            id={`confirm-${proposal.id}`}
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            autoComplete="off"
            className="h-7 w-full rounded-md border border-[var(--accent-sell)] bg-[var(--color-bg)]
                       px-2 text-[12px] text-[var(--color-fg)] outline-none"
          />
        </div>
      )}

      <div className="mt-2 flex gap-1.5">
        <button
          onClick={approve}
          disabled={busy || !confirmed}
          className="flex h-7 flex-1 items-center justify-center gap-1.5 rounded-md bg-brand-500
                     text-[12px] font-semibold text-white disabled:opacity-40"
        >
          {busy ? <LoadingSpinner size="sm" /> : null}
          Approve
        </button>
        <button
          onClick={decline}
          disabled={busy}
          className="h-7 flex-1 rounded-md border border-[var(--color-border)] text-[12px]
                     text-[var(--color-fg)] hover:bg-[var(--color-hover)] disabled:opacity-40"
        >
          Skip
        </button>
      </div>
    </div>
  )
}

// ── Activity ──────────────────────────────────────────────────────────────────

/**
 * What the agent has actually done, newest first.
 *
 * Derived from the order records rather than a dedicated event feed — there is
 * no agent-log endpoint, and inventing entries on a screen that places trades
 * would be worse than showing fewer of them. Every line here corresponds to a
 * row in `trades`.
 */
function ActivityLog({ orders }: { orders: TradeRecord[] }) {
  const recent = [...orders]
    .sort((a, b) => (b.opened_at ?? '').localeCompare(a.opened_at ?? ''))
    .slice(0, 12)

  if (recent.length === 0) {
    return (
      <p className="mt-2 text-[11px] text-[var(--color-fg-muted)]">
        No orders yet. Activity appears here as the agent places them.
      </p>
    )
  }

  return (
    <div className="mt-2 flex flex-col">
      {recent.map((o) => {
        const src = tradeSource(o.signal_type)
        const closed = o.closed_at != null
        const pnl = o.pnl
        return (
          <div
            key={o.id}
            className="flex gap-2 border-b border-[var(--color-border)] py-1.5 last:border-b-0"
          >
            <span className="num w-[52px] flex-shrink-0 text-[10.5px] text-[var(--color-fg-muted)]">
              {formatTime(closed ? o.closed_at : o.opened_at)}
            </span>
            <span className="text-[11px] leading-snug text-[var(--color-fg)]">
              <span className="num font-semibold">{o.ticker}</span>{' '}
              {closed ? 'closed' : `${o.action.toLowerCase()} ${o.qty}`}
              {!closed && o.limit_price ? ` @ ${usd.format(o.limit_price)}` : ''}
              {closed && pnl != null
                ? ` — ${pnl >= 0 ? '+' : '−'}${usd.format(Math.abs(pnl))}`
                : ''}
              <span className="text-[var(--color-fg-muted)]">
                {' · '}{SOURCE_LABEL[src]}{o.is_paper ? ' · paper' : ''}
                {o.status && !closed ? ` · ${o.status.toLowerCase()}` : ''}
              </span>
            </span>
          </div>
        )
      })}
    </div>
  )
}

// ── Sidebar ───────────────────────────────────────────────────────────────────

interface TradeSidebarProps {
  data: AnalyzeResponse | null
  proposals: Proposal[]
  orders: TradeRecord[]
  onOrderPlaced: () => void
  onProposalsChanged: () => void
}

export default function TradeSidebar({
  data,
  proposals,
  orders,
  onOrderPlaced,
  onProposalsChanged,
}: TradeSidebarProps) {
  const { settings } = useTradingSettings()

  const approvalsNote = settings?.mode === 'AUTO'
    ? 'In AUTO the agent places its own entries, so this queue is usually empty. Anything here was held back by a guard.'
    : settings?.mode === 'SEMI_AUTO'
      ? `In SEMI_AUTO the agent acts alone only at ${settings.auto_execute_conviction} conviction. Everything below that waits for you.`
      : 'In MANUAL the agent proposes and you place every order.'

  return (
    <aside className="min-h-0 overflow-y-auto border-l border-[var(--color-border)] bg-[var(--color-surface)]">
      {data ? (
        <OrderTicket data={data} onPlaced={onOrderPlaced} />
      ) : (
        <div className="border-b border-[var(--color-border)] px-3.5 py-3">
          <span className="label-micro">Order ticket</span>
          <p className="mt-2 text-[11px] text-[var(--color-fg-muted)]">
            Select a ticker to place an order.
          </p>
        </div>
      )}

      <div className="border-b border-[var(--color-border)] px-3.5 py-3">
        <div className="flex items-baseline justify-between">
          <span className="label-micro">Waiting on you</span>
          <span className="num text-[11px] text-brand-500">{proposals.length}</span>
        </div>
        <p className="mt-1.5 text-[10.5px] leading-snug text-[var(--color-fg-muted)]">{approvalsNote}</p>

        <div className="mt-2.5 flex flex-col gap-2">
          {proposals.length === 0 ? (
            <p className="text-[11px] text-[var(--color-fg-muted)]">Nothing waiting.</p>
          ) : (
            proposals.map((p) => (
              <ProposalCard key={p.id} proposal={p} onResolved={onProposalsChanged} />
            ))
          )}
        </div>
      </div>

      <div className="px-3.5 py-3">
        <span className="label-micro">Agent activity</span>
        <ActivityLog orders={orders} />
      </div>
    </aside>
  )
}
