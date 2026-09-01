import React, { useCallback, useEffect, useState } from 'react'
import { ActivityIndicator, RefreshControl, ScrollView, Switch, Text, View } from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { AlertCircle, CheckCircle2, HelpCircle, XCircle } from 'lucide-react-native'
import { performanceApi } from '../../src/lib/api'
import type {
  CalibrationBucket, CalibrationReport, ConfidenceBucket, OverrideBlock,
  ScoreBucket, ThresholdRow,
} from '../../src/types'
import Disclaimer from '../../src/components/Disclaimer'
import { usePalette, type Palette } from '../../src/lib/palette'

/**
 * Threshold calibration on the phone — the counterpart of the web
 * `CalibrationPage`.
 *
 * Same two rules, and they are the point of the screen:
 *   - Every number carries its sample size. Under `min_samples_for_signal` a
 *     bucket is marked *thin* rather than shown as a confident percentage.
 *   - It reports; it does not tune.
 */


function pct(v: number | null | undefined, digits = 0): string {
  return v == null ? '—' : `${(v * 100).toFixed(digits)}%`
}

function signedPct(v: number | null | undefined, digits = 2): string {
  if (v == null) return '—'
  const s = (v * 100).toFixed(digits)
  return v >= 0 ? `+${s}%` : `${s}%`
}

function returnTone(C: Palette, v: number | null | undefined): string {
  if (v == null) return C.fgMuted
  return v >= 0 ? C.green : C.red
}

/**
 * Sample-size marker. Deliberately loud — an unflagged 80% win rate on four
 * records is the most misleading thing this screen could render.
 */
function Sample({ row }: { row: CalibrationBucket }) {
  const C = usePalette()
  if (row.n === 0) {
    return <Text style={{ fontSize: 11, color: C.fgMuted }}>0</Text>
  }
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 5 }}>
      <Text style={{
        fontSize: 11, color: row.significant ? C.fg : C.fgMuted,
        fontVariant: ['tabular-nums'],
      }}>
        {row.n}
      </Text>
      {!row.significant && (
        <View style={{
          paddingHorizontal: 4, paddingVertical: 1, borderRadius: 3,
          backgroundColor: `${C.amber}1f`,
        }}>
          <Text style={{ fontSize: 8, fontWeight: '700', color: C.amber }}>THIN</Text>
        </View>
      )}
    </View>
  )
}

function Header({ cols }: { cols: string[] }) {
  const C = usePalette()
  return (
    <View style={{
      flexDirection: 'row', paddingHorizontal: 12, paddingVertical: 8,
      borderBottomWidth: 1, borderBottomColor: C.border,
    }}>
      {cols.map((c, i) => (
        <Text
          key={c}
          style={{
            flex: i === 0 ? 1.4 : 1, fontSize: 9, fontWeight: '700', color: C.fgMuted,
            textTransform: 'uppercase', letterSpacing: 0.8,
            textAlign: i === 0 ? 'left' : 'right',
          }}
        >
          {c}
        </Text>
      ))}
    </View>
  )
}

function Card({ children }: { children: React.ReactNode }) {
  const C = usePalette()
  return (
    <View style={{
      backgroundColor: C.surface, borderRadius: 12, borderWidth: 1,
      borderColor: C.border, overflow: 'hidden',
    }}>
      {children}
    </View>
  )
}

function Row({ cells, last }: { cells: React.ReactNode[]; last?: boolean }) {
  const C = usePalette()
  return (
    <View style={{
      flexDirection: 'row', alignItems: 'center', paddingHorizontal: 12, paddingVertical: 10,
      borderBottomWidth: last ? 0 : 1, borderBottomColor: `${C.border}80`,
    }}>
      {cells.map((cell, i) => (
        <View
          key={i}
          style={{ flex: i === 0 ? 1.4 : 1, alignItems: i === 0 ? 'flex-start' : 'flex-end' }}
        >
          {cell}
        </View>
      ))}
    </View>
  )
}

function Block({ title, blurb, children }: {
  title: string
  blurb: string
  children: React.ReactNode
}) {
  const C = usePalette()
  return (
    <View style={{ gap: 10, marginBottom: 28 }}>
      <View>
        <Text style={{
          fontSize: 11, fontWeight: '700', color: C.fgMuted,
          textTransform: 'uppercase', letterSpacing: 1,
        }}>
          {title}
        </Text>
        <Text style={{ fontSize: 11, color: C.fgMuted, marginTop: 4, lineHeight: 16 }}>
          {blurb}
        </Text>
      </View>
      {children}
    </View>
  )
}

function Verdict({ report }: { report: CalibrationReport }) {
  const C = usePalette()
  const ranks = report.score_ranks_outcomes
  const cfg = ranks === true
    ? {
        Icon: CheckCircle2, tone: C.green, bg: `${C.green}1a`,
        title: 'The score ranks outcomes.',
        body: `Average return rises across the ${report.usable_buckets} bands with enough `
            + 'settled records to say. The composite is separating winners from losers.',
      }
    : ranks === false
      ? {
          Icon: XCircle, tone: C.red, bg: `${C.red}1a`,
          title: 'The score does not rank outcomes.',
          body: 'No threshold is the right threshold on a flat curve — the answer is to '
              + 'fix the score, not to move the line.',
        }
      : {
          Icon: HelpCircle, tone: C.fgMuted, bg: `${C.border}70`,
          title: 'Not enough evidence yet.',
          body: `Fewer than two bands have reached ${report.min_samples_for_signal} settled `
              + 'records. This is the honest state of a young track record, not a failure.',
        }

  const { Icon, tone, bg, title, body } = cfg
  return (
    <View style={{
      flexDirection: 'row', gap: 12, alignItems: 'flex-start',
      backgroundColor: bg, borderRadius: 12, padding: 14, marginBottom: 20,
    }}>
      <Icon size={20} color={tone} style={{ marginTop: 1 }} />
      <View style={{ flex: 1 }}>
        <Text style={{ fontSize: 13, fontWeight: '700', color: tone }}>{title}</Text>
        <Text style={{ fontSize: 11, color: C.fgMuted, marginTop: 4, lineHeight: 16 }}>{body}</Text>
      </View>
    </View>
  )
}

function Stat({ label, value, tone, sub }: {
  label: string; value: string; tone?: string; sub: string
}) {
  const C = usePalette()
  return (
    <View style={{
      flex: 1, minWidth: '46%', backgroundColor: C.surface, borderRadius: 12,
      borderWidth: 1, borderColor: C.border, padding: 12,
    }}>
      <Text style={{
        fontSize: 9, fontWeight: '700', color: C.fgMuted,
        textTransform: 'uppercase', letterSpacing: 1,
      }}>
        {label}
      </Text>
      <Text style={{
        fontSize: 20, fontWeight: '700', color: tone ?? C.fg, marginTop: 2,
        fontVariant: ['tabular-nums'],
      }}>
        {value}
      </Text>
      <Text style={{ fontSize: 10, color: C.fgMuted, marginTop: 1 }}>{sub}</Text>
    </View>
  )
}

/**
 * One side of the analyst gate, against the decisions it left alone. The phone
 * counterpart of the web `OverrideBlockCard`.
 *
 * The two group figures are deliberately untoned: green-good would mean
 * opposite things on the two blocks — a refused buy doing badly is the gate
 * working, a forced exit doing badly is not — and a colour that inverts between
 * two cards on one screen teaches nothing. The gap carries the judgement.
 */
function OverrideCard({ block, minSamples }: {
  block: OverrideBlock; minSamples: number
}) {
  const C = usePalette()
  const refused = block.direction === 'long'
  return (
    <View style={{ gap: 10 }}>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
        <Stat
          label={refused ? 'Refused' : 'Forced out'}
          value={signedPct(block.overridden.avg_alpha)}
          sub={`${block.overridden.alpha_n} settled${refused ? '' : ' · sign-flipped'}`}
        />
        <Stat
          label="Left alone"
          value={signedPct(block.control.avg_alpha)}
          sub={`${block.control.alpha_n} settled`}
        />
        <Stat
          label="Gap"
          value={block.alpha_saved == null ? '—' : signedPct(block.alpha_saved)}
          tone={returnTone(C, block.alpha_saved)}
          sub="positive = gate was right"
        />
      </View>
      <Text style={{ fontSize: 11, color: C.fgMuted, lineHeight: 16 }}>
        {!block.conclusive
          ? `Not enough settled records on both sides to conclude anything. Under `
            + `${minSamples} a gap this size is noise.`
          : block.alpha_saved != null && block.alpha_saved > 0
            ? refused
              ? 'The buys the gate refused did worse than the ones it allowed. The gate is '
                + 'earning its place.'
              : 'The positions the gate forced out fell harder than the exits both sides '
                + 'agreed on. Overruling the analyst beat an ordinary exit.'
            : refused
              ? 'The buys the gate refused did no worse than the ones it allowed — on this '
                + 'evidence it is spending an opportunity on every refusal.'
              : 'The positions the gate forced out held up better than ordinary exits. The '
                + 'analyst was seeing something the score was not.'}
      </Text>
    </View>
  )
}


function AnalystGateBlock({ report }: { report: CalibrationReport }) {
  const C = usePalette()
  const gate = report.analyst_gate
  if (!gate) return null

  if (gate.recorded_records === 0) {
    return (
      <Block title="Was the analyst gate worth having?" blurb="Nothing to say yet.">
        <Text style={{ fontSize: 11, color: C.fgMuted, lineHeight: 16 }}>
          No settled signal yet carries a record of what the gate decided. The override
          has only been retained since 1.24.0 and a record needs about twenty trading
          days to settle, so the first reading is not due before October. Rows from
          before then cannot be backfilled — the decision was never stored.
        </Text>
      </Block>
    )
  }

  return (
    <Block
      title="Was the analyst gate worth having?"
      blurb="The AI analyst is overruled in two directions: a buy the rule refuses, and an
             exit it wanted to hold open. Never combined — opposite bets, and the exit
             figures are sign-flipped so a name falling reads as the right call."
    >
      <View style={{ gap: 16 }}>
        <View style={{ gap: 8 }}>
          <Text style={{
            fontSize: 9, fontWeight: '700', color: C.fgMuted,
            textTransform: 'uppercase', letterSpacing: 1,
          }}>
            Buys the gate refused
          </Text>
          <OverrideCard block={gate.buy_refused} minSamples={report.min_samples_for_signal} />
        </View>
        <View style={{ gap: 8 }}>
          <Text style={{
            fontSize: 9, fontWeight: '700', color: C.fgMuted,
            textTransform: 'uppercase', letterSpacing: 1,
          }}>
            Exits the gate forced
          </Text>
          <OverrideCard block={gate.sell_restored} minSamples={report.min_samples_for_signal} />
        </View>
        <Text style={{ fontSize: 10, color: C.fgMuted, lineHeight: 15 }}>
          {gate.recorded_records} settled record
          {gate.recorded_records === 1 ? '' : 's'} carry a gate decision. Signals from
          before 1.24.0 are excluded rather than counted as agreement.
        </Text>
      </View>
    </Block>
  )
}


export default function CalibrationScreen() {
  const C = usePalette()
  const [report, setReport] = useState<CalibrationReport | null>(null)
  const [riskGate, setRiskGate] = useState(true)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (gate: boolean) => {
    setError(null)
    try {
      const res = await performanceApi.calibration(undefined, gate)
      setReport(res.data)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setError(detail ?? 'Failed to load calibration data.')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => { load(riskGate) }, [load, riskGate])

  const num = (v: string) => (
    <Text style={{ fontSize: 12, color: C.fg, fontVariant: ['tabular-nums'] }}>{v}</Text>
  )
  const muted = (v: string) => (
    <Text style={{ fontSize: 12, color: C.fgMuted, fontVariant: ['tabular-nums'] }}>{v}</Text>
  )
  const ret = (v: number | null | undefined) => (
    <Text style={{ fontSize: 12, color: returnTone(C, v), fontVariant: ['tabular-nums'] }}>
      {signedPct(v)}
    </Text>
  )

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.bg }} edges={['top']}>
      <ScrollView
        contentContainerStyle={{ paddingHorizontal: 16, paddingTop: 20, paddingBottom: 100 }}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => { setRefreshing(true); load(riskGate) }}
            tintColor={C.brand}
          />
        }
      >
        <Text style={{ fontSize: 24, fontWeight: '300', color: C.fg }}>Calibration</Text>
        <Text style={{ fontSize: 13, color: C.fgMuted, marginTop: 2, marginBottom: 20, lineHeight: 19 }}>
          Were the thresholds in the right place? Measured against realised 20-day returns
          on settled signals.
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
        ) : !report || report.settled_records === 0 ? (
          <View style={{
            backgroundColor: C.surface, borderRadius: 12, borderWidth: 1,
            borderColor: C.border, padding: 24, alignItems: 'center', gap: 8,
          }}>
            <Text style={{ fontSize: 15, fontWeight: '600', color: C.fg }}>
              Nothing has settled yet
            </Text>
            <Text style={{ fontSize: 12, color: C.fgMuted, textAlign: 'center', lineHeight: 18 }}>
              Calibration needs signals at least 20 trading days old, so their realised
              return is known. Until then there is nothing to calibrate against — and no
              honest way to claim the thresholds are right.
            </Text>
          </View>
        ) : (
          <>
            <Verdict report={report} />

            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginBottom: 28 }}>
              <Stat label="Settled" value={String(report.settled_records)} sub="with a 20d outcome" />
              <Stat label="Base win rate" value={pct(report.base_rate.win_rate, 1)} sub="all signals" />
              <Stat
                label="Base avg 20d"
                value={signedPct(report.base_rate.avg_return)}
                tone={returnTone(C, report.base_rate.avg_return)}
                sub="the bar to beat"
              />
              <Stat
                label="Usable bands"
                value={String(report.usable_buckets)}
                sub={`≥${report.min_samples_for_signal} records`}
              />
            </View>

            <Block
              title="Does a higher score earn a higher return?"
              blurb="Read this first. A flat curve means the score is not separating winners
                     from losers, and moving the BUY threshold would only pick a different
                     arbitrary point on it."
            >
              <Card>
                <Header cols={['Band', 'Signals', 'Win', 'Avg 20d']} />
                {report.score_buckets.map((r: ScoreBucket, i) => (
                  <Row
                    key={`${r.lo}-${r.hi}`}
                    last={i === report.score_buckets.length - 1}
                    cells={[
                      num(`${r.lo.toFixed(2)}–${r.hi.toFixed(2)}`),
                      <Sample row={r} />,
                      muted(pct(r.win_rate, 0)),
                      ret(r.avg_return),
                    ]}
                  />
                ))}
              </Card>
            </Block>

            <Block
              title="What would each BUY cutoff have returned?"
              blurb="0.70 is the incumbent, placed by guess before there was history to place
                     it with. Evidence for a human decision, not a setting to auto-fit."
            >
              <View style={{
                flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 4,
              }}>
                <Switch
                  value={riskGate}
                  onValueChange={setRiskGate}
                  trackColor={{ false: C.border, true: C.brand }}
                  thumbColor="#ffffff"
                />
                <Text style={{ fontSize: 12, color: C.fg }}>Also apply the risk veto</Text>
              </View>
              <Card>
                <Header cols={['BUY above', 'Signals', 'Win', 'Avg 20d']} />
                {report.threshold_sweep.map((r: ThresholdRow, i) => {
                  const incumbent = Math.abs(r.threshold - 0.7) < 1e-9
                  return (
                    <Row
                      key={r.threshold}
                      last={i === report.threshold_sweep.length - 1}
                      cells={[
                        <Text style={{ fontSize: 12, color: C.fg, fontVariant: ['tabular-nums'] }}>
                          {r.threshold.toFixed(2)}
                          {incumbent && (
                            <Text style={{ fontSize: 9, color: C.brand }}>  CURRENT</Text>
                          )}
                        </Text>,
                        <Sample row={r} />,
                        muted(pct(r.win_rate, 0)),
                        ret(r.avg_return),
                      ]}
                    />
                  )
                })}
              </Card>
              {/* Reading a low-coverage sweep as the real gate would overstate it. */}
              {report.threshold_sweep[0]?.risk_filtered
                && report.threshold_sweep[0].risk_coverage < 1 && (
                <Text style={{ fontSize: 10, color: C.amber, lineHeight: 15 }}>
                  The risk veto could only be applied to{' '}
                  {pct(report.threshold_sweep[0].risk_coverage)} of these records — history
                  did not carry a risk score until recently, so this is not a full model of
                  the live gate.
                </Text>
              )}
            </Block>

            <Block
              title="Does stated confidence track being right?"
              blurb="Confidence is distance from the decision boundary, which is not a hit
                     rate and had never been compared to one."
            >
              <Card>
                <Header cols={['Confidence', 'Signals', 'Win', 'Avg 20d']} />
                {report.confidence_buckets.map((r: ConfidenceBucket, i) => (
                  <Row
                    key={`${r.lo}-${r.hi}`}
                    last={i === report.confidence_buckets.length - 1}
                    cells={[
                      num(`${pct(r.lo)}–${pct(r.hi)}`),
                      <Sample row={r} />,
                      muted(pct(r.win_rate, 0)),
                      ret(r.avg_return),
                    ]}
                  />
                ))}
              </Card>
            </Block>

            <AnalystGateBlock report={report} />

            <Text style={{ fontSize: 10, color: C.fgMuted, lineHeight: 15 }}>
              This screen reports; it does not tune. Fitting a threshold to its own history
              is how a system talks itself into whatever the last few months rewarded. Rows
              marked <Text style={{ color: C.amber, fontWeight: '700' }}>THIN</Text> have
              fewer than {report.min_samples_for_signal} settled records and are anecdote,
              not evidence.
            </Text>
          </>
        )}

        <Disclaimer />
      </ScrollView>
    </SafeAreaView>
  )
}
