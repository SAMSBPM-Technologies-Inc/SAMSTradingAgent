import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertCircle, RefreshCw } from 'lucide-react'
import { performanceApi, tradingApi } from '../lib/api'
import { formatDate } from '../lib/format'
import { useToast } from '../lib/toast-context'
import { SOURCE_LABEL, tradeSource } from '../lib/trade-source'
import type {
  AccountSummaryResponse,
  ClosedTrade,
  Holding,
  TradePerformanceResponse,
  TradeRecord,
} from '../types'
import Layout from '../components/Layout'
import LoadingSpinner from '../components/LoadingSpinner'
import BrokerPanel from '../components/BrokerPanel'
import OrderHistory, { StatusPill } from '../components/positions/OrderHistory'

/**
 * Positions — what is held, what is working, and what the closed trades did.
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

function money(v: number | null | undefined): string {
  return v == null ? '—' : usd.format(v)
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
      <div className="num mt-0.5 text-[21px] font-semibold" style={{ color: color ?? 'var(--color-fg)' }}>
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

export default function PositionsPage() {
  const navigate = useNavigate()
  const { toast, toastWithUndo } = useToast()

  const [account, setAccount] = useState<AccountSummaryResponse | null>(null)
  const [holdings, setHoldings] = useState<Holding[]>([])
  const [positions, setPositions] = useState<TradeRecord[]>([])
  const [orders, setOrders] = useState<TradeRecord[]>([])
  const [perf, setPerf] = useState<TradePerformanceResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [closing, setClosing] = useState<string | null>(null)

  const load = useCallback(async (spinner = false) => {
    if (spinner) setRefreshing(true)
    setError(null)
    try {
      const [acc, hold, pos, ord, tp] = await Promise.all([
        tradingApi.getAccount().catch(() => null),
        tradingApi.getHoldings().catch(() => null),
        tradingApi.getPositions().catch(() => null),
        tradingApi.getOrders().catch(() => null),
        performanceApi.trades().catch(() => null),
      ])
      setAccount(acc?.data ?? null)
      setHoldings(hold?.data.connected ? hold.data.holdings : [])
      setPositions(pos?.data ?? [])
      setOrders(ord?.data ?? [])
      setPerf(tp?.data ?? null)
      if (!ord) setError('Could not load your orders.')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

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
          load()
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
    <Layout>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1
            className="text-2xl font-light text-[var(--color-fg)]"
            style={{ fontFamily: 'Fraunces, Georgia, serif' }}
          >
            Positions
          </h1>
          <p className="mt-0.5 text-sm text-[var(--color-fg-muted)]">
            What is held, what is working, and what the closed trades actually returned.
          </p>
        </div>
        <button
          onClick={() => load(true)}
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

      {/* Broker session sits above everything: when it is down, every action on
          this screen is refused, and that should be the first thing you see. */}
      <BrokerPanel />

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
          <div className="mt-4 grid gap-px overflow-hidden rounded-lg border border-[var(--color-border)]
                          bg-[var(--color-border)] sm:grid-cols-2 lg:grid-cols-5">
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
                      <th scope="col" className={th}>Exit reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {closed.map((c, i) => (
                      <tr key={`${c.ticker}-${c.closed_at}-${i}`}
                          className="border-b border-[var(--color-border)]/50 last:border-0">
                        <td className="px-3 py-2.5 text-[11px] whitespace-nowrap text-[var(--color-fg-muted)]">
                          {formatDate(c.closed_at)}
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
                          <div className="flex flex-col gap-0.5">
                            <StatusPill status={c.status} />
                            {c.exit_reason && <span className="max-w-[14rem]">{c.exit_reason}</span>}
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
    </Layout>
  )
}
