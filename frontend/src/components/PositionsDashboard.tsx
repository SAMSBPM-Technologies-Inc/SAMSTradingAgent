import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertCircle, RefreshCw } from 'lucide-react'
import { tradingApi } from '../lib/api'
import { formatDateTime } from '../lib/format'
import { useToast } from '../lib/toast-context'
import { SOURCE_LABEL, tradeSource } from '../lib/trade-source'
import { exitReasonLabel } from '../lib/exit-reason'
import type { ClosedTrade, TradeStats } from '../types'
import LoadingSpinner from './LoadingSpinner'
import ActivityTable, { StatusPill } from './positions/ActivityTable'
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
/** Whole dollars. A six-figure balance does not need its cents on a tile. */
const usd0 = new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', maximumFractionDigits: 0,
})

function money(v: number | null | undefined): string {
  return v == null ? '—' : usd.format(v)
}

function money0(v: number | null | undefined): string {
  return v == null ? '—' : usd0.format(v)
}

/** A fraction as a signed percentage. `null` stays a dash — never 0%. */
function pct(v: number | null | undefined, digits = 1): string {
  if (v == null) return '—'
  return `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v * 100).toFixed(digits)}%`
}

/** Unsigned, for shares-of-a-whole like cash weight, where a sign means nothing. */
function share(v: number | null | undefined): string {
  return v == null ? '—' : `${Math.round(v * 100)}%`
}

/**
 * One rule for gain/loss colour, so the places that need it cannot drift.
 *
 * `eps` is the width of the dead band around zero, and it is a parameter
 * because the two callers work in different units: half a cent is nothing on a
 * dollar figure, while 0.005 as a *fraction* is half a percent and painting
 * that neutral would grey out a real move.
 */
function pnlColor(v: number | null | undefined, eps = 0.005): string | undefined {
  if (v == null) return undefined
  if (v < -eps) return 'var(--accent-sell)'
  if (v > eps) return 'var(--accent-buy)'
  return undefined
}

/** The same, for values that are fractions rather than dollars. */
const rateColor = (v: number | null | undefined) => pnlColor(v, 0.00005)

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

/**
 * `delta` is the percentage that makes the dollar figure mean something.
 *
 * A dollar figure alone cannot be judged — $400 up is a triumph on $4,000 and
 * a rounding error on $400,000 — so the tiles that have an honest denominator
 * carry the rate beside the amount, and the note underneath says what the
 * denominator was. Tiles with no honest denominator (net liquidation, fees)
 * pass nothing rather than inventing one.
 */
function Tile({ label, value, note, color, delta }: {
  label: string
  value: string
  note: string
  color?: string
  delta?: number | null
}) {
  return (
    <div className="bg-[var(--color-surface)] px-3 py-2.5">
      <div className="text-[10px] uppercase tracking-[0.1em] text-[var(--color-fg-muted)]">{label}</div>
      {/* Steps down two-up on a phone so a six-figure net liquidation still
          fits its half-width column instead of wrapping mid-number. */}
      <div className="mt-0.5 flex flex-wrap items-baseline gap-x-1.5">
        <span
          className="num text-[17px] font-semibold sm:text-[21px]"
          style={{ color: color ?? 'var(--color-fg)' }}
        >
          {value}
        </span>
        {delta != null && (
          <span className="num text-[12px] font-semibold" style={{ color: rateColor(delta) }}>
            {pct(delta)}
          </span>
        )}
      </div>
      <div className="mt-px text-[10.5px] leading-snug text-[var(--color-fg-muted)]">{note}</div>
    </div>
  )
}

// ── Head to head ──────────────────────────────────────────────────────────────

/**
 * The tool's picks against yours.
 *
 * Deliberately a *fourth* reading and not a replacement for the three buckets
 * on the Performance page. Those answer "does the engine work", and pooling
 * auto with semi would ruin that — half the semi bucket is whatever the trader
 * chose to approve. This answers a different question, "whose ideas were
 * better", and for that question who pressed the button is not part of it.
 *
 * So the split is printed under the agent column rather than hidden: a reader
 * who wants the clean read of the engine can see the unattended half on its
 * own, and is told where to get the full version.
 *
 * Two rules keep it from becoming a scoreboard that lies:
 *
 *  - **Rates, not dollars, decide it.** The agent and the trader size
 *    positions differently, so comparing totals would mostly measure who
 *    committed more money.
 *  - **Nothing is declared on a thin sample.** Under `MIN_MEANINGFUL` a side
 *    is marked provisional and the verdict line says the count out loud
 *    instead of naming a winner. Three lucky trades are not a track record,
 *    and a dashboard that says otherwise gets believed.
 */
const MIN_MEANINGFUL = 30

interface Side { key: string; label: string; blurb: string; stats: TradeStats | null }

/** Which way is up for a metric — a lower fee bill is not a better trader. */
type Better = 'high' | 'none'

function Metric({ label, hint, a, b, render, better = 'high' }: {
  label: string
  hint?: string
  a: number | null | undefined
  b: number | null | undefined
  render: (v: number | null | undefined) => React.ReactNode
  better?: Better
}) {
  // Only a comparison where both sides actually have a number is a comparison.
  const lead = better === 'none' || a == null || b == null || a === b
    ? null
    : a > b ? 'a' : 'b'
  const cell = (v: number | null | undefined, side: 'a' | 'b') => (
    <td
      className="px-3 py-2 text-right"
      style={lead === side ? { background: 'var(--tint-buy)' } : undefined}
    >
      <span className={lead === side ? 'font-semibold' : ''}>{render(v)}</span>
    </td>
  )
  return (
    <tr className="border-b border-[var(--color-border)]/50 last:border-0">
      <th scope="row" className="px-3 py-2 text-left font-normal text-[var(--color-fg-muted)]">
        {label}
        {hint && <span className="mt-px block text-[10px] leading-snug opacity-80">{hint}</span>}
      </th>
      {cell(a, 'a')}
      {cell(b, 'b')}
    </tr>
  )
}

function HeadToHead({ agent, manual, autoOnly, semi }: {
  agent: TradeStats | null
  manual: TradeStats | null
  autoOnly: TradeStats | null
  semi: TradeStats | null
}) {
  const sides: [Side, Side] = [
    { key: 'agent', label: 'Agent', blurb: 'Auto + semi — the tool picked it', stats: agent },
    { key: 'manual', label: 'You', blurb: 'You picked the ticker yourself', stats: manual },
  ]
  const [A, B] = sides

  const an = A.stats?.netted ?? 0
  const bn = B.stats?.netted ?? 0
  const ar = A.stats?.return_on_capital_net ?? null
  const br = B.stats?.return_on_capital_net ?? null

  /**
   * One sentence, and it refuses to name a winner more confidently than the
   * evidence allows. The three cases are genuinely different: nothing to
   * compare, a gap on too few trades, and a gap worth reading.
   */
  const verdict = (() => {
    if (an === 0 || bn === 0) {
      const missing = an === 0 ? A : B
      const other = an === 0 ? B : A
      const otherN = an === 0 ? bn : an
      return otherN === 0
        ? 'No closed trades with a complete fee total on either side yet — nothing to compare.'
        : `No nettable ${missing.key === 'agent' ? 'agent' : 'manual'} trades yet, so there is nothing to `
          + `hold ${other.label === 'You' ? 'your' : 'the agent’s'} ${otherN} against.`
    }
    if (ar == null || br == null) return 'One side has no return on capital yet — no comparison to draw.'
    const gap = Math.abs(ar - br) * 100
    const leader = ar > br ? A : B
    const thin = an < MIN_MEANINGFUL || bn < MIN_MEANINGFUL
    const head = ar === br
      ? 'Dead level on return on capital'
      : `${leader.label === 'You' ? 'You are' : 'The agent is'} ahead by ${gap.toFixed(1)} points of return on capital`
    return thin
      ? `${head} — on ${an} agent and ${bn} manual nettable trades. Far too few to mean anything; `
        + 'read it as a tally, not a verdict.'
      : `${head}, across ${an} agent and ${bn} manual nettable trades.`
  })()

  // Not `TableShell`: that puts everything inside the horizontal scroller, and
  // the two paragraphs below are prose that must wrap to the column rather
  // than slide sideways with a 30rem-wide table. Only the table scrolls.
  return (
    <div className="overflow-hidden rounded-lg border border-[var(--color-border)]
                    bg-[var(--color-surface)]">
      <div className="overflow-x-auto">
      <table className="w-full min-w-[30rem] text-sm">
        <caption className="sr-only">
          Agent-originated trades compared with trades you chose yourself
        </caption>
        <thead>
          <tr className="border-b border-[var(--color-border)] text-left">
            <th scope="col" className="px-3 py-2.5 text-[10.5px] uppercase tracking-widest
                                       text-[var(--color-fg-muted)]">
              Metric
            </th>
            {sides.map((s) => (
              <th key={s.key} scope="col" className="px-3 py-2.5 text-right">
                <span className="block text-[13px] font-bold">{s.label}</span>
                <span className="block text-[10px] font-normal leading-snug text-[var(--color-fg-muted)]">
                  {s.blurb}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {/* Rate first: it is the row that actually decides the thing. */}
          <Metric
            label="Return on capital"
            hint="Net P&L over the money each side turned over"
            a={ar} b={br}
            render={(v) => <span className="num" style={{ color: rateColor(v) }}>{pct(v)}</span>}
          />
          <Metric
            label="Realised net"
            hint="After commission — totals, so sizing shows up here"
            a={A.stats?.realised_pnl_net} b={B.stats?.realised_pnl_net}
            render={(v) => <Pnl value={v} />}
          />
          <Metric
            label="Win rate (net)"
            a={A.stats?.win_rate_net} b={B.stats?.win_rate_net}
            render={(v) => <span className="num">{v == null ? '—' : `${Math.round(v * 100)}%`}</span>}
          />
          {/* Alpha is the honest version of the whole comparison — it asks
              whether either side beat simply holding the index — so it is
              shown whenever either side has one, even though on a young
              account that is usually neither. */}
          {((A.stats?.alpha_measured ?? 0) > 0 || (B.stats?.alpha_measured ?? 0) > 0) && (
            <Metric
              label={`vs ${A.stats?.benchmark_ticker || B.stats?.benchmark_ticker || 'benchmark'}`}
              hint="Average alpha — return beyond what holding the index paid"
              a={A.stats?.avg_alpha} b={B.stats?.avg_alpha}
              render={(v) => <span className="num" style={{ color: rateColor(v) }}>{pct(v)}</span>}
            />
          )}
          <Metric
            label="Avg win"
            a={A.stats?.avg_win} b={B.stats?.avg_win}
            render={(v) => <Pnl value={v} />}
          />
          <Metric
            label="Avg loss"
            // Both are negative, so "higher is better" is the right test:
            // −$40 beats −$300.
            a={A.stats?.avg_loss} b={B.stats?.avg_loss}
            render={(v) => <Pnl value={v} />}
          />
          <Metric
            label="Closed trades"
            // Not the same denominator as the rates above, which count only
            // trades with a complete fee total. The line below the table names
            // those counts, so the two are never mistaken for each other.
            hint="All of them — the rates above use only the nettable ones"
            better="none"
            a={A.stats?.closed} b={B.stats?.closed}
            render={(v) => <span className="num">{v ?? 0}</span>}
          />
          <Metric
            label="Fees paid"
            better="none"
            a={A.stats?.commission_paid} b={B.stats?.commission_paid}
            render={(v) => <span className="num text-[var(--color-fg-muted)]">{money(v)}</span>}
          />
          <Metric
            label="Capital deployed"
            hint="Turned over, not held — sequential trades each count"
            better="none"
            a={A.stats?.capital_deployed_net} b={B.stats?.capital_deployed_net}
            render={(v) => <span className="num text-[var(--color-fg-muted)]">{money0(v)}</span>}
          />
        </tbody>
      </table>
      </div>

      <div className="border-t border-[var(--color-border)] px-3 py-2.5">
        <p className="text-[11.5px] leading-relaxed">{verdict}</p>
        {/* The pooling, shown rather than hidden. The agent column mixes trades
            the tool placed unattended with ones you approved, and only the
            first half is a clean read of the engine. */}
        <p className="mt-1.5 text-[10.5px] leading-relaxed text-[var(--color-fg-muted)]">
          The agent column is {autoOnly?.netted ?? 0} unattended and {semi?.netted ?? 0} you
          approved{autoOnly?.return_on_capital_net != null && (
            <> — unattended alone returned <span className="num" style={{ color: rateColor(autoOnly.return_on_capital_net) }}>
              {pct(autoOnly.return_on_capital_net)}
            </span></>
          )}. Only the unattended half is a clean measure of the engine; what you approved is
          filtered by what you declined, so it scores the pair. Performance keeps all three apart.
        </p>
      </div>
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
   * What the open book cost, and what it is up or down as a rate.
   *
   * Cost basis comes from the holdings rather than our own trade records for
   * the same reason the table iterates holdings: the broker is the authority
   * on what is held, and `avg_cost` there already blends every scale-in.
   *
   * The rate divides the broker's unrealised total by that basis. Both come
   * from the same refresh, so they describe the same instant — mixing a fresh
   * P&L with a stale basis is the one way this number could lie.
   */
  const openCost = useMemo(
    () => openRows.reduce((sum, { holding: h }) => sum + Math.abs(h.qty * h.avg_cost), 0),
    [openRows],
  )
  const unrealised = account?.unrealized_pnl ?? null
  const unrealisedPct = unrealised != null && openCost > 0 ? unrealised / openCost : null

  // Cash as a share of the account, which is the form the question is asked in
  // — "how much of this is still dry powder" rather than "how many dollars".
  const netLiq = account?.net_liquidation ?? null
  const cashShare = account?.total_cash != null && netLiq != null && netLiq > 0
    ? account.total_cash / netLiq
    : null

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

  // `agent_originated` is served by the API; read defensively anyway so a
  // client running ahead of a deploy degrades to hiding the panel rather than
  // throwing on the screen that shows the positions.
  const agentStats = perf?.agent_originated ?? null
  const manualStats = perf?.manual ?? null
  // Nothing to weigh until at least one side has actually closed something.
  const hasContest = (agentStats?.closed ?? 0) + (manualStats?.closed ?? 0) > 0

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
          {/* Two rows of four, and the split is the point: the top row is the
              account as it stands right now, the bottom is the record of what
              trading it has done. They are different questions and were
              previously interleaved. */}
          <div className="mt-4 grid grid-cols-2 gap-px overflow-hidden rounded-lg
                          border border-[var(--color-border)] bg-[var(--color-border)]
                          sm:grid-cols-4">
            <Tile
              label="Net liquidation"
              value={money0(netLiq)}
              note={account?.connected ? `Account ${account.account_id || '—'}` : 'Broker disconnected'}
            />
            <Tile
              label="Invested"
              value={money0(account?.gross_position_value)}
              note={openCost > 0
                ? `${money0(openCost)} cost · ${openRows.length} ${openRows.length === 1 ? 'position' : 'positions'}`
                : 'Nothing held'}
            />
            <Tile
              label="Cash"
              value={money0(account?.total_cash)}
              note={cashShare != null
                ? `${share(cashShare)} of account · ${money0(account?.buying_power)} buying power`
                : 'Broker disconnected'}
            />
            <Tile
              label="Unrealised"
              value={money(unrealised)}
              color={pnlColor(unrealised)}
              delta={unrealisedPct}
              note={openCost > 0
                ? `On ${money0(openCost)} of cost`
                : `${openRows.length} open ${openRows.length === 1 ? 'position' : 'positions'}`}
            />
            <Tile
              label="Realised net"
              value={money(stats?.realised_pnl_net)}
              color={pnlColor(stats?.realised_pnl_net)}
              delta={stats?.return_on_capital_net}
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
              label="Capital deployed"
              value={money0(stats?.capital_deployed_net)}
              // Says what the rate above was measured against, so it can be
              // checked rather than believed — and names it as turnover, since
              // a reader will otherwise take it for the account's size.
              note={stats?.capital_deployed_net != null
                ? `Turned over across ${stats.netted} closed ${stats.netted === 1 ? 'trade' : 'trades'} — not account size`
                : 'No nettable closed trades yet'}
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

          {/* ── Activity ───────────────────────────────────────────────────
              Pending and recent actions, in one place. This was two tables —
              "Agent positions" for the agent's open entries and "Order history"
              for everything else — which split one audit trail along a line
              that answered no question anybody asks. It leads the screen
              because the top of it is the part waiting on the reader. */}
          <Section
            title="Activity"
            note="pending and recent actions"
            footnote="Every attempt, including the refusals. A skip is a guard refusing an order the agent wanted to place, and worth seeing. Proposed and Declined never held a position slot — a proposal commits nothing until you accept it. Open a transaction for the full record and the rest of that ticker's history."
          >
            <ActivityTable orders={orders} onProposalsChanged={() => void reload()} />
          </Section>
          {/* ── Open positions ─────────────────────────────────────────── */}
          <Section
            title="Open positions"
            note={`${openRows.length} held`}
            footnote="Source records who decided. Agent means the tool decided and acted without you, Semi means it recommended and you actioned it, Manual means you chose the ticker yourself. Performance keeps the three apart — a set of the agent's picks that a human filtered is not a clean measure of the agent. Quantities come from the broker, not our records: if the two disagree, the broker is right."
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

          {/* ── Agent vs you ───────────────────────────────────────────────
              Sits between what is held and the rows it was computed from: the
              closed-trades table directly below is the evidence for every
              number in it. */}
          {hasContest && (
            <Section
              title="Agent vs you"
              note="whose picks did better"
              footnote="Rates decide this, not totals — the agent and you size positions differently, so comparing dollar P&L would mostly measure who committed more money. Both columns count only trades with a complete fee total, so a trade the venue never priced sits in neither. This is not the engine's report card: the agent column includes trades you approved, and the Performance page keeps unattended, approved and manual apart for that reason."
            >
              <HeadToHead
                agent={agentStats}
                manual={manualStats}
                autoOnly={perf?.signal_driven ?? null}
                semi={perf?.approved ?? null}
              />
            </Section>
          )}

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

        </>
      )}
    </>
  )
}
