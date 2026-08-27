import React, { useCallback, useEffect, useState } from 'react'
import { ActivityIndicator, Linking, Pressable, Text, View } from 'react-native'
import { AlertCircle, ExternalLink, RefreshCw } from 'lucide-react-native'

import { researchApi } from '../lib/api'
import { usePalette, type Palette } from '../lib/palette'
import type { DimensionScore, EvidenceItem, ResearchDossier } from '../types'

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
      {dossier.conviction != null && (
        <Text style={{ fontSize: 13, fontWeight: '500', color: C.fg }}>
          Conviction {Math.round(dossier.conviction)}/100
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
    </>
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
        </>
      )}

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

function Callout({
  C, tone, children,
}: { C: Palette; tone: string; children: React.ReactNode }) {
  return (
    <View style={{
      flexDirection: 'row', gap: 8, alignItems: 'flex-start',
      backgroundColor: C.tintHold, borderRadius: 6, padding: 10,
    }}>
      <AlertCircle size={13} color={tone} style={{ marginTop: 2 }} />
      <Text style={{ fontSize: 12, color: tone, flex: 1, lineHeight: 17 }}>{children}</Text>
    </View>
  )
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
