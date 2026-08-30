import React, { useMemo, useState } from 'react'
import { Pressable, ScrollView, Text, View } from 'react-native'
import { router } from 'expo-router'
import { Inbox } from 'lucide-react-native'
import { formatDate, formatTime } from '../lib/format'
import { SOURCE_LABEL, displaySource } from '../lib/trade-source'
import { exitReasonLabel } from '../lib/exit-reason'
import { usePalette, type Palette } from '../lib/palette'
import ProposalActions from './ProposalActions'
import type { TradeRecord } from '../types'

/**
 * Activity — every action taken on this account, pending ones first.
 *
 * This was three sections: a proposal queue, the agent's tracked positions, and
 * an order history. They split one audit trail along a line that answered no
 * question anybody asks; the question is *what has been happening*, and a
 * proposal waiting on you, a guard refusing an order and a filled entry are all
 * answers to it.
 *
 * Mirrors `frontend/src/components/positions/ActivityTable.tsx` — same groups,
 * same fields, same rule that a live approval needs the ticker typed back.
 */

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

function money(v: number | null | undefined): string {
  return v == null ? '—' : usd.format(v)
}

/** Same id carried by every email/Slack/WhatsApp message about this trade. */
export function shortRef(id: string): string {
  return id.slice(-8).toUpperCase()
}

/** Tint is the accent at low alpha, so the pair flips with the theme together. */
function statusTone(C: Palette): Record<string, { bg: string; fg: string }> {
  return {
    FILLED: { bg: `${C.green}20`, fg: C.green },
    PENDING: { bg: `${C.amber}20`, fg: C.amber },
    PARTIAL: { bg: `${C.amber}20`, fg: C.amber },
    PROPOSED: { bg: `${C.brand}20`, fg: C.brand },
    REJECTED: { bg: `${C.red}20`, fg: C.red },
    UNRECONCILED: { bg: `${C.red}20`, fg: C.red },
  }
}
const statusDefault = (C: Palette) => ({ bg: `${C.border}90`, fg: C.fgMuted })

export function StatusPill({ status }: { status: string }) {
  const C = usePalette()
  const tone = statusTone(C)[status] ?? statusDefault(C)
  return (
    <View style={{
      paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
      backgroundColor: tone.bg, alignSelf: 'flex-start',
    }}>
      <Text style={{ fontSize: 9, fontWeight: '700', color: tone.fg }}>{status}</Text>
    </View>
  )
}

export function Pnl({ value }: { value: number | null | undefined }) {
  const C = usePalette()
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

/**
 * Groups, not statuses.
 *
 * There are ten statuses and they answer three different questions — is this
 * waiting on me, is it live, is it over — so one chip per status buried the
 * distinction under a row of near-identical chips.
 */
interface Group { key: string; label: string; statuses: string[] | null; alwaysShow?: boolean }

const GROUPS: Group[] = [
  { key: 'waiting', label: 'Waiting on you', statuses: ['PROPOSED'], alwaysShow: true },
  { key: 'active', label: 'Active', statuses: ['PENDING', 'PARTIAL', 'FILLED'], alwaysShow: true },
  { key: 'closed', label: 'Closed', statuses: ['CLOSED'] },
  { key: 'not_taken', label: 'Not taken', statuses: ['SKIPPED', 'DECLINED', 'CANCELLED', 'REJECTED'] },
  { key: 'unreconciled', label: 'Unreconciled', statuses: ['UNRECONCILED'] },
  { key: 'all', label: 'All', statuses: null, alwaysShow: true },
]

export default function ActivityList({
  orders,
  onProposalsChanged,
  showTicker = true,
  highlightId,
  emptyNote,
}: {
  orders: TradeRecord[]
  onProposalsChanged: () => void
  showTicker?: boolean
  highlightId?: string
  emptyNote?: string
}) {
  const C = usePalette()
  const [chosen, setChosen] = useState<string | null>(null)

  const counts = useMemo(() => {
    const out: Record<string, number> = {}
    for (const g of GROUPS) {
      out[g.key] = g.statuses == null
        ? orders.length
        : orders.filter((o) => g.statuses!.includes(o.status)).length
    }
    return out
  }, [orders])

  // Waiting-on-you wins the default whenever there is anything in it — it is
  // the only group where nothing moves until the reader acts.
  const key = chosen ?? ((counts.waiting ?? 0) > 0 ? 'waiting' : 'active')
  const group = GROUPS.find((g) => g.key === key) ?? GROUPS[1]
  const visible = GROUPS.filter((g) => g.alwaysShow || (counts[g.key] ?? 0) > 0)

  const rows = useMemo(
    () => (group.statuses == null ? orders : orders.filter((o) => group.statuses!.includes(o.status))),
    [orders, group],
  )

  if (orders.length === 0) {
    return (
      <View style={{
        backgroundColor: C.surface, borderRadius: 12, borderWidth: 1,
        borderColor: C.border, padding: 28, alignItems: 'center', gap: 10,
      }}>
        <Inbox size={26} color={C.fgMuted} />
        <Text style={{ fontSize: 13, color: C.fgMuted, textAlign: 'center', lineHeight: 19 }}>
          {emptyNote ?? 'No activity yet. Open a ticker and tap Buy, or let the agent propose one.'}
        </Text>
      </View>
    )
  }

  return (
    <View style={{ gap: 10 }}>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={{ gap: 6, paddingRight: 8 }}
      >
        {visible.map((g) => {
          const on = g.key === key
          return (
            <Pressable
              key={g.key}
              onPress={() => setChosen(g.key)}
              accessibilityRole="tab"
              accessibilityState={{ selected: on }}
              style={{
                paddingHorizontal: 12, paddingVertical: 7, borderRadius: 9,
                backgroundColor: on ? C.brand : `${C.border}80`,
              }}
            >
              <Text style={{ fontSize: 12, fontWeight: '600', color: on ? '#fff' : C.fgMuted }}>
                {g.label} {counts[g.key] ?? 0}
              </Text>
            </Pressable>
          )
        })}
      </ScrollView>

      {rows.length === 0 ? (
        <View style={{
          backgroundColor: C.surface, borderRadius: 12, borderWidth: 1,
          borderColor: C.border, padding: 24, alignItems: 'center',
        }}>
          <Text style={{ fontSize: 13, color: C.fgMuted }}>
            Nothing under {group.label.toLowerCase()}.
          </Text>
        </View>
      ) : (
        <View style={{
          backgroundColor: C.surface, borderRadius: 12, borderWidth: 1,
          borderColor: C.border, overflow: 'hidden',
        }}>
          {rows.map((o, i) => (
            <Pressable
              key={o.id}
              onPress={() => router.push(`/transaction/${o.id}`)}
              accessibilityRole="button"
              accessibilityLabel={`Transaction ${shortRef(o.id)}, ${o.ticker}`}
              style={{
                padding: 14, gap: 6,
                borderTopWidth: i === 0 ? 0 : 1, borderTopColor: C.border,
                backgroundColor: o.id === highlightId ? `${C.brand}12` : undefined,
              }}
            >
              <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flexShrink: 1 }}>
                  {showTicker && (
                    <Text style={{ fontSize: 14, fontWeight: '700', color: C.fg }}>{o.ticker}</Text>
                  )}
                  <Text style={{ fontSize: 11, color: C.fgMuted }}>
                    {o.action} · {SOURCE_LABEL[displaySource(o)]}
                  </Text>
                </View>
                <StatusPill status={o.status} />
              </View>

              <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
                <Text style={{ fontSize: 11, color: C.fgMuted }}>
                  {(o.filled_qty ?? o.qty)
                    ? `${o.filled_qty ?? o.qty} @ ${money(o.entry_price ?? o.limit_price)}`
                    : '—'}
                  {'  ·  '}
                  {formatDate(o.opened_at)} · {formatTime(o.opened_at)} ET
                </Text>
                {/* An estimate from the limit we asked for is not a result.
                    Until settlement replaces it with the real fill, say the sale
                    is working rather than show a P&L that may not be what
                    happened. */}
                {o.closed_at && o.exit_price_estimated ? (
                  <Text style={{ fontSize: 11, color: C.fgMuted }}>sale working</Text>
                ) : (
                  <Pnl value={o.pnl} />
                )}
              </View>

              {/* Three different sentences answering three different questions,
                  so none of them substitutes for another: `reason` is a guard's
                  refusal or a size adjustment, `entry_reason` is why the
                  position was opened, and `exit_reason` is why it ended. Web
                  shows the same three, in the same order. */}
              {[o.reason, o.entry_reason, exitReasonLabel(o.exit_reason)]
                .filter(Boolean)
                .map((line, n) => (
                  <Text
                    key={line as string}
                    style={{ fontSize: 10, lineHeight: 14, color: n === 0 ? C.fg : C.fgMuted }}
                  >
                    {line}
                  </Text>
                ))}

              <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
                <Text style={{ fontSize: 9, color: C.fgMuted, fontFamily: 'monospace' }}>
                  Ref {shortRef(o.id)}
                </Text>
                <Text style={{ fontSize: 9, color: C.fgMuted }}>
                  {o.signal_score != null ? `Score ${Math.round(o.signal_score * 100)}` : 'No score'}
                </Text>
              </View>

              {/* A proposal is resolvable where it is read. The card has room
                  for the typed confirmation a live order needs, so unlike the
                  web table it does not have to send anyone elsewhere. */}
              {o.status === 'PROPOSED' && (
                <View style={{ marginTop: 6 }}>
                  <ProposalActions
                    id={o.id}
                    ticker={o.ticker}
                    isPaper={o.is_paper}
                    onResolved={onProposalsChanged}
                  />
                </View>
              )}
            </Pressable>
          ))}
        </View>
      )}
    </View>
  )
}

/**
 * Three months, or ten rows, whichever reaches further.
 *
 * A fixed window hides everything on a name traded twice a year; a fixed count
 * hides most of a busy week. Taking the larger of the two means the reader
 * always gets either the recent period or a usable sample, and the caller is
 * told which rule produced the list — a truncated history that does not say it
 * is truncated is how someone concludes a trade never happened.
 *
 * Mirrors `tickerHistory` in the web client.
 */
export function tickerHistory(orders: TradeRecord[], ticker: string): {
  rows: TradeRecord[]
  rule: string
} {
  const HISTORY_MONTHS = 3
  const HISTORY_MIN_ROWS = 10

  const mine = orders
    .filter((o) => o.ticker === ticker)
    .slice()
    .sort((a, b) => (b.opened_at ?? '').localeCompare(a.opened_at ?? ''))

  const cutoff = new Date()
  cutoff.setMonth(cutoff.getMonth() - HISTORY_MONTHS)
  const withinWindow = mine.filter((o) => {
    const t = Date.parse(o.opened_at)
    return Number.isFinite(t) && t >= cutoff.getTime()
  })

  if (withinWindow.length >= HISTORY_MIN_ROWS) {
    return { rows: withinWindow, rule: `Everything in the last ${HISTORY_MONTHS} months.` }
  }
  const rows = mine.slice(0, HISTORY_MIN_ROWS)
  return {
    rows,
    rule: rows.length > withinWindow.length
      ? `Fewer than ${HISTORY_MIN_ROWS} transactions in the last ${HISTORY_MONTHS} months, so this reaches further back — the ${rows.length} most recent.`
      : `Everything in the last ${HISTORY_MONTHS} months.`,
  }
}
