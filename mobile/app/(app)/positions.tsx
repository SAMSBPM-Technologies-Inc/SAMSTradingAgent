import React, { useCallback, useEffect, useState } from 'react'
import {
  ActivityIndicator, Pressable, RefreshControl, ScrollView, Text, TextInput, View,
} from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { router } from 'expo-router'
import { AlertCircle, Check, Inbox, X } from 'lucide-react-native'
import { tradingApi } from '../../src/lib/api'
import { useToast } from '../../src/lib/toast-context'
import { formatDate, formatTime } from '../../src/lib/format'
import { SOURCE_LABEL, tradeSource } from '../../src/lib/trade-source'
import type { Holding, Proposal, TradeRecord } from '../../src/types'
import SignalBadge from '../../src/components/SignalBadge'
import Disclaimer from '../../src/components/Disclaimer'

/**
 * Positions — holdings, the proposal queue, and every order ever sent.
 *
 * The phone counterpart of the web `PositionsPage`, and merged along the same
 * line: Holdings asked the broker what it holds, Orders asked our records what
 * we sent, and "am I up or down" needed both. On a phone that mattered more
 * than on a desktop — it was two taps and a lost scroll position.
 *
 * Broker holdings load on mount here rather than on demand as the old Holdings
 * tab did. That tab existed to be visited deliberately; this one is where you
 * land, and a screen called Positions that shows no positions until you press
 * a button reads as broken.
 */

const C = {
  bg: '#f5f2ed', surface: '#ffffff', fg: '#14110c',
  fgMuted: '#83786a', border: '#e7e2d8', brand: '#f2600c',
  red: '#b91c1c', green: '#15803d', amber: '#b45309',
}

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

function money(v: number | null | undefined): string {
  return v == null ? '—' : usd.format(v)
}

/** Broker-statement convention: gains green, losses red in parentheses. */
function Pnl({ value }: { value: number | null | undefined }) {
  if (value == null) return <Text style={{ color: C.fgMuted, fontSize: 12 }}>—</Text>
  const loss = value < -0.005
  const gain = value > 0.005
  return (
    <Text style={{
      fontSize: 12, fontVariant: ['tabular-nums'],
      color: loss ? C.red : gain ? C.green : C.fg,
    }}>
      {loss ? `(${usd.format(Math.abs(value))})` : usd.format(value)}
    </Text>
  )
}

const STATUS_TONE: Record<string, { bg: string; fg: string }> = {
  FILLED: { bg: 'rgba(21,128,61,0.12)', fg: C.green },
  PENDING: { bg: 'rgba(180,83,9,0.12)', fg: C.amber },
  PARTIAL: { bg: 'rgba(180,83,9,0.12)', fg: C.amber },
  PROPOSED: { bg: 'rgba(242,96,12,0.12)', fg: C.brand },
  REJECTED: { bg: 'rgba(185,28,28,0.12)', fg: C.red },
  UNRECONCILED: { bg: 'rgba(185,28,28,0.12)', fg: C.red },
}
const STATUS_DEFAULT = { bg: `${C.border}90`, fg: C.fgMuted }

function StatusPill({ status }: { status: string }) {
  const tone = STATUS_TONE[status] ?? STATUS_DEFAULT
  return (
    <View style={{
      paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
      backgroundColor: tone.bg, alignSelf: 'flex-start',
    }}>
      <Text style={{ fontSize: 9, fontWeight: '700', color: tone.fg }}>{status}</Text>
    </View>
  )
}

/** Who decided — the distinction the performance split rests on. */
function sourceLabel(signalType?: string | null): string {
  return signalType ? SOURCE_LABEL[tradeSource(signalType)] : '—'
}

function SectionTitle({ children, note }: { children: string; note?: string }) {
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

// ── Proposal card ─────────────────────────────────────────────────────────────

function ProposalCard({ proposal, onResolved }: {
  proposal: Proposal
  onResolved: () => void
}) {
  const { toast } = useToast()
  const [busy, setBusy] = useState<'approve' | 'decline' | null>(null)
  // A live-money proposal must not be approvable in one tap. The order ticket
  // asks the user to type the ticker; approving is the same act.
  const [confirmLive, setConfirmLive] = useState('')
  const needsConfirm = !proposal.is_paper
  const liveConfirmed =
    !needsConfirm || confirmLive.trim().toUpperCase() === proposal.ticker.toUpperCase()

  const approve = async () => {
    if (!liveConfirmed) return
    setBusy('approve')
    try {
      const { data } = await tradingApi.approveProposal(proposal.id, needsConfirm)
      toast(
        data.placed
          ? `Order placed: ${data.qty} ${data.ticker} at ${usd.format(data.limit_price)}`
          : data.reason ?? 'The order could not be placed.',
        data.placed ? 'success' : 'error',
      )
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
    <View style={{
      backgroundColor: C.surface, borderRadius: 12, borderWidth: 1,
      borderColor: C.border, padding: 14, gap: 12, marginBottom: 10,
    }}>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', gap: 10 }}>
        <View style={{ flex: 1 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <Text style={{ fontSize: 15, fontWeight: '700', color: C.fg }}>
              {proposal.ticker}
            </Text>
            <SignalBadge signal="BUY" />
            {proposal.conviction && (
              <Text style={{ fontSize: 10, color: C.fgMuted }}>
                {proposal.conviction} conviction
              </Text>
            )}
          </View>
          {proposal.reason && (
            <Text style={{ fontSize: 11, color: C.fgMuted, marginTop: 4, lineHeight: 16 }}>
              {proposal.reason}
            </Text>
          )}
        </View>
        {proposal.is_paper && (
          <View style={{
            paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
            backgroundColor: `${C.border}90`, alignSelf: 'flex-start',
          }}>
            <Text style={{ fontSize: 9, fontWeight: '700', color: C.fgMuted }}>PAPER</Text>
          </View>
        )}
      </View>

      {/* The arithmetic is already done — show it rather than asking for trust. */}
      <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
        {([
          ['Quantity', String(proposal.qty), C.fg],
          ['Limit', money(proposal.limit_price), C.fg],
          ['Stop', money(proposal.stop_loss), C.red],
          ['Target', money(proposal.take_profit), C.green],
        ] as const).map(([label, value, tone]) => (
          <View key={label} style={{ width: '50%', paddingVertical: 3 }}>
            <Text style={{ fontSize: 10, color: C.fgMuted }}>{label}</Text>
            <Text style={{ fontSize: 13, color: tone, fontVariant: ['tabular-nums'] }}>
              {value}
            </Text>
          </View>
        ))}
      </View>

      {needsConfirm && (
        <View style={{ gap: 4 }}>
          <Text style={{ fontSize: 11, color: C.red }}>
            Live money — type {proposal.ticker} to approve
          </Text>
          <TextInput
            value={confirmLive}
            onChangeText={setConfirmLive}
            autoCapitalize="characters"
            autoCorrect={false}
            accessibilityLabel="Type the ticker to confirm a live approval"
            style={{
              borderWidth: 1, borderColor: C.red, borderRadius: 8,
              paddingHorizontal: 12, paddingVertical: 9, fontSize: 14,
              color: C.fg, backgroundColor: C.bg,
            }}
          />
        </View>
      )}

      <View style={{ flexDirection: 'row', gap: 8 }}>
        <Pressable
          onPress={approve}
          disabled={busy !== null || !liveConfirmed}
          accessibilityRole="button"
          style={{
            flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
            gap: 6, backgroundColor: C.brand, borderRadius: 9, paddingVertical: 11,
            opacity: busy !== null || !liveConfirmed ? 0.4 : 1,
          }}
        >
          {busy === 'approve'
            ? <ActivityIndicator size="small" color="#fff" />
            : <Check size={15} color="#fff" />}
          <Text style={{ color: '#fff', fontWeight: '700', fontSize: 13 }}>Approve</Text>
        </Pressable>
        <Pressable
          onPress={decline}
          disabled={busy !== null}
          accessibilityRole="button"
          style={{
            flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
            gap: 6, backgroundColor: C.surface, borderRadius: 9, paddingVertical: 11,
            borderWidth: 1, borderColor: C.border, opacity: busy !== null ? 0.4 : 1,
          }}
        >
          {busy === 'decline'
            ? <ActivityIndicator size="small" color={C.fgMuted} />
            : <X size={15} color={C.fgMuted} />}
          <Text style={{ color: C.fgMuted, fontWeight: '600', fontSize: 13 }}>Decline</Text>
        </Pressable>
      </View>
    </View>
  )
}

// ── Screen ────────────────────────────────────────────────────────────────────

export default function PositionsScreen() {
  const { toast, toastWithUndo } = useToast()
  const [proposals, setProposals] = useState<Proposal[]>([])
  const [positions, setPositions] = useState<TradeRecord[]>([])
  const [orders, setOrders] = useState<TradeRecord[]>([])
  const [holdings, setHoldings] = useState<Holding[]>([])
  const [brokerConnected, setBrokerConnected] = useState(false)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const [p, pos, ord, hold] = await Promise.all([
        tradingApi.getProposals().catch(() => ({ data: [] as Proposal[] })),
        tradingApi.getPositions(),
        tradingApi.getOrders(),
        tradingApi.getHoldings().catch(() => null),
      ])
      setProposals(p.data)
      setPositions(pos.data)
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

  useEffect(() => { load() }, [load])

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
        <Text style={{ fontSize: 24, fontWeight: '300', color: C.fg }}>Positions</Text>
        <Text style={{ fontSize: 13, color: C.fgMuted, marginTop: 2, marginBottom: 20 }}>
          What is held, what is waiting on you, and everything ever sent.
        </Text>

        {error && (
          <View style={{
            flexDirection: 'row', gap: 10, alignItems: 'center', marginBottom: 16,
            backgroundColor: 'rgba(185,28,28,0.10)', borderRadius: 10, padding: 12,
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
            {/* ── Proposals ────────────────────────────────────────────── */}
            {proposals.length > 0 && (
              <View style={{ marginBottom: 28 }}>
                <SectionTitle note="Entries the agent wanted to take but your trading mode does not let it take alone. Nothing here is committed.">
                  {`Awaiting your approval (${proposals.length})`}
                </SectionTitle>
                {proposals.map((p) => (
                  <ProposalCard key={p.id} proposal={p} onResolved={load} />
                ))}
              </View>
            )}

            {/* ── Holdings ─────────────────────────────────────────────────
                What the broker says is held, which is the authority. The block
                below it is our own record of *why* each one exists — they are
                different questions and can legitimately disagree, so they are
                shown as two lists rather than silently reconciled here. */}
            <View style={{ marginBottom: 28 }}>
              <SectionTitle
                note={brokerConnected ? undefined : 'Broker disconnected'}
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
                    <Pressable
                      key={h.ticker}
                      onPress={() => router.push(`/ticker/${h.ticker}`)}
                      accessibilityRole="button"
                      accessibilityLabel={`${h.ticker}, ${h.qty} shares`}
                      style={{
                        paddingHorizontal: 14, paddingVertical: 12, gap: 6,
                        borderTopWidth: i === 0 ? 0 : 1, borderTopColor: `${C.border}80`,
                      }}
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
                  ))}
                </View>
              )}
            </View>

            {/* ── Open positions ───────────────────────────────────────── */}
            <View style={{ marginBottom: 28 }}>
              <SectionTitle note="the agent's own record, with its bracket levels">
                {`Tracked positions (${positions.length})`}
              </SectionTitle>
              {positions.length === 0 ? (
                <View style={{
                  backgroundColor: C.surface, borderRadius: 12, borderWidth: 1,
                  borderColor: C.border, padding: 24, alignItems: 'center',
                }}>
                  <Text style={{ fontSize: 13, color: C.fgMuted }}>
                    No open positions tracked by the agent.
                  </Text>
                </View>
              ) : positions.map((p) => (
                <View
                  key={p.id}
                  style={{
                    backgroundColor: C.surface, borderRadius: 12, borderWidth: 1,
                    borderColor: C.border, padding: 14, marginBottom: 10, gap: 10,
                  }}
                >
                  <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Pressable onPress={() => router.push(`/ticker/${p.ticker}`)}>
                      <Text style={{ fontSize: 15, fontWeight: '700', color: C.fg }}>
                        {p.ticker}
                      </Text>
                    </Pressable>
                    <StatusPill status={p.status} />
                  </View>

                  <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
                    {([
                      ['Qty', String(p.filled_qty ?? p.qty), C.fg],
                      ['Entry', money(p.entry_price ?? p.limit_price), C.fg],
                      ['Stop', money(p.stop_loss), C.red],
                      ['Target', money(p.take_profit), C.green],
                    ] as const).map(([label, value, tone]) => (
                      <View key={label} style={{ width: '50%', paddingVertical: 3 }}>
                        <Text style={{ fontSize: 10, color: C.fgMuted }}>{label}</Text>
                        <Text style={{ fontSize: 13, color: tone, fontVariant: ['tabular-nums'] }}>
                          {value}
                        </Text>
                      </View>
                    ))}
                  </View>

                  <Pressable
                    onPress={() => closePosition(p.ticker)}
                    accessibilityRole="button"
                    style={{
                      alignSelf: 'flex-start', paddingHorizontal: 14, paddingVertical: 8,
                      borderRadius: 8, borderWidth: 1, borderColor: C.border,
                    }}
                  >
                    <Text style={{ fontSize: 12, fontWeight: '600', color: C.fgMuted }}>
                      Close position
                    </Text>
                  </Pressable>
                </View>
              ))}
            </View>

            {/* ── Order history ────────────────────────────────────────── */}
            <View style={{ marginBottom: 8 }}>
              <SectionTitle note="Every attempt, including the ones the risk guards refused — a skip is a decision worth seeing.">
                Order history
              </SectionTitle>
              {orders.length === 0 ? (
                <View style={{
                  backgroundColor: C.surface, borderRadius: 12, borderWidth: 1,
                  borderColor: C.border, padding: 28, alignItems: 'center', gap: 10,
                }}>
                  <Inbox size={26} color={C.fgMuted} />
                  <Text style={{ fontSize: 13, color: C.fgMuted, textAlign: 'center', lineHeight: 19 }}>
                    No orders yet. Open a ticker and tap Buy, or let the agent propose one.
                  </Text>
                </View>
              ) : (
                <View style={{
                  backgroundColor: C.surface, borderRadius: 12, borderWidth: 1,
                  borderColor: C.border, overflow: 'hidden',
                }}>
                  {orders.map((o, i) => (
                    <View
                      key={o.id}
                      style={{
                        padding: 14, gap: 6,
                        borderTopWidth: i === 0 ? 0 : 1, borderTopColor: C.border,
                      }}
                    >
                      <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
                        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                          <Pressable onPress={() => router.push(`/ticker/${o.ticker}`)}>
                            <Text style={{ fontSize: 14, fontWeight: '700', color: C.fg }}>
                              {o.ticker}
                            </Text>
                          </Pressable>
                          <Text style={{ fontSize: 11, color: C.fgMuted }}>
                            {o.action} · {sourceLabel(o.signal_type)}
                          </Text>
                        </View>
                        <StatusPill status={o.status} />
                      </View>

                      <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
                        <Text style={{ fontSize: 11, color: C.fgMuted }}>
                          {o.qty ? `${o.qty} @ ${money(o.entry_price ?? o.limit_price)}` : '—'}
                          {'  ·  '}
                          {formatDate(o.opened_at)} · {formatTime(o.opened_at)} ET
                        </Text>
                        <Pnl value={o.pnl} />
                      </View>

                      {o.reason && (
                        <Text style={{ fontSize: 10, color: C.fgMuted, lineHeight: 14 }}>
                          {o.reason}
                        </Text>
                      )}
                    </View>
                  ))}
                </View>
              )}
            </View>

            <Text style={{ fontSize: 10, color: C.fgMuted, lineHeight: 15, marginTop: 12 }}>
              <Text style={{ fontWeight: '700' }}>Source </Text>
              records who decided. Agent placed unattended, Approved means the agent
              proposed and you accepted, You means you chose the ticker. Performance keeps
              the three apart — a set of the agent&rsquo;s picks that a human filtered is
              not a clean measure of the agent.
            </Text>
          </>
        )}

        <Disclaimer />
      </ScrollView>
    </SafeAreaView>
  )
}
