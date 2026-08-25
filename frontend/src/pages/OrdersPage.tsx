import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  AlertCircle,
  Check,
  ClipboardList,
  Inbox,
  RefreshCw,
  X,
} from 'lucide-react'
import { tradingApi } from '../lib/api'
import { useToast } from '../lib/toast-context'
import { dateKey, formatDate, formatTime, relativeTime } from '../lib/format'
import type { Proposal, TradeRecord } from '../types'
import Layout from '../components/Layout'
import LoadingSpinner from '../components/LoadingSpinner'
import SignalBadge from '../components/SignalBadge'
import BrokerPanel from '../components/BrokerPanel'

/**
 * Orders, positions, and the agent's proposal queue.
 *
 * `GET /trading/positions` and `GET /trading/orders` existed and were called by
 * nothing — the product routed real orders to a broker and had no screen where
 * you could see them. This is that screen.
 */

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

function money(v: number | null | undefined): string {
  return v == null ? '—' : usd.format(v)
}

/** Broker-statement convention, matching AccountBar and Holdings. */
function Pnl({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="text-[var(--color-fg-muted)]">—</span>
  const loss = value < -0.005
  const gain = value > 0.005
  const tone = loss ? 'text-[var(--accent-sell)]'
    : gain ? 'text-[var(--accent-buy)]'
    : 'text-[var(--color-fg)]'
  return (
    <span className={`tabular-nums ${tone}`}>
      {loss ? `(${usd.format(Math.abs(value))})` : usd.format(value)}
    </span>
  )
}

const STATUS_TONE: Record<string, string> = {
  FILLED: 'bg-green-500/10 text-[var(--accent-buy)]',
  PENDING: 'bg-amber-500/10 text-[var(--accent-hold)]',
  PARTIAL: 'bg-amber-500/10 text-[var(--accent-hold)]',
  CLOSED: 'bg-[var(--color-border)]/60 text-[var(--color-fg-muted)]',
  REJECTED: 'bg-red-500/10 text-[var(--accent-sell)]',
  CANCELLED: 'bg-[var(--color-border)]/60 text-[var(--color-fg-muted)]',
  SKIPPED: 'bg-[var(--color-border)]/60 text-[var(--color-fg-muted)]',
  DECLINED: 'bg-[var(--color-border)]/60 text-[var(--color-fg-muted)]',
  PROPOSED: 'bg-brand-500/10 text-brand-500',
  UNRECONCILED: 'bg-red-500/10 text-[var(--accent-sell)]',
}

function StatusPill({ status }: { status: string }) {
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-[0.65rem] font-semibold
                      uppercase tracking-wide whitespace-nowrap
                      ${STATUS_TONE[status] ?? STATUS_TONE.CLOSED}`}>
      {status}
    </span>
  )
}

/** How an order came to exist — the distinction the performance page rests on. */
type SourceKey = 'AGENT' | 'APPROVED' | 'YOU'
const SOURCE_LABEL: Record<SourceKey, string> = { AGENT: 'Agent', APPROVED: 'Approved', YOU: 'You' }

function sourceKey(signalType?: string | null): SourceKey | null {
  if (signalType === 'MANUAL') return 'YOU'
  if (signalType === 'PROPOSAL_APPROVED') return 'APPROVED'
  if (signalType) return 'AGENT'
  return null
}

function SourceLabel({ signalType }: { signalType?: string | null }) {
  const key = sourceKey(signalType)
  return (
    <span className="text-[0.65rem] text-[var(--color-fg-muted)]">
      {key ? SOURCE_LABEL[key] : '—'}
    </span>
  )
}

// ── Order history: tabs + column filters ───────────────────────────────────────
//
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
  source: string
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

  if (f.source && sourceKey(o.signal_type) !== f.source) return false

  return true
}

const filterInputCls = 'w-full bg-transparent border border-[var(--color-border)] rounded ' +
  'px-1.5 py-1 text-[11px] leading-tight text-[var(--color-fg)] ' +
  'placeholder:text-[var(--color-fg-muted)] focus:outline-none focus:ring-1 ' +
  'focus:ring-[#f2600c] focus:border-[#f2600c]'

// ── Proposal queue ────────────────────────────────────────────────────────────

function ProposalCard({
  proposal,
  onResolved,
}: {
  proposal: Proposal
  onResolved: () => void
}) {
  const { toast } = useToast()
  const [busy, setBusy] = useState<'approve' | 'decline' | null>(null)
  // A live-money proposal must not be approvable in one click. The order
  // ticket asks the user to type the ticker; approving is the same act with
  // the same consequences, so it asks for the same thing.
  const [confirmLive, setConfirmLive] = useState('')
  const needsConfirm = !proposal.is_paper
  const liveConfirmed =
    !needsConfirm || confirmLive.trim().toUpperCase() === proposal.ticker.toUpperCase()

  const approve = async () => {
    if (!liveConfirmed) return
    setBusy('approve')
    try {
      const { data } = await tradingApi.approveProposal(proposal.id, needsConfirm)
      if (data.placed) {
        toast(
          `Order placed: ${data.qty} ${data.ticker} at ${usd.format(data.limit_price)}`,
          'success',
        )
      } else {
        toast(data.reason ?? 'The order could not be placed.', 'error')
      }
      onResolved()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      toast(detail ?? 'Could not approve this proposal.', 'error')
      onResolved()
    } finally {
      setBusy(null)
    }
  }

  const decline = async () => {
    setBusy('decline')
    try {
      await tradingApi.declineProposal(proposal.id)
      toast(`Declined ${proposal.ticker}.`, 'info')
      onResolved()
    } catch {
      toast('Could not decline this proposal.', 'error')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="card flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className="font-semibold text-[var(--color-fg)]"
              style={{ fontFamily: 'Archivo, system-ui, sans-serif' }}
            >
              {proposal.ticker}
            </span>
            <SignalBadge signal="BUY" />
            {proposal.conviction && (
              <span className="text-[0.65rem] text-[var(--color-fg-muted)]">
                {proposal.conviction} conviction
              </span>
            )}
          </div>
          <p className="text-xs text-[var(--color-fg-muted)] mt-1">
            {proposal.reason} · {relativeTime(proposal.proposed_at)}
          </p>
        </div>
        {proposal.is_paper && (
          <span className="text-[0.6rem] uppercase tracking-wide px-1.5 py-0.5 rounded
                           bg-[var(--color-border)]/60 text-[var(--color-fg-muted)] flex-shrink-0">
            Paper
          </span>
        )}
      </div>

      {/* The arithmetic is already done — show it rather than making them trust it. */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-1 text-xs">
        <div className="flex flex-col">
          <span className="text-[var(--color-fg-muted)]">Quantity</span>
          <span className="tabular-nums text-[var(--color-fg)]">{proposal.qty}</span>
        </div>
        <div className="flex flex-col">
          <span className="text-[var(--color-fg-muted)]">Limit</span>
          <span className="tabular-nums text-[var(--color-fg)]">{money(proposal.limit_price)}</span>
        </div>
        <div className="flex flex-col">
          <span className="text-[var(--color-fg-muted)]">Stop</span>
          <span className="tabular-nums text-[var(--accent-sell)]">{money(proposal.stop_loss)}</span>
        </div>
        <div className="flex flex-col">
          <span className="text-[var(--color-fg-muted)]">Target</span>
          <span className="tabular-nums text-[var(--accent-buy)]">{money(proposal.take_profit)}</span>
        </div>
      </div>

      {needsConfirm && (
        <div className="flex flex-col gap-1">
          <label
            htmlFor={`confirm-${proposal.id}`}
            className="text-xs text-[var(--accent-sell)]"
          >
            Live money — type <strong>{proposal.ticker}</strong> to approve
          </label>
          <input
            id={`confirm-${proposal.id}`}
            type="text"
            value={confirmLive}
            onChange={(e) => setConfirmLive(e.target.value)}
            autoComplete="off"
            className="input text-sm"
          />
        </div>
      )}

      <div className="flex gap-2">
        <button
          onClick={approve}
          disabled={busy !== null || !liveConfirmed}
          className="btn-primary flex-1"
        >
          {busy === 'approve' ? <LoadingSpinner size="sm" /> : <Check className="w-4 h-4" />}
          Approve
        </button>
        <button onClick={decline} disabled={busy !== null} className="btn-secondary flex-1">
          {busy === 'decline' ? <LoadingSpinner size="sm" /> : <X className="w-4 h-4" />}
          Decline
        </button>
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function OrdersPage() {
  const navigate = useNavigate()
  const { toast, toastWithUndo } = useToast()
  const [proposals, setProposals] = useState<Proposal[]>([])
  const [positions, setPositions] = useState<TradeRecord[]>([])
  const [orders, setOrders] = useState<TradeRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [closing, setClosing] = useState<string | null>(null)
  const [activeStatus, setActiveStatus] = useState<string>('FILLED')
  const [orderFilters, setOrderFilters] = useState<OrderFilters>(EMPTY_ORDER_FILTERS)

  const setOrderFilter = (key: keyof OrderFilters, value: string) =>
    setOrderFilters((f) => ({ ...f, [key]: value }))
  const hasActiveFilters = Object.values(orderFilters).some((v) => v !== '')
  const clearOrderFilters = () => setOrderFilters(EMPTY_ORDER_FILTERS)

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

  const load = useCallback(async (spinner = false) => {
    if (spinner) setRefreshing(true)
    setError(null)
    try {
      const [p, pos, ord] = await Promise.all([
        tradingApi.getProposals().catch(() => ({ data: [] as Proposal[] })),
        tradingApi.getPositions(),
        tradingApi.getOrders(),
      ])
      setProposals(p.data)
      setPositions(pos.data)
      setOrders(ord.data)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setError(detail ?? 'Could not load your orders.')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

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
          const detail = (err as { response?: { data?: { detail?: string } } })
            ?.response?.data?.detail
          toast(detail ?? `Could not close ${ticker}.`, 'error')
        } finally {
          setClosing(null)
        }
      },
      () => toast(`Kept ${ticker}.`, 'info'),
    )
  }

  return (
    <Layout>
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3 mb-6">
        <div>
          <h1
            className="text-2xl font-light text-[var(--color-fg)]"
            style={{ fontFamily: 'Fraunces, Georgia, serif' }}
          >
            Orders
          </h1>
          <p className="text-sm text-[var(--color-fg-muted)] mt-0.5">
            Proposals awaiting you, open positions, and everything the agent has sent.
          </p>
        </div>
        <button
          onClick={() => load(true)}
          disabled={refreshing || loading}
          className="btn-secondary flex-shrink-0 self-start"
        >
          <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {error && (
        <div role="alert" className="flex items-center gap-3 px-4 py-3 rounded-xl mb-6
                        bg-red-500/10 border border-red-500/20 text-red-500 text-sm">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          {error}
        </div>
      )}

      {/* Broker session sits above everything: when it is down, every action on
          this page is refused, and that should be the first thing you see. */}
      <div className="mb-8">
        <BrokerPanel />
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <LoadingSpinner size="lg" />
        </div>
      ) : (
        <div className="flex flex-col gap-8">
          {/* ── Proposals ──────────────────────────────────────────────── */}
          {proposals.length > 0 && (
            <section className="flex flex-col gap-3">
              <div>
                <h2 className="text-[11px] font-semibold uppercase tracking-widest text-[var(--color-fg-muted)]">
                  Awaiting your approval ({proposals.length})
                </h2>
                <p className="text-xs text-[var(--color-fg-muted)] mt-1 max-w-2xl">
                  Entries the agent wanted to take but your trading mode does not let it
                  take alone. Nothing here is committed and none of it holds a position slot.
                </p>
              </div>
              <div className="grid gap-3 lg:grid-cols-2">
                {proposals.map((p) => (
                  <ProposalCard key={p.id} proposal={p} onResolved={load} />
                ))}
              </div>
            </section>
          )}

          {/* ── Open positions ─────────────────────────────────────────── */}
          <section className="flex flex-col gap-3">
            <h2 className="text-[11px] font-semibold uppercase tracking-widest text-[var(--color-fg-muted)]">
              Open positions ({positions.length})
            </h2>
            {positions.length === 0 ? (
              <div className="card p-8 text-center text-sm text-[var(--color-fg-muted)]">
                No open positions tracked by the agent.
              </div>
            ) : (
              <div className="card overflow-hidden p-0">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm min-w-[40rem]">
                    <thead>
                      <tr className="border-b border-[var(--color-border)] text-[10.5px]
                                     uppercase tracking-widest text-[var(--color-fg-muted)]">
                        <th scope="col" className="text-left font-semibold px-4 py-2.5">Ticker</th>
                        <th scope="col" className="text-right font-semibold px-3 py-2.5">Qty</th>
                        <th scope="col" className="text-right font-semibold px-3 py-2.5">Entry</th>
                        <th scope="col" className="text-right font-semibold px-3 py-2.5">Stop</th>
                        <th scope="col" className="text-right font-semibold px-3 py-2.5">Target</th>
                        <th scope="col" className="text-left font-semibold px-3 py-2.5">Status</th>
                        <th scope="col" className="text-right font-semibold px-4 py-2.5">&nbsp;</th>
                      </tr>
                    </thead>
                    <tbody>
                      {positions.map((p) => (
                        <tr key={p.id} className="border-b border-[var(--color-border)]/50 last:border-0">
                          <td className="px-4 py-3">
                            <button
                              onClick={() => navigate(`/ticker/${p.ticker}`)}
                              className="font-semibold text-[var(--color-fg)] hover:text-brand-500"
                              style={{ fontFamily: 'Archivo, system-ui, sans-serif' }}
                            >
                              {p.ticker}
                            </button>
                          </td>
                          <td className="px-3 py-3 text-right tabular-nums text-[var(--color-fg)]">
                            {p.filled_qty ?? p.qty}
                          </td>
                          <td className="px-3 py-3 text-right tabular-nums text-[var(--color-fg-muted)]">
                            {money(p.entry_price ?? p.limit_price)}
                          </td>
                          <td className="px-3 py-3 text-right tabular-nums text-[var(--accent-sell)]">
                            {money(p.stop_loss)}
                          </td>
                          <td className="px-3 py-3 text-right tabular-nums text-[var(--accent-buy)]">
                            {money(p.take_profit)}
                          </td>
                          <td className="px-3 py-3"><StatusPill status={p.status} /></td>
                          <td className="px-4 py-3 text-right">
                            <button
                              onClick={() => closePosition(p.ticker)}
                              disabled={closing === p.ticker}
                              className="btn-secondary text-xs px-2 py-1 h-auto min-h-0"
                            >
                              {closing === p.ticker ? <LoadingSpinner size="sm" /> : 'Close'}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </section>

          {/* ── Order history ──────────────────────────────────────────── */}
          <section className="flex flex-col gap-3">
            <div>
              <h2 className="text-[11px] font-semibold uppercase tracking-widest text-[var(--color-fg-muted)]">
                Order history
              </h2>
              <p className="text-xs text-[var(--color-fg-muted)] mt-1">
                Every attempt, including the ones the risk guards refused — a skip is a
                decision worth seeing.
              </p>
            </div>
            {orders.length === 0 ? (
              <div className="card p-10 flex flex-col items-center gap-3 text-center">
                <Inbox className="w-8 h-8 text-[var(--color-fg-muted)]" />
                <p className="text-sm text-[var(--color-fg-muted)]">
                  No orders yet. Open a ticker and use <strong>Buy</strong>, or let the
                  agent propose one.
                </p>
              </div>
            ) : (
              <div className="flex flex-col gap-3">
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
                      <span className={`ml-1.5 tabular-nums ${activeStatus === t.key ? 'opacity-80' : 'opacity-60'}`}>
                        {statusCounts[t.key] ?? 0}
                      </span>
                    </button>
                  ))}
                </div>

                <div
                  id="order-history-panel"
                  role="tabpanel"
                  aria-labelledby={`order-tab-${activeStatus}`}
                  className="card overflow-hidden p-0"
                >
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm min-w-[48rem]">
                      <thead>
                        <tr className="border-b border-[var(--color-border)] text-[10.5px]
                                       uppercase tracking-widest text-[var(--color-fg-muted)]">
                          <th scope="col" className="text-left font-semibold px-4 py-2.5">Date (ET)</th>
                          <th scope="col" className="text-left font-semibold px-3 py-2.5">Ticker</th>
                          <th scope="col" className="text-left font-semibold px-3 py-2.5">Side</th>
                          <th scope="col" className="text-right font-semibold px-3 py-2.5">Qty</th>
                          <th scope="col" className="text-right font-semibold px-3 py-2.5">Price</th>
                          <th scope="col" className="text-right font-semibold px-3 py-2.5">P&amp;L</th>
                          <th scope="col" className="text-left font-semibold px-3 py-2.5">Source</th>
                          <th scope="col" className="text-left font-semibold px-4 py-2.5">Status</th>
                        </tr>
                        {/* One filter per column. Status has none of its own — the tab above is that filter. */}
                        <tr className="border-b border-[var(--color-border)] bg-[var(--color-bg)]/60">
                          <td className="px-4 py-2 align-top">
                            <div className="flex flex-col gap-1">
                              <input
                                type="date"
                                aria-label="From date"
                                value={orderFilters.dateFrom}
                                onChange={(e) => setOrderFilter('dateFrom', e.target.value)}
                                className={filterInputCls}
                              />
                              <input
                                type="date"
                                aria-label="To date"
                                value={orderFilters.dateTo}
                                onChange={(e) => setOrderFilter('dateTo', e.target.value)}
                                className={filterInputCls}
                              />
                            </div>
                          </td>
                          <td className="px-3 py-2 align-top">
                            <input
                              type="text"
                              aria-label="Filter by ticker"
                              placeholder="Ticker"
                              value={orderFilters.ticker}
                              onChange={(e) => setOrderFilter('ticker', e.target.value)}
                              className={filterInputCls}
                            />
                          </td>
                          <td className="px-3 py-2 align-top">
                            <select
                              aria-label="Filter by side"
                              value={orderFilters.side}
                              onChange={(e) => setOrderFilter('side', e.target.value)}
                              className={filterInputCls}
                            >
                              <option value="">All</option>
                              {sideOptions.map((a) => <option key={a} value={a}>{a}</option>)}
                            </select>
                          </td>
                          <td className="px-3 py-2 align-top">
                            <div className="flex flex-col gap-1">
                              <input
                                type="number"
                                inputMode="numeric"
                                aria-label="Minimum quantity"
                                placeholder="Min"
                                value={orderFilters.qtyMin}
                                onChange={(e) => setOrderFilter('qtyMin', e.target.value)}
                                className={`${filterInputCls} text-right`}
                              />
                              <input
                                type="number"
                                inputMode="numeric"
                                aria-label="Maximum quantity"
                                placeholder="Max"
                                value={orderFilters.qtyMax}
                                onChange={(e) => setOrderFilter('qtyMax', e.target.value)}
                                className={`${filterInputCls} text-right`}
                              />
                            </div>
                          </td>
                          <td className="px-3 py-2 align-top">
                            <div className="flex flex-col gap-1">
                              <input
                                type="number"
                                inputMode="decimal"
                                aria-label="Minimum price"
                                placeholder="Min"
                                value={orderFilters.priceMin}
                                onChange={(e) => setOrderFilter('priceMin', e.target.value)}
                                className={`${filterInputCls} text-right`}
                              />
                              <input
                                type="number"
                                inputMode="decimal"
                                aria-label="Maximum price"
                                placeholder="Max"
                                value={orderFilters.priceMax}
                                onChange={(e) => setOrderFilter('priceMax', e.target.value)}
                                className={`${filterInputCls} text-right`}
                              />
                            </div>
                          </td>
                          <td className="px-3 py-2 align-top">
                            <select
                              aria-label="Filter by profit or loss"
                              value={orderFilters.pnl}
                              onChange={(e) => setOrderFilter('pnl', e.target.value as OrderFilters['pnl'])}
                              className={filterInputCls}
                            >
                              <option value="">All</option>
                              <option value="gain">Gain</option>
                              <option value="loss">Loss</option>
                            </select>
                          </td>
                          <td className="px-3 py-2 align-top">
                            <select
                              aria-label="Filter by source"
                              value={orderFilters.source}
                              onChange={(e) => setOrderFilter('source', e.target.value)}
                              className={filterInputCls}
                            >
                              <option value="">All</option>
                              <option value="AGENT">Agent</option>
                              <option value="APPROVED">Approved</option>
                              <option value="YOU">You</option>
                            </select>
                          </td>
                          <td className="px-4 py-2 align-top text-right">
                            {hasActiveFilters && (
                              <button
                                onClick={clearOrderFilters}
                                className="text-[11px] text-[var(--color-fg-muted)]
                                           hover:text-[var(--color-fg)] underline underline-offset-2
                                           whitespace-nowrap"
                              >
                                Clear filters
                              </button>
                            )}
                          </td>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredOrders.length === 0 ? (
                          <tr>
                            <td colSpan={8} className="px-4 py-10 text-center text-sm text-[var(--color-fg-muted)]">
                              {hasActiveFilters
                                ? 'No orders match these filters.'
                                : `No ${activeTabLabel.toLowerCase()} orders.`}
                            </td>
                          </tr>
                        ) : (
                          filteredOrders.map((o) => (
                            <tr key={o.id} className="border-b border-[var(--color-border)]/50 last:border-0">
                              <td className="px-4 py-3 text-xs text-[var(--color-fg-muted)] whitespace-nowrap">
                                {/* Several orders can land in one session, so the
                                    clock time is what tells them apart. */}
                                <div className="text-[var(--color-fg)]">{formatDate(o.opened_at)}</div>
                                <div className="tabular-nums">{formatTime(o.opened_at)}</div>
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
                              <td className="px-3 py-3 text-right tabular-nums text-[var(--color-fg)]">
                                {o.qty || '—'}
                              </td>
                              <td className="px-3 py-3 text-right tabular-nums text-[var(--color-fg-muted)]">
                                {money(o.entry_price ?? o.limit_price ?? null)}
                              </td>
                              <td className="px-3 py-3 text-right"><Pnl value={o.pnl} /></td>
                              <td className="px-3 py-3"><SourceLabel signalType={o.signal_type} /></td>
                              <td className="px-4 py-3">
                                <div className="flex flex-col gap-0.5">
                                  <StatusPill status={o.status} />
                                  {o.reason && (
                                    <span className="text-[0.6rem] text-[var(--color-fg-muted)] max-w-[16rem]">
                                      {o.reason}
                                    </span>
                                  )}
                                </div>
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            )}
          </section>

          <p className="flex items-start gap-2 text-[0.65rem] text-[var(--color-fg-muted)] leading-relaxed">
            <ClipboardList className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
            <span>
              <strong>Source</strong> records who decided: <em>Agent</em> placed unattended,
              <em> Approved</em> means the agent proposed and you accepted, <em>You</em> means
              you chose the ticker. Performance keeps the three apart — a set of the agent's
              picks that a human filtered is not a clean measure of the agent.
            </span>
          </p>
        </div>
      )}
    </Layout>
  )
}
