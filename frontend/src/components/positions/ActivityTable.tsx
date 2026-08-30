import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { Filter as FilterIcon, Inbox } from 'lucide-react'
import { dateKey, formatDate, formatTime } from '../../lib/format'
import { SOURCE_LABEL, displaySource, type TradeSource } from '../../lib/trade-source'
import { exitReasonLabel } from '../../lib/exit-reason'
import { useIsCompact } from '../../lib/use-media-query'
import { ProposalRowActions } from '../trade/ProposalActions'
import { RecordCard } from './RecordCard'
import type { TradeRecord } from '../../types'

/**
 * Activity — every action taken on this account, pending ones first.
 *
 * This was two tables. "Agent positions" listed the agent's currently open
 * entries and "Order history" listed everything else, which split one audit
 * trail along a line that answered no question anybody asks: the interesting
 * question is *what has been happening*, and a proposal waiting on you, a guard
 * refusing an order, and a filled entry are all answers to it.
 *
 * So: one table, grouped by what a status means rather than by the status
 * itself, with the proposal queue's Approve/Reject brought into the row. A row
 * opens the transaction, which carries the full record and the rest of that
 * ticker's history.
 *
 * The funnel filters, the compact card fallback and the status pills are
 * carried over from the order history table unchanged — they shipped in
 * 1.6.2/1.6.3 and a restructure is not a reason to make someone re-learn a
 * table they already know.
 */

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

function money(v: number | null | undefined): string {
  return v == null ? '—' : usd.format(v)
}

/**
 * The same id that identifies this trade in every email, Slack and WhatsApp
 * message about it — see notifier.py's "Reference" row. Shown short here
 * because a table row has no room for the full 24-character id; the full
 * value is still one hover (desktop) or the transaction page away.
 */
export function shortRef(id: string): string {
  return id.slice(-8).toUpperCase()
}

/**
 * Why one order happened, in the order the questions get asked.
 *
 * A record can carry up to three different sentences and they answer different
 * questions, so they are not interchangeable and none of them may be dropped:
 *
 *   - `entry_reason` — why the position was opened. Present on every order the
 *     agent or the user actually sent.
 *   - `exit_reason` — why it closed. Only on a closed record.
 *   - `reason` — why an order was *refused*, or how its size was adjusted. On
 *     a SKIPPED row this is the whole story, which is why it leads.
 *
 * Rendered as separate lines rather than joined with a separator: they are
 * three facts about one row, and running them together reads as one sentence
 * that contradicts itself.
 */
export function OrderWhy({ order }: { order: TradeRecord }) {
  const exit = exitReasonLabel(order.exit_reason)
  const lines = [order.reason, order.entry_reason, exit].filter(Boolean) as string[]
  if (lines.length === 0) return null
  return (
    <span className="block">
      {lines.map((line, i) => (
        <span
          key={line}
          className={`block ${i === 0 ? '' : 'mt-0.5 text-[var(--color-fg-muted)]'}`}
        >
          {line}
        </span>
      ))}
    </span>
  )
}

/** Broker-statement convention, matching AccountBar and the position table. */
function Pnl({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="text-[var(--color-fg-muted)]">—</span>
  const loss = value < -0.005
  const gain = value > 0.005
  const tone = loss ? 'text-[var(--accent-sell)]'
    : gain ? 'text-[var(--accent-buy)]'
    : 'text-[var(--color-fg)]'
  return (
    <span className={`num ${tone}`}>
      {loss ? `(${usd.format(Math.abs(value))})` : usd.format(value)}
    </span>
  )
}

const STATUS_TONE: Record<string, string> = {
  FILLED: 'bg-[var(--tint-buy)] text-[var(--accent-buy)]',
  PENDING: 'bg-[var(--tint-hold)] text-[var(--accent-hold)]',
  PARTIAL: 'bg-[var(--tint-hold)] text-[var(--accent-hold)]',
  CLOSED: 'bg-[var(--color-hover)] text-[var(--color-fg-muted)]',
  REJECTED: 'bg-[var(--tint-sell)] text-[var(--accent-sell)]',
  CANCELLED: 'bg-[var(--color-hover)] text-[var(--color-fg-muted)]',
  SKIPPED: 'bg-[var(--color-hover)] text-[var(--color-fg-muted)]',
  DECLINED: 'bg-[var(--color-hover)] text-[var(--color-fg-muted)]',
  PROPOSED: 'bg-brand-500/10 text-brand-500',
  UNRECONCILED: 'bg-[var(--tint-sell)] text-[var(--accent-sell)]',
}

export function StatusPill({ status }: { status: string }) {
  return (
    <span className={`inline-flex whitespace-nowrap rounded px-2 py-0.5 text-[0.65rem] font-semibold
                      uppercase tracking-wide ${STATUS_TONE[status] ?? STATUS_TONE.CLOSED}`}>
      {status}
    </span>
  )
}

function SourceLabel({ order }: { order: TradeRecord }) {
  return (
    <span className="text-[0.65rem] text-[var(--color-fg-muted)]">
      {SOURCE_LABEL[displaySource(order)]}
    </span>
  )
}

function scoreOf(o: TradeRecord): string {
  return o.signal_score != null ? String(Math.round(o.signal_score * 100)) : '—'
}

/**
 * Groups, not statuses.
 *
 * There are ten statuses and they answer three different questions — is this
 * waiting on me, is it live, is it over — so one tab per status buried the
 * distinction under a row of near-identical chips. These are the questions.
 *
 * `Waiting on you` leads and is the default whenever it has anything in it:
 * it is the only group on the screen where nothing happens until the reader
 * acts.
 */
export interface ActivityGroup {
  key: string
  label: string
  statuses: string[] | null   // null = everything
  /** Hidden at zero. Waiting-on-you and Active always show. */
  alwaysShow?: boolean
}

const GROUPS: ActivityGroup[] = [
  { key: 'waiting', label: 'Waiting on you', statuses: ['PROPOSED'], alwaysShow: true },
  { key: 'active', label: 'Active', statuses: ['PENDING', 'PARTIAL', 'FILLED'], alwaysShow: true },
  { key: 'closed', label: 'Closed', statuses: ['CLOSED'] },
  { key: 'not_taken', label: 'Not taken', statuses: ['SKIPPED', 'DECLINED', 'CANCELLED', 'REJECTED'] },
  { key: 'unreconciled', label: 'Unreconciled', statuses: ['UNRECONCILED'] },
  { key: 'all', label: 'All', statuses: null, alwaysShow: true },
]

interface OrderFilters {
  dateFrom: string
  dateTo: string
  ticker: string
  side: string
  qtyMin: string
  qtyMax: string
  priceMin: string
  priceMax: string
  pnl: '' | 'gain' | 'loss'
  source: '' | TradeSource
}

const EMPTY_ORDER_FILTERS: OrderFilters = {
  dateFrom: '', dateTo: '', ticker: '', side: '',
  qtyMin: '', qtyMax: '', priceMin: '', priceMax: '', pnl: '', source: '',
}

function matchesOrderFilters(o: TradeRecord, f: OrderFilters): boolean {
  if (f.dateFrom || f.dateTo) {
    const key = dateKey(o.opened_at)
    if (!key) return false
    if (f.dateFrom && key < f.dateFrom) return false
    if (f.dateTo && key > f.dateTo) return false
  }
  if (f.ticker && !o.ticker.toLowerCase().includes(f.ticker.trim().toLowerCase())) return false
  if (f.side && o.action !== f.side) return false
  if (f.qtyMin && !(o.qty >= Number(f.qtyMin))) return false
  if (f.qtyMax && !(o.qty <= Number(f.qtyMax))) return false

  const price = o.entry_price ?? o.limit_price ?? null
  if (f.priceMin && (price == null || price < Number(f.priceMin))) return false
  if (f.priceMax && (price == null || price > Number(f.priceMax))) return false

  if (f.pnl === 'gain' && !(o.pnl != null && o.pnl > 0.005)) return false
  if (f.pnl === 'loss' && !(o.pnl != null && o.pnl < -0.005)) return false

  if (f.source && displaySource(o) !== f.source) return false

  return true
}

const filterInputCls = 'w-full bg-transparent border border-[var(--color-border)] rounded ' +
  'px-1.5 py-1 text-[11px] leading-tight normal-case tracking-normal font-normal ' +
  'text-[var(--color-fg)] placeholder:text-[var(--color-fg-muted)] focus:outline-none ' +
  'focus:ring-1 focus:ring-[#f2600c] focus:border-[#f2600c]'
const filterLabelCls = 'flex flex-col gap-1 text-[10px] uppercase tracking-wide text-[var(--color-fg-muted)]'

const POPOVER_WIDTH = 208

/**
 * A funnel icon that opens a small popover of column-specific inputs.
 *
 * A permanent filter row under every header doubled the header's height and
 * read as clutter on columns nobody was filtering. Positioned `fixed` and
 * portalled to `document.body` rather than `absolute` in place, because the
 * table sits in a horizontally (and, per the CSS overflow spec, therefore
 * also vertically) auto-scrolling container — an in-flow popover would get
 * clipped by that same scroll box it needs to escape.
 */
function ColumnFilterMenu({
  label,
  active,
  align = 'left',
  children,
}: {
  label: string
  active: boolean
  align?: 'left' | 'right'
  children: ReactNode
}) {
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)
  const btnRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (e: Event) => {
      const target = e.target as Node
      if (panelRef.current?.contains(target) || btnRef.current?.contains(target)) return
      setOpen(false)
    }
    // Escape returns focus to the trigger; an outside click leaves focus
    // wherever the user just clicked, which is already where they intended it.
    const closeOnKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setOpen(false)
      btnRef.current?.focus()
    }
    document.addEventListener('mousedown', close)
    window.addEventListener('scroll', close, true)
    document.addEventListener('keydown', closeOnKey)
    return () => {
      document.removeEventListener('mousedown', close)
      window.removeEventListener('scroll', close, true)
      document.removeEventListener('keydown', closeOnKey)
    }
  }, [open])

  const toggle = () => {
    if (!open && btnRef.current) {
      const r = btnRef.current.getBoundingClientRect()
      setPos({
        top: r.bottom + 6,
        left: align === 'right' ? r.right - POPOVER_WIDTH : r.left,
      })
    }
    setOpen((o) => !o)
  }

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        onClick={toggle}
        aria-label={label}
        aria-expanded={open}
        aria-haspopup="true"
        className={`inline-flex items-center justify-center w-5 h-5 rounded flex-shrink-0
                    normal-case tracking-normal transition-colors focus:outline-none
                    focus-visible:ring-2 focus-visible:ring-brand-500/60 ${
          active ? 'text-brand-500' : 'text-[var(--color-fg-muted)] hover:text-[var(--color-fg)]'
        }`}
      >
        <FilterIcon className="w-3 h-3" fill={active ? 'currentColor' : 'none'} />
      </button>
      {open && pos && createPortal(
        <div
          ref={panelRef}
          role="dialog"
          aria-label={label}
          style={{ position: 'fixed', top: pos.top, left: pos.left, width: POPOVER_WIDTH }}
          className="z-50 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]
                     shadow-lg p-2.5 flex flex-col gap-1.5 normal-case tracking-normal font-normal
                     text-[var(--color-fg)]"
        >
          {children}
        </div>,
        document.body,
      )}
    </>
  )
}

// ── Table ─────────────────────────────────────────────────────────────────────

export default function ActivityTable({
  orders,
  onProposalsChanged,
  /** Set on the transaction page, where the surrounding context is one name. */
  scopedTicker,
  /** The row the reader came from, marked so it is findable in its own history. */
  highlightId,
  /** Ticker links are pointless on a single-ticker list. */
  showTicker = true,
  emptyNote,
}: {
  orders: TradeRecord[]
  onProposalsChanged: () => void
  scopedTicker?: string
  highlightId?: string
  showTicker?: boolean
  emptyNote?: string
}) {
  const navigate = useNavigate()
  const [activeGroup, setActiveGroup] = useState<string | null>(null)
  const [orderFilters, setOrderFilters] = useState<OrderFilters>(EMPTY_ORDER_FILTERS)

  const setOrderFilter = (key: keyof OrderFilters, value: string) =>
    setOrderFilters((f) => ({ ...f, [key]: value }))
  const hasActiveFilters = Object.values(orderFilters).some((v) => v !== '')
  const clearOrderFilters = () => setOrderFilters(EMPTY_ORDER_FILTERS)
  const compact = useIsCompact()

  const openTransaction = (id: string) => navigate(`/transaction/${id}`)

  // Group counts reflect the full history regardless of the column filters, so
  // switching groups never hides one because a filter from a different group is
  // still applied.
  const groupCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const g of GROUPS) {
      counts[g.key] = g.statuses == null
        ? orders.length
        : orders.filter((o) => g.statuses!.includes(o.status)).length
    }
    return counts
  }, [orders])

  const visibleGroups = GROUPS.filter((g) => g.alwaysShow || (groupCounts[g.key] ?? 0) > 0)

  // Waiting-on-you wins the default whenever there is anything in it — it is
  // the only group where nothing moves until the reader acts. Chosen on each
  // render rather than stored, so a proposal arriving on the 60-second poll
  // surfaces itself; an explicit click pins the choice.
  const defaultGroup = (groupCounts.waiting ?? 0) > 0 ? 'waiting' : 'active'
  const group = activeGroup ?? defaultGroup
  const activeDef = GROUPS.find((g) => g.key === group) ?? GROUPS[1]

  const sideOptions = useMemo(
    () => Array.from(new Set(orders.map((o) => o.action))).sort(),
    [orders],
  )
  const ordersInGroup = useMemo(
    () => (activeDef.statuses == null
      ? orders
      : orders.filter((o) => activeDef.statuses!.includes(o.status))),
    [orders, activeDef],
  )
  const filteredOrders = useMemo(
    () => ordersInGroup.filter((o) => matchesOrderFilters(o, orderFilters)),
    [ordersInGroup, orderFilters],
  )

  const dateFilterActive = orderFilters.dateFrom !== '' || orderFilters.dateTo !== ''
  const qtyFilterActive = orderFilters.qtyMin !== '' || orderFilters.qtyMax !== ''
  const priceFilterActive = orderFilters.priceMin !== '' || orderFilters.priceMax !== ''

  if (orders.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-lg border border-[var(--color-border)]
                      bg-[var(--color-surface)] p-10 text-center">
        <Inbox className="h-8 w-8 text-[var(--color-fg-muted)]" aria-hidden="true" />
        <p className="text-sm text-[var(--color-fg-muted)]">
          {emptyNote ?? (scopedTicker
            ? `No transactions recorded for ${scopedTicker}.`
            : 'No activity yet. Open a ticker and use Buy, or let the agent propose one.')}
        </p>
      </div>
    )
  }

  const rowActions = (o: TradeRecord) =>
    o.status === 'PROPOSED' ? (
      <ProposalRowActions
        id={o.id}
        ticker={o.ticker}
        isPaper={o.is_paper}
        onResolved={onProposalsChanged}
        onNeedsConfirmation={() => openTransaction(o.id)}
      />
    ) : null

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div role="tablist" aria-label="Activity" className="flex items-center gap-1 flex-wrap">
          {visibleGroups.map((g) => (
            <button
              key={g.key}
              role="tab"
              id={`activity-tab-${g.key}`}
              aria-selected={group === g.key}
              aria-controls="activity-panel"
              onClick={() => setActiveGroup(g.key)}
              className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors
                focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/60 ${
                group === g.key
                  ? 'bg-brand-500 text-white'
                  : 'bg-[var(--color-border)]/50 text-[var(--color-fg-muted)] hover:text-[var(--color-fg)]'
              }`}
            >
              {g.label}
              <span className={`ml-1.5 num ${group === g.key ? 'opacity-80' : 'opacity-60'}`}>
                {groupCounts[g.key] ?? 0}
              </span>
            </button>
          ))}
        </div>
        {hasActiveFilters && (
          <button
            onClick={clearOrderFilters}
            className="text-[11px] text-[var(--color-fg-muted)] hover:text-[var(--color-fg)]
                       underline underline-offset-2 whitespace-nowrap"
          >
            Clear all filters
          </button>
        )}
      </div>

      {/* Below md this table is wider than the column it sits in — Price, P&L,
          Source and Status all fall off the right edge with nothing to say they
          are there. Cards carry the same fields vertically. Rendered instead of
          the table, never alongside it. */}
      {compact ? (
        <div
          id="activity-panel"
          role="tabpanel"
          aria-labelledby={`activity-tab-${group}`}
          className="overflow-hidden rounded-lg border border-[var(--color-border)]
                     bg-[var(--color-surface)]"
        >
          {filteredOrders.length === 0 ? (
            <p className="px-4 py-10 text-center text-sm text-[var(--color-fg-muted)]">
              {hasActiveFilters
                ? 'No transactions match these filters.'
                : `Nothing under ${activeDef.label.toLowerCase()}.`}
            </p>
          ) : (
            filteredOrders.map((o) => (
              <RecordCard
                key={o.id}
                title={showTicker ? o.ticker : shortRef(o.id)}
                onTitleClick={() => openTransaction(o.id)}
                badges={
                  <>
                    <StatusPill status={o.status} />
                    <SourceLabel order={o} />
                    {o.id === highlightId && (
                      <span className="rounded bg-brand-500/10 px-1.5 py-0.5 text-[10px] text-brand-500">
                        This one
                      </span>
                    )}
                  </>
                }
                fields={[
                  {
                    label: 'Transaction',
                    value: <span className="font-mono" title={o.id}>{shortRef(o.id)}</span>,
                  },
                  {
                    label: 'Time of action',
                    value: (
                      <>
                        {formatDate(o.opened_at)}{' '}
                        <span className="text-[var(--color-fg-muted)]">
                          {formatTime(o.opened_at)}
                        </span>
                      </>
                    ),
                  },
                  { label: 'Action', value: o.action },
                  { label: 'Qty', value: (o.filled_qty ?? o.qty) || '—' },
                  { label: 'Price', value: money(o.entry_price ?? o.limit_price ?? null) },
                  { label: 'Score', value: scoreOf(o) },
                  { label: 'P&L', value: <Pnl value={o.pnl} /> },
                ]}
                note={<OrderWhy order={o} />}
                action={rowActions(o)}
              />
            ))
          )}
        </div>
      ) : (
      <div
        id="activity-panel"
        role="tabpanel"
        aria-labelledby={`activity-tab-${group}`}
        className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]"
      >
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[68rem]">
            <thead>
              {/* Status has no funnel of its own — the group above already is
                  that filter. */}
              <tr className="border-b border-[var(--color-border)] text-[10.5px]
                             uppercase tracking-widest text-[var(--color-fg-muted)]">
                <th scope="col" className="text-left font-semibold px-3 py-2.5" title="Same id as in email/Slack/WhatsApp for this trade">
                  Transaction
                </th>
                <th scope="col" className="text-left font-semibold px-4 py-2.5">
                  <div className="flex items-center gap-1">
                    <span>Time of action</span>
                    <ColumnFilterMenu label="Filter by date" active={dateFilterActive}>
                      <label className={filterLabelCls}>
                        From
                        <input
                          type="date"
                          value={orderFilters.dateFrom}
                          onChange={(e) => setOrderFilter('dateFrom', e.target.value)}
                          className={filterInputCls}
                        />
                      </label>
                      <label className={filterLabelCls}>
                        To
                        <input
                          type="date"
                          value={orderFilters.dateTo}
                          onChange={(e) => setOrderFilter('dateTo', e.target.value)}
                          className={filterInputCls}
                        />
                      </label>
                      {dateFilterActive && (
                        <button
                          onClick={() => setOrderFilters((f) => ({ ...f, dateFrom: '', dateTo: '' }))}
                          className="self-start text-[11px] text-[var(--color-fg-muted)]
                                     hover:text-[var(--color-fg)] underline underline-offset-2"
                        >
                          Clear
                        </button>
                      )}
                    </ColumnFilterMenu>
                  </div>
                </th>
                {showTicker && (
                  <th scope="col" className="text-left font-semibold px-3 py-2.5">
                    <div className="flex items-center gap-1">
                      <span>Ticker</span>
                      <ColumnFilterMenu label="Filter by ticker" active={orderFilters.ticker !== ''}>
                        <input
                          type="text"
                          aria-label="Ticker"
                          placeholder="Ticker"
                          value={orderFilters.ticker}
                          onChange={(e) => setOrderFilter('ticker', e.target.value)}
                          className={filterInputCls}
                        />
                        {orderFilters.ticker !== '' && (
                          <button
                            onClick={() => setOrderFilter('ticker', '')}
                            className="self-start text-[11px] text-[var(--color-fg-muted)]
                                       hover:text-[var(--color-fg)] underline underline-offset-2"
                          >
                            Clear
                          </button>
                        )}
                      </ColumnFilterMenu>
                    </div>
                  </th>
                )}
                <th scope="col" className="text-left font-semibold px-3 py-2.5">
                  <div className="flex items-center gap-1">
                    <span>Action</span>
                    <ColumnFilterMenu label="Filter by action" active={orderFilters.side !== ''}>
                      <select
                        aria-label="Action"
                        value={orderFilters.side}
                        onChange={(e) => setOrderFilter('side', e.target.value)}
                        className={filterInputCls}
                      >
                        <option value="">All</option>
                        {sideOptions.map((a) => <option key={a} value={a}>{a}</option>)}
                      </select>
                    </ColumnFilterMenu>
                  </div>
                </th>
                <th scope="col" className="text-right font-semibold px-3 py-2.5">
                  <div className="flex items-center justify-end gap-1">
                    <ColumnFilterMenu label="Filter by quantity" active={qtyFilterActive}>
                      <label className={filterLabelCls}>
                        Min
                        <input
                          type="number"
                          inputMode="numeric"
                          placeholder="Min"
                          value={orderFilters.qtyMin}
                          onChange={(e) => setOrderFilter('qtyMin', e.target.value)}
                          className={filterInputCls}
                        />
                      </label>
                      <label className={filterLabelCls}>
                        Max
                        <input
                          type="number"
                          inputMode="numeric"
                          placeholder="Max"
                          value={orderFilters.qtyMax}
                          onChange={(e) => setOrderFilter('qtyMax', e.target.value)}
                          className={filterInputCls}
                        />
                      </label>
                      {qtyFilterActive && (
                        <button
                          onClick={() => setOrderFilters((f) => ({ ...f, qtyMin: '', qtyMax: '' }))}
                          className="self-start text-[11px] text-[var(--color-fg-muted)]
                                     hover:text-[var(--color-fg)] underline underline-offset-2"
                        >
                          Clear
                        </button>
                      )}
                    </ColumnFilterMenu>
                    <span>Qty</span>
                  </div>
                </th>
                <th scope="col" className="text-right font-semibold px-3 py-2.5">
                  <div className="flex items-center justify-end gap-1">
                    <ColumnFilterMenu label="Filter by price" active={priceFilterActive} align="right">
                      <label className={filterLabelCls}>
                        Min
                        <input
                          type="number"
                          inputMode="decimal"
                          placeholder="Min"
                          value={orderFilters.priceMin}
                          onChange={(e) => setOrderFilter('priceMin', e.target.value)}
                          className={filterInputCls}
                        />
                      </label>
                      <label className={filterLabelCls}>
                        Max
                        <input
                          type="number"
                          inputMode="decimal"
                          placeholder="Max"
                          value={orderFilters.priceMax}
                          onChange={(e) => setOrderFilter('priceMax', e.target.value)}
                          className={filterInputCls}
                        />
                      </label>
                      {priceFilterActive && (
                        <button
                          onClick={() => setOrderFilters((f) => ({ ...f, priceMin: '', priceMax: '' }))}
                          className="self-start text-[11px] text-[var(--color-fg-muted)]
                                     hover:text-[var(--color-fg)] underline underline-offset-2"
                        >
                          Clear
                        </button>
                      )}
                    </ColumnFilterMenu>
                    <span>Price</span>
                  </div>
                </th>
                {/* The score the agent was working from when it acted. A dash
                    means nobody scored it — a manual order has no signal behind
                    it, and saying 0 would read as a terrible one. */}
                <th scope="col" className="text-right font-semibold px-3 py-2.5" title="Composite score at the time of the action, out of 100">
                  Score
                </th>
                <th scope="col" className="text-right font-semibold px-3 py-2.5">
                  <div className="flex items-center justify-end gap-1">
                    <ColumnFilterMenu label="Filter by profit or loss" active={orderFilters.pnl !== ''} align="right">
                      <select
                        aria-label="Profit or loss"
                        value={orderFilters.pnl}
                        onChange={(e) => setOrderFilter('pnl', e.target.value as OrderFilters['pnl'])}
                        className={filterInputCls}
                      >
                        <option value="">All</option>
                        <option value="gain">Gain</option>
                        <option value="loss">Loss</option>
                      </select>
                    </ColumnFilterMenu>
                    <span>P&amp;L</span>
                  </div>
                </th>
                <th scope="col" className="text-left font-semibold px-3 py-2.5">
                  <div className="flex items-center gap-1">
                    <span>Source</span>
                    <ColumnFilterMenu label="Filter by source" active={orderFilters.source !== ''} align="right">
                      <select
                        aria-label="Source"
                        value={orderFilters.source}
                        onChange={(e) => setOrderFilter('source', e.target.value as OrderFilters['source'])}
                        className={filterInputCls}
                      >
                        <option value="">All</option>
                        {/* Values are the TradeSource keys, not display text —
                            they are compared against displaySource() output. */}
                        <option value="agent">Agent</option>
                        <option value="approved">Semi</option>
                        <option value="manual">Manual</option>
                      </select>
                    </ColumnFilterMenu>
                  </div>
                </th>
                <th scope="col" className="text-left font-semibold px-4 py-2.5">Status</th>
                {/* Last, and unfiltered: it is the column you read after the
                    numbers have made you ask a question, not one you sort by. */}
                <th scope="col" className="text-left font-semibold px-3 py-2.5">Why</th>
                <th scope="col" className="text-right font-semibold px-3 py-2.5">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {filteredOrders.length === 0 ? (
                <tr>
                  <td colSpan={showTicker ? 12 : 11} className="px-4 py-10 text-center text-sm text-[var(--color-fg-muted)]">
                    {hasActiveFilters
                      ? 'No transactions match these filters.'
                      : `Nothing under ${activeDef.label.toLowerCase()}.`}
                  </td>
                </tr>
              ) : (
                filteredOrders.map((o) => (
                  <tr
                    key={o.id}
                    className={`border-b border-[var(--color-border)]/50 last:border-0
                                ${o.id === highlightId ? 'bg-brand-500/5' : ''}`}
                  >
                    <td className="px-3 py-3 text-[10px] whitespace-nowrap">
                      {/* The id is the row's own link. The whole row is not
                          clickable: it carries a ticker link and two action
                          buttons, and a row-level handler would swallow or
                          duplicate them. */}
                      <button
                        onClick={() => openTransaction(o.id)}
                        title={o.id}
                        className="font-mono text-[var(--color-fg-muted)] underline
                                   underline-offset-2 hover:text-brand-500"
                      >
                        {shortRef(o.id)}
                      </button>
                    </td>
                    <td className="px-4 py-3 text-xs text-[var(--color-fg-muted)] whitespace-nowrap">
                      {/* Several orders can land in one session, so the
                          clock time is what tells them apart. */}
                      <div className="text-[var(--color-fg)]">{formatDate(o.opened_at)}</div>
                      <div className="num">{formatTime(o.opened_at)}</div>
                    </td>
                    {showTicker && (
                      <td className="px-3 py-3">
                        <button
                          onClick={() => navigate(`/ticker/${o.ticker}`)}
                          className="font-semibold text-[var(--color-fg)] hover:text-brand-500"
                          style={{ fontFamily: 'Archivo, system-ui, sans-serif' }}
                        >
                          {o.ticker}
                        </button>
                      </td>
                    )}
                    <td className="px-3 py-3 text-xs text-[var(--color-fg)]">{o.action}</td>
                    <td className="px-3 py-3 text-right num text-[var(--color-fg)]">
                      {(o.filled_qty ?? o.qty) || '—'}
                    </td>
                    <td className="px-3 py-3 text-right num text-[var(--color-fg-muted)]">
                      {money(o.entry_price ?? o.limit_price ?? null)}
                    </td>
                    <td className="px-3 py-3 text-right num text-[var(--color-fg-muted)]">
                      {scoreOf(o)}
                    </td>
                    <td className="px-3 py-3 text-right"><Pnl value={o.pnl} /></td>
                    <td className="px-3 py-3"><SourceLabel order={o} /></td>
                    <td className="px-4 py-3">
                      <StatusPill status={o.status} />
                    </td>
                    <td className="px-3 py-3 align-top">
                      {/* Capped rather than wrapped free: one long reason must
                          not set the row height for the fifty rows around it.
                          The full text is one hover away, and the card view
                          below `lg` shows it whole. */}
                      <span
                        className="block max-w-[22rem] text-[11px] leading-snug
                                   text-[var(--color-fg)]"
                        title={
                          [o.reason, o.entry_reason, o.exit_reason]
                            .filter(Boolean)
                            .join(' — ') || undefined
                        }
                      >
                        <OrderWhy order={o} />
                      </span>
                    </td>
                    <td className="px-3 py-3 text-right whitespace-nowrap">{rowActions(o)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
      )}

    </div>
  )
}
