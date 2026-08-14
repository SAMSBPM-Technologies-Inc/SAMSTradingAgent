import React, { useEffect, useState } from 'react'
import { View, Text, ScrollView } from 'react-native'
import { AlertCircle, BarChart2, Clock, TrendingUp } from 'lucide-react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { performanceApi } from '../../src/lib/api'
import type { PerformanceResponse, Signal, SignalRecord, Conviction } from '../../src/types'
import SignalBadge from '../../src/components/SignalBadge'
import ConvictionBadge from '../../src/components/ConvictionBadge'
import LoadingSpinner from '../../src/components/LoadingSpinner'

const C = {
  bg: '#f5f2ed', surface: '#ffffff', fg: '#14110c',
  fgMuted: '#83786a', border: '#e7e2d8', brand: '#f2600c',
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtPct(val?: number | null): string {
  if (val == null) return '—'
  return `${(val * 100).toFixed(1)}%`
}

function fmtReturn(val?: number | null): string {
  if (val == null) return '—'
  const pct = (val * 100).toFixed(1)
  return val >= 0 ? `+${pct}%` : `${pct}%`
}

function returnColor(val?: number | null): string {
  if (val == null) return C.fgMuted
  return val >= 0 ? '#22c55e' : '#ef4444'
}

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
  } catch { return iso }
}

function fmtScore(score?: number | null): string {
  if (score == null) return '—'
  return `${Math.round(score)}%`
}

function fmtPrice(val?: number | null): string {
  if (val == null) return '—'
  return `$${val.toFixed(2)}`
}

// ── Stat card ─────────────────────────────────────────────────────────────────

function StatCard({ label, value, sub, valueColor }: {
  label: string; value: string; sub?: string; valueColor?: string
}) {
  return (
    <View style={{
      flex: 1, borderWidth: 1, borderColor: C.border, borderRadius: 10, padding: 14,
    }}>
      <Text style={{
        fontSize: 9, fontWeight: '700', color: C.fgMuted,
        textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 4,
      }}>
        {label}
      </Text>
      <Text style={{
        fontSize: 20, fontWeight: '700', color: valueColor ?? C.fg,
      }}>
        {value}
      </Text>
      {sub && <Text style={{ fontSize: 10, color: C.fgMuted, marginTop: 2 }}>{sub}</Text>}
    </View>
  )
}

// ── Signal accuracy card ──────────────────────────────────────────────────────

const tintBg: Record<Signal, string> = {
  BUY: '#eaf6ee', SELL: '#fbebeb', HOLD: '#fbf1e2',
}
const barColor: Record<Signal, string> = {
  BUY: '#15803d', SELL: '#b91c1c', HOLD: '#b45309',
}
const SIGNAL_ORDER: Signal[] = ['BUY', 'HOLD', 'SELL']

function SignalAccuracyCard({ row }: { row: PerformanceResponse['by_signal'][number] }) {
  const pending = row.settled === 0
  const winPct = row.win_rate != null ? row.win_rate * 100 : 0
  const signal = row.signal as Signal

  return (
    <View style={{ backgroundColor: tintBg[signal], borderRadius: 10, padding: 16, gap: 10, flex: 1 }}>
      <SignalBadge signal={signal} />

      {pending ? (
        <Text style={{ fontSize: 22, fontWeight: '700', color: C.fgMuted }}>Pending</Text>
      ) : (
        <>
          <Text style={{ fontSize: 22, fontWeight: '700', color: C.fg }}>{fmtPct(row.win_rate)}</Text>
          <View style={{ height: 4, borderRadius: 2, backgroundColor: `${C.border}80`, overflow: 'hidden' }}>
            <View style={{
              height: '100%', width: `${winPct}%`,
              backgroundColor: barColor[signal], borderRadius: 2,
            }} />
          </View>
        </>
      )}

      <View>
        <Text style={{ fontSize: 11, color: C.fgMuted }}>{row.settled} of {row.total} settled</Text>
        <Text style={{ fontSize: 12, fontWeight: '600', color: returnColor(row.avg_return_20d) }}>
          Avg 20d: {fmtReturn(row.avg_return_20d)}
        </Text>
      </View>
    </View>
  )
}

// ── Signal history rows ───────────────────────────────────────────────────────

function SignalHistoryRow({ rec }: { rec: SignalRecord }) {
  return (
    <View style={{
      flexDirection: 'row', alignItems: 'center',
      paddingHorizontal: 14, paddingVertical: 10,
      borderBottomWidth: 1, borderBottomColor: `${C.border}80`,
      gap: 8,
    }}>
      <Text style={{ fontSize: 10, color: C.fgMuted, width: 68 }} numberOfLines={1}>
        {fmtDate(rec.generated_at)}
      </Text>
      <Text style={{ fontSize: 12, fontWeight: '700', color: C.fg, width: 40 }}>{rec.ticker}</Text>
      <View style={{ width: 38 }}>
        <SignalBadge signal={rec.signal} />
      </View>
      <Text style={{ fontSize: 11, color: C.fgMuted, width: 30, textAlign: 'right' }}>
        {fmtScore(rec.score)}
      </Text>
      <Text style={{ fontSize: 11, color: returnColor(rec.return_20d), flex: 1, textAlign: 'right' }}>
        {rec.return_20d != null ? fmtReturn(rec.return_20d) : 'Pending'}
      </Text>
      <Text style={{ fontSize: 10, width: 48, textAlign: 'right',
        color: rec.was_correct ? '#15803d' : rec.return_20d == null ? C.fgMuted : '#b91c1c',
        fontWeight: rec.return_20d != null ? '600' : '400',
      }}>
        {rec.return_20d == null ? '—' : rec.was_correct ? '✓ Yes' : '✗ No'}
      </Text>
    </View>
  )
}

// ── By-ticker table ───────────────────────────────────────────────────────────

function ByTickerRow({ row }: { row: PerformanceResponse['by_ticker'][number] }) {
  return (
    <View style={{
      flexDirection: 'row', alignItems: 'center',
      paddingHorizontal: 14, paddingVertical: 10,
      borderBottomWidth: 1, borderBottomColor: `${C.border}80`,
    }}>
      <Text style={{ fontSize: 12, fontWeight: '700', color: C.fg, flex: 1 }}>{row.ticker}</Text>
      <Text style={{ fontSize: 11, color: C.fgMuted, width: 40, textAlign: 'right' }}>{row.total}</Text>
      <Text style={{ fontSize: 11, color: C.fgMuted, width: 48, textAlign: 'right' }}>{row.settled}</Text>
      <Text style={{
        fontSize: 11, width: 56, textAlign: 'right',
        color: row.win_rate != null && row.win_rate >= 0.5 ? '#22c55e' : C.fgMuted,
        fontWeight: '600',
      }}>
        {fmtPct(row.win_rate)}
      </Text>
      <Text style={{ fontSize: 11, width: 56, textAlign: 'right', color: returnColor(row.avg_return_20d), fontWeight: '600' }}>
        {fmtReturn(row.avg_return_20d)}
      </Text>
    </View>
  )
}

// ── Performance Screen ────────────────────────────────────────────────────────

export default function PerformanceScreen() {
  const [data, setData] = useState<PerformanceResponse | null>(null)
  const [signalHistory, setSignalHistory] = useState<SignalRecord[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([performanceApi.get(), performanceApi.signals()])
      .then(([perfRes, sigRes]) => {
        setData(perfRes.data as PerformanceResponse)
        setSignalHistory(sigRes.data)
      })
      .catch((err: unknown) => {
        const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        setError(msg ?? 'Failed to load performance data.')
      })
      .finally(() => setIsLoading(false))
  }, [])

  const orderedBySignal = data
    ? SIGNAL_ORDER.map(
        (sig) =>
          data.by_signal.find((r) => r.signal === sig) ?? {
            signal: sig, total: 0, settled: 0, correct: 0,
          },
      )
    : []

  const isPending = data && data.total_signals > 0 && data.settled_signals === 0
  const sortedByTicker = data
    ? [...data.by_ticker].sort((a, b) => (b.win_rate ?? 0) - (a.win_rate ?? 0))
    : []

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.bg }} edges={['top']}>
      <ScrollView
        contentContainerStyle={{ paddingHorizontal: 16, paddingTop: 20, paddingBottom: 100 }}
        showsVerticalScrollIndicator={false}
      >
        {/* Header */}
        <Text style={{ fontSize: 22, fontWeight: '700', color: C.fg, marginBottom: 4 }}>
          Signal Accuracy
        </Text>
        <Text style={{ fontSize: 13, color: C.fgMuted, marginBottom: 24 }}>
          Historical accuracy of AI-generated trading signals
        </Text>

        {isLoading ? (
          <View style={{ alignItems: 'center', paddingVertical: 60 }}>
            <LoadingSpinner size="lg" />
          </View>
        ) : error ? (
          <View style={{
            flexDirection: 'row', alignItems: 'center', gap: 10,
            padding: 14, borderRadius: 10,
            backgroundColor: 'rgba(239,68,68,0.08)', borderWidth: 1, borderColor: 'rgba(239,68,68,0.2)',
          }}>
            <AlertCircle size={16} color="#ef4444" />
            <Text style={{ fontSize: 13, color: '#ef4444', flex: 1 }}>{error}</Text>
          </View>
        ) : !data || data.total_signals === 0 ? (
          <View style={{ alignItems: 'center', paddingVertical: 48 }}>
            <View style={{
              width: 64, height: 64, borderRadius: 18,
              backgroundColor: 'rgba(242,96,12,0.1)',
              alignItems: 'center', justifyContent: 'center', marginBottom: 16,
            }}>
              <BarChart2 size={32} color={C.brand} />
            </View>
            <Text style={{ fontSize: 16, fontWeight: '600', color: C.fg, marginBottom: 8 }}>
              No performance data yet
            </Text>
            <Text style={{ fontSize: 13, color: C.fgMuted, textAlign: 'center', maxWidth: 260 }}>
              Signals settle after 20 trading days (~28 calendar days).
            </Text>
          </View>
        ) : (
          <>
            {/* Overview stats */}
            <View style={{ flexDirection: 'row', gap: 8, marginBottom: 8 }}>
              <StatCard label="Total Signals" value={String(data.total_signals)} sub="All time" />
              <StatCard label="Settled" value={String(data.settled_signals)} sub="20d+ old" />
            </View>
            <View style={{ flexDirection: 'row', gap: 8, marginBottom: 24 }}>
              <StatCard
                label="Win Rate" value={fmtPct(data.overall_win_rate)}
                sub={isPending ? 'Pending settlement' : 'On settled signals'}
                valueColor={data.overall_win_rate != null && data.overall_win_rate >= 0.5 ? '#22c55e' : C.fg}
              />
              <StatCard
                label="Avg 20d Return" value={fmtReturn(data.overall_avg_return_20d)}
                sub="Per signal" valueColor={returnColor(data.overall_avg_return_20d)}
              />
            </View>

            {isPending && (
              <View style={{
                flexDirection: 'row', alignItems: 'flex-start', gap: 10,
                padding: 12, borderRadius: 10,
                backgroundColor: 'rgba(234,179,8,0.1)', borderWidth: 1, borderColor: 'rgba(234,179,8,0.2)',
                marginBottom: 24,
              }}>
                <TrendingUp size={14} color="#ca8a04" style={{ marginTop: 1 }} />
                <Text style={{ fontSize: 12, color: '#ca8a04', flex: 1 }}>
                  {data.total_signals} signal{data.total_signals !== 1 ? 's' : ''} tracking — win rate appears after 20 trading days.
                </Text>
              </View>
            )}

            {/* By signal type */}
            <Text style={{
              fontSize: 9, fontWeight: '700', color: C.fgMuted,
              textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 12,
            }}>
              By Signal Type
            </Text>
            <View style={{ flexDirection: 'row', gap: 8, marginBottom: 24 }}>
              {orderedBySignal.map((row) => (
                <SignalAccuracyCard key={row.signal} row={row} />
              ))}
            </View>

            {/* Signal history */}
            <Text style={{
              fontSize: 9, fontWeight: '700', color: C.fgMuted,
              textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 12,
            }}>
              Signal History
            </Text>
            <View style={{
              backgroundColor: C.surface, borderRadius: 12,
              borderWidth: 1, borderColor: C.border, overflow: 'hidden', marginBottom: 24,
            }}>
              {signalHistory.length === 0 ? (
                <View style={{ padding: 24, alignItems: 'center', gap: 8 }}>
                  <Clock size={20} color={C.fgMuted} />
                  <Text style={{ fontSize: 13, color: C.fgMuted }}>No signal history yet.</Text>
                </View>
              ) : (
                <>
                  {/* Table header */}
                  <View style={{
                    flexDirection: 'row', paddingHorizontal: 14, paddingVertical: 8,
                    borderBottomWidth: 1, borderBottomColor: C.border,
                  }}>
                    {['Date', 'Ticker', 'Sig', 'Score', '20d Ret', 'Correct'].map((h, i) => (
                      <Text key={h} style={{
                        fontSize: 8, fontWeight: '700', color: C.fgMuted,
                        textTransform: 'uppercase', letterSpacing: 0.6,
                        width: i === 0 ? 68 : i === 1 ? 40 : i === 2 ? 38 : i === 3 ? 30 : i === 4 ? undefined : 48,
                        flex: i === 4 ? 1 : undefined,
                        textAlign: i >= 3 ? 'right' : 'left',
                      }}>
                        {h}
                      </Text>
                    ))}
                  </View>
                  {signalHistory.slice(0, 50).map((rec, i) => (
                    <SignalHistoryRow key={`${rec.ticker}-${rec.generated_at}-${i}`} rec={rec} />
                  ))}
                </>
              )}
            </View>

            {/* By ticker */}
            {sortedByTicker.length > 0 && (
              <>
                <Text style={{
                  fontSize: 9, fontWeight: '700', color: C.fgMuted,
                  textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 12,
                }}>
                  By Ticker
                </Text>
                <View style={{
                  backgroundColor: C.surface, borderRadius: 12,
                  borderWidth: 1, borderColor: C.border, overflow: 'hidden', marginBottom: 24,
                }}>
                  <View style={{
                    flexDirection: 'row', paddingHorizontal: 14, paddingVertical: 8,
                    borderBottomWidth: 1, borderBottomColor: C.border,
                  }}>
                    {['Ticker', 'Total', 'Settled', 'Win %', 'Avg 20d'].map((h, i) => (
                      <Text key={h} style={{
                        fontSize: 8, fontWeight: '700', color: C.fgMuted,
                        textTransform: 'uppercase', letterSpacing: 0.6,
                        flex: i === 0 ? 1 : undefined,
                        width: i > 0 ? [40, 48, 56, 56][i - 1] : undefined,
                        textAlign: i > 0 ? 'right' : 'left',
                      }}>
                        {h}
                      </Text>
                    ))}
                  </View>
                  {sortedByTicker.map((row) => <ByTickerRow key={row.ticker} row={row} />)}
                </View>
              </>
            )}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  )
}
