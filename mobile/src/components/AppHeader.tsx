import React from 'react'
import { View, Text } from 'react-native'
import { usePalette } from '../lib/palette'
import { useAccount } from '../lib/use-account'
import LogoLockup from './LogoLockup'

/**
 * Brand lockup and account badge, at the top of every destination.
 *
 * Mobile carried no logo or product name on any screen once you were past the
 * login page — the app identified itself only by its tab bar. The web header
 * shows the mark on every route, and this is its phone counterpart.
 *
 * The right-hand slot holds net liquidation, the one account figure worth
 * carrying on every screen: it is what the position cap is measured against,
 * and it answers "how much is this account worth" without a trip to Positions.
 * The volatile figures — available, in trade, unrealised — stay in the Trade
 * strip rather than being crushed into a badge.
 *
 * This is a mobile-only arrangement. The web header has its own account bar and
 * is not affected.
 */

const usd = new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', maximumFractionDigits: 0,
})

function AccountBadge() {
  const C = usePalette()
  const { account, loading } = useAccount()

  const connected = !!account?.connected
  const value = loading ? '—'
    : connected ? usd.format(account!.net_liquidation)
      : 'Offline'

  return (
    <View
      accessibilityRole="summary"
      accessibilityLabel={
        connected
          ? `Account net liquidation ${value}`
          : 'Broker disconnected — balances unavailable'
      }
      style={{
        minWidth: 92,
        borderRadius: 10,
        borderWidth: 1,
        borderColor: C.border,
        backgroundColor: C.surface,
        paddingHorizontal: 10,
        paddingVertical: 7,
        alignItems: 'flex-end',
        gap: 2,
      }}
    >
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
        <View style={{
          width: 5, height: 5, borderRadius: 2.5,
          backgroundColor: connected ? C.green : C.fgMuted,
        }} />
        <Text style={{
          fontSize: 8, fontWeight: '700', color: C.fgMuted,
          textTransform: 'uppercase', letterSpacing: 0.7,
        }}>
          Net liq
        </Text>
      </View>
      <Text
        numberOfLines={1}
        style={{ fontSize: 13, fontWeight: '700', color: connected ? C.fg : C.fgMuted }}
      >
        {value}
      </Text>
    </View>
  )
}

export default function AppHeader() {
  return (
    <View style={{
      flexDirection: 'row', alignItems: 'center',
      justifyContent: 'space-between', marginBottom: 18,
    }}>
      <LogoLockup />
      <AccountBadge />
    </View>
  )
}
