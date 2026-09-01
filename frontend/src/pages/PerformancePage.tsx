import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertCircle, BarChart2, Clock, Target, TrendingUp } from 'lucide-react'
import { performanceApi } from '../lib/api'
import { formatDateTime } from '../lib/format'
import type {
  ClosedTrade,
  ExitBucket,
  PerformanceResponse,
  Signal,
  SignalRecord,
  TradePerformanceResponse,
  TradeStats,
} from '../types'
import Layout from '../components/Layout'
import SignalBadge from '../components/SignalBadge'
import ConvictionBadge from '../components/ConvictionBadge'
import LoadingSpinner from '../components/LoadingSpinner'
import { CardList, RecordCard } from '../components/positions/RecordCard'
import { exitReasonLabel } from '../lib/exit-reason'
import { useIsCompact } from '../lib/use-media-query'
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
    <div className="border border-[var(--color-border)] p-4 flex flex-col gap-1" style={{ borderRadius: '10px' }}>
      <span className="text-[11px] font-semibold uppercase tracking-widest text-[var(--color-fg-muted)]">{label}</span>
      <span
        className={`text-[22px] font-bold tabular-nums ${valueClass ?? 'text-[var(--color-fg)]'}`}
        style={{ fontFamily: 'Archivo, system-ui, sans-serif' }}
      >
        {value}
      </span>
      {sub && <span className="text-[11px] text-[var(--color-fg-muted)]">{sub}</span>}
    </div>
  )
}

// ── Realised trading performance ──────────────────────────────────────────────
//
// Separate from signal accuracy on purpose. That measures whether a call was
// right 20 days later and only scores BUY/SELL; this measures money, and is
// available the moment a position closes.

const usd = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

/** Broker-statement convention: gains green, losses red in parentheses. */
function Pnl({ value, className = '' }: { value: number | null | undefined; className?: string }) {
  if (value == null) return <span className="text-[var(--color-fg-muted)]">—</span>
  const loss = value < -0.005
  const gain = value > 0.005
  const tone = loss ? 'text-red-500' : gain ? 'text-green-600' : 'text-[var(--color-fg)]'
  return (
    <span className={`tabular-nums ${tone} ${className}`}>
      {loss ? `(${usd.format(Math.abs(value))})` : usd.format(value)}
    </span>
  )
}

function TradeStatsBlock({ title, note, stats }: {
  title: string
  note: string
  stats: TradeStats
}) {
  const nothing = stats.closed === 0 && stats.open === 0 && stats.unreconciled === 0
  // Net leads when it is known. Gross is what the position did; net is what
  // reached the account, and on a small account the two are far apart — a
  // fixed ticket costs 0.5% of a $200 round trip and 0.005% of a $20,000 one.
  const hasNet = stats.realised_pnl_net != null
  const headline = hasNet ? stats.realised_pnl_net : stats.realised_pnl
  return (
    <div className="border border-[var(--color-border)] p-4" style={{ borderRadius: '10px' }}>
      <div className="flex items-baseline justify-between gap-3 mb-1">
        <span className="text-[11px] font-semibold uppercase tracking-widest text-[var(--color-fg-muted)]">
          {title}
        </span>
        {headline != null && (
          <span className="flex items-baseline gap-1.5">
            <Pnl value={headline} className="text-[18px] font-bold" />
            <span className="text-[10px] uppercase tracking-wider text-[var(--color-fg-muted)]">
              {hasNet ? 'net' : 'gross'}
            </span>
          </span>
        )}
      </div>
      <p className="text-[11px] text-[var(--color-fg-muted)] mb-3">{note}</p>

      {nothing ? (
        <p className="text-sm text-[var(--color-fg-muted)]">No trades yet.</p>
      ) : (
        <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
          <span className="text-[var(--color-fg-muted)]">Closed</span>
          <span className="tabular-nums text-right text-[var(--color-fg)]">{stats.closed}</span>
          <span className="text-[var(--color-fg-muted)]">Open</span>
          <span className="tabular-nums text-right text-[var(--color-fg)]">{stats.open}</span>
          <span className="text-[var(--color-fg-muted)]">Win rate</span>
          <span className="tabular-nums text-right text-[var(--color-fg)]">
            {stats.win_rate == null
              ? '—'
              : `${Math.round(stats.win_rate * 100)}% (${stats.wins}/${stats.wins + stats.losses})`}
          </span>
          <span className="text-[var(--color-fg-muted)]">Avg win</span>
          <span className="text-right"><Pnl value={stats.avg_win} /></span>
          <span className="text-[var(--color-fg-muted)]">Avg loss</span>
          <span className="text-right"><Pnl value={stats.avg_loss} /></span>

          {hasNet && (
            <>
              <span className="text-[var(--color-fg-muted)]">Gross</span>
              <span className="text-right"><Pnl value={stats.realised_pnl} /></span>
              <span className="text-[var(--color-fg-muted)]">Commission</span>
              <span className="tabular-nums text-right text-[var(--color-fg)]">
                {stats.commission_paid == null ? '—' : usd.format(stats.commission_paid)}
                {stats.commission_drag != null && (
                  <span className="text-[var(--color-fg-muted)]">
                    {' '}({Math.round(stats.commission_drag * 100)}%)
                  </span>
                )}
              </span>
              <span className="text-[var(--color-fg-muted)]">Win rate net</span>
              <span className="tabular-nums text-right text-[var(--color-fg)]">
                {stats.win_rate_net == null
                  ? '—'
                  : `${Math.round(stats.win_rate_net * 100)}% (${stats.netted})`}
              </span>
              {/* The number that should drive the sizing thresholds: trades
                  that made money until the ticket was paid. */}
              {stats.wins_lost_to_fees > 0 && (
                <>
                  <span className="text-[var(--color-fg-muted)]">Wins lost to fees</span>
                  <span className="tabular-nums text-right text-red-500">
                    {stats.wins_lost_to_fees}
                  </span>
                </>
              )}
            </>
          )}
          {/* Priced, but with no usable fee figure — mostly trades that closed
              before fee capture shipped. Shown rather than folded in at zero,
              which would understate cost in one direction every time. */}
          {stats.net_unknown > 0 && (
            <>
              <span className="text-[var(--color-fg-muted)]">Fees unknown</span>
              <span className="tabular-nums text-right text-[var(--color-fg-muted)]">
                {stats.net_unknown}
              </span>
            </>
          )}
          {stats.closed_unpriced > 0 && (
            <>
              <span className="text-[var(--color-fg-muted)]">Unpriced</span>
              <span className="tabular-nums text-right text-[var(--color-fg-muted)]">
                {stats.closed_unpriced}
              </span>
            </>
          )}
          {stats.unreconciled > 0 && (
            <>
              <span className="text-[var(--color-fg-muted)]">Unreconciled</span>
              <span className="tabular-nums text-right text-[var(--color-fg-muted)]">
                {stats.unreconciled}
              </span>
            </>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * Why a position closed, preferring what was recorded over what can be guessed.
 *
 * This used to infer the reason by comparing the exit price to the stop and the
 * target: at or below the stop meant "stop hit". That was the best available
 * answer when nothing recorded the cause, but it is only a coincidence test —
 * an exit the agent took on a fallen score prints below the stop often enough,
 * and would be labelled "stop hit" against a record that says otherwise. The
 * exit path now writes the reason it acted on, so that wins; the price
 * comparison survives only for rows closed before it did.
 */
const EXIT_LABEL: Record<string, string> = {
  TAKE_PROFIT: 'Target reached',
  STOP_LOSS: 'Stopped out',
  SELL_SIGNAL: 'Sell signal',
  MANUAL_CLOSE: 'You closed it',
  unknown: 'Unattributed',
}

/**
 * How positions ended, and how much of the move was still there when they did.
 *
 * The three buckets above answer "who chose this trade". This answers "how did
 * it end", which for a strategy built on buying weakness and selling strength
 * is the other half — and which no surface could show while reconciliation
 * stamped one value on every bracket exit.
 *
 * `Gave back` is the number a trailing stop should be argued from. It carries
 * its own sample count because the excursion series starts later than the trade
 * series: a mean over four of forty rows must not read as one over forty, the
 * same discipline alpha follows.
 */
function ExitBreakdown({ exits }: { exits: Record<string, ExitBucket> }) {
  const rows = Object.entries(exits ?? {})
    .filter(([, b]) => b.n > 0)
    .sort((a, b) => b[1].n - a[1].n)
  if (rows.length === 0) return null

  return (
    <div className="rounded-[7px] border border-[var(--color-border)] overflow-hidden">
      <div className="px-3 py-2 border-b border-[var(--color-border)]">
        <div className="text-[12px] font-semibold">How positions ended</div>
        <p className="text-[11px] text-[var(--color-fg-muted)] mt-0.5">
          Peak and give-back are measured against entry, so a bucket returning
          −5% that peaked at +6% is a different system from one that never rose.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead className="text-[11px] uppercase tracking-wide text-[var(--color-fg-muted)]">
            <tr className="border-b border-[var(--color-border)]">
              <th scope="col" className="text-left font-medium px-3 py-1.5">Exit</th>
              <th scope="col" className="text-right font-medium px-3 py-1.5">Trades</th>
              <th scope="col" className="text-right font-medium px-3 py-1.5">Won</th>
              <th scope="col" className="text-right font-medium px-3 py-1.5">Avg return</th>
              <th scope="col" className="text-right font-medium px-3 py-1.5">Avg peak</th>
              <th scope="col" className="text-right font-medium px-3 py-1.5">Gave back</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([key, b]) => (
              <tr key={key} className="border-b border-[var(--color-border)] last:border-0">
                <td className="px-3 py-1.5">
                  {EXIT_LABEL[key] ?? key}
                  {!b.significant && (
                    <span className="ml-1.5 text-[10px] uppercase tracking-wide text-[var(--color-fg-muted)]">
                      thin
                    </span>
                  )}
                </td>
                <td className="px-3 py-1.5 text-right tabular-nums">{b.n}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{b.wins}</td>
                <td className={`px-3 py-1.5 text-right tabular-nums ${returnColor(b.avg_return_pct)}`}>
                  {fmtReturn(b.avg_return_pct)}
                </td>
                {/* Both excursion columns are blank rather than 0 when nothing
                    was measured — every trade closed before the high-water mark
                    existed has a return and no peak. */}
                <td className="px-3 py-1.5 text-right tabular-nums">
                  {b.measured_n > 0 ? fmtReturn(b.avg_mfe_pct) : '—'}
                </td>
                <td className="px-3 py-1.5 text-right tabular-nums">
                  {b.measured_n > 0 ? fmtReturn(b.avg_gave_back_pct) : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="px-3 py-1.5 text-[11px] text-[var(--color-fg-muted)] border-t border-[var(--color-border)]">
        Peak and give-back cover{' '}
        {rows.reduce((n, [, b]) => n + b.measured_n, 0)} of{' '}
        {rows.reduce((n, [, b]) => n + b.n, 0)} closed trades.
      </p>
    </div>
  )
}


/**
 * Why a closed row says it closed.
 *
 * The stop/target comparison below now duplicates
 * `trade_manager._classify_bracket_exit`, and deliberately: the server names the
 * leg on rows it closes from here on, but a trade already settled as
 * `bracket_or_manual` is never reconciled again and would otherwise stay
 * unattributed forever. So this reads the same two inequalities for the back
 * catalogue only. It must not gain rules the server does not have — a client
 * that can explain an exit the server cannot is the drift that produced two
 * disagreeing definitions of a dip.
 */
function closedReason(t: ClosedTrade): string {
  const recorded = exitReasonLabel(t.exit_reason)
  if (recorded && t.exit_reason !== 'bracket_or_manual') return recorded

  if (t.status === 'UNRECONCILED') return 'no broker record'
  if (t.stop_loss && t.exit_price && t.exit_price <= t.stop_loss) return 'stop hit'
  if (t.take_profit && t.exit_price && t.exit_price >= t.take_profit) return 'target hit'
  return recorded ?? 'closed'
}

/**
 * Is there trading activity worth reporting at all?
 *
 * An UNRECONCILED trade is terminal and *unknowable*, not absent — the broker
 * has no record and the execution log no longer reaches back far enough to say
 * what happened. The API ships those rows in `recent_closed` alongside CLOSED
 * precisely so they stay visible, so gating this section on closed/open alone
 * hid a table that had rows to draw. `TradeStatsBlock` already counts them as
 * activity; only this gate had forgotten to.
 *
 * PROPOSED and DECLINED are excluded on purpose, and that is not an oversight:
 * a proposal commits nothing, has no realised result, and belongs to the queue
 * on /orders. Realised performance is about money that moved.
 */
function hasRealisedActivity(t: TradePerformanceResponse): boolean {
  return t.all.closed > 0 || t.all.open > 0 || t.all.unreconciled > 0
}

function ClosedTradesTable({ trades }: { trades: ClosedTrade[] }) {
  const compact = useIsCompact()

  if (trades.length === 0) {
    return (
      <div className="card p-8 text-center text-sm text-[var(--color-fg-muted)]">
        No closed trades yet. Positions appear here once they exit.
      </div>
    )
  }
  if (compact) {
    return (
      <CardList>
        {trades.map((t, i) => (
          <RecordCard
            key={`${t.ticker}-${t.closed_at ?? i}`}
            title={t.ticker}
            badges={
              t.scale_ins > 0 ? (
                <span className="text-[10px] text-[var(--color-fg-muted)]">
                  +{t.scale_ins} add{t.scale_ins > 1 ? 's' : ''}
                </span>
              ) : null
            }
            fields={[
              // When it happened, not just that it did. Without this a list of
              // recent closes is unorderable by eye — every row looks equally
              // recent, which is exactly wrong when you are checking whether
              // the one from ten minutes ago settled.
              { label: 'Closed', value: formatDateTime(t.closed_at) },
              { label: 'Qty', value: t.qty?.toLocaleString() ?? '—' },
              { label: '%', value: t.pnl_pct == null ? '—' : `${(t.pnl_pct * 100).toFixed(2)}%` },
              { label: 'Entry', value: fmtPrice(t.entry_price) },
              { label: 'Exit', value: fmtPrice(t.exit_price) },
              { label: 'P&L', value: <Pnl value={t.pnl} /> },
              {
                label: 'Net',
                value: t.pnl_net != null
                  ? <Pnl value={t.pnl_net} />
                  : <span className="text-[var(--color-fg-muted)]">—</span>,
              },
              {
                label: 'Fees',
                value: t.commission_paid == null ? '—' : usd.format(t.commission_paid),
              },
            ]}
            note={
              <>
                {t.entry_reason && (
                  <span className="block text-[var(--color-fg)]">{t.entry_reason}</span>
                )}
                <span className="block">{closedReason(t)}</span>
              </>
            }
          />
        ))}
      </CardList>
    )
  }

  return (
    <div className="card overflow-hidden p-0">
      <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[46rem]">
          <thead>
            <tr className="border-b border-[var(--color-border)] text-[11px] uppercase tracking-widest text-[var(--color-fg-muted)]">
              <th scope="col" className="text-left font-semibold px-4 py-2.5">Closed (ET)</th>
              <th scope="col" className="text-left font-semibold px-4 py-2.5">Ticker</th>
              <th scope="col" className="text-right font-semibold px-3 py-2.5">Qty</th>
              <th scope="col" className="text-right font-semibold px-3 py-2.5">Entry</th>
              <th scope="col" className="text-right font-semibold px-3 py-2.5">Exit</th>
              <th scope="col" className="text-right font-semibold px-3 py-2.5">P&amp;L</th>
              {/* Gross above, net below, in one column — side-by-side columns
                  read as two unrelated numbers, and the point is the gap. */}
              <th scope="col" className="text-right font-semibold px-3 py-2.5">Fees</th>
              <th scope="col" className="text-right font-semibold px-3 py-2.5">%</th>
              {/* Was a second column also labelled "Exit", then "Reason" — it
                  is why the position was taken and why it ended, not the price
                  it closed at. */}
              <th scope="col" className="text-left font-semibold px-4 py-2.5">Why</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t, i) => (
              <tr
                key={`${t.ticker}-${t.closed_at ?? i}`}
                className="border-b border-[var(--color-border)] last:border-b-0"
              >
                <td className="px-4 py-2.5 whitespace-nowrap text-[11px] text-[var(--color-fg-muted)]">
                  {formatDateTime(t.closed_at)}
                </td>
                <td className="px-4 py-2.5">
                  <span className="font-semibold text-[var(--color-fg)]">{t.ticker}</span>
                  {t.signal_type && t.signal_type !== 'BUY' && t.signal_type !== 'SELL' && (
                    <span className="ml-2 text-[10px] uppercase tracking-wider text-[var(--color-fg-muted)]">
                      manual
                    </span>
                  )}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums text-[var(--color-fg)]">
                  {t.qty?.toLocaleString() ?? '—'}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums text-[var(--color-fg-muted)]">
                  {fmtPrice(t.entry_price)}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums text-[var(--color-fg-muted)]">
                  {fmtPrice(t.exit_price)}
                </td>
                <td className="px-3 py-2.5 text-right">
                  <Pnl value={t.pnl} />
                  {t.pnl_net != null && (
                    <div className="text-[11px] mt-0.5">
                      <span className="text-[var(--color-fg-muted)]">net </span>
                      <Pnl value={t.pnl_net} className="text-[11px]" />
                    </div>
                  )}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums text-[var(--color-fg-muted)] text-[13px]">
                  {t.commission_paid == null
                    ? '—'
                    : usd.format(t.commission_paid)}
                  {/* An add is a second ticket on one position — the reason
                      adds are rationed. Worth seeing next to the fee. */}
                  {t.scale_ins > 0 && (
                    <div className="text-[10px]">+{t.scale_ins} add{t.scale_ins > 1 ? 's' : ''}</div>
                  )}
                  {t.commission_paid != null && !t.commission_complete && (
                    <div className="text-[10px]" title="At least one execution never reported a commission — this is a floor, not a total.">
                      incomplete
                    </div>
                  )}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {t.pnl_pct == null ? (
                    <span className="text-[var(--color-fg-muted)]">—</span>
                  ) : (
                    <span className={t.pnl_pct < 0 ? 'text-red-500' : 'text-green-600'}>
                      {(t.pnl_pct * 100).toFixed(2)}%
                    </span>
                  )}
                </td>
                <td className="px-4 py-2.5 text-[13px] max-w-[20rem]">
                  {/* The thesis above the outcome. A realised P&L is a test of
                      a claim, and this table showed the result without ever
                      showing the claim it tested. */}
                  {t.entry_reason && (
                    <div className="text-[11px] leading-snug text-[var(--color-fg)]">
                      {t.entry_reason}
                    </div>
                  )}
                  <div className="text-[var(--color-fg-muted)]">{closedReason(t)}</div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Signal accuracy cards (Section 2) ─────────────────────────────────────────

const SIGNAL_ORDER: Signal[] = ['BUY', 'HOLD', 'SELL']

const tintBg: Record<Signal, string> = {
  BUY: 'var(--tint-buy)', SELL: 'var(--tint-sell)', HOLD: 'var(--tint-hold)',
}
const barColor: Record<Signal, string> = {
  BUY: 'var(--accent-buy)', SELL: 'var(--accent-sell)', HOLD: 'var(--accent-hold)',
}

function SignalAccuracyCard({ row }: { row: PerformanceResponse['by_signal'][number] }) {
  const pending = row.settled === 0
  const winPct = row.win_rate != null ? row.win_rate * 100 : 0
  const signal = row.signal as Signal

  return (
    <div className="flex flex-col gap-3" style={{ background: tintBg[signal], borderRadius: 10, padding: 20 }}>
      {/* Signal badge */}
      <SignalBadge signal={signal} />

      {/* Win rate */}
      {pending ? (
        <div className="flex flex-col gap-1">
          <span
            className="text-[var(--color-fg-muted)] tabular-nums"
            style={{ fontFamily: 'Archivo, system-ui, sans-serif', fontWeight: 700, fontSize: '28px' }}
          >
            Pending
          </span>
          <div className="bg-[var(--color-border)] overflow-hidden" style={{ height: 4, borderRadius: 2 }}>
            <div style={{ height: '100%', width: 0, background: barColor[signal], borderRadius: 2 }} />
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-1">
          <span
            className="text-[var(--color-fg)] tabular-nums"
            style={{ fontFamily: 'Archivo, system-ui, sans-serif', fontWeight: 700, fontSize: '28px' }}
          >
            {fmtPct(row.win_rate)}
          </span>
          <div className="bg-[var(--color-border)] overflow-hidden" style={{ height: 4, borderRadius: 2 }}>
            <div
              style={{ height: '100%', width: `${winPct}%`, background: barColor[signal], borderRadius: 2, transition: 'width 500ms' }}
            />
          </div>
        </div>
      )}

      {/* Counts, average return, and what the market did over the same days */}
      <div className="flex flex-col gap-0.5">
        <span className="text-xs text-[var(--color-fg-muted)] tabular-nums">
          {row.settled} of {row.total} settled
        </span>
        <span className={`text-sm font-medium tabular-nums ${returnColor(row.avg_return_20d)}`}>
          Avg 20d: {fmtReturn(row.avg_return_20d)}
        </span>
        {/* Alpha has its own denominator: records settled before benchmark
            measurement existed carry a return and no alpha. Rendering a dash
            under the settled count would present a handful of samples with the
            authority of hundreds, so the count is stated whenever it differs
            and the line is absent entirely when there is nothing to show. */}
        {row.alpha_settled ? (
          <span className={`text-sm font-medium tabular-nums ${returnColor(row.avg_alpha_20d)}`}>
            Alpha: {fmtReturn(row.avg_alpha_20d)}
            {row.alpha_settled !== row.settled && (
              <span className="text-[var(--color-fg-muted)] font-normal">
                {' '}(of {row.alpha_settled})
              </span>
            )}
          </span>
        ) : null}
      </div>
    </div>
  )
}

// ── Recent signal history table (Section 3) ────────────────────────────────────

function OutcomeCell({ rec }: { rec: SignalRecord }) {
  if (rec.return_20d == null) return <span className="text-[var(--color-fg-muted)] text-xs">Pending</span>
  if (rec.was_correct) return <span className="text-[var(--accent-buy)] text-xs font-medium">✓ Correct</span>
  return <span className="text-[var(--accent-sell)] text-xs font-medium">✗ Wrong</span>
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
    // Section label lives on the page's <h2>; a card heading here repeated it.
    <div className="card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--color-border)]">
              <th scope="col" className="px-4 py-2.5 text-left text-[10.5px] font-semibold uppercase tracking-widest text-[var(--color-fg-muted)]">Date</th>
              <th scope="col" className="px-4 py-2.5 text-left text-[10.5px] font-semibold uppercase tracking-widest text-[var(--color-fg-muted)]">Ticker</th>
              <th scope="col" className="px-4 py-2.5 text-left text-[10.5px] font-semibold uppercase tracking-widest text-[var(--color-fg-muted)]">Signal</th>
              <th scope="col" className="px-4 py-2.5 text-right text-[10.5px] font-semibold uppercase tracking-widest text-[var(--color-fg-muted)]">Score</th>
              <th scope="col" className="px-4 py-2.5 text-left text-[10.5px] font-semibold uppercase tracking-widest text-[var(--color-fg-muted)]">Conviction</th>
              <th scope="col" className="px-4 py-2.5 text-right text-[10.5px] font-semibold uppercase tracking-widest text-[var(--color-fg-muted)]">Entry Price</th>
              <th scope="col" className="px-4 py-2.5 text-right text-[10.5px] font-semibold uppercase tracking-widest text-[var(--color-fg-muted)]">20d Return</th>
              <th scope="col" className="px-4 py-2.5 text-left text-[10.5px] font-semibold uppercase tracking-widest text-[var(--color-fg-muted)]">Outcome</th>
            </tr>
          </thead>
          <tbody>
            {displayed.map((rec, i) => (
              <tr
                key={`${rec.ticker}-${rec.generated_at}-${i}`}
                className="border-b border-[var(--color-border)]/50 last:border-0"
              >
                <td className="px-4 py-3 text-xs text-[var(--color-fg-muted)] tabular-nums whitespace-nowrap">
                  {formatDateTime(rec.generated_at)}
                </td>
                <td className="px-4 py-3">
                  <span
                    className="font-semibold text-[var(--color-fg)]"
                    style={{ fontFamily: 'Archivo, system-ui, sans-serif' }}
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
    // Section label lives on the page's <h2>; a card heading here repeated it.
    <div className="card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-[12px] sm:text-sm">
          <thead>
            <tr className="border-b border-[var(--color-border)]">
              <th scope="col" className="px-2 py-2.5 sm:px-4 text-left text-[10.5px] font-semibold uppercase tracking-widest text-[var(--color-fg-muted)]">Ticker</th>
              <th scope="col" className="px-2 py-2.5 sm:px-4 text-right text-[10.5px] font-semibold uppercase tracking-widest text-[var(--color-fg-muted)]">Signals</th>
              <th scope="col" className="px-2 py-2.5 sm:px-4 text-right text-[10.5px] font-semibold uppercase tracking-widest text-[var(--color-fg-muted)]">Settled</th>
              <th scope="col" className="px-2 py-2.5 sm:px-4 text-right text-[10.5px] font-semibold uppercase tracking-widest text-[var(--color-fg-muted)]">Win Rate</th>
              <th scope="col" className="px-2 py-2.5 sm:px-4 text-right text-[10.5px] font-semibold uppercase tracking-widest text-[var(--color-fg-muted)]">Avg 20d</th>
              <th scope="col" className="px-2 py-2.5 sm:px-4 text-right text-[10.5px] font-semibold uppercase tracking-widest text-[var(--color-fg-muted)]">Alpha</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
              <tr key={row.ticker} className="border-b border-[var(--color-border)]/50 last:border-0">
                <td className="px-2 py-3 sm:px-4">
                  <span
                    className="font-semibold text-[var(--color-fg)]"
                    style={{ fontFamily: 'Archivo, system-ui, sans-serif' }}
                  >
                    {row.ticker}
                  </span>
                </td>
                <td className="px-2 py-3 sm:px-4 text-right text-[var(--color-fg)] tabular-nums">{row.total}</td>
                <td className="px-2 py-3 sm:px-4 text-right text-[var(--color-fg)] tabular-nums">{row.settled}</td>
                <td className="px-2 py-3 sm:px-4 text-right tabular-nums">
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
                <td className={`px-2 py-3 sm:px-4 text-right tabular-nums ${returnColor(row.avg_return_20d)}`}>
                  {fmtReturn(row.avg_return_20d)}
                </td>
                {/* Blank rather than a dash when no record for this ticker has
                    been benchmarked. A dash beside a real return reads as zero
                    alpha, which is a measurement this row does not have. */}
                <td className={`px-2 py-3 sm:px-4 text-right tabular-nums ${returnColor(row.avg_alpha_20d)}`}>
                  {row.alpha_settled ? fmtReturn(row.avg_alpha_20d) : ''}
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
        className="text-lg font-semibold text-[var(--color-fg)] mb-2"
        style={{ fontFamily: 'Archivo, system-ui, sans-serif' }}
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
  const [trades, setTrades] = useState<TradePerformanceResponse | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([
      performanceApi.get(),
      performanceApi.signals(),
      // Trade stats are additive, not required: a failure here should not
      // blank the signal dashboard that already works.
      performanceApi.trades().catch(() => null),
    ])
      .then(([perfRes, sigRes, tradeRes]) => {
        setData(perfRes.data as PerformanceResponse)
        setSignalHistory(sigRes.data)
        if (tradeRes) setTrades(tradeRes.data)
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
      <div className="mb-6 flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-[var(--color-fg)]" style={{ fontFamily: 'Archivo, system-ui, sans-serif' }}>
            Signal Accuracy Dashboard
          </h1>
          <p className="text-sm text-[var(--color-fg-muted)] mt-0.5">
            Historical accuracy of AI-generated trading signals
          </p>
        </div>
        {/* "Was it right?" is this page; "were the thresholds in the right
            place?" is the next one, and it is the harder question. */}
        <Link to="/calibration" className="btn-secondary flex-shrink-0 self-start">
          <Target className="w-4 h-4" />
          Calibration
        </Link>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <LoadingSpinner size="lg" />
        </div>
      ) : error ? (
        <div
          role="alert"
          className="flex items-center gap-3 px-4 py-3 rounded-xl
                      bg-red-500/10 border border-red-500/20 text-red-500 text-sm"
        >
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          {error}
        </div>
      ) : (
        <>
        {trades && trades.approved && hasRealisedActivity(trades) && (
          <div className="flex flex-col gap-3 mb-6">
            <div>
              <h2 className="text-[11px] font-semibold uppercase tracking-widest text-[var(--color-fg-muted)] mb-1">
                Realised trading performance
              </h2>
              <p className="text-[12px] text-[var(--color-fg-muted)]">
                What the executed orders did. Signal accuracy below measures
                whether a call was right after 20 days; this measures money.
              </p>
            </div>
            {/* Three buckets, never pooled. The middle one is the whole point
                of the manual/semi-auto ladder: it shows what the agent's picks
                did once a human filtered them. */}
            <div className="grid gap-3 sm:grid-cols-3">
              <TradeStatsBlock
                title="Agent"
                note="The tool decided and acted without you — the only clean read of the engine."
                stats={trades.signal_driven}
              />
              {/* "Semi" here and "approved" in the API are the same bucket. The
                  label follows the activity table's vocabulary; the key follows
                  the backend's. See lib/trade-source.ts. */}
              <TradeStatsBlock
                title="Semi"
                note="The tool recommended it, you actioned it. Biased by what you declined — measures the pair."
                stats={trades.approved}
              />
              <TradeStatsBlock
                title="Manual"
                note="You chose the ticker, without a tool recommendation. Not evidence about the signals."
                stats={trades.manual}
              />
            </div>
            <ExitBreakdown exits={trades.exits} />
            <ClosedTradesTable trades={trades.recent_closed} />
          </div>
        )}
        {!data || data.total_signals === 0 ? (
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
            <h2 className="text-[11px] font-semibold uppercase tracking-widest text-[var(--color-fg-muted)] mb-3">
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
            <h2 className="text-[11px] font-semibold uppercase tracking-widest text-[var(--color-fg-muted)] mb-3">
              Signal History
            </h2>
            <SignalHistoryTable records={signalHistory} />
          </div>

          {/* ── Section 4: By ticker table ────────────────────────────────── */}
          {data.by_ticker && data.by_ticker.length > 0 && (
            <div>
              <h2 className="text-[11px] font-semibold uppercase tracking-widest text-[var(--color-fg-muted)] mb-3">
                By Ticker
              </h2>
              <ByTickerTable rows={data.by_ticker} />
            </div>
          )}
        </div>
      )}
        </>
      )}
    </Layout>
  )
}
