import React, { useCallback, useEffect, useState } from 'react'
import {
  View, Text, Pressable, ScrollView, Linking, Share,
} from 'react-native'
import { useLocalSearchParams, router } from 'expo-router'
import {
  Activity, AlertCircle, Calendar, ChevronDown, ChevronUp,
  RefreshCw, Share2, Shield, Target, TrendingDown, TrendingUp, Users, Zap,
} from 'lucide-react-native'
import Svg, { Path } from 'react-native-svg'
import { analyzeApi, tradingApi } from '../../src/lib/api'
import type {
  AnalyzeResponse, AlternativeData, Quote, SignalInputs, TradeRecord,
} from '../../src/types'
import SignalBadge from '../../src/components/SignalBadge'
import ConvictionBadge from '../../src/components/ConvictionBadge'
import LoadingSpinner from '../../src/components/LoadingSpinner'
import Disclaimer from '../../src/components/Disclaimer'
import ResearchPanel from '../../src/components/ResearchPanel'
import OrderTicket from '../../src/components/OrderTicket'
import PriceChart from '../../src/components/PriceChart'
import { FactorBreakdown, RiskPanel } from '../../src/components/ScorePanels'
import ActivityList from '../../src/components/ActivityList'
import { useNow } from '../../src/lib/use-refresh'
import { usePalette, type Palette } from '../../src/lib/palette'
import { useAuth } from '../../src/lib/auth-context'
import { entitlementsOf } from '../../src/lib/entitlements'


const cardStyle = (C: Palette) => ({
  backgroundColor: C.surface, borderRadius: 12,
  borderWidth: 1, borderColor: C.border, padding: 16, marginBottom: 10,
})

// ── Score gauge ───────────────────────────────────────────────────────────────

function ScoreGauge({ score }: { score: number }) {
  const C = usePalette()
  const card = cardStyle(C)
  const pct = Math.round(score * 100)
  const color = pct >= 70 ? C.green : pct >= 40 ? C.amber : C.red
  const dashLen = (pct / 100) * 176

  return (
    <View style={{ alignItems: 'center', gap: 4 }}>
      <View style={{ width: 120, height: 60 }}>
        <Svg width={120} height={60} viewBox="0 0 128 64">
          <Path
            d="M 8 64 A 56 56 0 0 1 120 64"
            fill="none"
            stroke={C.border}
            strokeWidth="10"
            strokeLinecap="round"
          />
          <Path
            d="M 8 64 A 56 56 0 0 1 120 64"
            fill="none"
            stroke={color}
            strokeWidth="10"
            strokeLinecap="round"
            strokeDasharray={`${dashLen} 176`}
          />
        </Svg>
      </View>
      <Text style={{ fontSize: 28, fontWeight: '300', color: C.fg }}>{pct}</Text>
      <Text style={{ fontSize: 11, color: C.fgMuted }}>/ 100 score</Text>
    </View>
  )
}

// ── Stat cell ─────────────────────────────────────────────────────────────────

function StatCell({ label, value, icon: Icon, color }: {
  label: string; value: string
  icon?: React.FC<{ size: number; color: string }>; color?: string
}) {
  const C = usePalette()
  const card = cardStyle(C)
  return (
    <View style={{
      flex: 1, padding: 12, borderRadius: 10,
      backgroundColor: C.bg, borderWidth: 1, borderColor: C.border,
    }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4, marginBottom: 4 }}>
        {Icon && <Icon size={12} color={C.fgMuted} />}
        <Text style={{ fontSize: 10, color: C.fgMuted }}>{label}</Text>
      </View>
      <Text style={{ fontSize: 14, fontWeight: '700', color: color ?? C.fg }}>{value}</Text>
    </View>
  )
}

// ── Section block ─────────────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  const C = usePalette()
  const card = cardStyle(C)
  return (
    <View style={card}>
      <Text style={{ fontSize: 15, fontWeight: '500', color: C.fg, marginBottom: 10 }}>{title}</Text>
      {children}
    </View>
  )
}

// ── Bullet list ───────────────────────────────────────────────────────────────

function BulletList({ items, color }: { items: string[]; color?: string }) {
  const C = usePalette()
  const card = cardStyle(C)
  return (
    <View style={{ gap: 8 }}>
      {items.map((item, i) => (
        <View key={i} style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 8 }}>
          <View style={{
            width: 6, height: 6, borderRadius: 3,
            backgroundColor: color ?? C.brand, marginTop: 6, flexShrink: 0,
          }} />
          <Text style={{ fontSize: 13, color: C.fg, flex: 1, lineHeight: 19 }}>{item}</Text>
        </View>
      ))}
    </View>
  )
}

// ── Bull / bear case ──────────────────────────────────────────────────────────

/** At most this many bullets a side. Past three it stops being a glance. */
const MAX_CASE_POINTS = 3

/**
 * One side of the argument, bullets first — mirrors `CasePanel` on the web.
 *
 * `points` is written by the analyst, never derived here: splitting a paragraph
 * on its full stops is a guess at which clause carried the argument. An
 * analysis stored before the analyst was asked for bullets shows its paragraph
 * instead, folded behind the same control.
 */
function CaseBlock({
  label,
  color,
  Icon,
  points,
  prose,
  extraLabel,
  extra,
}: {
  label: string
  color: string
  Icon: typeof TrendingUp
  points: string[]
  prose?: string | null
  extraLabel: string
  extra: string[]
}) {
  const C = usePalette()
  const bullets = points.slice(0, MAX_CASE_POINTS)
  const hasMore = !!prose || extra.length > 0

  return (
    <View style={{ gap: 8 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
        <Icon size={14} color={color} />
        <Text style={{
          fontSize: 10, fontWeight: '700', color, letterSpacing: 0.6,
          textTransform: 'uppercase',
        }}>
          {label}
        </Text>
      </View>

      {bullets.length > 0 ? (
        <BulletList items={bullets} color={color} />
      ) : prose ? (
        <Text
          numberOfLines={3}
          style={{ fontSize: 13, color: C.fg, lineHeight: 19 }}
        >
          {prose}
        </Text>
      ) : (
        <Text style={{ fontSize: 12, color: C.fgMuted }}>Not recorded for this analysis.</Text>
      )}

      {hasMore && (
        <Collapsible title="Full case" defaultOpen={false}>
          <View style={{ gap: 12 }}>
            {prose && bullets.length > 0 && (
              <Text style={{ fontSize: 13, color: C.fgMuted, lineHeight: 19 }}>{prose}</Text>
            )}
            {extra.length > 0 && (
              <View style={{ gap: 8 }}>
                <Text style={{
                  fontSize: 10, fontWeight: '700', color: C.fgMuted,
                  letterSpacing: 0.6, textTransform: 'uppercase',
                }}>
                  {extraLabel}
                </Text>
                <BulletList items={extra} color={color} />
              </View>
            )}
          </View>
        </Collapsible>
      )}
    </View>
  )
}

// ── Collapsible ───────────────────────────────────────────────────────────────

function Collapsible({
  title,
  defaultOpen = true,
  children,
}: {
  title: string
  defaultOpen?: boolean
  children: React.ReactNode
}) {
  const C = usePalette()
  const card = cardStyle(C)
  const [open, setOpen] = useState(defaultOpen)
  return (
    <View>
      <Pressable
        onPress={() => setOpen((v) => !v)}
        style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 4 }}
      >
        <Text style={{ fontSize: 13, fontWeight: '500', color: C.fgMuted }}>{title}</Text>
        {open ? <ChevronUp size={15} color={C.fgMuted} /> : <ChevronDown size={15} color={C.fgMuted} />}
      </Pressable>
      {open && <View style={{ marginTop: 10 }}>{children}</View>}
    </View>
  )
}

// ── Sentiment pill ────────────────────────────────────────────────────────────

function SentimentPill({ label, value }: { label: string; value: string | null | undefined }) {
  const C = usePalette()
  const card = cardStyle(C)
  if (!value) return null
  const bullish = ['BULLISH', 'MILDLY_BULLISH', 'LOW'].includes(value)
  const bearish = ['BEARISH', 'MILDLY_BEARISH', 'HIGH'].includes(value)
  return (
    <View style={{
      paddingHorizontal: 7, paddingVertical: 2, borderRadius: 20,
      backgroundColor: bullish ? `${C.green}1a` : bearish ? `${C.red}1a` : `${C.border}80`,
    }}>
      <Text style={{
        fontSize: 10, fontWeight: '600',
        color: bullish ? C.green : bearish ? C.red : C.fgMuted,
      }}>
        {label}: {value.replace('_', ' ')}
      </Text>
    </View>
  )
}

// ── Alt data row ──────────────────────────────────────────────────────────────

function AltDataRow({ label, value, sub }: { label: string; value: string; sub?: string }) {
  const C = usePalette()
  const card = cardStyle(C)
  return (
    <View style={{
      flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start',
      paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: C.border,
    }}>
      <Text style={{ fontSize: 11, color: C.fgMuted, flexShrink: 0 }}>{label}</Text>
      <View style={{ alignItems: 'flex-end' }}>
        <Text style={{ fontSize: 11, fontWeight: '600', color: C.fg }}>{value}</Text>
        {sub && <Text style={{ fontSize: 9, color: C.fgMuted, marginTop: 1 }}>{sub}</Text>}
      </View>
    </View>
  )
}

// ── Alternative data section ──────────────────────────────────────────────────

function AlternativeDataSection({ data }: { data: AlternativeData }) {
  const C = usePalette()
  const card = cardStyle(C)
  const si = data.short_interest
  const opt = data.options_flow
  const ins = data.insider_trades

  const hasAny =
    si?.short_percent_of_float != null ||
    opt?.put_call_ratio != null ||
    ins?.buy_count_90d != null ||
    ins?.sell_count_90d != null

  if (!hasAny) return null

  return (
    <Section title="Alternative Data">
      <View style={{ gap: 16 }}>
        {opt?.put_call_ratio != null && (
          <View>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 8 }}>
              <Activity size={12} color={C.fgMuted} />
              <Text style={{ fontSize: 9, fontWeight: '700', color: C.fgMuted, textTransform: 'uppercase', letterSpacing: 0.6 }}>
                Options Flow
              </Text>
              <SentimentPill label="signal" value={opt.sentiment} />
            </View>
            <AltDataRow
              label="Put/Call Ratio"
              value={opt.put_call_ratio.toFixed(2)}
              sub={`${(opt.put_volume ?? 0).toLocaleString()} puts / ${(opt.call_volume ?? 0).toLocaleString()} calls · exp ${opt.expiry ?? ''}`}
            />
            <Text style={{ fontSize: 9, color: C.fgMuted, marginTop: 4 }}>
              {'<0.7 = calls dominating (bullish) · >1.5 = puts dominating (bearish)'}
            </Text>
          </View>
        )}

        {si?.short_percent_of_float != null && (
          <View>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 8 }}>
              <TrendingDown size={12} color={C.fgMuted} />
              <Text style={{ fontSize: 9, fontWeight: '700', color: C.fgMuted, textTransform: 'uppercase', letterSpacing: 0.6 }}>
                Short Interest
              </Text>
              {si.squeeze_risk && <SentimentPill label="squeeze risk" value={si.squeeze_risk} />}
            </View>
            <AltDataRow
              label="% of Float Shorted"
              value={`${((si.short_percent_of_float ?? 0) * 100).toFixed(1)}%`}
            />
            {si.short_ratio != null && (
              <AltDataRow
                label="Days to Cover"
                value={`${si.short_ratio.toFixed(1)}d`}
                sub="avg days for shorts to buy back at current volume"
              />
            )}
          </View>
        )}

        {(ins?.buy_count_90d != null || ins?.sell_count_90d != null) && (
          <View>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 8 }}>
              <Users size={12} color={C.fgMuted} />
              <Text style={{ fontSize: 9, fontWeight: '700', color: C.fgMuted, textTransform: 'uppercase', letterSpacing: 0.6 }}>
                Insider Activity (90d)
              </Text>
              <SentimentPill label="signal" value={ins?.net_sentiment} />
            </View>
            <AltDataRow
              label="Transactions"
              value={`${ins?.buy_count_90d ?? 0} buys / ${ins?.sell_count_90d ?? 0} sells`}
            />
            {ins?.recent && ins.recent.length > 0 && (
              <View style={{ marginTop: 6, gap: 4 }}>
                {ins.recent.slice(0, 3).map((t, i) => (
                  <View key={i} style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
                    <Text style={{ fontSize: 10, color: C.fgMuted, flex: 1 }} numberOfLines={1}>
                      {t.insider ?? 'Unknown'}
                    </Text>
                    <Text style={{ fontSize: 10, color: C.fgMuted }}>
                      {t.transaction ?? ''}{t.shares ? ` · ${t.shares.toLocaleString()} sh` : ''} · {t.date ?? ''}
                    </Text>
                  </View>
                ))}
              </View>
            )}
          </View>
        )}
      </View>
    </Section>
  )
}

// ── Analyst note bullet split ─────────────────────────────────────────────────

function AnalystNoteSummary({ note }: { note: string }) {
  const C = usePalette()
  const card = cardStyle(C)
  const sentences = note
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 20)
  return (
    <View style={{ gap: 8 }}>
      {sentences.map((s, i) => (
        <View key={i} style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 8 }}>
          <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: C.brand, marginTop: 6, flexShrink: 0 }} />
          <Text style={{ fontSize: 13, color: C.fgMuted, flex: 1, lineHeight: 19 }}>{s}</Text>
        </View>
      ))}
    </View>
  )
}

// ── Export helpers ────────────────────────────────────────────────────────────

function buildExportText(data: AnalyzeResponse): string {
  const lines: string[] = [
    `${data.ticker} — Analysis Report`,
    `Generated: ${new Date(data.generated_at).toLocaleString()}`,
    '',
    `Signal: ${data.signal}  |  Score: ${Math.round(data.score * 100)}/100  |  Confidence: ${Math.round(data.confidence * 100)}%`,
    data.conviction ? `Analyst conviction: ${data.conviction}` : '',
    data.price_target ? `Price Target: $${data.price_target.toFixed(2)}` : '',
    data.stop_loss ? `Stop Loss: $${data.stop_loss.toFixed(2)}` : '',
    data.time_horizon ? `Time Horizon: ${data.time_horizon}` : '',
    '',
  ]
  if (data.thesis) lines.push('INVESTMENT THESIS', data.thesis, '')
  if (data.analyst_note) lines.push('ANALYST NOTE', data.analyst_note, '')
  if (data.bull_case) lines.push('BULL CASE', data.bull_case, '')
  if (data.bear_case) lines.push('BEAR CASE', data.bear_case, '')
  if (data.entry_suggestion) lines.push('ENTRY', data.entry_suggestion, '')
  if (data.exit_suggestion) lines.push('EXIT', data.exit_suggestion, '')
  if (data.catalysts?.length) lines.push('CATALYSTS', ...data.catalysts.map((c) => `• ${c}`), '')
  if (data.key_risks?.length) lines.push('KEY RISKS', ...data.key_risks.map((r) => `• ${r}`), '')
  if (data.explanation) lines.push('EXPLANATION', data.explanation, '')
  lines.push('---', 'Disclaimer: This report is generated by SAMSTradingAgent for informational purposes only and does not constitute financial advice.')
  return lines.filter((l) => l !== undefined).join('\n')
}

// ── Ticker Screen ─────────────────────────────────────────────────────────────

/**
 * Source badge vocabulary, mirroring the web panel exactly.
 *
 * Every row used to be a literal, so this list claimed Finnhub and FRED were
 * "Live" on a server that might hold neither key. `dev` survives as its own
 * state and is never derived from health: it is a *licensing* statement about
 * yfinance, and a source can be working perfectly and still unlicensed for
 * production.
 */
type SourceBadge = 'live' | 'dev' | 'thin' | 'off' | 'planned'

function stateBadge(
  inputs: SignalInputs | null | undefined,
  key: string,
  whenMeasured: SourceBadge = 'live',
): SourceBadge {
  const factor = inputs?.factors?.find((f) => f.key === key)
  if (!factor) return whenMeasured
  if (factor.state === 'fallback') return 'off'
  if (factor.state === 'partial') return 'thin'
  return whenMeasured
}

/** The note a factor's own coverage earns, appended to the editorial prose. */
function stateNote(inputs: SignalInputs | null | undefined, key: string): string {
  const factor = inputs?.factors?.find((f) => f.key === key)
  if (!factor) return ''
  if (factor.state === 'fallback') {
    return '. Not available for this report — the factor sits at a neutral 0.50 and says nothing about this company'
  }
  if (factor.state === 'partial') {
    return `. Partial for this report (${Math.round(factor.coverage * 100)}% of its inputs); the rest is blended toward neutral`
  }
  return ''
}

/**
 * The price, and where it came from.
 *
 * Always the quote's, never the analysis's. `data.current_price` is whatever
 * the price was when the pipeline last ran, which on a stored read is by
 * definition not now — and the point of separating the two steps was that a
 * stale verdict should not drag a stale price along with it.
 *
 * A price that is not live says so. A stored figure shown unlabelled is the one
 * number on this screen someone would act on without checking.
 */
function LivePrice({ quote, fallback }: { quote: Quote | null; fallback?: AnalyzeResponse | null }) {
  const C = usePalette()
  const price = quote?.price ?? fallback?.current_price ?? null
  const chg = quote?.price != null ? quote.day_change_pct : fallback?.day_change_pct

  return (
    <View>
      <View style={{ flexDirection: 'row', alignItems: 'baseline', gap: 8 }}>
        <Text style={{ fontSize: 22, fontWeight: '700', color: C.fg }}>
          {price != null ? `$${price.toFixed(2)}` : '—'}
        </Text>
        {chg != null && (
          <Text style={{ fontSize: 13, fontWeight: '600', color: chg >= 0 ? C.green : C.red }}>
            {chg >= 0 ? '+' : ''}{chg.toFixed(2)}%
          </Text>
        )}
      </View>
      <Text style={{ fontSize: 10, color: C.fgMuted, marginTop: 2 }}>
        {quote?.source === 'live'
          ? 'Live'
          : quote?.source === 'stored'
            ? `Last recorded price — ${quote.note ?? 'no live quote'}`
            : quote?.source === 'unavailable'
              ? quote.note ?? 'No price available'
              : 'Fetching price…'}
      </Text>
    </View>
  )
}

/**
 * The only control on this client that starts a pipeline run.
 *
 * Reads the plan itself rather than being gated at each call site — there are
 * two of them, and a control this expensive should not depend on both
 * remembering. Renders a sentence rather than nothing: it sits beside a stored
 * reading the user can see in full, and a button that vanished next to visible
 * content reads as a bug rather than as a plan.
 */
function RunAnalysisButton({ analysing, hasData, onPress }: {
  analysing: boolean
  hasData: boolean
  onPress: () => void
}) {
  const C = usePalette()
  const { user } = useAuth()

  if (!entitlementsOf(user).may_spend_tokens) {
    return (
      <Text style={{ marginTop: 12, fontSize: 12, lineHeight: 18, color: C.fgMuted }}>
        Running a new analysis is part of the Pro plan. Adding this ticker to
        your watchlist puts it on the engine&rsquo;s five-minute cycle, which
        scores it without anyone asking.
      </Text>
    )
  }

  return (
    <Pressable
      onPress={onPress}
      disabled={analysing}
      accessibilityRole="button"
      style={({ pressed }) => ({
        flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6,
        marginTop: 12, paddingHorizontal: 14, paddingVertical: 11, borderRadius: 9,
        backgroundColor: C.brand, opacity: analysing ? 0.5 : pressed ? 0.8 : 1,
      })}
    >
      {analysing ? <LoadingSpinner size="sm" /> : <RefreshCw size={14} color="#fff" />}
      <Text style={{ fontSize: 13, fontWeight: '700', color: '#fff' }}>
        {analysing ? 'Analysing…' : hasData ? 'Run full analysis again' : 'Run full analysis'}
      </Text>
    </Pressable>
  )
}

/**
 * What has been traded on this name.
 *
 * The web client puts this in the side rail beside the analysis; a phone has no
 * rail, so it is a section. Same content either way: what was bought, sold,
 * proposed or refused on *this* ticker, which is the context that turns a
 * verdict into a decision.
 */
function TickerTransactions({ ticker, orders, onChanged }: {
  ticker: string
  orders: TradeRecord[]
  onChanged: () => void
}) {
  const C = usePalette()
  return (
    <View style={{ marginTop: 18, gap: 10 }}>
      <Text style={{
        fontSize: 11, fontWeight: '700', color: C.fgMuted,
        textTransform: 'uppercase', letterSpacing: 1,
      }}>
        {`Transactions — ${ticker}`}
      </Text>
      <ActivityList
        orders={orders}
        onProposalsChanged={onChanged}
        showTicker={false}
        emptyNote={`Nothing has been traded on ${ticker}.`}
      />
    </View>
  )
}

export default function TickerScreen() {
  const C = usePalette()
  const card = cardStyle(C)
  const { user } = useAuth()
  const ent = entitlementsOf(user)
  const { symbol } = useLocalSearchParams<{ symbol: string }>()
  const ticker = symbol?.toUpperCase() ?? ''
  const [data, setData] = useState<AnalyzeResponse | null>(null)
  const [quote, setQuote] = useState<Quote | null>(null)
  const [orders, setOrders] = useState<TradeRecord[]>([])
  const [isLoading, setIsLoading] = useState(true)
  // Separate from `isLoading` on purpose. Reading the stored analysis is a
  // Mongo lookup; running one is the whole pipeline plus an analyst call. Only
  // the second is something the user asked for.
  const [analysing, setAnalysing] = useState(false)
  // Nothing has ever been analysed for this ticker. Not an error — an empty
  // state with a button.
  const [neverAnalysed, setNeverAnalysed] = useState(false)

  // Ticks so the age below stays true while the screen sits in the background.
  // The threshold is the server's own `_CACHE_TTL_MINUTES`: past it `/analyze`
  // would rebuild rather than serve this, which makes it the point where what
  // is on screen stops being what the engine would say.
  const now = useNow()
  const [error, setError] = useState<string | null>(null)

  /**
   * Read what is stored. Never runs the pipeline.
   *
   * Opening a ticker used to call plain `/analyze`, which rebuilds anything
   * older than thirty minutes — yfinance, Finnhub, FRED, fundamentals and a
   * Claude call. On a phone, on mobile data, that is a blank screen for tens of
   * seconds of work nobody asked for.
   */
  const loadStored = useCallback(async () => {
    if (!ticker) return
    setIsLoading(true)
    setError(null)
    setNeverAnalysed(false)
    try {
      const res = await analyzeApi.get(ticker)
      setData(res.data)
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      setData(null)
      if (status === 404) setNeverAnalysed(true)
      else {
        const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        setError(msg ?? 'Failed to load the stored analysis.')
      }
    } finally {
      setIsLoading(false)
    }
  }, [ticker])

  /** The live price, independently of the analysis. Cheap, and always current. */
  const loadQuote = useCallback(async () => {
    if (!ticker) return
    try {
      setQuote((await analyzeApi.quote(ticker)).data)
    } catch {
      setQuote(null)
    }
  }, [ticker])

  /** This ticker's own audit trail, for the section under the analysis. */
  const loadOrders = useCallback(async () => {
    if (!ticker) return
    try {
      setOrders((await tradingApi.getOrders(ticker, 100)).data)
    } catch {
      setOrders([])
    }
  }, [ticker])

  /** The explicit run — the only path on this client that starts a pipeline. */
  const runAnalysis = useCallback(async () => {
    if (!ticker) return
    setAnalysing(true)
    setError(null)
    try {
      const res = await analyzeApi.run(ticker)
      setData(res.data)
      setNeverAnalysed(false)
      void loadQuote()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'The analysis could not be completed.')
    } finally {
      setAnalysing(false)
    }
  }, [ticker, loadQuote])

  // All three start together. None of them can run the pipeline.
  useEffect(() => {
    void loadStored()
    void loadQuote()
    void loadOrders()
  }, [loadStored, loadQuote, loadOrders])

  const handleShare = async () => {
    if (!data) return
    const text = buildExportText(data)
    try {
      await Share.share({ message: text, title: `${data.ticker} Analysis` })
    } catch { /* user cancelled */ }
  }

  if (isLoading) {
    return (
      <View style={{ flex: 1, backgroundColor: C.bg, alignItems: 'center', justifyContent: 'center' }}>
        <LoadingSpinner size="lg" />
      </View>
    )
  }

  if (error && !data) {
    return (
      <View style={{ flex: 1, backgroundColor: C.bg, alignItems: 'center', justifyContent: 'center', padding: 32, gap: 16 }}>
        <AlertCircle size={40} color={C.red} />
        <Text style={{ fontSize: 14, color: C.fgMuted, textAlign: 'center' }}>{error}</Text>
        <Pressable
          onPress={() => void loadStored()}
          style={{ paddingHorizontal: 20, paddingVertical: 10, borderRadius: 10, borderWidth: 1, borderColor: C.border }}
        >
          <Text style={{ fontSize: 14, fontWeight: '600', color: C.fg }}>Try again</Text>
        </Pressable>
      </View>
    )
  }

  /**
   * A name with no stored verdict is still a page worth painting.
   *
   * That is the whole of the two-step change: the price is live and the
   * transaction history is real, so the screen shows those and offers the
   * analysis as a button rather than starting one on arrival.
   */
  if (!data) {
    return (
      <ScrollView
        style={{ flex: 1, backgroundColor: C.bg }}
        contentContainerStyle={{ paddingHorizontal: 16, paddingTop: 12, paddingBottom: 100 }}
      >
        <View style={card}>
          <Text style={{ fontSize: 36, fontWeight: '300', color: C.fg, marginBottom: 4 }}>
            {ticker}
          </Text>
          <LivePrice quote={quote} />
          <Text style={{ fontSize: 12, color: C.fgMuted, marginTop: 12, lineHeight: 17 }}>
            {neverAnalysed
              ? `No in-depth analysis has been run for ${ticker}. Scoring the name means fetching prices, news, fundamentals and macro data and putting an analyst over the result — tens of seconds of work, so it happens when you ask for it.`
              : (error ?? 'The stored analysis could not be read.')}
          </Text>
          <RunAnalysisButton analysing={analysing} hasData={false} onPress={() => void runAnalysis()} />
        </View>

        <TickerTransactions
          ticker={ticker}
          orders={orders}
          onChanged={() => { void loadOrders() }}
        />
        <Disclaimer />
      </ScrollView>
    )
  }

  /** Mirrors `_CACHE_TTL_MINUTES` in backend/app/routes/analysis.py. */
  const generatedMs = Date.parse(data.generated_at)
  const stale = Number.isFinite(generatedMs) && now - generatedMs > 30 * 60 * 1000

  const scorePct = Math.round(data.score * 100)

  return (
    <View style={{ flex: 1, backgroundColor: C.bg }}>
      <ScrollView
        contentContainerStyle={{ paddingHorizontal: 16, paddingTop: 12, paddingBottom: 100 }}
        showsVerticalScrollIndicator={false}
      >
        {/* Header card */}
        <View style={card}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <View style={{ flex: 1 }}>
              <Text style={{ fontSize: 36, fontWeight: '300', color: C.fg, marginBottom: 4 }}>
                {data.ticker}
              </Text>
              <View style={{ marginBottom: 8 }}>
                <LivePrice quote={quote} fallback={data} />
              </View>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <SignalBadge signal={data.signal} size="lg" />
                {data.conviction && <ConvictionBadge conviction={data.conviction} size="lg" />}
              </View>
            </View>

            <ScoreGauge score={data.score} />
          </View>

          {/* Act on it. A verdict with no action was a dead end — you read BUY,
              then switched to the broker app. Removed rather than disabled for
              a plan without trading: there is no broker connection to make, so
              a dimmed ticket would be an upsell where a control should be. */}
          {ent.may_trade && (
            <View style={{ marginTop: 14, paddingTop: 12, borderTopWidth: 1, borderTopColor: C.border }}>
              <OrderTicket data={data} />
            </View>
          )}

          {/* Actions row */}
          <View style={{
            flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
            marginTop: 14, paddingTop: 12, borderTopWidth: 1, borderTopColor: C.border,
          }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, flexShrink: 1 }}>
              <Calendar size={12} color={C.fgMuted} />
              {/* Named and dated outright rather than left as a bare
                  timestamp. This is now the one line that says whether the
                  verdict above is from ten minutes ago or from Tuesday, because
                  nothing on this screen re-runs on its own any more. */}
              <Text style={{ fontSize: 10, color: C.fgMuted }}>
                Last in-depth analysis {new Date(data.generated_at).toLocaleString()}
              </Text>
              {/* Past the server's own cache window this analysis is older than
                  anything `/analyze` would still serve, so say so rather than
                  let a quiet timestamp pass for current. Matters more on a
                  phone than a browser: an app is resumed, not reloaded. */}
              {stale && (
                <View style={{
                  flexDirection: 'row', alignItems: 'center', gap: 3,
                  paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                  backgroundColor: `${C.amber}20`,
                }}>
                  <AlertCircle size={10} color={C.amber} />
                  <Text style={{ fontSize: 9, fontWeight: '700', color: C.amber }}>STALE</Text>
                </View>
              )}
            </View>
            <View style={{ flexDirection: 'row', gap: 8 }}>
              <Pressable
                onPress={handleShare}
                style={({ pressed }) => ({
                  flexDirection: 'row', alignItems: 'center', gap: 5,
                  paddingHorizontal: 10, paddingVertical: 7, borderRadius: 8,
                  backgroundColor: C.surface, borderWidth: 1, borderColor: C.border,
                  opacity: pressed ? 0.7 : 1,
                })}
              >
                <Share2 size={13} color={C.fgMuted} />
                <Text style={{ fontSize: 12, fontWeight: '600', color: C.fgMuted }}>Share</Text>
              </Pressable>
            </View>
          </View>

          <RunAnalysisButton analysing={analysing} hasData onPress={() => void runAnalysis()} />
          {error && (
            <Text style={{ fontSize: 11, color: C.red, marginTop: 8, lineHeight: 16 }}>{error}</Text>
          )}
        </View>

        {/* Stats grid */}
        <View style={{ flexDirection: 'row', gap: 8, marginBottom: 10 }}>
          {data.price_target && (
            <StatCell label="Price Target" value={`$${data.price_target.toFixed(2)}`} icon={Target} color={C.brand} />
          )}
          {data.stop_loss && (
            <StatCell label="Stop Loss" value={`$${data.stop_loss.toFixed(2)}`} icon={Shield} color={C.red} />
          )}
        </View>
        <View style={{ flexDirection: 'row', gap: 8, marginBottom: 10 }}>
          {data.time_horizon && (
            <StatCell label="Time Horizon" value={data.time_horizon} icon={Calendar} />
          )}
          <StatCell
            label="Confidence" icon={Zap}
            value={`${Math.round(data.confidence * 100)}%`}
            color={data.confidence >= 0.7 ? C.green : data.confidence >= 0.4 ? C.amber : C.red}
          />
        </View>

        {/* The two cases first, as bullets. They used to sit below the chart,
            the factor breakdown and the risk panel; the argument for the name
            is what a reader opens the page for, and the numbers behind it are
            what they open when they want to disagree. Kept in step with the
            web ticker view deliberately. */}
        {(data.bull_case || data.bear_case
          || data.bull_points?.length || data.bear_points?.length
          || data.catalysts?.length || data.key_risks?.length) && (
          <Section title="Bull & Bear Case">
            <View style={{ gap: 18 }}>
              <CaseBlock
                label="Bull case"
                color={C.green}
                Icon={TrendingUp}
                points={data.bull_points ?? []}
                prose={data.bull_case}
                extraLabel="Catalysts"
                extra={data.catalysts ?? []}
              />
              <CaseBlock
                label="Bear case"
                color={C.red}
                Icon={TrendingDown}
                points={data.bear_points ?? []}
                prose={data.bear_case}
                extraLabel="Key risks"
                extra={data.key_risks ?? []}
              />
            </View>
          </Section>
        )}

        {/* The one detail left open: a chart is scanned, not read. */}
        <Section title="Price">
          <PriceChart ticker={data.ticker} />
        </Section>

        {/* Why this score, and why this verdict — the workings, folded. */}
        {data.breakdown && (
          <Section title="Score Breakdown">
            <Collapsible title="How the score was built" defaultOpen={false}>
              <FactorBreakdown breakdown={data.breakdown} inputs={data.inputs} />
            </Collapsible>
          </Section>
        )}
        {data.risk && (
          <Section title="Risk & Signal Gate">
            <Collapsible title="Risk and the buy gate" defaultOpen={false}>
              <RiskPanel
                risk={data.risk}
                gate={data.gate}
                signal={data.signal}
                score={data.score}
              />
            </Collapsible>
          </Section>
        )}

        {data.thesis && (
          <Section title="Investment Thesis">
            <Text style={{ fontSize: 13, color: C.fg, lineHeight: 20 }}>{data.thesis}</Text>
          </Section>
        )}

        {/* Analyst note */}
        {data.analyst_note && (
          <Section title="Analyst Note">
            <AnalystNoteSummary note={data.analyst_note} />
          </Section>
        )}

        {/* Entry & Exit */}
        {(data.entry_suggestion || data.exit_suggestion) && (
          <Section title="Entry & Exit">
            <View style={{ gap: 12 }}>
              {data.entry_suggestion && (
                <View>
                  <Text style={{ fontSize: 10, fontWeight: '700', color: C.green, letterSpacing: 0.6, textTransform: 'uppercase', marginBottom: 4 }}>
                    Entry
                  </Text>
                  <Text style={{ fontSize: 13, color: C.fg, lineHeight: 19 }}>{data.entry_suggestion}</Text>
                </View>
              )}
              {data.exit_suggestion && (
                <View>
                  <Text style={{ fontSize: 10, fontWeight: '700', color: C.red, letterSpacing: 0.6, textTransform: 'uppercase', marginBottom: 4 }}>
                    Exit
                  </Text>
                  <Text style={{ fontSize: 13, color: C.fg, lineHeight: 19 }}>{data.exit_suggestion}</Text>
                </View>
              )}
            </View>
          </Section>
        )}

        {/* Alternative data */}
        {data.alternative_data && <AlternativeDataSection data={data.alternative_data} />}

        {/* Deep research — a slower, sourced second opinion. Everything in it
            cites a dated fact; anything that did not was deleted server-side
            before storage. */}
        <Section title="Deep Research">
          <ResearchPanel ticker={data.ticker} />
        </Section>

        {/* Explanation */}
        {data.explanation && (
          <Section title="Explanation">
            <Text style={{ fontSize: 13, color: C.fgMuted, lineHeight: 20 }}>{data.explanation}</Text>
          </Section>
        )}

        {/* Analysis sources */}
        <View style={card}>
          <Text style={{ fontSize: 15, fontWeight: '500', color: C.fg, marginBottom: 12 }}>
            Analysis Sources
          </Text>
          <View style={{ gap: 10 }}>
            {([
              {
                label: 'Price & Market Data',
                value: (data.data_sources?.price === 'polygon'
                  ? 'Polygon (via Massive)'
                  : 'Yahoo Finance')
                  + ' — 90 days OHLCV, current price, day change. The one input that can stop a cycle',
                status: data.data_sources?.price === 'polygon' ? 'live' : 'dev',
              },
              { label: 'Financial Statements', value: 'Massive (Polygon.io) — up to 12 annual and 12 quarterly filings, accumulated so margin trends and CAGRs are computable' + stateNote(data.inputs, 'fundamental'), status: stateBadge(data.inputs, 'fundamental') },
              { label: 'Company Profile & Ratios', value: 'Alpha Vantage OVERVIEW — business description, forward P/E, EV/EBITDA, margins, ROE/ROA, beta, analyst consensus', status: stateBadge(data.inputs, 'fundamental') },
              { label: 'Earnings Record', value: 'Alpha Vantage EARNINGS — reported vs estimated EPS, surprise history, next report date', status: stateBadge(data.inputs, 'catalyst') },
              { label: 'News & Sentiment', value: 'Finnhub API — last 7 days of headlines with publisher, date and link, scored with VADER. Headline text only' + stateNote(data.inputs, 'sentiment'), status: stateBadge(data.inputs, 'sentiment') },
              { label: 'Macro Environment', value: 'FRED — Fed funds rate, Treasuries, CPI, unemployment, VIX' + stateNote(data.inputs, 'macro'), status: stateBadge(data.inputs, 'macro') },
              { label: 'Options Flow', value: 'Yahoo Finance — nearest-expiry put/call volume ratio only' + stateNote(data.inputs, 'alternative_data'), status: stateBadge(data.inputs, 'alternative_data', 'dev') },
              { label: 'Short Interest', value: 'Yahoo Finance — % of float shorted. Usually unavailable from this host', status: 'dev' },
              { label: 'Insider Activity', value: 'Yahoo Finance (Form 4) — counts over the most recent filed transactions, not a date-bounded window', status: stateBadge(data.inputs, 'alternative_data', 'dev') },
              // Model name comes from the response, not a literal — the old
              // hardcoded string had drifted from what the server calls.
              data.analyst_model
                ? {
                    label: 'AI Analyst',
                    value: `${data.analyst_model} — synthesises all above into signal and thesis`,
                    status: data.analyst_used ? 'live' : 'planned',
                  }
                : {
                    label: 'AI Analyst',
                    value: 'Disabled on this server — signals come from the rule-based path',
                    status: 'planned',
                  },
              { label: 'Deep Research Agents', value: 'Four scoped analysts over one sourced evidence ledger, merged by a fifth. Uncited claims are deleted before storage', status: 'live' },
              { label: 'Institutional Ownership', value: '13F holdings — not carried by any configured provider', status: 'planned' },
              { label: 'Earnings Transcripts', value: 'Guidance and call commentary — no provider supplies these, so earnings analysis stops at estimates vs actuals', status: 'planned' },
              { label: 'SEC Filings', value: 'EDGAR — 10-K/10-Q risk factors, and document-level citations', status: 'planned' },
              { label: 'Peer Screening', value: 'A real comparable universe. Research peers come from your watchlist plus a small static map', status: 'planned' },
              { label: 'ML Scoring Model', value: 'XGBoost — trained on signal history', status: 'planned' },
            ] as { label: string; value: string; status: SourceBadge }[]).map(({ label, value, status }) => {
              const badge = {
                live: { bg: `${C.green}1f`, fg: C.green, text: 'Live' },
                dev: { bg: `${C.amber}1f`, fg: C.amber, text: 'Dev data' },
                // Answered with less than it should. Warning-toned: it is a
                // real fact about the score above it.
                thin: { bg: `${C.amber}1f`, fg: C.amber, text: 'Thin' },
                // Not configured. Deliberately not the sell tone — an absent
                // key is a choice, not a fault.
                off: { bg: `${C.border}80`, fg: C.fgMuted, text: 'Off' },
                planned: { bg: `${C.border}80`, fg: C.fgMuted, text: 'Soon' },
              }[status]
              return (
                <View key={label} style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 10 }}>
                  <View style={{
                    paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4, marginTop: 1,
                    backgroundColor: badge.bg,
                  }}>
                    <Text style={{ fontSize: 8, fontWeight: '700', color: badge.fg }}>
                      {badge.text}
                    </Text>
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={{ fontSize: 12, fontWeight: '600', color: C.fg }}>{label}</Text>
                    <Text style={{ fontSize: 11, color: C.fgMuted, marginTop: 1 }}>{value}</Text>
                  </View>
                </View>
              )
            })}
          </View>
          <Text style={{
            fontSize: 10, color: C.fgMuted, marginTop: 12, paddingTop: 10,
            borderTopWidth: 1, borderTopColor: C.border, lineHeight: 14,
          }}>
            Scoring is a weighted composite of technical, fundamental, sentiment, macro, volatility, and alternative data. See docs/09-analysis-sources.md for full methodology.
          </Text>
          <Text style={{ fontSize: 10, color: C.amber, marginTop: 6, lineHeight: 14 }}>
            Evaluation data. Rows marked Dev data come from yfinance, licensed for personal
            and development use only. Production requires a commercial data provider.
          </Text>
        </View>

        <TickerTransactions
          ticker={ticker}
          orders={orders}
          onChanged={() => { void loadOrders() }}
        />

        <Disclaimer />
      </ScrollView>
    </View>
  )
}
