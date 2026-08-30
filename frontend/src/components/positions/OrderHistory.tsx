import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { Filter as FilterIcon, Inbox } from 'lucide-react'
import { dateKey, formatDate, formatTime } from '../../lib/format'
import { SOURCE_LABEL, tradeSource, type TradeSource } from '../../lib/trade-source'
import { exitReasonLabel } from '../../lib/exit-reason'
import { useIsCompact } from '../../lib/use-media-query'
import { RecordCard } from './RecordCard'
import type { TradeRecord } from '../../types'

/**
 * Every order the agent or the user ever sent, including the refusals.
 *
 * Lifted out of OrdersPage when the 1.7 redesign merged that screen into
 * Positions. The tab-per-status structure and the funnel column filters are
 * carried over unchanged — they shipped in 1.6.2/1.6.3 and a redesign is not a
 * reason to make someone re-learn a table they just learned.
 *
 * One thing did change: source classification now comes from the shared
 * `tradeSource` helper. The copy that lived here treated *any* non-MANUAL,
 * non-PROPOSAL_APPROVED signal_type as agent-placed, while the backend counts
 * only BUY/SELL/EXIT_ALERT as agent and everything else as manual — so an
 * unusual signal_type was labelled "Agent" on this table and folded into
 * `manual` on the performance page. Same record, two answers.
 */

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

function money(v: number | null | undefined): string {
  return v == null ? '—' : usd.format(v)
}

/**
 * The same id that identifies this trade in every email, Slack and WhatsApp
 * message about it — see notifier.py's "Reference" row. Shown short here
 * because a table row has no room for the full 24-character id; the full
 * value is still one hover (desktop) or the record itself away via `title`.
 */
function shortRef(id: string): string {
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
function OrderWhy({ order }: { order: TradeRecord }) {
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

function SourceLabel({ signalType }: { signalType?: string | null }) {
  return (
    <span className="text-[0.65rem] text-[var(--color-fg-muted)]">
      {signalType ? SOURCE_LABEL[tradeSource(signalType)] : '—'}
    </span>
  )
}

// One status per tab rather than one "All" table with a status filter, because
// the ten possible statuses (see TradeStatus in the backend) span three
// different questions — is it open, is it a proposal awaiting you, is it a
// guard's refusal — and a single sorted list buries that distinction. Filled
// is the default: it's the tab that answers "what did the agent actually do".
const STATUS_TABS: { key: string; label: string }[] = [
  { key: 'FILLED', label: 'Filled' },
  { key: 'PARTIAL', label: 'Partial' },
  { key: 'PENDING', label: 'Pending' },
  { key: 'PROPOSED', label: 'Proposed' },
  { key: 'CLOSED', label: 'Closed' },
  { key: 'CANCELLED', label: 'Cancelled' },
  { key: 'SKIPPED', label: 'Skipped' },
  { key: 'DECLINED', label: 'Declined' },
  { key: 'REJECTED', label: 'Rejected' },
  { key: 'UNRECONCILED', label: 'Unreconciled' },
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

  if (f.source && tradeSource(o.signal_type) !== f.source) return false

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

export default function OrderHistory({ orders }: { orders: TradeRecord[] }) {
  const navigate = useNavigate()
  const [activeStatus, setActiveStatus] = useState<string>('FILLED')
  const [orderFilters, setOrderFilters] = useState<OrderFilters>(EMPTY_ORDER_FILTERS)

  const setOrderFilter = (key: keyof OrderFilters, value: string) =>
    setOrderFilters((f) => ({ ...f, [key]: value }))
  const hasActiveFilters = Object.values(orderFilters).some((v) => v !== '')
  const clearOrderFilters = () => setOrderFilters(EMPTY_ORDER_FILTERS)
  const compact = useIsCompact()

  // Tab counts reflect the full history regardless of the column filters, so
  // switching tabs never hides a status because a filter from a different one
  // is still applied. Filled always shows even at zero — it's the default.
  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const o of orders) counts[o.status] = (counts[o.status] ?? 0) + 1
    return counts
  }, [orders])
  const visibleTabs = STATUS_TABS.filter((t) => t.key === 'FILLED' || (statusCounts[t.key] ?? 0) > 0)
  const activeTabLabel = STATUS_TABS.find((t) => t.key === activeStatus)?.label ?? activeStatus

  const sideOptions = useMemo(
    () => Array.from(new Set(orders.map((o) => o.action))).sort(),
    [orders],
  )
  const ordersInTab = useMemo(
    () => orders.filter((o) => o.status === activeStatus),
    [orders, activeStatus],
  )
  const filteredOrders = useMemo(
    () => ordersInTab.filter((o) => matchesOrderFilters(o, orderFilters)),
    [ordersInTab, orderFilters],
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
          No orders yet. Open a ticker on Trade and use <strong>Buy</strong>, or let the
          agent propose one.
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div role="tablist" aria-label="Order status" className="flex items-center gap-1 flex-wrap">
          {visibleTabs.map((t) => (
            <button
              key={t.key}
              role="tab"
              id={`order-tab-${t.key}`}
              aria-selected={activeStatus === t.key}
              aria-controls="order-history-panel"
              onClick={() => setActiveStatus(t.key)}
              className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors
                focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/60 ${
                activeStatus === t.key
                  ? 'bg-brand-500 text-white'
                  : 'bg-[var(--color-border)]/50 text-[var(--color-fg-muted)] hover:text-[var(--color-fg)]'
              }`}
            >
              {t.label}
              <span className={`ml-1.5 num ${activeStatus === t.key ? 'opacity-80' : 'opacity-60'}`}>
                {statusCounts[t.key] ?? 0}
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

      {/* Below md this table is 48rem wide in a 356px column — Price, P&L,
          Source and Status all fall off the right edge with nothing to say they
          are there. Cards carry the same eight fields vertically. Rendered
          instead of the table, never alongside it. */}
      {compact ? (
        <div
          id="order-history-panel"
          role="tabpanel"
          aria-labelledby={`order-tab-${activeStatus}`}
          className="overflow-hidden rounded-lg border border-[var(--color-border)]
                     bg-[var(--color-surface)]"
        >
          {filteredOrders.length === 0 ? (
            <p className="px-4 py-10 text-center text-sm text-[var(--color-fg-muted)]">
              {hasActiveFilters
                ? 'No orders match these filters.'
                : `No ${activeTabLabel.toLowerCase()} orders.`}
            </p>
          ) : (
            filteredOrders.map((o) => (
              <RecordCard
                key={o.id}
                title={o.ticker}
                onTitleClick={() => navigate(`/ticker/${o.ticker}`)}
                badges={
                  <>
                    <StatusPill status={o.status} />
                    <SourceLabel signalType={o.signal_type} />
                  </>
                }
                fields={[
                  {
                    label: 'Date (ET)',
                    value: (
                      <>
                        {formatDate(o.opened_at)}{' '}
                        <span className="text-[var(--color-fg-muted)]">
                          {formatTime(o.opened_at)}
                        </span>
                      </>
                    ),
                  },
                  { label: 'Side', value: o.action },
                  { label: 'Qty', value: o.qty || '—' },
                  { label: 'Price', value: money(o.entry_price ?? o.limit_price ?? null) },
                  { label: 'P&L', value: <Pnl value={o.pnl} /> },
                  {
                    label: 'Ref',
                    value: <span className="font-mono" title={o.id}>{shortRef(o.id)}</span>,
                  },
                ]}
                note={<OrderWhy order={o} />}
              />
            ))
          )}
        </div>
      ) : (
      <div
        id="order-history-panel"
        role="tabpanel"
        aria-labelledby={`order-tab-${activeStatus}`}
        className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]"
      >
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[62rem]">
            <thead>
              {/* Status has no funnel of its own — the tab above already is that filter. */}
              <tr className="border-b border-[var(--color-border)] text-[10.5px]
                             uppercase tracking-widest text-[var(--color-fg-muted)]">
                <th scope="col" className="text-left font-semibold px-3 py-2.5" title="Same id as in email/Slack/WhatsApp for this trade">
                  Ref
                </th>
                <th scope="col" className="text-left font-semibold px-4 py-2.5">
                  <div className="flex items-center gap-1">
                    <span>Date (ET)</span>
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
                <th scope="col" className="text-left font-semibold px-3 py-2.5">
                  <div className="flex items-center gap-1">
                    <span>Side</span>
                    <ColumnFilterMenu label="Filter by side" active={orderFilters.side !== ''}>
                      <select
                        aria-label="Side"
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
                            they are compared against tradeSource() output. */}
                        <option value="agent">Agent</option>
                        <option value="approved">Approved</option>
                        <option value="manual">You</option>
                      </select>
                    </ColumnFilterMenu>
                  </div>
                </th>
                <th scope="col" className="text-left font-semibold px-4 py-2.5">Status</th>
                {/* Last, and unfiltered: it is the column you read after the
                    numbers have made you ask a question, not one you sort by. */}
                <th scope="col" className="text-left font-semibold px-3 py-2.5">Why</th>
              </tr>
            </thead>
            <tbody>
              {filteredOrders.length === 0 ? (
                <tr>
                  <td colSpan={10} className="px-4 py-10 text-center text-sm text-[var(--color-fg-muted)]">
                    {hasActiveFilters
                      ? 'No orders match these filters.'
                      : `No ${activeTabLabel.toLowerCase()} orders.`}
                  </td>
                </tr>
              ) : (
                filteredOrders.map((o) => (
                  <tr key={o.id} className="border-b border-[var(--color-border)]/50 last:border-0">
                    <td
                      className="px-3 py-3 text-[10px] font-mono text-[var(--color-fg-muted)] whitespace-nowrap"
                      title={o.id}
                    >
                      {shortRef(o.id)}
                    </td>
                    <td className="px-4 py-3 text-xs text-[var(--color-fg-muted)] whitespace-nowrap">
                      {/* Several orders can land in one session, so the
                          clock time is what tells them apart. */}
                      <div className="text-[var(--color-fg)]">{formatDate(o.opened_at)}</div>
                      <div className="num">{formatTime(o.opened_at)}</div>
                    </td>
                    <td className="px-3 py-3">
                      <button
                        onClick={() => navigate(`/ticker/${o.ticker}`)}
                        className="font-semibold text-[var(--color-fg)] hover:text-brand-500"
                        style={{ fontFamily: 'Archivo, system-ui, sans-serif' }}
                      >
                        {o.ticker}
                      </button>
                    </td>
                    <td className="px-3 py-3 text-xs text-[var(--color-fg)]">{o.action}</td>
                    <td className="px-3 py-3 text-right num text-[var(--color-fg)]">
                      {o.qty || '—'}
                    </td>
                    <td className="px-3 py-3 text-right num text-[var(--color-fg-muted)]">
                      {money(o.entry_price ?? o.limit_price ?? null)}
                    </td>
                    <td className="px-3 py-3 text-right"><Pnl value={o.pnl} /></td>
                    <td className="px-3 py-3"><SourceLabel signalType={o.signal_type} /></td>
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
