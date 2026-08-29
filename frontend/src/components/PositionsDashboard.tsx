import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertCircle, RefreshCw } from 'lucide-react'
import { tradingApi } from '../lib/api'
import { formatDateTime } from '../lib/format'
import { useToast } from '../lib/toast-context'
import { SOURCE_LABEL, tradeSource } from '../lib/trade-source'
import { exitReasonLabel } from '../lib/exit-reason'
import type { ClosedTrade } from '../types'
import LoadingSpinner from './LoadingSpinner'
import OrderHistory, { StatusPill } from './positions/OrderHistory'
import { CardList, RecordCard } from './positions/RecordCard'
import { useIsCompact } from '../lib/use-media-query'
import { useTradingSettings } from '../lib/trading-context'
import { usePortfolio } from '../lib/portfolio-context'

/**
 * Positions — what is held, what is working, and what the closed trades did.
 *
 * The centre column of the Trade dashboard. It was a routed page of its own
 * until Trade and Positions merged; `/positions` now redirects to `/`, so this
 * is a component rather than a page and takes its data from `usePortfolio`
 * instead of fetching its own — the rail and the analysis overlay read the
 * same records, and fetching them here as well requested every one twice.
 *
 * Merges the old Holdings and Orders screens. They were split along a line that
 * did not mean anything to a reader: Holdings asked the broker what it holds,
 * Orders asked our own records what we sent, and answering "am I up or down"
 * needed both.
 *
 * Every number on this screen carries its own caveat, because most of them have
 * one. Gross is what a position did; net is what reached the account. A
 * commission the venue has not reported stays unknown rather than being folded
 * in at zero, which would understate cost in one direction every single time.
 */

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

/** Mirrors `TradeStatus.OPEN` on the backend: a live commitment, not a proposal. */
const OPEN_STATUSES = new Set(['PENDING', 'FILLED', 'PARTIAL'])

function money(v: number | null | undefined): string {
  return v == null ? '—' : usd.format(v)
}

/**
 * The two sentences a closed trade can tell, one under the other.
 *
 * A realised result read without the thesis behind it teaches nothing about
 * the thesis: −$1,234 on AVGO is a number until you can see that it was bought
 * on strong technicals and sold when the score fell. The entry reason leads
 * because it came first and because it is the claim the result actually tests.
 *
 * Machine codes in `exit_reason` are translated; a sentence the exit path
 * recorded passes through as written.
 */
function ClosedWhy({ trade }: { trade: ClosedTrade }) {
  const exit = exitReasonLabel(trade.exit_reason)
  if (!trade.entry_reason && !exit) return null
  return (
    <span className="block text-[11px] leading-snug">
      {trade.entry_reason && (
        <span className="block text-[var(--color-fg)]">{trade.entry_reason}</span>
      )}
      {exit && (
        <span className="mt-0.5 block text-[var(--color-fg-muted)]">{exit}</span>
      )}
    </span>
  )
}

/** Broker-statement convention: gains green, losses red in parentheses. */
function Pnl({ value, className = '' }: { value: number | null | undefined; className?: string }) {
  if (value == null) return <span className={`text-[var(--color-fg-muted)] ${className}`}>—</span>
  const loss = value < -0.005
  const gain = value > 0.005
  return (
    <span
      className={`num ${className}`}
      style={{
        color: loss ? 'var(--accent-sell)' : gain ? 'var(--accent-buy)' : 'var(--color-fg)',
      }}
    >
      {loss ? `(${usd.format(Math.abs(value))})` : usd.format(value)}
    </span>
  )
}

// ── Tiles ─────────────────────────────────────────────────────────────────────

function Tile({ label, value, note, color }: {
  label: string
  value: string
  note: string
  color?: string
}) {
  return (
    <div className="bg-[var(--color-surface)] px-3 py-2.5">
      <div className="text-[10px] uppercase tracking-[0.1em] text-[var(--color-fg-muted)]">{label}</div>
      {/* Steps down two-up on a phone so a six-figure net liquidation still
          fits its half-width column instead of wrapping mid-number. */}
      <div
        className="num mt-0.5 text-[17px] font-semibold sm:text-[21px]"
        style={{ color: color ?? 'var(--color-fg)' }}
      >
        {value}
      </div>
      <div className="mt-px text-[10.5px] leading-snug text-[var(--color-fg-muted)]">{note}</div>
    </div>
  )
}

function Section({ title, note, footnote, children }: {
  title: string
  note?: string
  footnote: string
  children: React.ReactNode
}) {
  return (
    <section className="mt-5">
      <div className="mb-2 flex flex-wrap items-baseline gap-2.5">
        <h2
          className="m-0 text-[13px] font-bold uppercase tracking-[0.06em]"
          style={{ fontFamily: 'Archivo, system-ui, sans-serif' }}
        >
          {title}
        </h2>
        {note && <span className="text-[11px] text-[var(--color-fg-muted)]">{note}</span>}
      </div>
      {children}
      <p className="mt-1.5 text-[10.5px] leading-relaxed text-[var(--color-fg-muted)]">{footnote}</p>
    </section>
  )
}

function TableShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]">
      <div className="overflow-x-auto">{children}</div>
    </div>
  )
}

const th = 'px-3 py-2.5 text-left font-semibold'
const thR = 'px-3 py-2.5 text-right font-semibold'

// ── Page ──────────────────────────────────────────────────────────────────────

export default function PositionsDashboard() {
  const navigate = useNavigate()
  const { toast, toastWithUndo } = useToast()

  const [closing, setClosing] = useState<string | null>(null)
  // Below md the record tables are 46-52rem wide in a 356px column, hiding
  // more than half of every row behind an invisible scroller. Cards instead —
  // and rendered *instead of*, not alongside, so no wide table exists there.
  const compact = useIsCompact()
  // One copy of the balances, shared with the account strip above.
  const { account } = useTradingSettings()
  // One copy of the portfolio, shared with the watchlist rail and the analysis
  // overlay. Refresh re-reads for all three, so they cannot disagree about what
  // is held — which is the failure a second local fetch invites.
  const { holdings, positions, orders, perf, loading, refreshing, error, reload } = usePortfolio()

  const stats = perf?.all ?? null

  /**
   * Broker holdings joined to our own record of why each one exists.
   *
   * The broker is the authority on *what* is held — reconcile writes our
   * records from it, not the reverse — so this iterates holdings and looks up
   * the trade, never the other way round. A position the broker reports and we
   * have no record of still appears, with an unknown source, which is exactly
   * the case worth seeing.
   */
  const openRows = useMemo(() => holdings
    .filter((h) => h.qty !== 0)
    .map((h) => ({
      holding: h,
      trade: positions.find((p) => p.ticker === h.ticker && p.closed_at == null) ?? null,
    })), [holdings, positions])

  /**
   * The agent's own open entries.
   *
   * Deliberately read from our trade records rather than from broker holdings:
   * the question here is "what did the agent decide", and a holding carries no
   * decision. A position the agent opened and a position you opened look
   * identical at the broker.
   *
   * `PROPOSED` is not among these — it commits nothing and lives in the
   * approvals queue — and neither is `SKIPPED`, which is a refusal, not a
   * position.
   */
  const agentRows = useMemo(
    () => positions.filter(
      (p) => p.closed_at == null
        && OPEN_STATUSES.has(p.status)
        && tradeSource(p.signal_type) === 'agent',
    ),
    [positions],
  )

  const closePosition = (ticker: string) => {
    // Closing sends a real order, so it gets an undo window rather than a
    // confirm dialog — the action is reversible right up until it is sent.
    toastWithUndo(
      `Closing ${ticker}…`,
      async () => {
        setClosing(ticker)
        try {
          await tradingApi.closePosition(ticker)
          toast(`Close order submitted for ${ticker}.`, 'success')
          void reload()
        } catch (err: unknown) {
          const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
          toast(detail ?? `Could not close ${ticker}.`, 'error')
        } finally {
          setClosing(null)
        }
      },
      () => toast(`Kept ${ticker}.`, 'info'),
    )
  }

  const closed: ClosedTrade[] = perf?.recent_closed ?? []

  return (
    <>
      <div className="mb-2 flex flex-wrap items-start justify-between gap-3">
        <h2 className="label-micro">Positions</h2>
        <button
          onClick={() => reload(true)}
          disabled={refreshing || loading}
          className="btn-secondary flex-shrink-0"
        >
          <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} aria-hidden="true" />
          Refresh
        </button>
      </div>

      {error && (
        <div
          role="alert"
          className="mb-4 flex items-center gap-3 rounded-lg border px-4 py-3 text-sm"
          style={{ background: 'var(--tint-sell)', borderColor: 'var(--accent-sell)', color: 'var(--accent-sell)' }}
        >
          <AlertCircle className="h-4 w-4 flex-shrink-0" aria-hidden="true" />
          {error}
        </div>
      )}

      {/* Broker session is not repeated here: the dashboard's right rail carries
          it as a small box, and stating "IB Gateway disconnected" twice on one
          screen makes neither copy more believable. */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <LoadingSpinner size="lg" />
        </div>
      ) : (
        <>
          {/* ── Tiles ──────────────────────────────────────────────────────
              Day P&L is not among these deliberately: the broker summary this
              screen reads carries no day-open figure, and a "day" number
              derived from something else would be a different quantity wearing
              the same label. */}
          {/* Two-up on a phone rather than one. Stacked singly these five tiles
              were 850px of chrome before the first holding, putting "what do I
              actually own" a screen and a half below the fold on the screen
              that exists to answer it. */}
          <div className="mt-4 grid grid-cols-2 gap-px overflow-hidden rounded-lg
                          border border-[var(--color-border)] bg-[var(--color-border)]
                          lg:grid-cols-5">
            <Tile
              label="Net liquidation"
              value={money(account?.net_liquidation)}
              note={account?.connected ? `Account ${account.account_id || '—'}` : 'Broker disconnected'}
            />
            <Tile
              label="Unrealised"
              value={money(account?.unrealized_pnl)}
              color={account?.unrealized_pnl == null ? undefined
                : account.unrealized_pnl < -0.005 ? 'var(--accent-sell)'
                  : account.unrealized_pnl > 0.005 ? 'var(--accent-buy)' : undefined}
              note={`${openRows.length} open ${openRows.length === 1 ? 'position' : 'positions'}`}
            />
            <Tile
              label="Realised net"
              value={money(stats?.realised_pnl_net)}
              color={stats?.realised_pnl_net == null ? undefined
                : stats.realised_pnl_net < -0.005 ? 'var(--accent-sell)'
                  : stats.realised_pnl_net > 0.005 ? 'var(--accent-buy)' : undefined}
              note={stats
                ? `After commission · ${stats.netted} of ${stats.closed} closed trades nettable`
                : 'No closed trades yet'}
            />
            <Tile
              label="Win rate (net)"
              value={stats?.win_rate_net != null ? `${Math.round(stats.win_rate_net * 100)}%` : '—'}
              note={stats
                ? stats.netted < 30
                  ? `Thin — only ${stats.netted} nettable trades`
                  : `Across ${stats.netted} nettable trades`
                : 'No closed trades yet'}
            />
            <Tile
              label="Fees paid"
              value={money(stats?.commission_paid)}
              note={stats && stats.wins_lost_to_fees > 0
                ? `${stats.wins_lost_to_fees} ${stats.wins_lost_to_fees === 1 ? 'trade' : 'trades'} profitable before fees, not after`
                : 'Commission on closed trades'}
            />
          </div>

          {stats && stats.net_unknown > 0 && (
            <p className="mt-2 rounded-lg px-3 py-2 text-[11px] leading-relaxed"
               style={{ background: 'var(--tint-hold)', color: 'var(--accent-hold)' }}>
              {stats.net_unknown} closed {stats.net_unknown === 1 ? 'trade has' : 'trades have'} no
              usable commission figure and {stats.net_unknown === 1 ? 'is' : 'are'} excluded from every
              net number above — reported rather than counted at zero, which would understate cost.
              Trades closed before 1.6.0 can never be netted: IB only serves the current session.
            </p>
          )}

          {/* ── Agent positions ────────────────────────────────────────────
              What the agent decided, as distinct from what is held. These are
              our own trade records, so a row here is a decision with a reason
              behind it; the Open positions table below is the broker's account
              of the same money and is the authority on quantity. */}
          <Section
            title="Agent positions"
            note={`${agentRows.length} open`}
            footnote="Entries the agent placed unattended from its own signals. Proposals awaiting your approval are not here — nothing is committed until you accept one — and neither are skipped evaluations, which are refusals rather than positions."
          >
            {agentRows.length === 0 ? (
              <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]
                              p-6 text-center text-sm text-[var(--color-fg-muted)]">
                The agent holds nothing right now.
              </div>
            ) : compact ? (
              <CardList>
                {agentRows.map((t) => (
                  <RecordCard
                    key={t.id}
                    title={t.ticker}
                    onTitleClick={() => navigate(`/ticker/${t.ticker}`)}
                    badges={<StatusPill status={t.status} />}
                    fields={[
                      { label: 'Qty', value: (t.filled_qty ?? t.qty).toLocaleString() },
                      { label: 'Entry', value: money(t.entry_price ?? t.limit_price) },
                      {
                        label: 'Stop',
                        value: <span style={{ color: 'var(--accent-sell)' }}>{money(t.stop_loss)}</span>,
                      },
                      {
                        label: 'Target',
                        value: <span style={{ color: 'var(--accent-buy)' }}>{money(t.take_profit)}</span>,
                      },
                      { label: 'Opened', value: formatDateTime(t.opened_at) },
                      { label: 'Score', value: t.signal_score != null ? `${Math.round(t.signal_score * 100)}` : '—' },
                    ]}
                  />
                ))}
              </CardList>
            ) : (
              <TableShell>
                <table className="w-full min-w-[42rem] text-sm">
                  <thead>
                    <tr className="border-b border-[var(--color-border)] text-[10.5px] uppercase
                                   tracking-widest text-[var(--color-fg-muted)]">
                      <th scope="col" className={th}>Ticker</th>
                      <th scope="col" className={th}>Status</th>
                      <th scope="col" className={thR}>Qty</th>
                      <th scope="col" className={thR}>Entry</th>
                      <th scope="col" className={thR}>Stop</th>
                      <th scope="col" className={thR}>Target</th>
                      <th scope="col" className={thR}>Score</th>
                      <th scope="col" className={th}>Opened</th>
                    </tr>
                  </thead>
                  <tbody>
                    {agentRows.map((t) => (
                      <tr key={t.id} className="border-b border-[var(--color-border)]/50 last:border-0">
                        <td className="px-3 py-2.5">
                          <button
                            onClick={() => navigate(`/ticker/${t.ticker}`)}
                            className="num font-semibold text-[var(--color-fg)] hover:text-brand-500"
                          >
                            {t.ticker}
                          </button>
                        </td>
                        <td className="px-3 py-2.5"><StatusPill status={t.status} /></td>
                        <td className="num px-3 py-2.5 text-right">
                          {(t.filled_qty ?? t.qty).toLocaleString()}
                        </td>
                        <td className="num px-3 py-2.5 text-right text-[var(--color-fg-muted)]">
                          {money(t.entry_price ?? t.limit_price)}
                        </td>
                        <td className="num px-3 py-2.5 text-right" style={{ color: 'var(--accent-sell)' }}>
                          {money(t.stop_loss)}
                        </td>
                        <td className="num px-3 py-2.5 text-right" style={{ color: 'var(--accent-buy)' }}>
                          {money(t.take_profit)}
                        </td>
                        <td className="num px-3 py-2.5 text-right text-[var(--color-fg-muted)]">
                          {t.signal_score != null ? Math.round(t.signal_score * 100) : '—'}
                        </td>
                        <td className="px-3 py-2.5 text-[11px] text-[var(--color-fg-muted)]">
                          {formatDateTime(t.opened_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableShell>
            )}
          </Section>

          {/* ── Open positions ─────────────────────────────────────────── */}
          <Section
            title="Open positions"
            note={`${openRows.length} held`}
            footnote="Source records who decided. Agent placed it unattended, Approved means the agent proposed and you accepted, You means you chose the ticker. Performance keeps the three apart — a set of the agent's picks that a human filtered is not a clean measure of the agent. Quantities come from the broker, not our records: if the two disagree, the broker is right."
          >
            {openRows.length === 0 ? (
              <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]
                              p-8 text-center text-sm text-[var(--color-fg-muted)]">
                {account?.connected ? 'No open positions.' : 'Broker disconnected — positions unavailable.'}
              </div>
            ) : compact ? (
              <CardList>
                {openRows.map(({ holding: h, trade: t }) => (
                  <RecordCard
                    key={h.ticker}
                    title={h.ticker}
                    onTitleClick={() => navigate(`/ticker/${h.ticker}`)}
                    badges={
                      <span className="rounded bg-[var(--color-hover)] px-1.5 py-0.5 text-[10px]
                                       text-[var(--color-fg-muted)]">
                        {t ? SOURCE_LABEL[tradeSource(t.signal_type)] : 'No record'}
                      </span>
                    }
                    fields={[
                      { label: 'Qty', value: h.qty.toLocaleString() },
                      { label: 'Avg cost', value: money(h.avg_cost) },
                      { label: 'Value', value: money(h.market_value) },
                      { label: 'Unrealised', value: <Pnl value={h.unrealized_pnl} /> },
                      {
                        label: 'Stop',
                        value: <span style={{ color: 'var(--accent-sell)' }}>{money(t?.stop_loss)}</span>,
                      },
                      {
                        label: 'Target',
                        value: <span style={{ color: 'var(--accent-buy)' }}>{money(t?.take_profit)}</span>,
                      },
                    ]}
                    action={
                      <button
                        onClick={() => closePosition(h.ticker)}
                        disabled={closing === h.ticker}
                        className="btn-secondary w-full"
                      >
                        {closing === h.ticker ? <LoadingSpinner size="sm" /> : `Close ${h.ticker}`}
                      </button>
                    }
                  />
                ))}
              </CardList>
            ) : (
              <TableShell>
                <table className="w-full min-w-[46rem] text-sm">
                  <thead>
                    <tr className="border-b border-[var(--color-border)] text-[10.5px] uppercase
                                   tracking-widest text-[var(--color-fg-muted)]">
                      <th scope="col" className={th}>Ticker</th>
                      <th scope="col" className={th}>Source</th>
                      <th scope="col" className={thR}>Qty</th>
                      <th scope="col" className={thR}>Avg cost</th>
                      <th scope="col" className={thR}>Value</th>
                      <th scope="col" className={thR}>Unrealised</th>
                      <th scope="col" className={thR}>Stop</th>
                      <th scope="col" className={thR}>Target</th>
                      <th scope="col" className={thR}><span className="sr-only">Actions</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {openRows.map(({ holding: h, trade: t }) => (
                      <tr key={h.ticker} className="border-b border-[var(--color-border)]/50 last:border-0">
                        <td className="px-3 py-2.5">
                          <button
                            onClick={() => navigate(`/ticker/${h.ticker}`)}
                            className="num font-semibold text-[var(--color-fg)] hover:text-brand-500"
                          >
                            {h.ticker}
                          </button>
                        </td>
                        <td className="px-3 py-2.5 text-[11px] text-[var(--color-fg-muted)]">
                          {t ? SOURCE_LABEL[tradeSource(t.signal_type)] : 'No record'}
                        </td>
                        <td className="num px-3 py-2.5 text-right">{h.qty.toLocaleString()}</td>
                        <td className="num px-3 py-2.5 text-right text-[var(--color-fg-muted)]">
                          {money(h.avg_cost)}
                        </td>
                        <td className="num px-3 py-2.5 text-right">{money(h.market_value)}</td>
                        <td className="px-3 py-2.5 text-right"><Pnl value={h.unrealized_pnl} /></td>
                        <td className="num px-3 py-2.5 text-right" style={{ color: 'var(--accent-sell)' }}>
                          {money(t?.stop_loss)}
                        </td>
                        <td className="num px-3 py-2.5 text-right" style={{ color: 'var(--accent-buy)' }}>
                          {money(t?.take_profit)}
                        </td>
                        <td className="px-3 py-2.5 text-right">
                          <button
                            onClick={() => closePosition(h.ticker)}
                            disabled={closing === h.ticker}
                            className="chip"
                          >
                            {closing === h.ticker ? <LoadingSpinner size="sm" /> : 'Close'}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableShell>
            )}
          </Section>

          {/* ── Closed trades ──────────────────────────────────────────── */}
          <Section
            title="Closed trades"
            note={stats ? `${stats.closed} closed` : undefined}
            footnote="Gross is what the position did; net is what reached the account. On a small account the gap is not a rounding detail — a $200 entry pays the same fixed ticket as a $20,000 one, so a round trip can cost 0.5% against 0.005%. A dash under Net means the venue never reported a complete fee total for that trade; it is excluded from the net figures above rather than counted as free."
          >
            {closed.length === 0 ? (
              <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]
                              p-8 text-center text-sm text-[var(--color-fg-muted)]">
                No closed trades yet.
              </div>
            ) : compact ? (
              <CardList>
                {closed.map((c, i) => (
                  <RecordCard
                    key={`${c.ticker}-${c.closed_at}-${i}`}
                    title={c.ticker}
                    onTitleClick={() => navigate(`/ticker/${c.ticker}`)}
                    badges={
                      <>
                        <StatusPill status={c.status} />
                        <span className="rounded bg-[var(--color-hover)] px-1.5 py-0.5 text-[10px]
                                         text-[var(--color-fg-muted)]">
                          {SOURCE_LABEL[tradeSource(c.signal_type)]}
                        </span>
                        {c.scale_ins > 0 && (
                          <span className="text-[10px] text-[var(--color-fg-muted)]">
                            +{c.scale_ins} {c.scale_ins === 1 ? 'add' : 'adds'}
                          </span>
                        )}
                      </>
                    }
                    fields={[
                      { label: 'Closed', value: formatDateTime(c.closed_at) },
                      { label: 'Qty', value: c.qty ?? '—' },
                      { label: 'Entry', value: money(c.entry_price) },
                      { label: 'Exit', value: money(c.exit_price) },
                      { label: 'Gross', value: <Pnl value={c.pnl} /> },
                      {
                        label: 'Fees',
                        // An incomplete total is a floor, not a figure.
                        value: c.commission_complete ? money(c.commission_paid) : '—',
                      },
                      {
                        label: 'Net',
                        value: c.commission_complete
                          ? <Pnl value={c.pnl_net} className="font-semibold" />
                          : <span className="text-[var(--color-fg-muted)]">—</span>,
                      },
                    ]}
                    note={<ClosedWhy trade={c} />}
                  />
                ))}
              </CardList>
            ) : (
              <TableShell>
                <table className="w-full min-w-[52rem] text-sm">
                  <thead>
                    <tr className="border-b border-[var(--color-border)] text-[10.5px] uppercase
                                   tracking-widest text-[var(--color-fg-muted)]">
                      <th scope="col" className={th}>Closed</th>
                      <th scope="col" className={th}>Ticker</th>
                      <th scope="col" className={th}>Source</th>
                      <th scope="col" className={thR}>Qty</th>
                      <th scope="col" className={thR}>Entry</th>
                      <th scope="col" className={thR}>Exit</th>
                      <th scope="col" className={thR}>Gross</th>
                      <th scope="col" className={thR}>Fees</th>
                      <th scope="col" className={thR}>Net</th>
                      {/* Was "Exit reason". It now carries both halves —
                          why the position was opened and why it ended — and a
                          header naming only the second would hide the first. */}
                      <th scope="col" className={th}>Why</th>
                    </tr>
                  </thead>
                  <tbody>
                    {closed.map((c, i) => (
                      <tr key={`${c.ticker}-${c.closed_at}-${i}`}
                          className="border-b border-[var(--color-border)]/50 last:border-0">
                        <td className="px-3 py-2.5 text-[11px] whitespace-nowrap text-[var(--color-fg-muted)]">
                          {formatDateTime(c.closed_at)}
                        </td>
                        <td className="px-3 py-2.5">
                          <button
                            onClick={() => navigate(`/ticker/${c.ticker}`)}
                            className="num font-semibold text-[var(--color-fg)] hover:text-brand-500"
                          >
                            {c.ticker}
                          </button>
                          {c.scale_ins > 0 && (
                            <span className="ml-1.5 text-[10px] text-[var(--color-fg-muted)]">
                              +{c.scale_ins} {c.scale_ins === 1 ? 'add' : 'adds'}
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2.5 text-[11px] text-[var(--color-fg-muted)]">
                          {SOURCE_LABEL[tradeSource(c.signal_type)]}
                        </td>
                        <td className="num px-3 py-2.5 text-right">{c.qty ?? '—'}</td>
                        <td className="num px-3 py-2.5 text-right text-[var(--color-fg-muted)]">
                          {money(c.entry_price)}
                        </td>
                        <td className="num px-3 py-2.5 text-right text-[var(--color-fg-muted)]">
                          {money(c.exit_price)}
                        </td>
                        <td className="px-3 py-2.5 text-right"><Pnl value={c.pnl} /></td>
                        <td className="num px-3 py-2.5 text-right text-[var(--color-fg-muted)]">
                          {/* An incomplete total is a floor, not a figure — show
                              gross only rather than a number that reads exact. */}
                          {c.commission_complete ? money(c.commission_paid) : '—'}
                        </td>
                        <td className="px-3 py-2.5 text-right">
                          {c.commission_complete
                            ? <Pnl value={c.pnl_net} className="font-semibold" />
                            : <span className="text-[var(--color-fg-muted)]" title="No complete fee total from the venue">—</span>}
                        </td>
                        <td className="px-3 py-2.5 text-[11px] text-[var(--color-fg-muted)]">
                          <div className="flex flex-col gap-0.5 max-w-[18rem]">
                            <StatusPill status={c.status} />
                            <ClosedWhy trade={c} />
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableShell>
            )}
          </Section>

          {/* ── Order history ──────────────────────────────────────────── */}
          <Section
            title="Order history"
            note="every attempt, including refusals"
            footnote="A skip is a decision worth seeing: it is a guard refusing an order the agent wanted to place. Proposed and Declined never held a position slot — a proposal commits nothing."
          >
            <OrderHistory orders={orders} />
          </Section>
        </>
      )}
    </>
  )
}
