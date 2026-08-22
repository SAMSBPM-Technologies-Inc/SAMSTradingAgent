import React, { useState } from 'react'
import { ActivityIndicator, Pressable, ScrollView, Text, View } from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { AlertCircle, RefreshCw, Wallet } from 'lucide-react-native'
import { tradingApi } from '../../src/lib/api'
import type { HoldingsResponse } from '../../src/types'
import Disclaimer from '../../src/components/Disclaimer'

/**
 * Holdings straight from the broker, fetched only when asked for.
 *
 * Deliberately not loaded on mount, matching the web screen: each fetch costs a
 * broker round-trip, and unlike the watchlist this is not something to poll in
 * the background. The user decides when the number matters.
 *
 * P&L follows the broker-statement convention used across the app — gains
 * green, losses red in parentheses, exact zero neutral.
 */

const C = {
  bg: '#f5f2ed', surface: '#ffffff', fg: '#14110c',
  fgMuted: '#83786a', border: '#e7e2d8', brand: '#f2600c',
  red: '#b91c1c', green: '#15803d',
}

const usd = new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD',
  minimumFractionDigits: 2, maximumFractionDigits: 2,
})

function money(v: number | null | undefined): string {
  return v == null ? '—' : usd.format(Math.abs(v))
}

function SignedMoney({ value, size = 12 }: { value: number | null | undefined; size?: number }) {
  if (value == null) return <Text style={{ color: C.fgMuted, fontSize: size }}>—</Text>
  const loss = value < -0.005
  const gain = value > 0.005
  return (
    <Text style={{
      fontSize: size, fontVariant: ['tabular-nums'],
      color: loss ? C.red : gain ? C.green : C.fg,
    }}>
      {loss ? `(${money(value)})` : money(value)}
    </Text>
  )
}

/**
 * Last fetch, held at module scope so it survives this screen unmounting as the
 * user moves between tabs. In memory rather than persisted: a fresh app launch
 * should clear it, because presenting a stale snapshot as current is worse than
 * showing the empty state and letting the user ask again.
 */
let cachedData: HoldingsResponse | null = null
let cachedAt: Date | null = null

export default function HoldingsScreen() {
  const [data, setData] = useState<HoldingsResponse | null>(cachedData)
  const [fetchedAt, setFetchedAt] = useState<Date | null>(cachedAt)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const { data: res } = await tradingApi.getHoldings()
      const now = new Date()
      setData(res)
      setFetchedAt(now)
      cachedData = res
      cachedAt = now
    } catch {
      // Keep whatever is on screen — a failed refresh should not wipe a
      // snapshot the user still finds useful.
      setError('Could not reach the broker. Check the connection and try again.')
    } finally {
      setLoading(false)
    }
  }

  const totalPnl = (data?.holdings ?? []).reduce(
    (sum, h) => sum + (h.unrealized_pnl ?? 0), 0,
  )

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.bg }} edges={['top']}>
      <ScrollView contentContainerStyle={{ paddingHorizontal: 16, paddingTop: 20, paddingBottom: 100 }}>
        <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
          <View style={{ flex: 1 }}>
            <Text style={{ fontSize: 24, fontWeight: '300', color: C.fg }}>Holdings</Text>
            <Text style={{ fontSize: 12, color: C.fgMuted, marginTop: 2 }}>
              {fetchedAt
                ? `As of ${fetchedAt.toLocaleTimeString()}`
                : 'Live positions, fetched on demand'}
            </Text>
          </View>
          <Pressable
            onPress={load}
            disabled={loading}
            accessibilityRole="button"
            style={{
              flexDirection: 'row', alignItems: 'center', gap: 6,
              backgroundColor: C.brand, borderRadius: 9,
              paddingHorizontal: 14, paddingVertical: 9,
              opacity: loading ? 0.6 : 1,
            }}
          >
            {loading
              ? <ActivityIndicator size="small" color="#fff" />
              : <RefreshCw size={14} color="#fff" />}
            <Text style={{ color: '#fff', fontWeight: '700', fontSize: 12 }}>
              {data ? 'Refresh' : 'Load'}
            </Text>
          </Pressable>
        </View>

        {error && (
          <View style={{
            flexDirection: 'row', gap: 10, alignItems: 'center', marginTop: 16,
            backgroundColor: 'rgba(185,28,28,0.10)', borderRadius: 10, padding: 12,
          }}>
            <AlertCircle size={16} color={C.red} />
            <Text style={{ flex: 1, fontSize: 12, color: C.red }}>{error}</Text>
          </View>
        )}

        {/* Nothing fetched yet — say so plainly rather than showing an empty table. */}
        {!data && !loading && !error && (
          <View style={{
            marginTop: 20, backgroundColor: C.surface, borderRadius: 12,
            borderWidth: 1, borderColor: C.border, padding: 28,
            alignItems: 'center', gap: 12,
          }}>
            <Wallet size={26} color={C.fgMuted} />
            <Text style={{ fontSize: 13, color: C.fgMuted, textAlign: 'center', lineHeight: 19 }}>
              Holdings aren&rsquo;t loaded automatically.{'\n'}
              Tap <Text style={{ color: C.fg, fontWeight: '600' }}>Load</Text> to fetch them
              from your broker.
            </Text>
          </View>
        )}

        {data && !data.connected && (
          <View style={{
            marginTop: 20, backgroundColor: C.surface, borderRadius: 12,
            borderWidth: 1, borderColor: C.border, padding: 24, alignItems: 'center',
          }}>
            <Text style={{ fontSize: 13, color: C.fgMuted }}>
              Broker disconnected — holdings unavailable.
            </Text>
          </View>
        )}

        {data?.connected && data.holdings.length === 0 && (
          <View style={{
            marginTop: 20, backgroundColor: C.surface, borderRadius: 12,
            borderWidth: 1, borderColor: C.border, padding: 24, alignItems: 'center',
          }}>
            <Text style={{ fontSize: 13, color: C.fgMuted }}>
              No open positions in {data.account_id || 'this account'}.
            </Text>
          </View>
        )}

        {data?.connected && data.holdings.length > 0 && (
          <View style={{
            marginTop: 20, backgroundColor: C.surface, borderRadius: 12,
            borderWidth: 1, borderColor: C.border, overflow: 'hidden',
          }}>
            <View style={{
              flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
              paddingHorizontal: 14, paddingVertical: 10,
              borderBottomWidth: 1, borderBottomColor: C.border,
            }}>
              <Text style={{
                fontSize: 9, color: C.fgMuted, textTransform: 'uppercase', letterSpacing: 1,
              }}>
                {data.account_id || '—'} · {data.holdings.length}{' '}
                {data.holdings.length === 1 ? 'position' : 'positions'}
              </Text>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                <Text style={{ fontSize: 10, color: C.fgMuted }}>Unrealised</Text>
                <SignedMoney value={totalPnl} size={13} />
              </View>
            </View>

            {data.holdings.map((h, i) => (
              <View
                key={h.ticker}
                style={{
                  paddingHorizontal: 14, paddingVertical: 12, gap: 6,
                  borderTopWidth: i === 0 ? 0 : 1, borderTopColor: `${C.border}80`,
                }}
              >
                <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Text style={{ fontSize: 14, fontWeight: '700', color: C.fg }}>{h.ticker}</Text>
                  <SignedMoney value={h.unrealized_pnl} size={13} />
                </View>
                <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
                  <Text style={{ fontSize: 11, color: C.fgMuted, fontVariant: ['tabular-nums'] }}>
                    {h.qty.toLocaleString()} @ {money(h.avg_cost)}
                  </Text>
                  <Text style={{ fontSize: 11, color: C.fg, fontVariant: ['tabular-nums'] }}>
                    {money(h.market_value)}
                  </Text>
                </View>
              </View>
            ))}

            <View style={{
              flexDirection: 'row', justifyContent: 'space-between',
              paddingHorizontal: 14, paddingVertical: 12,
              borderTopWidth: 1, borderTopColor: C.border,
            }}>
              <Text style={{
                fontSize: 9, color: C.fgMuted, textTransform: 'uppercase', letterSpacing: 1,
              }}>
                Total market value
              </Text>
              <Text style={{ fontSize: 13, fontWeight: '600', color: C.fg, fontVariant: ['tabular-nums'] }}>
                {money(data.total_market_value)}
              </Text>
            </View>
          </View>
        )}

        <Disclaimer />
      </ScrollView>
    </SafeAreaView>
  )
}
