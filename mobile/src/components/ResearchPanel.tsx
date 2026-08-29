import React, { useCallback, useEffect, useState } from 'react'
import { ActivityIndicator, Linking, Pressable, Text, View } from 'react-native'
import { AlertCircle, ExternalLink, RefreshCw, ShieldAlert } from 'lucide-react-native'

import { researchApi } from '../lib/api'
import { usePalette, type Palette } from '../lib/palette'
import type {
  DimensionScore,
  EvidenceItem,
  ModelUsed,
  PriorRecordCoverage,
  ResearchDebate,
  ResearchDossier,
  ResearchOutcome,
  ResearchStances,
  ResearchVetoStatus,
  TradeStance,
} from '../types'

/**
 * Deep research dossier — the mobile mirror of the web panel.
 *
 * Same two rules. It never builds a dossier on its own: that is five model
 * calls, so only the button starts one. And everything it renders carries a
 * citation, because anything that did not was deleted server-side before it
 * was stored.
 */
export default function ResearchPanel({ ticker }: { ticker: string }) {
  const C = usePalette()
  const [dossier, setDossier] = useState<ResearchDossier | null>(null)
  const [loading, setLoading] = useState(true)
  const [building, setBuilding] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const { data } = await researchApi.get(ticker)
      setDossier(data)
    } catch {
      // A 404 is the ordinary state for an unresearched ticker, not an error.
      setDossier(null)
    } finally {
      setLoading(false)
    }
  }, [ticker])

  useEffect(() => { void load() }, [load])

  const build = useCallback(async () => {
    setBuilding(true)
    setError(null)
    try {
      const { data } = await researchApi.build(ticker)
      setDossier(data)
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setError(detail ?? 'Research failed. Check the server logs.')
    } finally {
      setBuilding(false)
    }
  }, [ticker])

  if (loading) {
    return <Text style={{ fontSize: 13, color: C.fgMuted }}>Loading research…</Text>
  }

  return (
    <View style={{ gap: 14 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
        {dossier
          ? <Header dossier={dossier} C={C} />
          : <Text style={{ fontSize: 13, color: C.fgMuted }}>No dossier yet for {ticker}.</Text>}
      </View>

      <Pressable
        onPress={build}
        disabled={building}
        accessibilityRole="button"
        accessibilityLabel={dossier ? 'Re-run deep research' : 'Run deep research'}
        style={({ pressed }) => ({
          flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8,
          borderWidth: 1, borderColor: C.border, borderRadius: 8,
          paddingVertical: 10, paddingHorizontal: 14,
          backgroundColor: pressed ? C.hover : 'transparent',
          opacity: building ? 0.6 : 1,
        })}
      >
        {building
          ? <ActivityIndicator size="small" color={C.fgMuted} />
          : <RefreshCw size={14} color={C.fg} />}
        <Text style={{ fontSize: 13, fontWeight: '500', color: C.fg }}>
          {building ? 'Researching…' : dossier ? 'Re-run research' : 'Run deep research'}
        </Text>
      </Pressable>

      {building && (
        <Text style={{ fontSize: 12, color: C.fgMuted, lineHeight: 17 }}>
          Four analysts are working this name in parallel, then a fifth merges
          them. This takes a minute or two.
        </Text>
      )}

      {error && <Callout C={C} tone={C.red}>{error}</Callout>}

      <VetoNote veto={dossier?.veto} C={C} />

      {dossier && <Body dossier={dossier} C={C} />}
    </View>
  )
}

function Header({ dossier, C }: { dossier: ResearchDossier; C: Palette }) {
  const assessment = dossier.report?.assessment
  const tone = assessmentTone(assessment, C)
  return (
    <>
      {assessment && (
        <View style={{
          backgroundColor: tone.bg, borderRadius: 5,
          paddingHorizontal: 8, paddingVertical: 3,
        }}>
          <Text style={{ fontSize: 10, fontWeight: '700', color: tone.fg, letterSpacing: 0.5 }}>
            {assessment}
          </Text>
        </View>
      )}
      {dossier.research_conviction != null && (
        <Text style={{ fontSize: 13, fontWeight: '500', color: C.fg }}>
          {/* "Research conviction", never bare "Conviction" — the analyst's own
              HIGH/MEDIUM/LOW conviction is on this same screen and gates
              something else entirely. */}
          Research conviction {Math.round(dossier.research_conviction)}/100
        </Text>
      )}
      <Text style={{ fontSize: 12, color: C.fgMuted }}>{formatAge(dossier)}</Text>
      {dossier.stale && (
        <View style={{
          backgroundColor: C.tintHold, borderRadius: 4,
          paddingHorizontal: 6, paddingVertical: 2,
        }}>
          <Text style={{ fontSize: 9, fontWeight: '700', color: C.amber, letterSpacing: 0.4 }}>
            STALE
          </Text>
        </View>
      )}
      <VetoChip veto={dossier.veto} C={C} />
    </>
  )
}

/**
 * Whether this dossier is standing on the Buy button.
 *
 * In the header rather than the body because it is the one thing here that
 * changes what the system will do, as opposed to what it thinks. `blocking`
 * is a fact about now; `would_block` with the veto off is a fact about a
 * setting — calling the second one "blocked" would be untrue, and hiding it
 * would throw away the only evidence for deciding whether to switch it on.
 */
function VetoChip({ veto, C }: { veto?: ResearchVetoStatus | null; C: Palette }) {
  if (!veto?.would_block) return null
  const blocking = veto.blocking
  return (
    <View style={{
      flexDirection: 'row', alignItems: 'center', gap: 4,
      backgroundColor: blocking ? C.tintSell : C.tintHold,
      borderRadius: 4, paddingHorizontal: 6, paddingVertical: 2,
    }}>
      <ShieldAlert size={11} color={blocking ? C.red : C.amber} />
      <Text style={{
        fontSize: 9, fontWeight: '700', letterSpacing: 0.4,
        color: blocking ? C.red : C.amber,
      }}>
        {blocking ? 'BLOCKS BUYING' : 'WOULD BLOCK'}
      </Text>
    </View>
  )
}

/**
 * What this dossier does to a BUY, stated in full — the mobile mirror of the
 * web panel's note. Names the trigger, the threshold, and how much room is
 * left when nothing is blocking, because 38 against a floor of 35 is a
 * different situation from 90 against 35.
 */
function VetoNote({ veto, C }: { veto?: ResearchVetoStatus | null; C: Palette }) {
  if (!veto) return null

  if (!veto.considered) {
    if (veto.not_considered_reason === 'stale') {
      return (
        <Callout C={C} tone={C.amber}>
          This dossier is older than the {veto.max_age_hours}h the veto will
          trust, so it cannot block an entry. A research outage must not
          silently halt buying.
        </Callout>
      )
    }
    return null
  }

  if (veto.would_block) {
    const trigger = veto.trigger === 'bearish'
      ? 'the assessment is BEARISH'
      : `research conviction ${Math.round(veto.research_conviction ?? 0)} is below the ${Math.round(veto.min_conviction)} floor`
    return veto.blocking ? (
      <Callout C={C} tone={C.red} bg={C.tintSell}>
        Research is blocking new buying in this name — {trigger}. Both the
        agent and your own Buy button run the same guard, so an order placed
        here will be refused. Selling is unaffected: research may veto an
        entry, never an exit.
      </Callout>
    ) : (
      <Callout C={C} tone={C.amber}>
        Research would block a buy here — {trigger} — but the veto is switched
        off, so nothing is being stopped. This is what turning it on would
        have caught.
      </Callout>
    )
  }

  const margin = veto.research_conviction != null
    ? Math.round(veto.research_conviction - veto.min_conviction)
    : null
  return (
    <Text style={{ fontSize: 11, color: C.fgMuted, lineHeight: 16 }}>
      Research does not block buying in this name
      {margin != null && ` — conviction clears the ${Math.round(veto.min_conviction)} floor by ${margin}`}
      {!veto.enabled && ', and the veto is switched off in any case'}.
    </Text>
  )
}

function Body({ dossier, C }: { dossier: ResearchDossier; C: Palette }) {
  const report = dossier.report
  return (
    <View style={{ gap: 14 }}>
      <Dimensions scores={dossier.dimensions} C={C} />

      {dossier.agents_failed.length > 0 && (
        <Callout C={C} tone={C.amber}>
          {dossier.agents_failed.join(', ')} did not report — the call failed.
          Read this dossier as incomplete rather than as a verdict that
          considered everything.
        </Callout>
      )}

      {/* A different message from a failure on purpose: nothing broke, there
          was simply no data in that area to assess. */}
      {dossier.agents_skipped.length > 0 && (
        <Callout C={C} tone={C.amber}>
          No {dossier.agents_skipped.join(', ')} analysis was run — nothing has
          been collected in that area for this ticker yet. Treat those questions
          as open, not as neutral.
        </Callout>
      )}

      {!report && (
        <Callout C={C} tone={C.amber}>
          {dossier.synthesis_error
            ? `The scored dimensions and evidence were computed, but the merge step failed (${dossier.synthesis_error}). The numbers still stand on their own.`
            : 'The scored dimensions and evidence were computed, but no specialist produced anything to merge. The numbers still stand on their own.'}
        </Callout>
      )}

      {report && (
        <>
          <Prose label="Thesis" text={report.thesis} C={C} />
          <Prose label="Bull case" text={report.bull_case} color={C.green} C={C} />
          <Prose label="Bear case" text={report.bear_case} color={C.red} C={C} />
          <Prose
            label="What the market may be missing"
            text={report.what_the_market_is_missing}
            C={C}
          />
          <Bullets label="Key catalysts" items={report.key_catalysts} C={C} />
          <Bullets label="Key risks" items={report.key_risks} color={C.red} C={C} />
          <Bullets
            label="What would change this view"
            items={report.what_would_change_my_opinion}
            hint="Each is meant to be checkable — a figure crossing a level, a dated report."
            C={C}
          />
          <Bullets
            label="Risks raised and answered"
            items={report.risks_addressed}
            hint="Raised by the risk analyst and judged answered by the evidence. Shown so a dismissed risk is visible as a decision rather than a gap."
            C={C}
          />
          <Prose label="Conclusion" text={report.conclusion} C={C} />
          <Debate debate={dossier.debate} C={C} />
          <Stances stances={dossier.stances} C={C} />
        </>
      )}

      <ModelsLine models={dossier.models_used} C={C} />
      <PriorRecordNote coverage={dossier.prior_record} C={C} />
      <OutcomeNote outcome={dossier.outcome} C={C} />

      <Bullets
        label="What could not be assessed"
        items={dossier.data_gaps}
        hint="Named by the analysts themselves. A question this dossier does not answer is not a question with a neutral answer."
        C={C}
      />

      <Evidence items={dossier.evidence} C={C} />
    </View>
  )
}

/**
 * The six dimension bars.
 *
 * Direction is stated in the caption because it is not guessable: higher is
 * better on all six, and on `risk` that means safer. A bar running the other
 * way would be misread eventually.
 */
function Dimensions({ scores, C }: { scores: DimensionScore[]; C: Palette }) {
  if (scores.length === 0) return null
  return (
    <View>
      <Text style={{ fontSize: 11, fontWeight: '600', color: C.fgMuted, letterSpacing: 0.5 }}>
        SCORED DIMENSIONS
      </Text>
      <Text style={{ fontSize: 11, color: C.fgMuted, marginTop: 3, lineHeight: 15 }}>
        0–100, higher is better on all six — including risk, where higher means safer.
      </Text>
      <View style={{ gap: 8, marginTop: 10 }}>
        {scores.map((score) => (
          <View key={score.key} style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
            <Text style={{ fontSize: 12, color: C.fg, width: 96 }} numberOfLines={1}>
              {score.label}
            </Text>
            <View style={{
              flex: 1, height: 6, borderRadius: 3,
              backgroundColor: C.hover, overflow: 'hidden',
            }}>
              {score.score != null && (
                <View style={{
                  height: '100%', width: `${score.score}%`,
                  borderRadius: 3, backgroundColor: barColor(score.score, C),
                }} />
              )}
            </View>
            <Text style={{ fontSize: 11, color: C.fgMuted, width: 68, textAlign: 'right' }}>
              {score.score == null ? 'no data' : Math.round(score.score)}
              {score.thin && score.score != null ? ' · thin' : ''}
              {score.model_judged && score.score != null ? ' · judged' : ''}
            </Text>
          </View>
        ))}
      </View>
    </View>
  )
}

function Prose({
  label, text, color, C,
}: { label: string; text?: string | null; color?: string; C: Palette }) {
  // Absent rather than empty: a heading over nothing reads as a bug.
  if (!text) return null
  return (
    <View>
      <Text style={{
        fontSize: 11, fontWeight: '600', letterSpacing: 0.5,
        color: color ?? C.fgMuted,
      }}>
        {label.toUpperCase()}
      </Text>
      <Text style={{ fontSize: 13, color: C.fg, lineHeight: 19, marginTop: 4 }}>{text}</Text>
    </View>
  )
}

function Bullets({
  label, items, color, hint, C,
}: {
  label: string
  items?: string[]
  color?: string
  hint?: string
  C: Palette
}) {
  if (!items || items.length === 0) return null
  return (
    <View>
      <Text style={{
        fontSize: 11, fontWeight: '600', letterSpacing: 0.5,
        color: color ?? C.fgMuted,
      }}>
        {label.toUpperCase()}
      </Text>
      {hint && (
        <Text style={{ fontSize: 11, color: C.fgMuted, marginTop: 3, lineHeight: 15 }}>
          {hint}
        </Text>
      )}
      <View style={{ gap: 6, marginTop: 6 }}>
        {items.map((item, i) => (
          <View key={i} style={{ flexDirection: 'row', gap: 8 }}>
            <View style={{
              width: 5, height: 5, borderRadius: 2.5, marginTop: 7,
              backgroundColor: color ?? C.fgMuted,
            }} />
            <Text style={{ fontSize: 13, color: C.fg, flex: 1, lineHeight: 19 }}>{item}</Text>
          </View>
        ))}
      </View>
    </View>
  )
}

/**
 * The evidence ledger — what the citations in the prose point at.
 *
 * Collapsed by default because it is long, but present in full: a report whose
 * sources cannot be opened is one you have to take on trust.
 */
function Evidence({ items, C }: { items: EvidenceItem[]; C: Palette }) {
  const [open, setOpen] = useState(false)
  if (!items || items.length === 0) return null
  return (
    <View>
      <Pressable
        onPress={() => setOpen((v) => !v)}
        accessibilityRole="button"
        accessibilityState={{ expanded: open }}
        style={{ flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 4 }}
      >
        <Text style={{ fontSize: 11, fontWeight: '600', color: C.fgMuted, letterSpacing: 0.5 }}>
          EVIDENCE ({items.length} SOURCED FACTS)
        </Text>
        <Text style={{ fontSize: 12, color: C.brand }}>{open ? 'Hide' : 'Show'}</Text>
      </Pressable>
      {open && (
        <View style={{ gap: 8, marginTop: 8 }}>
          {items.map((item) => (
            <View key={item.id} style={{ flexDirection: 'row', gap: 6 }}>
              <Text style={{ fontSize: 11, color: C.fgMuted, minWidth: 32 }}>[{item.id}]</Text>
              <View style={{ flex: 1 }}>
                <Text style={{ fontSize: 12, color: C.fg, lineHeight: 17 }}>
                  {item.claim}: {item.value}
                </Text>
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 5 }}>
                  <Text style={{ fontSize: 11, color: C.fgMuted }}>
                    {item.source}{item.as_of ? `, ${item.as_of}` : ''}
                  </Text>
                  {item.url && (
                    <Pressable
                      onPress={() => void Linking.openURL(item.url as string)}
                      accessibilityRole="link"
                      accessibilityLabel={`Open source for ${item.claim}`}
                      hitSlop={8}
                    >
                      <ExternalLink size={11} color={C.brand} />
                    </Pressable>
                  )}
                </View>
              </View>
            </View>
          ))}
        </View>
      )}
    </View>
  )
}

/**
 * The panel's caveat block. `bg` is overridden only for the case that is not a
 * caveat but a refusal — research actively blocking an entry — which should
 * not read in the same amber as "an agent didn't report".
 */
function Callout({
  C, tone, bg, children,
}: { C: Palette; tone: string; bg?: string; children: React.ReactNode }) {
  return (
    <View style={{
      flexDirection: 'row', gap: 8, alignItems: 'flex-start',
      backgroundColor: bg ?? C.tintHold, borderRadius: 6, padding: 10,
    }}>
      <AlertCircle size={13} color={tone} style={{ marginTop: 2 }} />
      <Text style={{ fontSize: 12, color: tone, flex: 1, lineHeight: 17 }}>{children}</Text>
    </View>
  )
}

/**
 * The rebuttal exchange — mirrors the web panel.
 *
 * The concession is the part worth the most: a bear case nobody answered
 * reaches the report at full strength whether or not the evidence disposes of
 * it, and a defence that answered every risk is the clearest sign the step was
 * not done honestly. Neither is visible in the merged report alone.
 */
function Debate({ debate, C }: { debate?: ResearchDebate | null; C: Palette }) {
  const [open, setOpen] = useState(false)
  if (!debate) return null

  const risk = debate.risk_rebuttal
  const defence = debate.defence_rebuttal
  const conceded = defence?.conceded ?? []
  const surviving = risk?.surviving ?? []

  return (
    <View>
      <Pressable
        onPress={() => setOpen((v) => !v)}
        accessibilityRole="button"
        accessibilityLabel={open ? 'Hide the rebuttal' : 'Show the rebuttal'}
        style={{ flexDirection: 'row', justifyContent: 'space-between' }}
      >
        <Text style={{ fontSize: 11, fontWeight: '600', letterSpacing: 0.5, color: C.fgMuted }}>
          THE REBUTTAL
        </Text>
        <Text style={{ fontSize: 11, color: C.fgMuted }}>{open ? 'hide' : 'show'}</Text>
      </Pressable>
      <Text style={{ fontSize: 11, color: C.fgMuted, marginTop: 3, lineHeight: 15 }}>
        One exchange, after both sides had already written independently — so
        neither inherited the other&rsquo;s framing. {surviving.length} risk
        {surviving.length === 1 ? '' : 's'} survived the evidence;{' '}
        {conceded.length} {conceded.length === 1 ? 'was' : 'were'} conceded as
        unanswerable from what was collected.
      </Text>

      {open && (
        <View style={{ gap: 12, marginTop: 10 }}>
          {!risk && (
            <Callout C={C} tone={C.amber}>
              The risk analyst&rsquo;s reply did not come back. Its original
              risks stand unanswered rather than disposed of.
            </Callout>
          )}
          {!defence && (
            <Callout C={C} tone={C.amber}>
              No defence was recorded. Do not read any risk as answered because
              this half is missing.
            </Callout>
          )}
          <Bullets
            label="Conceded — the evidence does not answer these"
            items={conceded}
            color={C.red}
            hint="Named by the side arguing for the company. A concession here is the strongest thing in this panel."
            C={C}
          />
          <Bullets label="Survived the evidence" items={surviving} color={C.red} C={C} />
          <Bullets label="Made worse by the evidence" items={risk?.sharpened} color={C.red} C={C} />
          <Bullets
            label="Answered"
            items={defence?.answered}
            hint="Risks the collected evidence disposes of, each citing what does it."
            C={C}
          />
          {risk?.residual_severity != null && (
            <Text style={{ fontSize: 12, color: C.fgMuted, lineHeight: 17 }}>
              The risk analyst put the bear case at {risk.residual_severity}/100
              after the exchange
              {risk.residual_rationale ? ` — ${risk.residual_rationale}` : ''}
            </Text>
          )}
        </View>
      )}
    </View>
  )
}

/**
 * The advisory stance panel.
 *
 * The wording is load-bearing and matches the web copy exactly. These do not
 * size anything — sizing is arithmetic on a frozen equity basis, no part of the
 * trading guard chain reads them, and three unanimous WAITs still leave the
 * order the risk model computed.
 */
function Stances({ stances, C }: { stances?: ResearchStances | null; C: Palette }) {
  if (!stances) return null
  const rows: Array<[string, TradeStance | null | undefined]> = [
    ['Aggressive', stances.aggressive],
    ['Neutral', stances.neutral],
    ['Conservative', stances.conservative],
  ]
  if (!rows.some(([, stance]) => stance)) return null

  return (
    <View>
      <Text style={{ fontSize: 11, fontWeight: '600', letterSpacing: 0.5, color: C.fgMuted }}>
        HOW THREE READERS WOULD SIZE THIS
      </Text>
      <Text style={{ fontSize: 11, color: C.fgMuted, marginTop: 3, lineHeight: 15 }}>
        Advice, not sizing. The order quantity comes from the risk model and
        your account — nothing here changes it. These readers are also not shown
        how much of your account is already in this name.
      </Text>
      <View style={{ gap: 8, marginTop: 8 }}>
        {rows.map(([label, stance]) =>
          stance ? (
            <View key={label} style={{ gap: 2 }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                <Text style={{ fontSize: 12, fontWeight: '600', color: C.fg }}>{label}</Text>
                <Text
                  style={{
                    fontSize: 11, fontWeight: '600', paddingHorizontal: 6,
                    paddingVertical: 2, borderRadius: 4,
                    color: stanceColor(stance.stance, C),
                  }}
                >
                  {stanceLabel(stance.stance)}
                </Text>
              </View>
              {stance.rationale ? (
                <Text style={{ fontSize: 12.5, color: C.fg, lineHeight: 18 }}>
                  {stance.rationale}
                </Text>
              ) : (
                <Text style={{ fontSize: 11.5, color: C.fgMuted, fontStyle: 'italic', lineHeight: 16 }}>
                  Its reasoning cited no evidence and was removed.
                </Text>
              )}
            </View>
          ) : null,
        )}
      </View>
    </View>
  )
}

function stanceLabel(stance?: string | null): string {
  switch (stance) {
    case 'SIZE_UP': return 'lean in'
    case 'SIZE_DOWN': return 'take less'
    case 'HOLD_SIZE': return 'as sized'
    case 'WAIT': return 'wait'
    default: return 'no view'
  }
}

function stanceColor(stance: string | null | undefined, C: Palette): string {
  if (stance === 'SIZE_UP') return C.green
  if (stance === 'SIZE_DOWN' || stance === 'WAIT') return C.red
  return C.amber
}

/**
 * Whether the agents were given this desk's own track record.
 *
 * Zero is the honest answer for any name being read for the first time, and a
 * reader who assumes the agents know their history when they do not is drawing
 * a conclusion the panel never supported.
 */
function PriorRecordNote({
  coverage, C,
}: { coverage?: PriorRecordCoverage | null; C: Palette }) {
  if (!coverage) return null
  const { same_ticker: same, cross_ticker: cross } = coverage
  return (
    <Text style={{ fontSize: 11, color: C.fgMuted, lineHeight: 16 }}>
      {same === 0 && cross === 0
        ? 'The analysts had no settled record to work from on this name — every reading here comes from the current evidence alone.'
        : `The analysts were shown ${same} previous graded reading${same === 1 ? '' : 's'} of this name${
            cross > 0 ? ` and ${cross} from other names` : ''
          }, each with what the position went on to do. Those entries are cited like any other evidence, and they can lower conviction but never raise it past the arithmetic anchor.`}
    </Text>
  )
}

/**
 * How a past reading turned out. Judged on alpha, not raw return.
 */
function OutcomeNote({ outcome, C }: { outcome?: ResearchOutcome | null; C: Palette }) {
  if (!outcome || outcome.return == null) return null
  const correct = outcome.assessment_correct
  const tone = correct === true ? C.green : correct === false ? C.red : C.fgMuted

  return (
    <View>
      <Text style={{ fontSize: 11, fontWeight: '600', letterSpacing: 0.5, color: C.fgMuted }}>
        HOW THIS READING TURNED OUT
      </Text>
      <Text style={{ fontSize: 12.5, color: C.fg, lineHeight: 18, marginTop: 4 }}>
        Over the following {outcome.horizon_days} days the name returned{' '}
        {formatPct(outcome.return)}
        {outcome.alpha != null && outcome.benchmark_return != null
          ? `, against ${formatPct(outcome.benchmark_return)} for ${
              outcome.benchmark_ticker ?? 'the benchmark'
            } — ${formatPct(outcome.alpha)} of alpha`
          : ' (the benchmark could not be read for this window, so there is no alpha to judge it on)'}
        .{' '}
        <Text style={{ color: tone }}>
          {correct === true
            ? 'The call was right on alpha.'
            : correct === false
              ? 'The call was wrong on alpha.'
              : 'Not graded — the reading took no side, or the window could not be measured.'}
        </Text>
      </Text>
      {outcome.reflection?.lesson ? (
        <Text style={{ fontSize: 12.5, color: C.fg, lineHeight: 18, marginTop: 6 }}>
          <Text style={{ color: C.fgMuted }}>Lesson recorded: </Text>
          {outcome.reflection.lesson}
        </Text>
      ) : outcome.reflection?.uncited ? (
        <Text style={{ fontSize: 11, color: C.fgMuted, fontStyle: 'italic', marginTop: 6, lineHeight: 16 }}>
          A lesson was written but cited no evidence, so it was not kept. The
          figures above stand on their own.
        </Text>
      ) : null}
    </View>
  )
}

/** Which models wrote this reading — mirrors the web panel. */
function ModelsLine({ models, C }: { models?: ModelUsed[]; C: Palette }) {
  if (!models || models.length === 0) return null
  const text = models
    .map((m) => (m.agents.length ? `${m.model} (${m.agents.join(', ')})` : m.model))
    .join('; ')
  return (
    <Text style={{ fontSize: 11, color: C.fgMuted, lineHeight: 16 }}>
      Written by {text}.
    </Text>
  )
}

function formatPct(value: number): string {
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(1)}%`
}

function assessmentTone(assessment: string | null | undefined, C: Palette) {
  if (assessment === 'BULLISH') return { bg: C.tintBuy, fg: C.green }
  if (assessment === 'BEARISH') return { bg: C.tintSell, fg: C.red }
  return { bg: C.tintHold, fg: C.amber }
}

function barColor(value: number, C: Palette): string {
  if (value >= 60) return C.green
  if (value >= 40) return C.amber
  return C.red
}

function formatAge(dossier: ResearchDossier): string {
  const hours = dossier.age_hours
  if (hours == null) return 'undated'
  if (hours < 1) return 'just now'
  if (hours < 24) return `${Math.round(hours)}h ago`
  return `${Math.round(hours / 24)}d ago`
}
