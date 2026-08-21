import { useEffect, useState } from 'react'
import { AlertTriangle, ShoppingCart, WifiOff, X } from 'lucide-react'
import { tradingApi } from '../lib/api'
import { useToast } from '../lib/toast-context'
import type { AnalyzeResponse, AutoTradeSettingsResponse } from '../types'
import LoadingSpinner from './LoadingSpinner'

/**
 * Buy ticket, pre-filled from what the engine already computed.
 *
 * Before this, a BUY verdict was a dead end — you read it, then went to the
 * broker in another tab. The quantity, stop, and target here are the same
 * numbers `trade_manager` would have used, so the manual path and the
 * automated path place the same order.
 *
 * Two things this deliberately does NOT do:
 *   - Send the displayed quantity as authoritative. The server re-derives the
 *     fundable size and may return less; whatever comes back is what happened.
 *   - Let a live-money order through on one click. `confirm_live` is only set
 *     after the user types the ticker back.
 *
 * Selling is not here. Closing a position has to cancel the working bracket
 * first and size to what the broker actually holds — that is
 * `POST /trading/close/{ticker}`, surfaced on the Orders page.
 */

/** Mirrors trade_manager._volatility_size_factor so the preview matches the fill. */
const SIZING_PIVOT_VOL = 0.35
const SIZING_MIN_FACTOR = 0.35
const SIZING_MAX_FACTOR = 1.5

function volatilityFactor(vol?: number | null): number {
  if (!vol || vol <= 0) return 1
  return Math.max(SIZING_MIN_FACTOR, Math.min(SIZING_MAX_FACTOR, SIZING_PIVOT_VOL / vol))
}

function estimateQty(
  price: number,
  equity: number,
  positionSizePct: number,
  vol?: number | null,
): number {
  if (price <= 0 || equity <= 0) return 0
  return Math.max(1, Math.floor((equity * positionSizePct * volatilityFactor(vol)) / price))
}

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

export default function OrderTicket({
  data,
  onPlaced,
}: {
  data: AnalyzeResponse
  onPlaced?: () => void
}) {
  const { toast } = useToast()
  const [open, setOpen] = useState(false)
  const [settings, setSettings] = useState<AutoTradeSettingsResponse | null>(null)
  const [equity, setEquity] = useState<number | null>(null)
  const [qty, setQty] = useState<string>('')
  const [submitting, setSubmitting] = useState(false)
  const [confirmText, setConfirmText] = useState('')
  const [result, setResult] = useState<string | null>(null)

  // A key per opening of the ticket, so a double-click sends one order but a
  // deliberate second order later is still allowed through.
  const [idempotencyKey, setIdempotencyKey] = useState('')

  useEffect(() => {
    if (!open) return
    setIdempotencyKey(
      `${data.ticker}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    )
    Promise.all([
      tradingApi.getSettings().catch(() => null),
      tradingApi.getAccount().catch(() => null),
    ]).then(([s, a]) => {
      if (s) setSettings(s.data)
      if (a) setEquity(a.data.connected ? a.data.net_liquidation : null)
    })
  }, [open, data.ticker])

  const price = data.current_price ?? 0
  const isLive = settings ? !settings.paper_trading : false
  const connected = settings?.connected ?? false

  const suggested = settings && equity
    ? estimateQty(price, equity, settings.position_size_pct, null)
    : 0

  useEffect(() => {
    if (suggested > 0 && qty === '') setQty(String(suggested))
  }, [suggested, qty])

  const parsedQty = Number(qty) || 0
  const notional = parsedQty * price
  const liveConfirmed = !isLive || confirmText.trim().toUpperCase() === data.ticker.toUpperCase()

  const submit = async () => {
    if (submitting || !liveConfirmed) return
    setSubmitting(true)
    setResult(null)
    try {
      const res = await tradingApi.placeOrder({
        ticker: data.ticker,
        action: 'BUY',
        qty: parsedQty > 0 ? parsedQty : undefined,
        confirm_live: isLive,
        idempotency_key: idempotencyKey,
      })
      const r = res.data

      if (r.duplicate) {
        toast('That order was already submitted.', 'info')
      } else if (r.placed) {
        // Report what the server actually did, not what was requested — the
        // quantity may have been cut to fit available funds.
        toast(
          `Order placed: ${r.qty} ${data.ticker} at ${usd.format(r.limit_price)}`
          + (r.is_paper ? ' (paper)' : ''),
          'success',
        )
        setOpen(false)
        setConfirmText('')
        onPlaced?.()
      } else {
        setResult(r.reason ?? 'The order was not placed.')
      }

      if (r.placed && r.reason) {
        // e.g. "reduced to available funds" — a success worth explaining.
        toast(r.reason, 'info')
      }
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setResult(
        status === 428
          ? 'This account trades live money — confirm to continue.'
          : detail ?? 'Could not place the order.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} className="btn-primary w-full sm:w-auto">
        <ShoppingCart className="w-4 h-4" />
        Buy {data.ticker}
      </button>
    )
  }

  return (
    <div className="flex flex-col gap-3 p-4 rounded-xl border border-[var(--color-border)]
                    bg-[var(--color-bg)]">
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-[var(--color-fg)]">
          Buy {data.ticker}
        </span>
        <button
          onClick={() => { setOpen(false); setResult(null); setConfirmText('') }}
          aria-label="Close order ticket"
          className="text-[var(--color-fg-muted)] hover:text-[var(--color-fg)]"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {!connected ? (
        <div className="flex items-start gap-2 text-xs text-[var(--color-fg-muted)]">
          <WifiOff className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
          <p>
            Broker disconnected — orders cannot be placed. Start IB Gateway and try again.
          </p>
        </div>
      ) : (
        <>
          {/* Mode banner: paper vs live is the single most important fact here. */}
          <div className={`flex items-start gap-2 px-3 py-2 rounded-lg text-xs ${
            isLive
              ? 'bg-red-500/10 text-[var(--accent-sell)]'
              : 'bg-[var(--color-border)]/50 text-[var(--color-fg-muted)]'
          }`}>
            <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
            <p>
              {isLive
                ? 'This routes to your LIVE account and spends real money.'
                : 'Paper trading — this is a simulated order.'}
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1">
              <label htmlFor="order-qty" className="text-xs text-[var(--color-fg-muted)]">
                Quantity
              </label>
              <input
                id="order-qty"
                type="number"
                min={1}
                value={qty}
                onChange={(e) => setQty(e.target.value)}
                className="input text-sm"
              />
              {suggested > 0 && (
                <span className="text-[0.65rem] text-[var(--color-fg-muted)]">
                  Sized at {(settings!.position_size_pct * 100).toFixed(0)}% of equity
                </span>
              )}
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-xs text-[var(--color-fg-muted)]">Limit price</span>
              <div className="input text-sm flex items-center tabular-nums
                              text-[var(--color-fg)] cursor-default">
                {price > 0 ? usd.format(price) : '—'}
              </div>
              <span className="text-[0.65rem] text-[var(--color-fg-muted)]">
                Last known price
              </span>
            </div>
          </div>

          {/* Bracket preview — the levels the server will actually attach. */}
          <div className="flex flex-col gap-1 text-xs">
            <div className="flex justify-between">
              <span className="text-[var(--color-fg-muted)]">Estimated cost</span>
              <span className="tabular-nums text-[var(--color-fg)]">
                {notional > 0 ? usd.format(notional) : '—'}
              </span>
            </div>
            {data.stop_loss != null && (
              <div className="flex justify-between">
                <span className="text-[var(--color-fg-muted)]">Stop loss</span>
                <span className="tabular-nums text-[var(--accent-sell)]">
                  {usd.format(data.stop_loss)}
                </span>
              </div>
            )}
            {data.price_target != null && (
              <div className="flex justify-between">
                <span className="text-[var(--color-fg-muted)]">Take profit</span>
                <span className="tabular-nums text-[var(--accent-buy)]">
                  {usd.format(data.price_target)}
                </span>
              </div>
            )}
          </div>

          {isLive && (
            <div className="flex flex-col gap-1">
              <label htmlFor="confirm-live" className="text-xs text-[var(--accent-sell)]">
                Type <strong>{data.ticker}</strong> to confirm a live order
              </label>
              <input
                id="confirm-live"
                type="text"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                autoComplete="off"
                className="input text-sm"
              />
            </div>
          )}

          {result && (
            <p className="text-xs text-[var(--accent-sell)] leading-relaxed">{result}</p>
          )}

          <button
            onClick={submit}
            disabled={submitting || parsedQty < 1 || !liveConfirmed}
            className="btn-primary w-full"
          >
            {submitting ? <LoadingSpinner size="sm" /> : <ShoppingCart className="w-4 h-4" />}
            {submitting
              ? 'Placing…'
              : `Place ${isLive ? 'LIVE ' : 'paper '}order`}
          </button>

          <p className="text-[0.65rem] text-[var(--color-fg-muted)] leading-relaxed">
            The server re-checks position limits, your daily loss cap, and available
            funds before sending this, and will reduce the quantity if it must. Nothing
            here bypasses the risk guards the agent obeys.
          </p>
        </>
      )}
    </div>
  )
}
