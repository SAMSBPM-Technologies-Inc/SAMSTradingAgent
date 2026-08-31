import React from 'react'
import { Text, View } from 'react-native'
import { Check, Info, ShieldAlert, X } from 'lucide-react-native'
import type { RiskAssessment, ScoreBreakdown, Signal, SignalGate, SignalInputs } from '../types'
import { usePalette, type Palette } from '../lib/palette'

/**
 * Score attribution and the risk gate — the phone counterparts of the web
 * `FactorBreakdown` and `RiskPanel`.
 *
 * Both answer questions the composite number raises and previously could not:
 * where did this score come from, and why is (or isn't) this a BUY.
 */


function pct(v: number): string {
  return `${Math.round(v * 100)}`
}

/** Sub-score colouring matches the gauge: green good, red weak. */
function scoreTone(C: Palette, score: number): string {
  if (score >= 0.7) return C.green
  if (score >= 0.4) return C.amber
  return C.red
}

function Bar({ fraction, color, height = 6 }: {
  fraction: number
  color: string
  height?: number
}) {
  const C = usePalette()
  return (
    <View style={{
      height, borderRadius: height / 2, backgroundColor: C.border, overflow: 'hidden',
    }}>
      <View style={{
        height: '100%',
        width: `${Math.max(0, Math.min(100, fraction * 100))}%`,
        backgroundColor: color,
        borderRadius: height / 2,
      }} />
    </View>
  )
}

// ── Factor breakdown ──────────────────────────────────────────────────────────

/**
 * How much of this score was measured, stated above the factors themselves.
 *
 * A 0.50 sub-score in the rows below is ambiguous in a way nothing else on the
 * panel resolves: it means either "measured, and genuinely neutral" or "we
 * never found out". Renders nothing at full completeness — a banner that is
 * always there stops being read.
 */
function InputCompleteness({ inputs }: { inputs: SignalInputs }) {
  const C = usePalette()
  if (inputs.completeness == null || inputs.completeness >= 0.999) return null

  const measured = Math.round(inputs.completeness * 100)
  const named = inputs.fallback_factors
  return (
    <View style={{
      flexDirection: 'row', gap: 8, alignItems: 'flex-start',
      backgroundColor: `${C.border}60`, borderRadius: 8, padding: 10,
    }}>
      <Info size={13} color={C.fgMuted} style={{ marginTop: 2 }} />
      <Text style={{ flex: 1, fontSize: 11, lineHeight: 16, color: C.fgMuted }}>
        <Text style={{ fontWeight: '700', color: C.fg }}>
          {measured}% of this score came from measured data.
        </Text>
        {named.length > 0
          ? ` ${named.join(' and ')} ${named.length === 1 ? 'was' : 'were'} unavailable, so `
            + `${named.length === 1 ? 'it sits' : 'they sit'} at a neutral 0.50 and `
            + `${named.length === 1 ? 'says' : 'say'} nothing about this company.`
          : ' Some factors were built from partial data and are blended toward neutral.'}
      </Text>
    </View>
  )
}

export function FactorBreakdown({
  breakdown,
  inputs,
}: {
  breakdown: ScoreBreakdown
  inputs?: SignalInputs | null
}) {
  const C = usePalette()
  // The ML path did not compute this score from these weights, so a weighted
  // decomposition beside it would be a fabrication.
  if (!breakdown.attributable) {
    return (
      <View style={{ flexDirection: 'row', gap: 8, alignItems: 'flex-start' }}>
        <Info size={14} color={C.fgMuted} style={{ marginTop: 2 }} />
        <Text style={{ flex: 1, fontSize: 11, color: C.fgMuted, lineHeight: 16 }}>
          This score came from the {breakdown.method} model, not the weighted composite.
          A factor breakdown would not describe how it was produced, so none is shown.
        </Text>
      </View>
    )
  }

  const alt = breakdown.alternative_data
  const maxContribution = Math.max(
    ...breakdown.factors.map((f) => Math.abs(f.contribution)),
    alt ? Math.abs(alt.contribution) : 0,
    0.0001,
  )

  return (
    <View style={{ gap: 10 }}>
      {inputs ? <InputCompleteness inputs={inputs} /> : null}
      <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
        <Text style={{
          fontSize: 9, color: C.fgMuted, textTransform: 'uppercase', letterSpacing: 1,
        }}>
          Factor · sub-score / contribution
        </Text>
        {breakdown.personalized && (
          <Text style={{ fontSize: 9, color: C.brand }}>Your weights</Text>
        )}
      </View>

      {breakdown.factors.map((f) => {
        const inactive = f.weight === 0
        return (
          <View
            key={f.key}
            style={{
              flexDirection: 'row', alignItems: 'center', gap: 10,
              opacity: inactive ? 0.45 : 1,
            }}
          >
            <View style={{ width: 84 }}>
              <Text style={{ fontSize: 11, fontWeight: '600', color: C.fg }}>{f.label}</Text>
              <Text style={{ fontSize: 9, color: C.fgMuted }}>
                {inactive ? 'weight 0 — excluded' : `weight ${pct(f.weight)}%`}
              </Text>
            </View>

            <View style={{ flex: 1, gap: 3 }}>
              {/* How the factor rated. */}
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                <View style={{ flex: 1 }}>
                  <Bar fraction={f.score} color={scoreTone(C, f.score)} />
                </View>
                <Text style={{
                  fontSize: 9, color: C.fgMuted, width: 22, textAlign: 'right',
                  fontVariant: ['tabular-nums'],
                }}>
                  {pct(f.score)}
                </Text>
              </View>
              {/* How many points of the composite it actually supplied. */}
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                <View style={{ flex: 1 }}>
                  <Bar
                    fraction={Math.abs(f.contribution) / maxContribution}
                    color={C.fgMuted}
                    height={3}
                  />
                </View>
                <View style={{ width: 22 }} />
              </View>
            </View>

            <Text style={{
              width: 44, textAlign: 'right', fontSize: 11, fontWeight: '600',
              color: C.fg, fontVariant: ['tabular-nums'],
            }}>
              {f.contribution.toFixed(3)}
            </Text>
          </View>
        )
      })}

      {/* Totals — the arithmetic has to be checkable or the panel is decoration. */}
      <View style={{ gap: 3, paddingTop: 8, borderTopWidth: 1, borderTopColor: C.border }}>
        <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
          <Text style={{ fontSize: 11, color: C.fgMuted }}>Weighted base</Text>
          <Text style={{ fontSize: 11, color: C.fg, fontVariant: ['tabular-nums'] }}>
            {breakdown.base_total.toFixed(3)}
          </Text>
        </View>
        {alt && (
          <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
            <Text style={{ flex: 1, fontSize: 11, color: C.fgMuted }}>
              {alt.label} modifier ({pct(alt.score)} vs 50 neutral)
            </Text>
            <Text style={{
              fontSize: 11, fontVariant: ['tabular-nums'],
              color: alt.contribution > 0 ? C.green : alt.contribution < 0 ? C.red : C.fg,
            }}>
              {alt.contribution >= 0 ? '+' : ''}{alt.contribution.toFixed(3)}
            </Text>
          </View>
        )}
        <View style={{
          flexDirection: 'row', justifyContent: 'space-between',
          paddingTop: 5, borderTopWidth: 1, borderTopColor: C.border,
        }}>
          <Text style={{ fontSize: 12, fontWeight: '700', color: C.fg }}>Composite</Text>
          <Text style={{ fontSize: 12, fontWeight: '700', color: C.fg, fontVariant: ['tabular-nums'] }}>
            {breakdown.composite.toFixed(3)} = {pct(breakdown.composite)}/100
          </Text>
        </View>
      </View>

      <Text style={{ fontSize: 10, color: C.fgMuted, lineHeight: 15 }}>
        The top bar is how the factor scored; the thin bar beneath is how many points of
        the composite it supplied. A factor with weight 0 is excluded no matter how it
        rates — Volatility is priced at the risk gate instead.
      </Text>
    </View>
  )
}

// ── Risk and gate ─────────────────────────────────────────────────────────────

const levelTone = (C: Palette): Record<RiskAssessment['risk_level'], string> => ({
  LOW: C.green, MEDIUM: C.amber, HIGH: C.red,
})

function GateRow({ label, passed, detail }: {
  label: string
  passed: boolean
  detail: string
}) {
  const C = usePalette()
  return (
    <View style={{ flexDirection: 'row', gap: 8, alignItems: 'flex-start' }}>
      {passed
        ? <Check size={14} color={C.green} style={{ marginTop: 1 }} />
        : <X size={14} color={C.red} style={{ marginTop: 1 }} />}
      <Text style={{ flex: 1, fontSize: 12, color: C.fg }}>
        {label}{' '}
        <Text style={{ color: C.fgMuted, fontVariant: ['tabular-nums'] }}>{detail}</Text>
      </Text>
    </View>
  )
}

/**
 * Who decided this verdict, and what the analyst wanted instead. Mirrors the
 * web `AnalystVerdict` in `RiskPanel.tsx`.
 *
 * The gate rows above describe a rule. Until 1.22.0 the AI analyst published
 * verdicts that rule never saw, so a BUY at 62 rendered "✗ Score above
 * threshold" beside a BUY badge with nothing to say the two described
 * different decisions. Renders nothing in the ordinary case.
 */
function AnalystVerdict({ gate }: { gate: SignalGate }) {
  const C = usePalette()
  const analyst = gate.analyst
  if (!analyst) return null

  if (!analyst.checked) {
    return (
      <View style={{
        flexDirection: 'row', gap: 8, alignItems: 'flex-start',
        backgroundColor: C.hover, borderRadius: 8, padding: 10, marginTop: 2,
      }}>
        <Info size={14} color={C.fgMuted} style={{ marginTop: 1 }} />
        <Text style={{ flex: 1, fontSize: 11, color: C.fgMuted, lineHeight: 16 }}>
          The AI analyst decided this one, and it was recorded before the gate above
          was applied to that path. The thresholds shown describe the rule, not
          necessarily this verdict.
        </Text>
      </View>
    )
  }

  if (analyst.override) {
    const restored = analyst.override === 'sell_restored'
    return (
      <View style={{
        flexDirection: 'row', gap: 8, alignItems: 'flex-start',
        backgroundColor: `${C.amber}1a`, borderRadius: 8, padding: 10, marginTop: 2,
      }}>
        <ShieldAlert size={14} color={C.amber} style={{ marginTop: 1 }} />
        <Text style={{ flex: 1, fontSize: 11, color: C.amber, lineHeight: 16 }}>
          <Text style={{ fontWeight: '600' }}>
            The AI analyst read this as {analyst.wanted}; the gate
            {restored ? ' overruled it' : ' refused'}.
          </Text>{' '}
          {analyst.reason}{' '}
          {restored
            ? 'An exit is never held back — not by the risk gate, not by research, and not by the analyst.'
            : 'The analyst may talk the engine out of buying. It cannot talk it into it.'}
        </Text>
      </View>
    )
  }

  return (
    <Text style={{ fontSize: 10, color: C.fgMuted, lineHeight: 15 }}>
      The AI analyst produced this verdict and the gate above agreed with it.
    </Text>
  )
}

export function RiskPanel({ risk, gate, signal, score }: {
  risk: RiskAssessment
  gate?: SignalGate | null
  signal: Signal
  score: number
}) {
  const C = usePalette()
  const tone = levelTone(C)[risk.risk_level] ?? C.amber

  return (
    <View style={{ gap: 14 }}>
      <View style={{ gap: 6 }}>
        <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline' }}>
          <Text style={{ fontSize: 12, color: C.fgMuted }}>Risk score</Text>
          <Text style={{ fontSize: 13, fontVariant: ['tabular-nums'] }}>
            <Text style={{ fontWeight: '700', color: C.fg }}>{risk.risk_score.toFixed(1)}</Text>
            <Text style={{ color: C.fgMuted }}> / 10  </Text>
            <Text style={{ fontWeight: '700', color: tone }}>{risk.risk_level}</Text>
          </Text>
        </View>

        {/* The veto line, drawn where the engine actually puts it. */}
        <View style={{ height: 8, borderRadius: 4, backgroundColor: C.border, overflow: 'hidden' }}>
          <View style={{
            height: '100%',
            width: `${Math.max(0, Math.min(100, (risk.risk_score / 10) * 100))}%`,
            backgroundColor: tone,
            borderRadius: 4,
          }} />
        </View>
        {gate && (
          <View style={{
            position: 'relative', height: 10, marginTop: -14, marginBottom: 4,
          }} pointerEvents="none">
            <View style={{
              position: 'absolute',
              left: `${(gate.risk_max_for_buy / 10) * 100}%`,
              width: 1, top: 0, height: 8, backgroundColor: C.fg,
            }} />
          </View>
        )}
        {gate && (
          <Text style={{ fontSize: 10, color: C.fgMuted, lineHeight: 15 }}>
            The marker is {gate.risk_max_for_buy} — at or above it, BUY is vetoed
            regardless of score.
          </Text>
        )}
      </View>

      <Text style={{ fontSize: 12, color: C.fgMuted, lineHeight: 18 }}>
        {risk.explanation}
      </Text>

      {gate && (
        <View style={{ gap: 8, paddingTop: 12, borderTopWidth: 1, borderTopColor: C.border }}>
          <Text style={{
            fontSize: 9, color: C.fgMuted, textTransform: 'uppercase', letterSpacing: 1,
          }}>
            BUY gate
          </Text>
          <GateRow
            label="Score above threshold"
            passed={gate.score_passes_buy}
            detail={`${score.toFixed(2)} vs ${gate.effective_buy_threshold.toFixed(2)}`}
          />
          {/* The band, stated only when it is doing something. A standing BUY
              holds to a lower level than it took to open, and testing against
              the entry threshold printed ✗ underneath a correct BUY. */}
          {gate.effective_buy_threshold < gate.buy_threshold && (
            <Text style={{
              fontSize: 10, color: C.fgMuted, lineHeight: 15, marginTop: -4, marginLeft: 22,
            }}>
              A BUY already in force holds to {gate.effective_buy_threshold.toFixed(2)};
              opening one needs the full {gate.buy_threshold.toFixed(2)}. The band is
              one-sided, so it can never make a BUY easier to acquire.
            </Text>
          )}
          <GateRow
            label="Risk below veto"
            passed={gate.risk_passes_buy}
            detail={`${risk.risk_score.toFixed(1)} vs ${gate.risk_max_for_buy.toFixed(1)}`}
          />

          {/* The case the invisible risk score used to hide entirely. */}
          {gate.score_passes_buy && !gate.risk_passes_buy && signal !== 'BUY' && (
            <View style={{
              flexDirection: 'row', gap: 8, alignItems: 'flex-start',
              backgroundColor: `${C.amber}1a`, borderRadius: 8, padding: 10, marginTop: 2,
            }}>
              <ShieldAlert size={14} color={C.amber} style={{ marginTop: 1 }} />
              <Text style={{ flex: 1, fontSize: 11, color: C.amber, lineHeight: 16 }}>
                Scored high enough to buy, but the risk gate refused it. This is the gate
                doing its job, not a weak signal.
              </Text>
            </View>
          )}

          <AnalystVerdict gate={gate} />

          <Text style={{ fontSize: 10, color: C.fgMuted, lineHeight: 15 }}>
            Only BUY is risk-gated. Refusing to exit a position because conditions look
            dangerous would be backwards, so SELL below {gate.sell_threshold.toFixed(2)} is
            unconditional.
          </Text>
        </View>
      )}
    </View>
  )
}
