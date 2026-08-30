import React, { useCallback, useEffect, useState } from 'react'
import { ActivityIndicator, RefreshControl, ScrollView, Text, View } from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { AlertTriangle, CheckCircle2, CircleSlash, Info, MinusCircle, XCircle } from 'lucide-react-native'
import { systemApi } from '../../src/lib/api'
import type {
  CapabilityStatus, CapabilityTier, SourceState, SystemStatus,
} from '../../src/types'
import { usePalette, type Palette } from '../../src/lib/palette'

/**
 * What is working, and what each gap costs — the phone counterpart of the web
 * `StatusPage`.
 *
 * Same two rules, and they are the point of the screen:
 *   - **Nothing is probed.** Every row is what the source actually did on the
 *     last analysis cycle, which is the same data the signals were built from.
 *   - **A source with no key is not broken.** It reads *Off* in a muted tone,
 *     never red — an absent key is a configuration choice, and rendering it as
 *     a fault is how a status screen stops being opened.
 *
 * The verdict sentence is composed on the server and rendered verbatim here, so
 * this screen and the web one cannot word "degraded" differently.
 */

function stateStyle(C: Palette, state: SourceState) {
  switch (state) {
    case 'ok':
      return { label: 'Working', fg: C.green, bg: `${C.green}1f`, Icon: CheckCircle2 }
    case 'stale':
      return { label: 'Stale', fg: C.amber, bg: `${C.amber}1f`, Icon: Info }
    case 'degraded':
      return { label: 'Degraded', fg: C.amber, bg: `${C.amber}1f`, Icon: AlertTriangle }
    case 'failed':
      return { label: 'Failing', fg: C.red, bg: `${C.red}1f`, Icon: XCircle }
    case 'not_configured':
      return { label: 'Off', fg: C.fgMuted, bg: `${C.border}80`, Icon: MinusCircle }
    default:
      return { label: 'No reading', fg: C.fgMuted, bg: `${C.border}80`, Icon: CircleSlash }
  }
}

const TIER_TITLE: Record<CapabilityTier, string> = {
  stops: 'Stops trading',
  behaviour: 'Changes what the agent does',
  quiet: 'Degrades a score quietly',
}

const TIER_BLURB: Record<CapabilityTier, string> = {
  stops: 'Without these the cycle does not complete and no order is evaluated. Trading pauses rather than running on stale data.',
  behaviour: 'These do not stop anything. They change which decision path runs, so the same market produces a different action.',
  quiet: 'These fail silently by design: the factor they feed goes to a neutral 0.50 and the verdict still publishes. This is the group worth checking before you trust a score.',
}

const TIER_ORDER: CapabilityTier[] = ['stops', 'behaviour', 'quiet']

function formatWhen(value: string | null): string {
  if (!value) return 'Never'
  const d = new Date(value)
  return d.toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
    timeZone: 'America/New_York',
  })
}

function StatePill({ state }: { state: SourceState }) {
  const C = usePalette()
  const style = stateStyle(C, state)
  return (
    <View style={{
      flexDirection: 'row', alignItems: 'center', gap: 4,
      paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
      backgroundColor: style.bg,
    }}>
      <style.Icon size={10} color={style.fg} />
      <Text style={{ fontSize: 9, fontWeight: '700', color: style.fg }}>
        {style.label}
      </Text>
    </View>
  )
}

function CapabilityRow({ row, first }: { row: CapabilityStatus; first: boolean }) {
  const C = usePalette()
  return (
    <View style={{
      padding: 14, gap: 5,
      borderTopWidth: first ? 0 : 1, borderTopColor: C.border,
    }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <Text style={{ fontSize: 13, fontWeight: '700', color: C.fg }}>{row.label}</Text>
        <StatePill state={row.state} />
      </View>

      <Text style={{ fontSize: 11.5, lineHeight: 16, color: C.fg }}>{row.detail}</Text>

      {/* The reason the row is worth reading. "FRED: failing" is not
          actionable on a phone; what it costs the score is. */}
      <Text style={{ fontSize: 11.5, lineHeight: 16, color: C.fgMuted }}>
        <Text style={{ fontWeight: '600', color: C.fg }}>Without it: </Text>
        {row.impact}
      </Text>

      {row.feeds ? (
        <Text style={{ fontSize: 10.5, color: C.fgMuted }}>Feeds {row.feeds}</Text>
      ) : null}

      {row.last_success_at ? (
        <Text style={{ fontSize: 10.5, color: C.fgMuted }}>
          Last answered {formatWhen(row.last_success_at)} ET
        </Text>
      ) : null}

      {row.state === 'failed' && row.last_error ? (
        <Text style={{ fontSize: 10.5, lineHeight: 15, color: C.red }}>{row.last_error}</Text>
      ) : null}
    </View>
  )
}

export default function StatusScreen() {
  const C = usePalette()
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState(false)

  const load = useCallback(async () => {
    try {
      const { data } = await systemApi.status()
      setStatus(data)
      setError(false)
    } catch {
      setError(true)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const onRefresh = useCallback(() => { setRefreshing(true); load() }, [load])

  const overallTone = status?.overall === 'halted' ? C.red
    : status?.overall === 'degraded' ? C.amber
    : C.green

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.bg }} edges={['top']}>
      <ScrollView
        contentContainerStyle={{ padding: 16, gap: 16, paddingBottom: 40 }}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={C.fgMuted} />
        }
      >
        <View>
          <Text style={{ fontSize: 20, fontWeight: '700', color: C.fg }}>System status</Text>
          <Text style={{ fontSize: 12, lineHeight: 17, color: C.fgMuted, marginTop: 4 }}>
            Which inputs the engine actually has, and what each missing one costs
            the score. Nothing here is a live probe — every row is what the source
            did on the last analysis cycle, which is the same data your signals
            were built from.
          </Text>
        </View>

        {loading ? <ActivityIndicator color={C.fgMuted} /> : null}

        {error && !loading ? (
          <Text style={{ fontSize: 13, color: C.fgMuted, textAlign: 'center', paddingVertical: 24 }}>
            Could not read system status.
          </Text>
        ) : null}

        {status ? (
          <>
            {/* Composed on the server, rendered verbatim on both clients. */}
            <View style={{
              flexDirection: 'row', gap: 10, padding: 12, borderRadius: 10,
              backgroundColor: `${overallTone}1f`,
            }}>
              {status.overall === 'ok'
                ? <CheckCircle2 size={16} color={overallTone} />
                : <AlertTriangle size={16} color={overallTone} />}
              <Text style={{ flex: 1, fontSize: 12.5, lineHeight: 18, color: overallTone }}>
                {status.summary}
              </Text>
            </View>

            <View style={{
              backgroundColor: C.surface, borderRadius: 12, borderWidth: 1,
              borderColor: C.border, padding: 14, gap: 6,
            }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                <Text style={{ fontSize: 13, fontWeight: '700', color: C.fg }}>
                  Analysis cycle
                </Text>
                <StatePill state={status.cycle.stale ? 'degraded' : 'ok'} />
                <Text style={{ fontSize: 10.5, color: C.fgMuted, marginLeft: 'auto' }}>
                  Market {status.market_open ? 'open' : 'closed'}
                </Text>
              </View>
              {/* Stated before the rows below, because they all describe this
                  cycle — if it is hours old, none of them means what it looks like. */}
              <Text style={{ fontSize: 11.5, lineHeight: 16, color: C.fgMuted }}>
                Everything below describes the most recent run. Scores refresh every
                five minutes while the market is open, and not at all outside it — a
                quiet overnight is the design, not an outage.
              </Text>
              <Text style={{ fontSize: 11.5, color: C.fg }}>
                Last run {formatWhen(status.cycle.last_run_at)} ET
                {status.cycle.age_minutes != null ? ` (${status.cycle.age_minutes}m ago)` : ''}
                {status.cycle.tickers_total
                  ? ` · ${status.cycle.tickers_ok ?? 0} of ${status.cycle.tickers_total} tickers`
                  : ''}
              </Text>
              {status.cycle.failed_tickers.length > 0 ? (
                <Text style={{ fontSize: 11, color: C.red }}>
                  Failed: {status.cycle.failed_tickers.join(', ')}
                </Text>
              ) : null}
            </View>

            {TIER_ORDER.map((tier) => {
              const rows = status.capabilities.filter((c) => c.tier === tier)
              if (rows.length === 0) return null
              return (
                <View key={tier} style={{ gap: 6 }}>
                  <Text style={{ fontSize: 13, fontWeight: '700', color: C.fg }}>
                    {TIER_TITLE[tier]}
                  </Text>
                  <Text style={{ fontSize: 11.5, lineHeight: 16, color: C.fgMuted }}>
                    {TIER_BLURB[tier]}
                  </Text>
                  <View style={{
                    backgroundColor: C.surface, borderRadius: 12, borderWidth: 1,
                    borderColor: C.border, overflow: 'hidden',
                  }}>
                    {rows.map((row, i) => (
                      <CapabilityRow key={row.id} row={row} first={i === 0} />
                    ))}
                  </View>
                </View>
              )
            })}

            <Text style={{ fontSize: 10.5, lineHeight: 15, color: C.fgMuted }}>
              A source shown as <Text style={{ fontWeight: '700', color: C.fg }}>Off</Text> has
              no API key on this server — a configuration choice, not a fault. The factor
              it feeds sits at a neutral 0.50 rather than scoring badly.
            </Text>
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  )
}
