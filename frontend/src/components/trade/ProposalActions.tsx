import { useState } from 'react'
import { tradingApi } from '../../lib/api'
import { useToast } from '../../lib/toast-context'
import LoadingSpinner from '../LoadingSpinner'

/**
 * Accepting or refusing an entry the agent wanted but was not permitted to take
 * alone — in one place, because there are now three of them.
 *
 * The approvals queue in the right rail, a row of the activity table, and the
 * transaction detail all resolve the same proposal, and the live-money gate is
 * the thing that must not be reimplemented twice: approving a proposal *is*
 * placing an order, and the fact that the agent chose the name rather than the
 * human does not make it a smaller commitment. So it asks for the ticker to be
 * typed back, exactly as the order ticket does.
 *
 * A table row cannot hold a text input, so the row form does not try. It hands
 * a live proposal to `onNeedsConfirmation` — the caller routes to the detail
 * panel, which has room for the full form. Approving without typing the ticker
 * is never reachable from anywhere.
 */

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

interface ProposalTarget {
  id: string
  ticker: string
  /** Live money is the only case that needs the typed confirmation. */
  isPaper: boolean
}

export function useProposalActions({ id, ticker, isPaper, onResolved }: ProposalTarget & {
  onResolved: () => void
}) {
  const { toast } = useToast()
  const [busy, setBusy] = useState<'approve' | 'decline' | null>(null)
  const [confirmText, setConfirmText] = useState('')

  const isLive = !isPaper
  const confirmed = !isLive || confirmText.trim().toUpperCase() === ticker.toUpperCase()

  const approve = async () => {
    if (busy || !confirmed) return
    setBusy('approve')
    try {
      const { data } = await tradingApi.approveProposal(id, isLive)
      if (data.placed) {
        toast(
          `Order placed: ${data.qty} ${data.ticker} at ${usd.format(data.limit_price)}`
          + (data.is_paper ? ' (paper)' : '')
          + (data.trade_id ? ` — Ref ${data.trade_id.slice(-8).toUpperCase()}` : ''),
          'success',
        )
      } else {
        toast(data.reason ?? 'The order was not placed.', 'error')
      }
      onResolved()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast(detail ?? 'Could not approve that proposal.', 'error')
    } finally {
      setBusy(null)
    }
  }

  const decline = async () => {
    if (busy) return
    setBusy('decline')
    try {
      await tradingApi.declineProposal(id)
      toast(`Skipped ${ticker}.`, 'info')
      onResolved()
    } catch {
      toast('Could not skip that proposal.', 'error')
    } finally {
      setBusy(null)
    }
  }

  return { busy, confirmText, setConfirmText, isLive, confirmed, approve, decline }
}

/** The full form: the typed confirmation for live money, then Approve / Skip. */
export function ProposalActions({ id, ticker, isPaper, onResolved }: ProposalTarget & {
  onResolved: () => void
}) {
  const { busy, confirmText, setConfirmText, isLive, confirmed, approve, decline } =
    useProposalActions({ id, ticker, isPaper, onResolved })

  return (
    <>
      {isLive && (
        <div className="mt-2">
          <label
            htmlFor={`confirm-${id}`}
            className="mb-1 block text-[10.5px] text-[var(--accent-sell)]"
          >
            Type <strong>{ticker}</strong> to approve a live order
          </label>
          <input
            id={`confirm-${id}`}
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            autoComplete="off"
            className="h-11 w-full rounded-md border border-[var(--accent-sell)] bg-[var(--color-bg)]
                       px-2 text-[12px] text-[var(--color-fg)] outline-none sm:h-7"
          />
        </div>
      )}

      <div className="mt-2 flex gap-1.5">
        <button
          onClick={approve}
          disabled={!!busy || !confirmed}
          className="flex h-11 flex-1 items-center justify-center gap-1.5 rounded-md bg-brand-500
                     text-[12px] font-semibold text-white disabled:opacity-40 sm:h-7"
        >
          {busy === 'approve' ? <LoadingSpinner size="sm" /> : null}
          Approve
        </button>
        <button
          onClick={decline}
          disabled={!!busy}
          className="h-11 flex-1 rounded-md border border-[var(--color-border)] text-[12px]
                     text-[var(--color-fg)] hover:bg-[var(--color-hover)] disabled:opacity-40 sm:h-7"
        >
          Reject
        </button>
      </div>
    </>
  )
}

/**
 * The row form. Two chips, no input.
 *
 * A paper proposal resolves in place. A live one routes to wherever the typed
 * confirmation can actually be shown — the row never approves live money.
 */
export function ProposalRowActions({
  id, ticker, isPaper, onResolved, onNeedsConfirmation,
}: ProposalTarget & {
  onResolved: () => void
  onNeedsConfirmation: () => void
}) {
  const { busy, isLive, approve, decline } =
    useProposalActions({ id, ticker, isPaper, onResolved })

  return (
    <div className="flex items-center justify-end gap-1">
      <button
        onClick={(e) => {
          e.stopPropagation()
          if (isLive) onNeedsConfirmation()
          else void approve()
        }}
        disabled={!!busy}
        className="rounded bg-brand-500 px-2 py-1 text-[11px] font-semibold text-white
                   disabled:opacity-40"
        title={isLive ? `Live money — confirm ${ticker} on the transaction page` : undefined}
      >
        {busy === 'approve' ? '…' : 'Approve'}
      </button>
      <button
        onClick={(e) => { e.stopPropagation(); void decline() }}
        disabled={!!busy}
        className="rounded border border-[var(--color-border)] px-2 py-1 text-[11px]
                   text-[var(--color-fg)] hover:bg-[var(--color-hover)] disabled:opacity-40"
      >
        {busy === 'decline' ? '…' : 'Reject'}
      </button>
    </div>
  )
}
