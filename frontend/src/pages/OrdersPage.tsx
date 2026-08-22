import { useCallback, useEffect, useState } from 'react'
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
import { relativeTime } from '../lib/format'
import type { Proposal, TradeRecord } from '../types'
import Layout from '../components/Layout'
import LoadingSpinner from '../components/LoadingSpinner'
import SignalBadge from '../components/SignalBadge'

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
function SourceLabel({ signalType }: { signalType?: string | null }) {
  const label = signalType === 'MANUAL' ? 'You'
    : signalType === 'PROPOSAL_APPROVED' ? 'Approved'
    : signalType ? 'Agent'
    : '—'
  return <span className="text-[0.65rem] text-[var(--color-fg-muted)]">{label}</span>
}

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
              <div className="card overflow-hidden p-0">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm min-w-[44rem]">
                    <thead>
                      <tr className="border-b border-[var(--color-border)] text-[10.5px]
                                     uppercase tracking-widest text-[var(--color-fg-muted)]">
                        <th scope="col" className="text-left font-semibold px-4 py-2.5">Date</th>
                        <th scope="col" className="text-left font-semibold px-3 py-2.5">Ticker</th>
                        <th scope="col" className="text-left font-semibold px-3 py-2.5">Side</th>
                        <th scope="col" className="text-right font-semibold px-3 py-2.5">Qty</th>
                        <th scope="col" className="text-right font-semibold px-3 py-2.5">Price</th>
                        <th scope="col" className="text-right font-semibold px-3 py-2.5">P&amp;L</th>
                        <th scope="col" className="text-left font-semibold px-3 py-2.5">Source</th>
                        <th scope="col" className="text-left font-semibold px-4 py-2.5">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {orders.map((o) => (
                        <tr key={o.id} className="border-b border-[var(--color-border)]/50 last:border-0">
                          <td className="px-4 py-3 text-xs text-[var(--color-fg-muted)] whitespace-nowrap">
                            {new Date(o.opened_at).toLocaleDateString()}
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
                      ))}
                    </tbody>
                  </table>
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
