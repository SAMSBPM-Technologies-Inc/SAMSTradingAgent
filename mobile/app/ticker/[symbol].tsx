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
import { analyzeApi } from '../../src/lib/api'
import type { AnalyzeResponse, AlternativeData } from '../../src/types'
import SignalBadge from '../../src/components/SignalBadge'
import ConvictionBadge from '../../src/components/ConvictionBadge'
import LoadingSpinner from '../../src/components/LoadingSpinner'
import Disclaimer from '../../src/components/Disclaimer'
import OrderTicket from '../../src/components/OrderTicket'

const C = {
  bg: '#f5f2ed', surface: '#ffffff', fg: '#14110c',
  fgMuted: '#83786a', border: '#e7e2d8', brand: '#f2600c',
}

const card = {
  backgroundColor: C.surface, borderRadius: 12,
  borderWidth: 1, borderColor: C.border, padding: 16, marginBottom: 10,
}

// ── Score gauge ───────────────────────────────────────────────────────────────

function ScoreGauge({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  const color = pct >= 70 ? '#22c55e' : pct >= 40 ? '#f97316' : '#ef4444'
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
  return (
    <View style={card}>
      <Text style={{ fontSize: 15, fontWeight: '500', color: C.fg, marginBottom: 10 }}>{title}</Text>
      {children}
    </View>
  )
}

// ── Bullet list ───────────────────────────────────────────────────────────────

function BulletList({ items, color }: { items: string[]; color?: string }) {
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

// ── Collapsible ───────────────────────────────────────────────────────────────

function Collapsible({ title, children }: { title: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(true)
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
  if (!value) return null
  const bullish = ['BULLISH', 'MILDLY_BULLISH', 'LOW'].includes(value)
  const bearish = ['BEARISH', 'MILDLY_BEARISH', 'HIGH'].includes(value)
  return (
    <View style={{
      paddingHorizontal: 7, paddingVertical: 2, borderRadius: 20,
      backgroundColor: bullish ? 'rgba(34,197,94,0.1)' : bearish ? 'rgba(239,68,68,0.1)' : `${C.border}80`,
    }}>
      <Text style={{
        fontSize: 10, fontWeight: '600',
        color: bullish ? '#16a34a' : bearish ? '#dc2626' : C.fgMuted,
      }}>
        {label}: {value.replace('_', ' ')}
      </Text>
    </View>
  )
}

// ── Alt data row ──────────────────────────────────────────────────────────────

function AltDataRow({ label, value, sub }: { label: string; value: string; sub?: string }) {
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
    data.conviction ? `Conviction: ${data.conviction}` : '',
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

export default function TickerScreen() {
  const { symbol } = useLocalSearchParams<{ symbol: string }>()
  const [data, setData] = useState<AnalyzeResponse | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async (force = false) => {
    if (!symbol) return
    if (force) setIsRefreshing(true)
    else setIsLoading(true)
    setError(null)
    try {
      const res = await analyzeApi.get(symbol.toUpperCase(), force)
      setData(res.data)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Failed to load analysis.')
    } finally {
      setIsLoading(false)
      setIsRefreshing(false)
    }
  }, [symbol])

  useEffect(() => { fetchData(false) }, [fetchData])

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

  if (error) {
    return (
      <View style={{ flex: 1, backgroundColor: C.bg, alignItems: 'center', justifyContent: 'center', padding: 32, gap: 16 }}>
        <AlertCircle size={40} color="#ef4444" />
        <Text style={{ fontSize: 14, color: C.fgMuted, textAlign: 'center' }}>{error}</Text>
        <Pressable
          onPress={() => fetchData(false)}
          style={{ paddingHorizontal: 20, paddingVertical: 10, borderRadius: 10, borderWidth: 1, borderColor: C.border }}
        >
          <Text style={{ fontSize: 14, fontWeight: '600', color: C.fg }}>Try again</Text>
        </Pressable>
      </View>
    )
  }

  if (!data) return null

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
              {data.current_price != null && (
                <View style={{ flexDirection: 'row', alignItems: 'baseline', gap: 8, marginBottom: 8 }}>
                  <Text style={{ fontSize: 22, fontWeight: '700', color: C.fg }}>
                    ${data.current_price.toFixed(2)}
                  </Text>
                  {data.day_change_pct != null && (
                    <Text style={{
                      fontSize: 13, fontWeight: '600',
                      color: data.day_change_pct >= 0 ? '#22c55e' : '#ef4444',
                    }}>
                      {data.day_change_pct >= 0 ? '+' : ''}{data.day_change_pct.toFixed(2)}%
                    </Text>
                  )}
                </View>
              )}
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <SignalBadge signal={data.signal} size="lg" />
                {data.conviction && <ConvictionBadge conviction={data.conviction} size="lg" />}
              </View>
            </View>

            <ScoreGauge score={data.score} />
          </View>

          {/* Act on it. A verdict with no action was a dead end — you read BUY,
              then switched to the broker app. */}
          <View style={{ marginTop: 14, paddingTop: 12, borderTopWidth: 1, borderTopColor: C.border }}>
            <OrderTicket data={data} />
          </View>

          {/* Actions row */}
          <View style={{
            flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
            marginTop: 14, paddingTop: 12, borderTopWidth: 1, borderTopColor: C.border,
          }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
              <Calendar size={12} color={C.fgMuted} />
              <Text style={{ fontSize: 10, color: C.fgMuted }}>
                {new Date(data.generated_at).toLocaleString()}
              </Text>
            </View>
            <View style={{ flexDirection: 'row', gap: 8 }}>
              <Pressable
                onPress={() => fetchData(true)}
                disabled={isRefreshing}
                style={({ pressed }) => ({
                  flexDirection: 'row', alignItems: 'center', gap: 5,
                  paddingHorizontal: 10, paddingVertical: 7, borderRadius: 8,
                  backgroundColor: C.surface, borderWidth: 1, borderColor: C.border,
                  opacity: pressed ? 0.7 : 1,
                })}
              >
                {isRefreshing ? <LoadingSpinner size="sm" /> : <RefreshCw size={13} color={C.fgMuted} />}
                <Text style={{ fontSize: 12, fontWeight: '600', color: C.fgMuted }}>
                  {isRefreshing ? 'Refreshing…' : 'Refresh'}
                </Text>
              </Pressable>
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
        </View>

        {/* Stats grid */}
        <View style={{ flexDirection: 'row', gap: 8, marginBottom: 10 }}>
          {data.price_target && (
            <StatCell label="Price Target" value={`$${data.price_target.toFixed(2)}`} icon={Target} color={C.brand} />
          )}
          {data.stop_loss && (
            <StatCell label="Stop Loss" value={`$${data.stop_loss.toFixed(2)}`} icon={Shield} color="#ef4444" />
          )}
        </View>
        <View style={{ flexDirection: 'row', gap: 8, marginBottom: 10 }}>
          {data.time_horizon && (
            <StatCell label="Time Horizon" value={data.time_horizon} icon={Calendar} />
          )}
          <StatCell
            label="Confidence" icon={Zap}
            value={`${Math.round(data.confidence * 100)}%`}
            color={data.confidence >= 0.7 ? '#22c55e' : data.confidence >= 0.4 ? '#eab308' : '#ef4444'}
          />
        </View>

        {/* Thesis */}
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

        {/* Bull & Bear */}
        {(data.bull_case || data.bear_case) && (
          <Section title="Bull & Bear Case">
            <View style={{ gap: 16 }}>
              {data.bull_case && (
                <Collapsible title="Bull Case">
                  <View style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 8 }}>
                    <TrendingUp size={14} color="#22c55e" style={{ marginTop: 2 }} />
                    <Text style={{ fontSize: 13, color: C.fg, flex: 1, lineHeight: 19 }}>{data.bull_case}</Text>
                  </View>
                </Collapsible>
              )}
              {data.bear_case && (
                <Collapsible title="Bear Case">
                  <View style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 8 }}>
                    <TrendingDown size={14} color="#ef4444" style={{ marginTop: 2 }} />
                    <Text style={{ fontSize: 13, color: C.fg, flex: 1, lineHeight: 19 }}>{data.bear_case}</Text>
                  </View>
                </Collapsible>
              )}
            </View>
          </Section>
        )}

        {/* Entry & Exit */}
        {(data.entry_suggestion || data.exit_suggestion) && (
          <Section title="Entry & Exit">
            <View style={{ gap: 12 }}>
              {data.entry_suggestion && (
                <View>
                  <Text style={{ fontSize: 10, fontWeight: '700', color: '#16a34a', letterSpacing: 0.6, textTransform: 'uppercase', marginBottom: 4 }}>
                    Entry
                  </Text>
                  <Text style={{ fontSize: 13, color: C.fg, lineHeight: 19 }}>{data.entry_suggestion}</Text>
                </View>
              )}
              {data.exit_suggestion && (
                <View>
                  <Text style={{ fontSize: 10, fontWeight: '700', color: '#dc2626', letterSpacing: 0.6, textTransform: 'uppercase', marginBottom: 4 }}>
                    Exit
                  </Text>
                  <Text style={{ fontSize: 13, color: C.fg, lineHeight: 19 }}>{data.exit_suggestion}</Text>
                </View>
              )}
            </View>
          </Section>
        )}

        {/* Catalysts */}
        {data.catalysts && data.catalysts.length > 0 && (
          <Section title="Catalysts">
            <BulletList items={data.catalysts} color="#22c55e" />
          </Section>
        )}

        {/* Key risks */}
        {data.key_risks && data.key_risks.length > 0 && (
          <Section title="Key Risks">
            <BulletList items={data.key_risks} color="#ef4444" />
          </Section>
        )}

        {/* Alternative data */}
        {data.alternative_data && <AlternativeDataSection data={data.alternative_data} />}

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
              { label: 'Price & Market Data', value: 'Yahoo Finance — 90 days OHLCV, current price, day change', status: 'dev' },
              { label: 'News & Sentiment', value: 'Finnhub API — last 7 days of headlines, VADER NLP', status: 'live' },
              { label: 'Macro Environment', value: 'FRED — Fed funds rate, Treasuries, CPI, unemployment, VIX', status: 'live' },
              { label: 'Options Flow', value: 'Yahoo Finance — nearest-expiry put/call ratio', status: 'dev' },
              { label: 'Short Interest', value: 'Yahoo Finance — % of float shorted, days-to-cover', status: 'dev' },
              { label: 'Insider Activity', value: 'Yahoo Finance (Form 4) — buy/sell counts over 90 days', status: 'dev' },
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
              { label: 'SEC Filings', value: 'EDGAR — 10-K/10-Q filings', status: 'planned' },
              { label: 'ML Scoring Model', value: 'XGBoost — trained on signal history', status: 'planned' },
            ] as { label: string; value: string; status: 'live' | 'dev' | 'planned' }[]).map(({ label, value, status }) => {
              const badge = {
                live: { bg: 'rgba(34,197,94,0.12)', fg: '#16a34a', text: 'Live' },
                dev: { bg: 'rgba(245,158,11,0.12)', fg: '#d97706', text: 'Dev data' },
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
          <Text style={{ fontSize: 10, color: '#d97706', marginTop: 6, lineHeight: 14 }}>
            Evaluation data. Rows marked Dev data come from yfinance, licensed for personal
            and development use only. Production requires a commercial data provider.
          </Text>
        </View>
        <Disclaimer />
      </ScrollView>
    </View>
  )
}
