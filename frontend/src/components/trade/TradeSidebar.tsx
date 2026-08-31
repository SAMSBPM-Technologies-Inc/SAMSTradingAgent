import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { formatDateTimeShort, relativeTime } from '../../lib/format'
import { useTradingSettings } from '../../lib/trading-context'
import { SOURCE_LABEL, displaySource } from '../../lib/trade-source'
import { exitReasonLabel } from '../../lib/exit-reason'
import type { AnalyzeResponse, Proposal, TradeRecord } from '../../types'
import OrderTicket from '../OrderTicket'
import { ProposalActions } from './ProposalActions'

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

// ── Approvals ─────────────────────────────────────────────────────────────────

/**
 * Entries the agent wanted to take but was not permitted to take alone.
 *
 * The card is the reading; the buttons are `ProposalActions`, shared with the
 * activity table's rows and the transaction page. Approving a proposal *is*
 * placing an order — the fact that the agent chose the name rather than the
 * human does not make it a smaller commitment — so the live-money gate lives in
 * exactly one place and every caller gets it.
 */
function ProposalCard({
  proposal,
  onResolved,
}: {
  proposal: Proposal
  onResolved: () => void
}) {
  const isLive = !proposal.is_paper

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

      {/* Why the agent wants this, above why it is asking. A card that says
          only "MANUAL mode — awaiting your approval" explains the queue, not
          the trade, and the queue is not what the reader has to decide about. */}
      {proposal.entry_reason && (
        <p className="mt-1.5 text-[11px] leading-snug text-[var(--color-fg)]">
          {proposal.entry_reason}
        </p>
      )}

      {proposal.reason && (
        <p className="mt-1.5 text-[11px] leading-snug text-[var(--color-fg-muted)]">{proposal.reason}</p>
      )}

      <p className="mt-1 text-[10px] text-[var(--color-fg-muted)]">
        Proposed {relativeTime(proposal.proposed_at)}
        {proposal.conviction ? ` · ${proposal.conviction} analyst conviction` : ''}
        {proposal.stop_loss != null ? ` · stop ${usd.format(proposal.stop_loss)}` : ''}
      </p>

      <ProposalActions
        id={proposal.id}
        ticker={proposal.ticker}
        isPaper={proposal.is_paper}
        onResolved={onResolved}
      />
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
 *
 * Every line states the action *and the reason*: how many shares, at what
 * result, and why. "AVGO closed 12 — −$1,234.00" says a position ended and
 * leaves the only interesting question unanswered; the record carries
 * `exit_reason`, so a closed line says which of a stop, a fallen score, or the
 * user's own Close button did it, and `entry_reason`, so an open one says what
 * the agent saw when it bought.
 */
function ActivityLog({ orders, ticker }: { orders: TradeRecord[]; ticker?: string }) {
  const navigate = useNavigate()
  const recent = useMemo(() => (ticker ? orders.filter((o) => o.ticker === ticker) : orders)
    .slice()
    .sort((a, b) => (b.closed_at ?? b.opened_at ?? '').localeCompare(a.closed_at ?? a.opened_at ?? ''))
    .slice(0, 12), [orders, ticker])

  if (recent.length === 0) {
    return (
      <p className="mt-2 text-[11px] text-[var(--color-fg-muted)]">
        {ticker
          ? `Nothing has been traded on ${ticker}.`
          : 'No orders yet. Activity appears here as the agent places them.'}
      </p>
    )
  }

  return (
    <div className="mt-2 flex flex-col">
      {recent.map((o) => {
        const src = displaySource(o)
        const closed = o.closed_at != null
        const pnl = o.pnl
        const qty = o.filled_qty ?? o.qty
        // A closed line answers "why did that end"; an open one answers "why
        // is this on". Both questions are the same question at different
        // times, and the feed used to answer only the first.
        const reason = closed
          ? exitReasonLabel(o.exit_reason)
          : o.entry_reason ?? null
        // An estimate from the limit we asked for is not a result. Settlement
        // clears the flag when the real fill lands; until then the line says
        // the sale is still working rather than showing a P&L that may not be
        // what happened.
        const settled = closed && !o.exit_price_estimated
        return (
          <button
            key={o.id}
            type="button"
            onClick={() => navigate(`/transaction/${o.id}`)}
            className="flex gap-2 border-b border-[var(--color-border)] py-1.5 text-left
                       last:border-b-0 hover:bg-[var(--color-hover)]"
          >
            {/* Date and time both. A log showing only "2:04 PM" is unreadable
                the moment it spans midnight — which it does by the second
                trading day — and the reader checking it is usually checking
                something recent, where "was that today?" is the question. */}
            <span className="num w-[104px] flex-shrink-0 text-[10.5px] text-[var(--color-fg-muted)]">
              {formatDateTimeShort(closed ? o.closed_at : o.opened_at)}
            </span>
            <span className="min-w-0 text-[11px] leading-snug text-[var(--color-fg)]">
              <span className="num font-semibold">{o.ticker}</span>{' '}
              {closed ? `sold ${qty}` : `${o.action.toLowerCase()} ${qty}`}
              {!closed && o.limit_price ? ` @ ${usd.format(o.limit_price)}` : ''}
              {closed && settled && pnl != null && (
                <span style={{ color: pnl >= 0 ? 'var(--accent-buy)' : 'var(--accent-sell)' }}>
                  {' — '}{pnl >= 0 ? '+' : '−'}{usd.format(Math.abs(pnl))}
                </span>
              )}
              {closed && !settled && (
                <span className="text-[var(--color-fg-muted)]"> — sale working</span>
              )}
              <span className="text-[var(--color-fg-muted)]">
                {' · '}{SOURCE_LABEL[src]}{o.is_paper ? ' · paper' : ''}
                {o.status && !closed ? ` · ${o.status.toLowerCase()}` : ''}
              </span>
              {/* The why. Its own line: it is the part worth reading, and
                  trailing it after four dot-separated fragments buries it. */}
              {reason && (
                <span className="mt-0.5 block text-[10.5px] leading-snug text-[var(--color-fg-muted)]">
                  {reason}
                </span>
              )}
            </span>
          </button>
        )
      })}
    </div>
  )
}

// ── Panels ────────────────────────────────────────────────────────────────────
//
// The sidebar is exported as three panels rather than one block because the two
// layouts want them in different orders, and because `TickerActions` now sits
// above them in the same column. At lg they stack in the right column; below lg
// they dissolve into the single flow and `TradePage` orders them with CSS.
//
// The distance that used to matter here — a 390px viewport put the ticket
// 2898px down and the queue 3255px down — was bought back by collapsing the
// analysis rather than by hoisting the panels above it, which is why they land
// after the centre column now. See the ordering note in `TradePage`.
//
// They are still mounted once each. `TradePage` reorders them with CSS; it does
// not render a second copy.

/** Buy ticket for the selected name, or the reason there isn't one. */
export function OrderPanel({
  data,
  onOrderPlaced,
}: {
  data: AnalyzeResponse | null
  onOrderPlaced: () => void
}) {
  // Mounted only with a ticker selected, so a missing analysis is the one
  // reason left for an empty ticket — the sizing, the stop and the score gate
  // all read from it. Saying "select a ticker" here would have been false.
  if (!data) {
    return (
      <div className="border-b border-[var(--color-border)] px-3.5 py-3">
        <span className="label-micro">Order ticket</span>
        <p className="mt-2 text-[11px] text-[var(--color-fg-muted)]">
          No stored analysis for this ticker yet — run one and the ticket fills in.
        </p>
      </div>
    )
  }
  return <OrderTicket data={data} onPlaced={onOrderPlaced} />
}

/** Entries the agent wanted but was not permitted to take alone. */
export function ApprovalsPanel({
  proposals,
  onProposalsChanged,
}: {
  proposals: Proposal[]
  onProposalsChanged: () => void
}) {
  const { settings } = useTradingSettings()

  const approvalsNote = settings?.mode === 'AUTO'
    ? 'In AUTO the agent places its own entries, so this queue is usually empty. Anything here was held back by a guard.'
    : settings?.mode === 'SEMI_AUTO'
      ? `In SEMI_AUTO the agent acts alone only at ${settings.auto_execute_conviction} analyst conviction. Everything below that waits for you.`
      : 'In MANUAL the agent proposes and you place every order.'

  return (
    // The anchor the "waiting on you" control scrolls to.
    <div id="approvals" className="border-b border-[var(--color-border)] px-3.5 py-3">
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
  )
}

/**
 * What has actually been done — for the whole account, or for the name being
 * read.
 *
 * With a ticker selected this is the audit trail beside the analysis: what was
 * bought, sold, proposed or refused on *this* name, which is the context that
 * turns a verdict into a decision. Without one it is the account-wide feed it
 * has always been.
 */
export function ActivityPanel({ orders, ticker }: { orders: TradeRecord[]; ticker?: string }) {
  return (
    <div className="px-3.5 py-3">
      <span className="label-micro">
        {ticker ? `Transactions — ${ticker}` : 'Agent activity'}
      </span>
      <ActivityLog orders={orders} ticker={ticker} />
    </div>
  )
}
