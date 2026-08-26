import { useEffect, useMemo, useState } from 'react'
import { ShoppingCart, WifiOff } from 'lucide-react'
import { tradingApi } from '../lib/api'
import { useToast } from '../lib/toast-context'
import { useTradingSettings } from '../lib/trading-context'
import type { AnalyzeResponse } from '../types'
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
 * `POST /trading/close/{ticker}`, surfaced on the Positions screen.
 *
 * 1.7 moves it into the Trade screen's right rail, where it is always open
 * rather than behind a "Buy" button, and reads settings from the shared
 * context so the header's paper/live pill and this ticket cannot disagree
 * about where an order is going.
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

function Line({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="flex justify-between">
      <span className="text-[var(--color-fg-muted)]">{label}</span>
      <span className="num" style={{ color: color ?? 'var(--color-fg)' }}>{value}</span>
    </div>
  )
}

export default function OrderTicket({
  data,
  onPlaced,
}: {
  data: AnalyzeResponse
  onPlaced?: () => void
}) {
  const { toast } = useToast()
  const { settings } = useTradingSettings()
  const [equity, setEquity] = useState<number | null>(null)
  const [qty, setQty] = useState<string>('')
  const [submitting, setSubmitting] = useState(false)
  const [confirmText, setConfirmText] = useState('')
  const [result, setResult] = useState<string | null>(null)

  // A key per ticker per mount, so a double-click sends one order but a
  // deliberate second order later is still allowed through.
  const idempotencyKey = useMemo(
    () => `${data.ticker}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    [data.ticker],
  )

  useEffect(() => {
    let cancelled = false
    tradingApi.getAccount()
      .then(({ data: a }) => { if (!cancelled) setEquity(a.connected ? a.net_liquidation : null) })
      .catch(() => { if (!cancelled) setEquity(null) })
    return () => { cancelled = true }
  }, [])

  const price = data.current_price ?? 0
  const isLive = settings ? !settings.paper_trading : false
  const connected = settings?.connected ?? false

  const suggested = settings && equity
    ? estimateQty(price, equity, settings.position_size_pct, null)
    : 0

  // Switching ticker must reset the quantity — carrying 400 shares of a $3
  // stock onto a $900 one is how you accidentally ask for a $360,000 order.
  useEffect(() => {
    setQty(suggested > 0 ? String(suggested) : '')
    setConfirmText('')
    setResult(null)
  }, [data.ticker, suggested])

  const parsedQty = Number(qty) || 0
  const notional = parsedQty * price
  const liveConfirmed = !isLive || confirmText.trim().toUpperCase() === data.ticker.toUpperCase()

  // The risk gate is the engine's, not this component's — read it off the
  // response rather than re-deriving a second opinion here.
  const riskVetoed = data.gate ? !data.gate.risk_passes_buy : false

  const rr = data.stop_loss != null && data.price_target != null && price > 0
    && price > data.stop_loss && data.price_target > price
    ? (data.price_target - price) / (price - data.stop_loss)
    : null

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

  const banner = !connected
    ? { bg: 'var(--color-hover)', fg: 'var(--color-fg-muted)', text: 'Broker disconnected — orders cannot be placed. Start IB Gateway and try again.' }
    : isLive
      ? { bg: 'var(--tint-sell)', fg: 'var(--accent-sell)', text: 'This routes to your LIVE account and spends real money.' }
      : { bg: 'var(--color-hover)', fg: 'var(--color-fg-muted)', text: 'Paper trading — this is a simulated order.' }

  return (
    <div className="border-b border-[var(--color-border)] px-3.5 py-3">
      <div className="flex items-baseline justify-between">
        <span className="text-[14px] font-semibold" style={{ fontFamily: 'Archivo, system-ui, sans-serif' }}>
          Buy {data.ticker}
        </span>
        <span className="text-[11px] text-[var(--color-fg-muted)]">Market on submit</span>
      </div>

      <p
        className="mt-2.5 rounded-md px-2.5 py-2 text-[11px] leading-snug"
        style={{ background: banner.bg, color: banner.fg }}
      >
        {banner.text}
      </p>

      {/* The gate refused a BUY — say so here rather than letting someone
          discover it from a server rejection after they've clicked. */}
      {connected && riskVetoed && (
        <p
          className="mt-2 rounded-md px-2.5 py-2 text-[11px] leading-snug"
          style={{ background: 'var(--tint-hold)', color: 'var(--accent-hold)' }}
        >
          The risk gate vetoes a BUY on this name. You can still place an order — the
          gate restricts what the agent may pick, not what you may.
        </p>
      )}

      {connected && (
        <>
          <div className="mt-2.5 grid grid-cols-2 gap-2">
            <div>
              <label htmlFor="order-qty" className="label-micro mb-1 block">Quantity</label>
              <input
                id="order-qty"
                type="number"
                min={1}
                inputMode="numeric"
                value={qty}
                onChange={(e) => setQty(e.target.value)}
                className="num h-[30px] w-full rounded-md border border-[var(--color-border)]
                           bg-[var(--color-bg)] px-2.5 text-[13px] text-[var(--color-fg)]
                           outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
              />
              <p className="mt-1 text-[9.5px] text-[var(--color-fg-muted)]">
                {suggested > 0
                  ? `Sized at ${(settings!.position_size_pct * 100).toFixed(0)}% of equity`
                  : 'Sizing unavailable — enter a quantity'}
              </p>
            </div>
            <div>
              <span className="label-micro mb-1 block">Limit price</span>
              <div className="num flex h-[30px] items-center rounded-md border border-[var(--color-border)]
                              bg-[var(--color-bg)] px-2.5 text-[13px]">
                {price > 0 ? usd.format(price) : '—'}
              </div>
              <p className="mt-1 text-[9.5px] text-[var(--color-fg-muted)]">Last known price</p>
            </div>
          </div>

          {/* Bracket preview — the levels the server will actually attach. */}
          <div className="mt-2.5 flex flex-col gap-1 text-[11.5px]">
            <Line label="Estimated cost" value={notional > 0 ? usd.format(notional) : '—'} />
            {data.stop_loss != null && (
              <Line label="Stop loss" value={usd.format(data.stop_loss)} color="var(--accent-sell)" />
            )}
            {data.price_target != null && (
              <Line label="Take profit" value={usd.format(data.price_target)} color="var(--accent-buy)" />
            )}
            {rr != null && <Line label="Reward : risk" value={`${rr.toFixed(2)} : 1`} />}
          </div>

          {isLive && (
            <div className="mt-2.5">
              <label htmlFor="confirm-live" className="mb-1 block text-[11px] text-[var(--accent-sell)]">
                Type <strong>{data.ticker}</strong> to confirm a live order
              </label>
              <input
                id="confirm-live"
                type="text"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                autoComplete="off"
                className="h-[30px] w-full rounded-md border border-[var(--accent-sell)]
                           bg-[var(--color-bg)] px-2.5 text-[12.5px] text-[var(--color-fg)] outline-none"
              />
            </div>
          )}

          {result && (
            <p className="mt-2 text-[11px] leading-relaxed text-[var(--accent-sell)]">{result}</p>
          )}

          <button
            onClick={submit}
            disabled={submitting || parsedQty < 1 || !liveConfirmed}
            className="btn-primary mt-2.5 w-full"
          >
            {submitting ? <LoadingSpinner size="sm" /> : <ShoppingCart className="h-4 w-4" aria-hidden="true" />}
            {submitting ? 'Placing…' : `Place ${isLive ? 'LIVE ' : 'paper '}order`}
          </button>
        </>
      )}

      {!connected && (
        <p className="mt-2.5 flex items-start gap-2 text-[11px] text-[var(--color-fg-muted)]">
          <WifiOff className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
          Connect IB Gateway from Settings → Broker to enable the ticket.
        </p>
      )}

      <p className="mt-2 text-[10px] leading-relaxed text-[var(--color-fg-muted)]">
        The server re-checks position limits, your daily loss cap and available funds
        before sending, and reduces the quantity if it must. Nothing here bypasses the
        guards the agent obeys.
      </p>
    </div>
  )
}
