import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, LineChart } from 'lucide-react'
import { tradingApi } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import { SOURCE_DESCRIPTION, SOURCE_LABEL, displaySource } from '../../lib/trade-source'
import { exitReasonLabel } from '../../lib/exit-reason'
import { usePortfolio } from '../../lib/portfolio-context'
import { ProposalActions } from '../trade/ProposalActions'
import LoadingSpinner from '../LoadingSpinner'
import ActivityTable, { OrderWhy, StatusPill, shortRef } from './ActivityTable'
import type { TradeRecord } from '../../types'

/**
 * One transaction, in full, with the rest of that ticker's history under it.
 *
 * The audit trail this screen exists for is not one row — it is the sequence.
 * "Why do I own 40 shares of AVGO" is answered by an entry, two adds and a
 * proposal that was declined in between, and no single record says that. So the
 * detail leads with the record the reader clicked and then puts it back in its
 * own history.
 *
 * It renders in the centre column rather than over it. A modal here would sit
 * on top of the table it came from and put the reader's context behind a
 * backdrop, which is the opposite of what an audit view is for.
 */

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

function money(v: number | null | undefined): string {
  return v == null ? '—' : usd.format(v)
}

/** How far back a ticker's history is worth showing. */
const HISTORY_MONTHS = 3
const HISTORY_MIN_ROWS = 10

/**
 * Three months, or ten rows, whichever reaches further.
 *
 * A fixed window hides everything on a name traded twice a year; a fixed count
 * hides most of a busy week. Taking the larger of the two means the reader
 * always gets either the recent period or a usable sample, and the caller is
 * told which rule produced the list — a truncated history that does not say it
 * is truncated is how someone concludes a trade never happened.
 */
export function tickerHistory(orders: TradeRecord[], ticker: string): {
  rows: TradeRecord[]
  rule: string
} {
  const mine = orders
    .filter((o) => o.ticker === ticker)
    .slice()
    .sort((a, b) => (b.opened_at ?? '').localeCompare(a.opened_at ?? ''))

  const cutoff = new Date()
  cutoff.setMonth(cutoff.getMonth() - HISTORY_MONTHS)
  const withinWindow = mine.filter((o) => {
    const t = Date.parse(o.opened_at)
    return Number.isFinite(t) && t >= cutoff.getTime()
  })

  if (withinWindow.length >= HISTORY_MIN_ROWS) {
    return { rows: withinWindow, rule: `Everything in the last ${HISTORY_MONTHS} months.` }
  }
  const rows = mine.slice(0, HISTORY_MIN_ROWS)
  return {
    rows,
    rule: rows.length > withinWindow.length
      ? `Fewer than ${HISTORY_MIN_ROWS} transactions in the last ${HISTORY_MONTHS} months, so this reaches further back — the ${rows.length} most recent.`
      : `Everything in the last ${HISTORY_MONTHS} months.`,
  }
}

function Field({ label, value, title }: { label: string; value: ReactNode; title?: string }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-[0.1em] text-[var(--color-fg-muted)]">
        {label}
      </dt>
      <dd className="num mt-px text-[13px] text-[var(--color-fg)]" title={title}>{value}</dd>
    </div>
  )
}

function Pnl({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="text-[var(--color-fg-muted)]">—</span>
  const loss = value < -0.005
  const gain = value > 0.005
  return (
    <span style={{
      color: loss ? 'var(--accent-sell)' : gain ? 'var(--accent-buy)' : 'var(--color-fg)',
    }}>
      {loss ? `(${usd.format(Math.abs(value))})` : usd.format(value)}
    </span>
  )
}

export default function TransactionDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { orders, loading, reload } = usePortfolio()

  // The portfolio carries the most recent 200 orders across every ticker, which
  // is usually enough and sometimes is not. A record older than that window is
  // fetched on its own rather than reported as missing.
  const [fetched, setFetched] = useState<TradeRecord[] | null>(null)
  const [fetching, setFetching] = useState(false)

  const pool = useMemo(() => (fetched ?? orders), [fetched, orders])
  const trade = useMemo(() => pool.find((o) => o.id === id) ?? null, [pool, id])

  useEffect(() => {
    if (loading || trade || fetching || fetched) return
    setFetching(true)
    tradingApi.getOrders(undefined, 1000)
      .then((r) => setFetched(r.data))
      .catch(() => setFetched([]))
      .finally(() => setFetching(false))
  }, [loading, trade, fetching, fetched])

  const history = useMemo(
    () => (trade ? tickerHistory(pool, trade.ticker) : null),
    [pool, trade],
  )

  if (loading || fetching) {
    return (
      <div className="flex items-center justify-center py-20">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  if (!trade) {
    return (
      <div className="flex flex-col items-start gap-3 py-10">
        <button onClick={() => navigate('/')} className="chip">
          <ArrowLeft className="h-3 w-3" aria-hidden="true" /> Back
        </button>
        <p className="text-sm text-[var(--color-fg-muted)]">
          No transaction with reference {id ? shortRef(id) : '—'} is on this account.
        </p>
      </div>
    )
  }

  const source = displaySource(trade)
  const exit = exitReasonLabel(trade.exit_reason)

  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <button onClick={() => navigate('/')} className="chip touch-target">
          <ArrowLeft className="h-3 w-3" aria-hidden="true" /> Back
        </button>
        <button
          onClick={() => navigate(`/ticker/${trade.ticker}`)}
          className="chip touch-target"
        >
          <LineChart className="h-3 w-3" aria-hidden="true" /> {trade.ticker} analysis
        </button>
      </div>

      {/* ── The record ──────────────────────────────────────────────────── */}
      <section className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
        <div className="flex flex-wrap items-baseline gap-2.5">
          <h1
            className="m-0 text-[22px] font-bold tracking-[-0.02em]"
            style={{ fontFamily: 'Archivo, system-ui, sans-serif' }}
          >
            {trade.ticker}
          </h1>
          <span className="text-[13px] font-semibold text-[var(--color-fg)]">{trade.action}</span>
          <StatusPill status={trade.status} />
          <span className="rounded bg-[var(--color-hover)] px-1.5 py-0.5 text-[10px]
                           text-[var(--color-fg-muted)]" title={SOURCE_DESCRIPTION[source]}>
            {SOURCE_LABEL[source]}
          </span>
          {!trade.is_paper && (
            <span
              className="rounded px-1.5 py-0.5 text-[10px] font-bold"
              style={{ background: 'var(--tint-sell)', color: 'var(--accent-sell)' }}
            >
              LIVE
            </span>
          )}
        </div>

        <p className="mt-1 text-[11px] text-[var(--color-fg-muted)]">
          {SOURCE_DESCRIPTION[source]}
          {trade.is_paper ? ' · paper' : ''}
        </p>

        <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3 lg:grid-cols-4">
          {/* Full, not shortened. This page is where someone matches a record
              against the reference in an alert email, and eight characters do
              not settle an argument. */}
          <Field label="Transaction ID" value={<span className="font-mono text-[11px] break-all">{trade.id}</span>} />
          <Field label="Time of action" value={formatDateTime(trade.opened_at)} />
          {trade.filled_at && <Field label="Filled" value={formatDateTime(trade.filled_at)} />}
          {trade.closed_at && <Field label="Closed" value={formatDateTime(trade.closed_at)} />}
          {/* Requested and filled are separate facts: the server clamps a
              requested quantity to what the risk model funds, and a partial
              fill clamps it again. */}
          <Field label="Qty requested" value={trade.qty || '—'} />
          <Field label="Qty filled" value={trade.filled_qty ?? '—'} />
          <Field label="Limit" value={money(trade.limit_price)} />
          <Field label="Entry" value={money(trade.entry_price)} />
          {trade.exit_price != null && (
            <Field
              label="Exit"
              value={
                <>
                  {money(trade.exit_price)}
                  {trade.exit_price_estimated && (
                    <span className="ml-1 text-[10px] text-[var(--color-fg-muted)]">est.</span>
                  )}
                </>
              }
              title={trade.exit_price_estimated
                ? 'The level we asked for, not a confirmed fill'
                : undefined}
            />
          )}
          <Field
            label="Stop"
            value={<span style={{ color: 'var(--accent-sell)' }}>{money(trade.stop_loss)}</span>}
          />
          <Field
            label="Target"
            value={<span style={{ color: 'var(--accent-buy)' }}>{money(trade.take_profit)}</span>}
          />
          <Field
            label="Score"
            value={trade.signal_score != null ? `${Math.round(trade.signal_score * 100)}/100` : '—'}
            title="Composite score at the time of the action"
          />
          <Field label="Analyst conviction" value={trade.conviction ?? '—'} />
          {/* How much of the score was built on measured inputs rather than
              fallbacks. Missing stays missing — a trade recorded before this was
              captured has no figure, and 100% would be a claim nobody made. */}
          <Field
            label="Input completeness"
            value={trade.input_completeness != null
              ? `${Math.round(trade.input_completeness * 100)}%`
              : '—'}
            title="Share of the score built on measured rather than fallback inputs"
          />
          <Field label="P&L" value={<Pnl value={trade.pnl} />} />
          {trade.order_id != null && (
            <Field label="Broker order" value={<span className="font-mono text-[11px]">{String(trade.order_id)}</span>} />
          )}
        </dl>

        {/* Three sentences answering three different questions. None of them is
            a substitute for another, so none is dropped. */}
        {(trade.reason || trade.entry_reason || exit) && (
          <div className="mt-4 border-t border-[var(--color-border)] pt-3">
            <span className="label-micro">Why</span>
            <div className="mt-1.5 text-[12px] leading-relaxed text-[var(--color-fg)]">
              <OrderWhy order={trade} />
            </div>
          </div>
        )}

        {/* ── Approve / reject ──────────────────────────────────────────
            The one place a live-money proposal can be approved, because it is
            the one place with room for the typed confirmation. */}
        {trade.status === 'PROPOSED' && (
          <div className="mt-4 border-t border-[var(--color-border)] pt-3">
            <span className="label-micro">Waiting on you</span>
            <p className="mt-1 text-[11px] text-[var(--color-fg-muted)]">
              Nothing is committed until you accept. Approving places the order;
              rejecting records the refusal and takes no position.
            </p>
            <ProposalActions
              id={trade.id}
              ticker={trade.ticker}
              isPaper={trade.is_paper}
              onResolved={() => { void reload(); navigate('/') }}
            />
          </div>
        )}
      </section>

      {/* ── The ticker's history ────────────────────────────────────────── */}
      {history && (
        <section className="mt-5">
          <div className="mb-2 flex flex-wrap items-baseline gap-2.5">
            <h2
              className="m-0 text-[13px] font-bold uppercase tracking-[0.06em]"
              style={{ fontFamily: 'Archivo, system-ui, sans-serif' }}
            >
              All transactions — {trade.ticker}
            </h2>
            <span className="text-[11px] text-[var(--color-fg-muted)]">
              {history.rows.length} {history.rows.length === 1 ? 'record' : 'records'}
            </span>
          </div>
          <ActivityTable
            orders={history.rows}
            onProposalsChanged={() => void reload()}
            scopedTicker={trade.ticker}
            highlightId={trade.id}
            showTicker={false}
          />
          <p className="mt-1.5 text-[10.5px] leading-relaxed text-[var(--color-fg-muted)]">
            {history.rule} Manual orders, agent entries, adds and refusals alike —
            this is the whole record for {trade.ticker}, not only the trades that
            filled.
          </p>
        </section>
      )}
    </>
  )
}
