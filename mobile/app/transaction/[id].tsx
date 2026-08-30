import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { ActivityIndicator, Pressable, ScrollView, Text, View } from 'react-native'
import { useLocalSearchParams, router } from 'expo-router'
import { LineChart } from 'lucide-react-native'
import { tradingApi } from '../../src/lib/api'
import { formatDate, formatTime } from '../../src/lib/format'
import { SOURCE_DESCRIPTION, SOURCE_LABEL, displaySource } from '../../src/lib/trade-source'
import { exitReasonLabel } from '../../src/lib/exit-reason'
import ActivityList, {
  Pnl, StatusPill, shortRef, tickerHistory,
} from '../../src/components/ActivityList'
import ProposalActions from '../../src/components/ProposalActions'
import Disclaimer from '../../src/components/Disclaimer'
import { usePalette } from '../../src/lib/palette'
import type { TradeRecord } from '../../src/types'

/**
 * One transaction, in full, with the rest of that ticker's history under it.
 *
 * The audit trail this exists for is not one row — it is the sequence. "Why do
 * I own 40 shares of AVGO" is answered by an entry, two adds and a proposal
 * that was rejected in between, and no single record says that. So the screen
 * leads with the record that was tapped and then puts it back in its own
 * history.
 *
 * Mirrors `frontend/src/components/positions/TransactionDetail.tsx`.
 */

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

function money(v: number | null | undefined): string {
  return v == null ? '—' : usd.format(v)
}

function Field({ label, value, tone }: { label: string; value: string; tone?: string }) {
  const C = usePalette()
  return (
    <View style={{ width: '50%', paddingVertical: 5 }}>
      <Text style={{ fontSize: 10, color: C.fgMuted }}>{label}</Text>
      <Text style={{ fontSize: 13, color: tone ?? C.fg, fontVariant: ['tabular-nums'] }}>
        {value}
      </Text>
    </View>
  )
}

export default function TransactionScreen() {
  const { id } = useLocalSearchParams<{ id: string }>()
  const C = usePalette()

  const [orders, setOrders] = useState<TradeRecord[]>([])
  const [loading, setLoading] = useState(true)

  /**
   * Fetch a wide window rather than the default page.
   *
   * A record reached from a deep link or an old alert can be well past the
   * newest 200 orders, and this screen has to be able to show it — and the
   * ticker history under it needs the same reach.
   */
  const load = useCallback(async () => {
    try {
      const { data } = await tradingApi.getOrders(undefined, 1000)
      setOrders(data)
    } catch {
      setOrders([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const trade = useMemo(() => orders.find((o) => o.id === id) ?? null, [orders, id])
  const history = useMemo(
    () => (trade ? tickerHistory(orders, trade.ticker) : null),
    [orders, trade],
  )

  if (loading) {
    return (
      <View style={{ flex: 1, backgroundColor: C.bg, paddingVertical: 60, alignItems: 'center' }}>
        <ActivityIndicator size="large" color={C.brand} />
      </View>
    )
  }

  if (!trade) {
    return (
      <View style={{ flex: 1, backgroundColor: C.bg, padding: 24 }}>
        <Text style={{ fontSize: 13, color: C.fgMuted, lineHeight: 19 }}>
          No transaction with reference {id ? shortRef(String(id)) : '—'} is on this
          account.
        </Text>
      </View>
    )
  }

  const source = displaySource(trade)
  const why = [trade.reason, trade.entry_reason, exitReasonLabel(trade.exit_reason)]
    .filter(Boolean) as string[]

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: C.bg }}
      contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 60 }}
    >
      {/* ── The record ──────────────────────────────────────────────────── */}
      <View style={{
        backgroundColor: C.surface, borderRadius: 12, borderWidth: 1,
        borderColor: C.border, padding: 16, gap: 10,
      }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <Text style={{ fontSize: 20, fontWeight: '700', color: C.fg }}>{trade.ticker}</Text>
          <Text style={{ fontSize: 13, fontWeight: '600', color: C.fg }}>{trade.action}</Text>
          <StatusPill status={trade.status} />
          <Text style={{ fontSize: 10, color: C.fgMuted }}>{SOURCE_LABEL[source]}</Text>
          {!trade.is_paper && (
            <View style={{
              paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
              backgroundColor: `${C.red}20`,
            }}>
              <Text style={{ fontSize: 9, fontWeight: '700', color: C.red }}>LIVE</Text>
            </View>
          )}
        </View>

        <Text style={{ fontSize: 11, color: C.fgMuted, lineHeight: 16 }}>
          {SOURCE_DESCRIPTION[source]}{trade.is_paper ? ' · paper' : ''}
        </Text>

        <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
          {/* Full, not shortened. This is where someone matches a record
              against the reference in an alert message, and eight characters do
              not settle an argument. */}
          <View style={{ width: '100%', paddingVertical: 5 }}>
            <Text style={{ fontSize: 10, color: C.fgMuted }}>Transaction ID</Text>
            <Text style={{ fontSize: 11, color: C.fg, fontFamily: 'monospace' }}>{trade.id}</Text>
          </View>
          <Field
            label="Time of action"
            value={`${formatDate(trade.opened_at)} · ${formatTime(trade.opened_at)} ET`}
          />
          {trade.filled_at && (
            <Field
              label="Filled"
              value={`${formatDate(trade.filled_at)} · ${formatTime(trade.filled_at)} ET`}
            />
          )}
          {trade.closed_at && (
            <Field
              label="Closed"
              value={`${formatDate(trade.closed_at)} · ${formatTime(trade.closed_at)} ET`}
            />
          )}
          {/* Requested and filled are separate facts: the server clamps a
              requested quantity to what the risk model funds, and a partial
              fill clamps it again. */}
          <Field label="Qty requested" value={trade.qty ? String(trade.qty) : '—'} />
          <Field label="Qty filled" value={trade.filled_qty != null ? String(trade.filled_qty) : '—'} />
          <Field label="Limit" value={money(trade.limit_price)} />
          <Field label="Entry" value={money(trade.entry_price)} />
          {trade.exit_price != null && (
            <Field
              label={trade.exit_price_estimated ? 'Exit (est.)' : 'Exit'}
              value={money(trade.exit_price)}
            />
          )}
          <Field label="Stop" value={money(trade.stop_loss)} tone={C.red} />
          <Field label="Target" value={money(trade.take_profit)} tone={C.green} />
          <Field
            label="Score"
            value={trade.signal_score != null ? `${Math.round(trade.signal_score * 100)}/100` : '—'}
          />
          <Field label="Analyst conviction" value={trade.conviction ?? '—'} />
          {/* How much of the score was built on measured inputs rather than
              fallbacks. Missing stays missing — a trade recorded before this was
              captured has no figure, and 100% would be a claim nobody made. */}
          <Field
            label="Input completeness"
            value={trade.input_completeness != null
              ? `${Math.round(trade.input_completeness * 100)}%`
              : '—'}
          />
          <View style={{ width: '50%', paddingVertical: 5 }}>
            <Text style={{ fontSize: 10, color: C.fgMuted }}>P&amp;L</Text>
            <Pnl value={trade.pnl} />
          </View>
          {trade.order_id != null && (
            <Field label="Broker order" value={String(trade.order_id)} />
          )}
        </View>

        {/* Three sentences answering three different questions. None of them is
            a substitute for another, so none is dropped. */}
        {why.length > 0 && (
          <View style={{ borderTopWidth: 1, borderTopColor: C.border, paddingTop: 10, gap: 4 }}>
            <Text style={{
              fontSize: 10, fontWeight: '700', color: C.fgMuted,
              textTransform: 'uppercase', letterSpacing: 1,
            }}>
              Why
            </Text>
            {why.map((line, n) => (
              <Text
                key={line}
                style={{ fontSize: 12, lineHeight: 17, color: n === 0 ? C.fg : C.fgMuted }}
              >
                {line}
              </Text>
            ))}
          </View>
        )}

        {trade.status === 'PROPOSED' && (
          <View style={{ borderTopWidth: 1, borderTopColor: C.border, paddingTop: 12, gap: 8 }}>
            <Text style={{ fontSize: 11, color: C.fgMuted, lineHeight: 16 }}>
              Nothing is committed until you accept. Approving places the order;
              rejecting records the refusal and takes no position.
            </Text>
            <ProposalActions
              id={trade.id}
              ticker={trade.ticker}
              isPaper={trade.is_paper}
              onResolved={() => router.back()}
            />
          </View>
        )}

        <Pressable
          onPress={() => router.push(`/ticker/${trade.ticker}`)}
          accessibilityRole="button"
          style={{
            flexDirection: 'row', alignItems: 'center', gap: 6, alignSelf: 'flex-start',
            paddingHorizontal: 14, paddingVertical: 8, borderRadius: 8,
            borderWidth: 1, borderColor: C.border,
          }}
        >
          <LineChart size={13} color={C.fgMuted} />
          <Text style={{ fontSize: 12, fontWeight: '600', color: C.fgMuted }}>
            {trade.ticker} analysis
          </Text>
        </Pressable>
      </View>

      {/* ── The ticker's history ────────────────────────────────────────── */}
      {history && (
        <View style={{ marginTop: 24, gap: 10 }}>
          <Text style={{
            fontSize: 11, fontWeight: '700', color: C.fgMuted,
            textTransform: 'uppercase', letterSpacing: 1,
          }}>
            {`All transactions — ${trade.ticker} (${history.rows.length})`}
          </Text>
          <ActivityList
            orders={history.rows}
            onProposalsChanged={load}
            showTicker={false}
            highlightId={trade.id}
            emptyNote={`No transactions recorded for ${trade.ticker}.`}
          />
          <Text style={{ fontSize: 10, color: C.fgMuted, lineHeight: 15 }}>
            {history.rule} Manual orders, agent entries, adds and refusals alike —
            this is the whole record for {trade.ticker}, not only the trades that
            filled.
          </Text>
        </View>
      )}

      <Disclaimer />
    </ScrollView>
  )
}
