import React from 'react'
import { View, Text, ActivityIndicator } from 'react-native'
import { usePalette, type Palette } from '../lib/palette'
import { useAccount } from '../lib/use-account'

/**
 * Broker balances on the Trade screen — the phone counterpart of the web
 * `AccountBar`.
 *
 * The web app carries this strip under the header on every page, so the money
 * you are trading against is always on screen. Mobile had no equivalent at all:
 * balances existed only on Positions, which meant deciding whether to buy meant
 * leaving the screen that was asking you to.
 *
 * Carries the three figures that move intraday, in the same order as web.
 * Net liquidation is the least volatile of the four — web drops it first on a
 * narrow viewport — so on mobile it lives in the header badge instead, leaving
 * this row to the numbers that actually change while you are looking at them.
 */

const usd = new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', maximumFractionDigits: 0,
})

function money(v: number | null | undefined): string {
  return v == null ? '—' : usd.format(v)
}

const cardStyle = (C: Palette) => ({
  backgroundColor: C.surface, borderRadius: 12, borderWidth: 1,
  borderColor: C.border, paddingHorizontal: 14, paddingVertical: 11,
  marginBottom: 16,
}) as const

function Field({ label, value, color }: { label: string; value: string; color?: string }) {
  const C = usePalette()
  return (
    <View style={{ flex: 1, gap: 2 }}>
      <Text style={{
        fontSize: 9, fontWeight: '700', color: C.fgMuted,
        textTransform: 'uppercase', letterSpacing: 0.7,
      }}>
        {label}
      </Text>
      <Text numberOfLines={1} style={{ fontSize: 13.5, fontWeight: '600', color: color ?? C.fg }}>
        {value}
      </Text>
    </View>
  )
}

export default function AccountStrip() {
  const C = usePalette()
  const card = cardStyle(C)
  const { account, loading } = useAccount()

  if (loading) {
    return (
      <View style={[card, { flexDirection: 'row', alignItems: 'center', gap: 8 }]}>
        <ActivityIndicator size="small" color={C.fgMuted} />
        <Text style={{ fontSize: 11, color: C.fgMuted }}>Loading balances…</Text>
      </View>
    )
  }

  if (!account?.connected) {
    return (
      <View style={[card, { flexDirection: 'row', alignItems: 'center', gap: 8 }]}>
        <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: C.fgMuted }} />
        <Text style={{ fontSize: 11, color: C.fgMuted }}>
          Broker disconnected — balances unavailable
        </Text>
      </View>
    )
  }

  const pnl = account.unrealized_pnl
  const pnlColor = pnl == null ? undefined
    : pnl < -0.005 ? C.red
      : pnl > 0.005 ? C.green : undefined

  return (
    <View style={card}>
      <View style={{
        flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 9,
      }}>
        <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: C.green }} />
        <Text style={{ fontSize: 11, fontWeight: '600', color: C.fgMuted }}>IBKR</Text>
        <Text numberOfLines={1} style={{ fontSize: 11, color: C.fgMuted, flex: 1 }}>
          {account.account_id || '—'}
        </Text>
      </View>

      <View style={{ flexDirection: 'row', gap: 10 }}>
        <Field label="Available" value={money(account.buying_power)} />
        <Field label="In trade" value={money(account.gross_position_value)} />
        <Field
          label="Unrealised"
          value={pnl != null && pnl < -0.005 ? `(${money(Math.abs(pnl))})` : money(pnl)}
          color={pnlColor}
        />
      </View>
    </View>
  )
}
