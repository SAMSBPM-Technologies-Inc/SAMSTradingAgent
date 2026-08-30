import React, { useCallback, useState } from 'react'
import {
  ActivityIndicator, Pressable, RefreshControl, ScrollView, Text, View,
} from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { router } from 'expo-router'
import { AlertCircle } from 'lucide-react-native'
import { tradingApi } from '../../src/lib/api'
import { useToast } from '../../src/lib/toast-context'
import { useRefreshOnFocus } from '../../src/lib/use-refresh'
import type { Holding, TradeRecord } from '../../src/types'
import ActivityList, { Pnl } from '../../src/components/ActivityList'
import Disclaimer from '../../src/components/Disclaimer'
import { usePalette } from '../../src/lib/palette'
import AppHeader from '../../src/components/AppHeader'

/**
 * Positions — what is held, and everything that has happened.
 *
 * The phone counterpart of the web Trade dashboard, and restructured along the
 * same line. It used to carry three lists: a proposal queue, the agent's own
 * tracked positions, and an order history. Those are one audit trail split into
 * three, and on a phone the split cost the most — the thing waiting on you and
 * the thing that explains it were two scrolls apart.
 *
 * Now: holdings, which is the broker's authority on what is owned, and Activity,
 * which is every action ever taken with the pending ones at the top. Tapping any
 * row opens the transaction, which carries the full record and the rest of that
 * ticker's history.
 *
 * Broker holdings load on mount rather than on demand as the old Holdings tab
 * did. That tab existed to be visited deliberately; this one is where you land,
 * and a screen called Positions that shows no positions until you press a
 * button reads as broken.
 */

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

function money(v: number | null | undefined): string {
  return v == null ? '—' : usd.format(v)
}

function SectionTitle({ children, note }: { children: string; note?: string }) {
  const C = usePalette()
  return (
    <View style={{ marginBottom: 10 }}>
      <Text style={{
        fontSize: 11, fontWeight: '700', color: C.fgMuted,
        textTransform: 'uppercase', letterSpacing: 1,
      }}>
        {children}
      </Text>
      {note && (
        <Text style={{ fontSize: 11, color: C.fgMuted, marginTop: 4, lineHeight: 16 }}>
          {note}
        </Text>
      )}
    </View>
  )
}

// ── Screen ────────────────────────────────────────────────────────────────────

export default function PositionsScreen() {
  const C = usePalette()
  const { toast, toastWithUndo } = useToast()
  const [orders, setOrders] = useState<TradeRecord[]>([])
  const [holdings, setHoldings] = useState<Holding[]>([])
  const [brokerConnected, setBrokerConnected] = useState(false)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  /**
   * One read, not three.
   *
   * `/trading/orders` already returns proposals — a PROPOSED record is a trade
   * row like any other — so the separate `/trading/proposals` call this screen
   * used to make was asking the server for a subset of what it had just been
   * given, and left two lists that could disagree about the same proposal for
   * as long as one of them was stale.
   */
  const load = useCallback(async () => {
    setError(null)
    try {
      const [ord, hold] = await Promise.all([
        tradingApi.getOrders(),
        tradingApi.getHoldings().catch(() => null),
      ])
      setOrders(ord.data)
      setBrokerConnected(hold?.data.connected ?? false)
      setHoldings(hold?.data.connected ? hold.data.holdings.filter((h) => h.qty !== 0) : [])
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setError(detail ?? 'Could not load your orders.')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  // Holdings, the proposal queue and order statuses all move without the phone
  // being told. A proposal waiting on you is the one thing here that should
  // never need a manual pull to appear.
  useRefreshOnFocus(load)

  const closePosition = (ticker: string) => {
    // Closing sends a real order, so it gets an undo window rather than a
    // confirm dialog — reversible right up until it is sent.
    toastWithUndo(
      `Closing ${ticker}…`,
      async () => {
        try {
          await tradingApi.closePosition(ticker)
          toast(`Close order submitted for ${ticker}.`, 'success')
          load()
        } catch (err: unknown) {
          const detail = (err as { response?: { data?: { detail?: string } } })
            ?.response?.data?.detail
          toast(detail ?? `Could not close ${ticker}.`, 'error')
        }
      },
      () => toast(`Kept ${ticker}.`, 'info'),
    )
  }

  const waiting = orders.filter((o) => o.status === 'PROPOSED').length

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.bg }} edges={['top']}>
      <ScrollView
        contentContainerStyle={{ paddingHorizontal: 16, paddingTop: 20, paddingBottom: 100 }}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => { setRefreshing(true); load() }}
            tintColor={C.brand}
          />
        }
      >
        <AppHeader />
        <Text style={{ fontSize: 24, fontWeight: '300', color: C.fg }}>Positions</Text>
        <Text style={{ fontSize: 13, color: C.fgMuted, marginTop: 2, marginBottom: 20 }}>
          What is held, what is waiting on you, and everything ever sent.
        </Text>

        {error && (
          <View style={{
            flexDirection: 'row', gap: 10, alignItems: 'center', marginBottom: 16,
            backgroundColor: `${C.red}1a`, borderRadius: 10, padding: 12,
          }}>
            <AlertCircle size={16} color={C.red} />
            <Text style={{ flex: 1, fontSize: 13, color: C.red }}>{error}</Text>
          </View>
        )}

        {loading ? (
          <View style={{ paddingVertical: 60, alignItems: 'center' }}>
            <ActivityIndicator size="large" color={C.brand} />
          </View>
        ) : (
          <>
            {/* ── Activity ─────────────────────────────────────────────────
                First, because the top of it is the part waiting on the
                reader. Holdings answer "what do I own"; this answers "what has
                been happening", which is the question that has an action
                attached to it. */}
            <View style={{ marginBottom: 28 }}>
              <SectionTitle note="Every attempt, including the ones the risk guards refused — a skip is a decision worth seeing. Proposed and Rejected never held a position: a proposal commits nothing until you accept it. Tap a row for the full record and that ticker's history.">
                {waiting > 0 ? `Activity — ${waiting} waiting on you` : 'Activity'}
              </SectionTitle>
              <ActivityList orders={orders} onProposalsChanged={load} />
            </View>

            {/* ── Holdings ─────────────────────────────────────────────────
                What the broker says is held, which is the authority. Our own
                records above say *why* each one exists — they are different
                questions and can legitimately disagree, so they are shown as
                two lists rather than silently reconciled here. */}
            <View style={{ marginBottom: 8 }}>
              <SectionTitle
                note={brokerConnected
                  ? 'Quantities come from the broker, not our records: if the two disagree, the broker is right.'
                  : 'Broker disconnected'}
              >
                {`Holdings (${holdings.length})`}
              </SectionTitle>
              {holdings.length === 0 ? (
                <View style={{
                  backgroundColor: C.surface, borderRadius: 12, borderWidth: 1,
                  borderColor: C.border, padding: 24, alignItems: 'center',
                }}>
                  <Text style={{ fontSize: 13, color: C.fgMuted, textAlign: 'center' }}>
                    {brokerConnected
                      ? 'No open positions in this account.'
                      : 'Broker disconnected — holdings unavailable.'}
                  </Text>
                </View>
              ) : (
                <View style={{
                  backgroundColor: C.surface, borderRadius: 12, borderWidth: 1,
                  borderColor: C.border, overflow: 'hidden',
                }}>
                  {holdings.map((h, i) => (
                    <View
                      key={h.ticker}
                      style={{
                        paddingHorizontal: 14, paddingVertical: 12, gap: 8,
                        borderTopWidth: i === 0 ? 0 : 1, borderTopColor: `${C.border}80`,
                      }}
                    >
                      <Pressable
                        onPress={() => router.push(`/ticker/${h.ticker}`)}
                        accessibilityRole="button"
                        accessibilityLabel={`${h.ticker}, ${h.qty} shares`}
                        style={{ gap: 6 }}
                      >
                        <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
                          <Text style={{ fontSize: 14, fontWeight: '700', color: C.fg }}>{h.ticker}</Text>
                          <Pnl value={h.unrealized_pnl} />
                        </View>
                        <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
                          <Text style={{ fontSize: 11, color: C.fgMuted, fontVariant: ['tabular-nums'] }}>
                            {h.qty.toLocaleString()} @ {money(h.avg_cost)}
                          </Text>
                          <Text style={{ fontSize: 11, color: C.fg, fontVariant: ['tabular-nums'] }}>
                            {money(h.market_value)}
                          </Text>
                        </View>
                      </Pressable>

                      <Pressable
                        onPress={() => closePosition(h.ticker)}
                        accessibilityRole="button"
                        style={{
                          alignSelf: 'flex-start', paddingHorizontal: 14, paddingVertical: 8,
                          borderRadius: 8, borderWidth: 1, borderColor: C.border,
                        }}
                      >
                        <Text style={{ fontSize: 12, fontWeight: '600', color: C.fgMuted }}>
                          Close {h.ticker}
                        </Text>
                      </Pressable>
                    </View>
                  ))}
                </View>
              )}
            </View>

            <Text style={{ fontSize: 10, color: C.fgMuted, lineHeight: 15, marginTop: 12 }}>
              <Text style={{ fontWeight: '700' }}>Source </Text>
              records who decided. Agent means the tool decided and acted without you,
              Semi means it recommended and you actioned it, Manual means you chose the
              ticker yourself. Performance keeps the three apart — a set of the
              agent&rsquo;s picks that a human filtered is not a clean measure of the
              agent.
            </Text>
          </>
        )}

        <Disclaimer />
      </ScrollView>
    </SafeAreaView>
  )
}
