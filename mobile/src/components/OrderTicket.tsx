import React, { useEffect, useRef, useState } from 'react'
import { ActivityIndicator, Pressable, Text, TextInput, View } from 'react-native'
import { AlertTriangle, ShoppingCart, WifiOff, X } from 'lucide-react-native'
import { tradingApi } from '../lib/api'
import { useToast } from '../lib/toast-context'
import type { AnalyzeResponse, AutoTradeSettingsResponse } from '../types'
import { usePalette } from '../lib/palette'

/**
 * Buy ticket for the mobile ticker screen — the phone counterpart of the web
 * `OrderTicket`.
 *
 * Same two refusals as the web version:
 *   - The displayed quantity is never authoritative. The server re-derives the
 *     fundable size and may return less; what comes back is what happened.
 *   - A live-money order cannot go through on one tap. `confirm_live` is only
 *     set after the user types the ticker back.
 *
 * Selling is not here. Closing a position must cancel the working bracket
 * first and size to what the broker actually holds — that is the Orders tab.
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
  price: number, equity: number, positionSizePct: number, vol?: number | null,
): number {
  if (price <= 0 || equity <= 0) return 0
  return Math.max(1, Math.floor((equity * positionSizePct * volatilityFactor(vol)) / price))
}

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

function Row({ label, value, tone }: { label: string; value: string; tone?: string }) {
  const C = usePalette()
  return (
    <View style={{ flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 2 }}>
      <Text style={{ fontSize: 12, color: C.fgMuted }}>{label}</Text>
      <Text style={{ fontSize: 12, color: tone ?? C.fg, fontVariant: ['tabular-nums'] }}>
        {value}
      </Text>
    </View>
  )
}

export default function OrderTicket({ data }: { data: AnalyzeResponse }) {
  const C = usePalette()
  const { toast } = useToast()
  const [open, setOpen] = useState(false)
  const [settings, setSettings] = useState<AutoTradeSettingsResponse | null>(null)
  const [equity, setEquity] = useState<number | null>(null)
  const [qty, setQty] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [confirmText, setConfirmText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [idempotencyKey, setIdempotencyKey] = useState('')

  useEffect(() => {
    if (!open) return
    // A key per opening, so a double-tap sends one order but a deliberate
    // second order later still gets through.
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

  // Fill in the suggestion once it can be computed, but never over a number the
  // user typed. The `qty === ''` guard this replaces got the common case right
  // and one case wrong: clearing the field to retype snapped the suggestion
  // straight back in, so the first digit landed after it. `touched` separates
  // "has not chosen yet" from "chose, and we are about to overrule them".
  const touched = useRef(false)

  useEffect(() => {
    if (touched.current) return
    if (suggested > 0) setQty(String(suggested))
  }, [suggested])

  // A new opening is a fresh decision — drop any quantity from the last one.
  useEffect(() => {
    if (!open) touched.current = false
  }, [open])

  const parsedQty = Number(qty) || 0
  const notional = parsedQty * price
  const liveConfirmed =
    !isLive || confirmText.trim().toUpperCase() === data.ticker.toUpperCase()

  const submit = async () => {
    if (submitting || !liveConfirmed || parsedQty < 1) return
    setSubmitting(true)
    setError(null)
    try {
      const { data: r } = await tradingApi.placeOrder({
        ticker: data.ticker,
        action: 'BUY',
        qty: parsedQty,
        confirm_live: isLive,
        idempotency_key: idempotencyKey,
      })

      if (r.duplicate) {
        toast('That order was already submitted.', 'info')
        setOpen(false)
      } else if (r.placed) {
        // Report what the server did, not what was requested — the quantity
        // may have been cut to fit available funds.
        toast(
          `Order placed: ${r.qty} ${data.ticker} at ${usd.format(r.limit_price)}`
          + (r.is_paper ? ' (paper)' : ''),
          'success',
        )
        if (r.reason) toast(r.reason, 'info')
        setOpen(false)
        setConfirmText('')
      } else {
        setError(r.reason ?? 'The order was not placed.')
      }
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setError(
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
      <Pressable
        onPress={() => setOpen(true)}
        accessibilityRole="button"
        style={{
          flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8,
          backgroundColor: C.brand, borderRadius: 10, paddingVertical: 12,
        }}
      >
        <ShoppingCart size={16} color="#fff" />
        <Text style={{ color: '#fff', fontWeight: '700', fontSize: 14 }}>
          Buy {data.ticker}
        </Text>
      </Pressable>
    )
  }

  return (
    <View style={{
      backgroundColor: C.bg, borderRadius: 12, borderWidth: 1,
      borderColor: C.border, padding: 14, gap: 12,
    }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
        <Text style={{ fontSize: 14, fontWeight: '700', color: C.fg }}>
          Buy {data.ticker}
        </Text>
        <Pressable
          onPress={() => { setOpen(false); setError(null); setConfirmText('') }}
          accessibilityLabel="Close order ticket"
          hitSlop={8}
        >
          <X size={16} color={C.fgMuted} />
        </Pressable>
      </View>

      {!connected ? (
        <View style={{ flexDirection: 'row', gap: 8, alignItems: 'flex-start' }}>
          <WifiOff size={14} color={C.fgMuted} style={{ marginTop: 2 }} />
          <Text style={{ flex: 1, fontSize: 12, color: C.fgMuted, lineHeight: 17 }}>
            Broker disconnected — orders cannot be placed. Start IB Gateway and try again.
          </Text>
        </View>
      ) : (
        <>
          {/* Paper vs live is the single most important fact on this screen. */}
          <View style={{
            flexDirection: 'row', gap: 8, alignItems: 'flex-start',
            backgroundColor: isLive ? `${C.red}1a` : `${C.border}80`,
            borderRadius: 8, padding: 10,
          }}>
            <AlertTriangle size={14} color={isLive ? C.red : C.fgMuted} style={{ marginTop: 1 }} />
            <Text style={{
              flex: 1, fontSize: 11, lineHeight: 16,
              color: isLive ? C.red : C.fgMuted,
            }}>
              {isLive
                ? 'This routes to your LIVE account and spends real money.'
                : 'Paper trading — this is a simulated order.'}
            </Text>
          </View>

          <View style={{ gap: 4 }}>
            <Text style={{ fontSize: 12, color: C.fgMuted }}>Quantity</Text>
            <TextInput
              value={qty}
              onChangeText={(t) => { touched.current = true; setQty(t) }}
              keyboardType="number-pad"
              accessibilityLabel="Order quantity"
              style={{
                borderWidth: 1, borderColor: C.border, borderRadius: 8,
                paddingHorizontal: 12, paddingVertical: 10,
                fontSize: 14, color: C.fg, backgroundColor: C.surface,
              }}
            />
            {suggested > 0 && (
              <Text style={{ fontSize: 10, color: C.fgMuted }}>
                Sized at {(settings!.position_size_pct * 100).toFixed(0)}% of equity
              </Text>
            )}
          </View>

          {/* The levels the server will actually attach. */}
          <View style={{ gap: 2 }}>
            <Row label="Limit price" value={price > 0 ? usd.format(price) : '—'} />
            <Row label="Estimated cost" value={notional > 0 ? usd.format(notional) : '—'} />
            {data.stop_loss != null && (
              <Row label="Stop loss" value={usd.format(data.stop_loss)} tone={C.red} />
            )}
            {data.price_target != null && (
              <Row label="Take profit" value={usd.format(data.price_target)} tone={C.green} />
            )}
          </View>

          {isLive && (
            <View style={{ gap: 4 }}>
              <Text style={{ fontSize: 11, color: C.red }}>
                Live money — type {data.ticker} to confirm
              </Text>
              <TextInput
                value={confirmText}
                onChangeText={setConfirmText}
                autoCapitalize="characters"
                autoCorrect={false}
                accessibilityLabel="Type the ticker to confirm a live order"
                style={{
                  borderWidth: 1, borderColor: C.red, borderRadius: 8,
                  paddingHorizontal: 12, paddingVertical: 10,
                  fontSize: 14, color: C.fg, backgroundColor: C.surface,
                }}
              />
            </View>
          )}

          {error && (
            <Text style={{ fontSize: 11, color: C.red, lineHeight: 16 }}>{error}</Text>
          )}

          <Pressable
            onPress={submit}
            disabled={submitting || parsedQty < 1 || !liveConfirmed}
            accessibilityRole="button"
            style={{
              flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8,
              backgroundColor: C.brand, borderRadius: 10, paddingVertical: 12,
              opacity: submitting || parsedQty < 1 || !liveConfirmed ? 0.4 : 1,
            }}
          >
            {submitting
              ? <ActivityIndicator size="small" color="#fff" />
              : <ShoppingCart size={16} color="#fff" />}
            <Text style={{ color: '#fff', fontWeight: '700', fontSize: 14 }}>
              {submitting ? 'Placing…' : `Place ${isLive ? 'LIVE' : 'paper'} order`}
            </Text>
          </Pressable>

          <Text style={{ fontSize: 10, color: C.fgMuted, lineHeight: 15 }}>
            The server re-checks position limits, your daily loss cap, and available funds
            before sending this, and will reduce the quantity if it must. Nothing here
            bypasses the risk guards the agent obeys.
          </Text>
        </>
      )}
    </View>
  )
}
