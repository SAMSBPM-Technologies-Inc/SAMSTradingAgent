import React, { useCallback, useEffect, useRef, useState } from 'react'
import {
  View,
  Text,
  TextInput,
  Pressable,
  FlatList,
  ScrollView,
  KeyboardAvoidingView,
  Platform,
  ActivityIndicator,
} from 'react-native'
import { router } from 'expo-router'
import {
  AlertTriangle, ArrowRight, CheckCircle2, ChevronDown, ChevronUp,
  Clock, Crosshair, Minus, Plus, RefreshCw, Trash2, TrendingDown, TrendingUp, X,
} from 'lucide-react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { analyzeApi, radarApi, watchlistApi } from '../../src/lib/api'
import type { DipBuyCandidate, DipBuyScanResponse } from '../../src/types'
import LoadingSpinner from '../../src/components/LoadingSpinner'

const C = {
  bg: '#f5f2ed', surface: '#ffffff', fg: '#14110c',
  fgMuted: '#83786a', border: '#e7e2d8', brand: '#f2600c',
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(n?: number, decimals = 1) {
  if (n == null) return '—'
  return n.toFixed(decimals)
}

function fmtPrice(n?: number) {
  if (n == null) return '—'
  return `$${n.toFixed(2)}`
}

function relativeTime(iso: string) {
  const diff = Date.now() - new Date(iso).getTime()
  const m = Math.floor(diff / 60000)
  if (m < 1) return 'just now'
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

// ── Indicator bar ─────────────────────────────────────────────────────────────

function IndicatorBar({
  label, value, min, max, danger, format,
}: {
  label: string; value?: number; min: number; max: number
  danger: 'low' | 'high'; format?: (v: number) => string
}) {
  if (value == null) return null
  const pct = Math.min(100, Math.max(0, ((value - min) / (max - min)) * 100))
  let barColor = '#22c55e'
  if (danger === 'high') {
    barColor = pct > 75 ? '#ef4444' : pct > 50 ? '#f59e0b' : '#22c55e'
  } else {
    barColor = pct < 25 ? C.brand : pct < 50 ? '#f59e0b' : '#22c55e'
  }

  return (
    <View style={{ gap: 3 }}>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
        <Text style={{ fontSize: 11, color: C.fgMuted }}>{label}</Text>
        <Text style={{ fontSize: 11, fontWeight: '600', color: C.fg }}>
          {format ? format(value) : fmt(value)}
        </Text>
      </View>
      <View style={{ height: 5, borderRadius: 3, backgroundColor: C.border, overflow: 'hidden' }}>
        <View style={{ height: '100%', width: `${pct}%`, backgroundColor: barColor, borderRadius: 3 }} />
      </View>
    </View>
  )
}

// ── Candidate card ────────────────────────────────────────────────────────────

function CandidateCard({
  c, borderColor, tag, tagBg, tagText, tagIcon: TagIcon, onNavigate, onRemove,
}: {
  c: DipBuyCandidate
  borderColor: string
  tag: string
  tagBg: string
  tagText: string
  tagIcon: React.FC<{ size: number; color: string }>
  onNavigate: (t: string) => void
  onRemove: (t: string) => void
}) {
  const [removing, setRemoving] = useState(false)
  const distLabel = c.pct_from_ma20 != null
    ? `${c.pct_from_ma20 > 0 ? '+' : ''}${c.pct_from_ma20.toFixed(1)}% from MA-20`
    : null

  const handleRemove = async () => {
    if (removing) return
    setRemoving(true)
    try {
      await watchlistApi.remove(c.ticker)
      onRemove(c.ticker)
    } catch {
      setRemoving(false)
    }
  }

  return (
    <Pressable
      onPress={() => onNavigate(c.ticker)}
      style={({ pressed }) => ({
        backgroundColor: pressed ? C.bg : C.surface,
        borderRadius: 12, borderWidth: 1, borderColor: C.border,
        borderLeftWidth: 4, borderLeftColor: borderColor,
        padding: 14, marginBottom: 10,
      })}
    >
      {/* Header */}
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginBottom: 12 }}>
        <View>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 2 }}>
            <Text style={{ fontSize: 17, fontWeight: '700', color: C.fg }}>{c.ticker}</Text>
            <View style={{
              flexDirection: 'row', alignItems: 'center', gap: 4,
              backgroundColor: tagBg, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 20,
            }}>
              <TagIcon size={10} color={tagText} />
              <Text style={{ fontSize: 9, fontWeight: '700', color: tagText }}>{tag}</Text>
            </View>
          </View>
          <Text style={{ fontSize: 13, color: C.fgMuted }}>{fmtPrice(c.current_price)}</Text>
        </View>
        <View style={{ alignItems: 'flex-end', gap: 2 }}>
          <Text style={{ fontSize: 10, color: C.fgMuted }}>{relativeTime(c.computed_at)}</Text>
          {distLabel && <Text style={{ fontSize: 10, color: C.fgMuted }}>{distLabel}</Text>}
          <Pressable onPress={handleRemove} disabled={removing} hitSlop={8}>
            {removing
              ? <ActivityIndicator size={14} color={C.fgMuted} />
              : <Trash2 size={14} color={C.fgMuted} />}
          </Pressable>
        </View>
      </View>

      {/* Indicators */}
      <View style={{ gap: 8, marginBottom: 10 }}>
        <IndicatorBar label="RSI-14" value={c.rsi_14} min={0} max={100} danger="high" />
        <IndicatorBar
          label="Stoch RSI" min={0} max={100} danger="high"
          value={c.stoch_rsi != null ? c.stoch_rsi * 100 : undefined}
          format={(v) => `${v.toFixed(0)}%`}
        />
        <IndicatorBar
          label="BB Position" min={0} max={100} danger="high"
          value={c.bb_pct != null ? c.bb_pct * 100 : undefined}
          format={(v) => `${v.toFixed(0)}%`}
        />
      </View>

      {/* Volume */}
      {c.volume_anomaly != null && (
        <View style={{
          flexDirection: 'row', justifyContent: 'space-between',
          borderTopWidth: 1, borderTopColor: C.border, paddingTop: 8, marginBottom: 6,
        }}>
          <Text style={{ fontSize: 11, color: C.fgMuted }}>Volume vs avg</Text>
          <Text style={{
            fontSize: 11, fontWeight: '600',
            color: c.volume_anomaly >= 1.2 ? '#22c55e' : C.fgMuted,
          }}>
            {c.volume_anomaly.toFixed(2)}x
          </Text>
        </View>
      )}

      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
        <Text style={{ fontSize: 11, fontWeight: '600', color: C.brand }}>View full analysis</Text>
        <ArrowRight size={11} color={C.brand} />
      </View>
    </Pressable>
  )
}

function PendingCard({
  ticker, onNavigate, onRemove,
}: { ticker: string; onNavigate: (t: string) => void; onRemove: (t: string) => void }) {
  const [removing, setRemoving] = useState(false)

  const handleRemove = async () => {
    if (removing) return
    setRemoving(true)
    try { await watchlistApi.remove(ticker); onRemove(ticker) }
    catch { setRemoving(false) }
  }

  return (
    <Pressable
      onPress={() => onNavigate(ticker)}
      style={({ pressed }) => ({
        backgroundColor: pressed ? C.bg : C.surface,
        borderRadius: 12, borderWidth: 1, borderColor: C.border,
        borderLeftWidth: 4, borderLeftColor: C.border,
        padding: 14, marginBottom: 10,
        flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
      })}
    >
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
        <View style={{
          width: 32, height: 32, borderRadius: 8, backgroundColor: `${C.border}80`,
          alignItems: 'center', justifyContent: 'center',
        }}>
          <Clock size={16} color={C.fgMuted} />
        </View>
        <View>
          <Text style={{ fontSize: 15, fontWeight: '700', color: C.fg }}>{ticker}</Text>
          <Text style={{ fontSize: 11, color: C.fgMuted }}>Awaiting data</Text>
        </View>
      </View>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
        <Pressable onPress={handleRemove} disabled={removing} hitSlop={8}>
          {removing ? <ActivityIndicator size={14} color={C.fgMuted} /> : <Trash2 size={14} color={C.fgMuted} />}
        </Pressable>
        <ArrowRight size={14} color={C.fgMuted} />
      </View>
    </Pressable>
  )
}

// ── Add ticker form ───────────────────────────────────────────────────────────

function AddTickerForm({ onAdded }: { onAdded: () => void }) {
  const [query, setQuery] = useState('')
  const [suggestions, setSuggestions] = useState<{ symbol: string; name: string }[]>([])
  const [status, setStatus] = useState<'idle' | 'adding' | 'done' | 'error'>('idle')
  const [errorMsg, setErrorMsg] = useState('')
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const search = useCallback(async (q: string) => {
    if (q.length < 1) { setSuggestions([]); return }
    try {
      const res = await analyzeApi.search(q)
      setSuggestions(res.data.slice(0, 6))
    } catch { setSuggestions([]) }
  }, [])

  const handleAdd = async () => {
    const ticker = query.trim().toUpperCase()
    if (!ticker) return
    setStatus('adding')
    setSuggestions([])
    try {
      await watchlistApi.add(ticker)
      setStatus('done')
      setQuery('')
      onAdded()
      setTimeout(() => setStatus('idle'), 2500)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to add ticker'
      setErrorMsg(msg)
      setStatus('error')
      setTimeout(() => setStatus('idle'), 3000)
    }
  }

  return (
    <View style={{
      backgroundColor: C.surface, borderRadius: 12,
      borderWidth: 1, borderColor: C.border, padding: 14, marginBottom: 16,
    }}>
      <Text style={{ fontSize: 13, fontWeight: '600', color: C.fg, marginBottom: 10 }}>
        Add ticker to radar
      </Text>
      <View style={{ flexDirection: 'row', gap: 8 }}>
        <View style={{ flex: 1 }}>
          <View style={{
            flexDirection: 'row', alignItems: 'center',
            borderWidth: 1, borderColor: C.border, borderRadius: 10,
            backgroundColor: C.surface, paddingHorizontal: 12, gap: 8,
          }}>
            <TextInput
              value={query}
              onChangeText={(val) => {
                const v = val.toUpperCase()
                setQuery(v)
                if (debounceRef.current) clearTimeout(debounceRef.current)
                debounceRef.current = setTimeout(() => search(v), 300)
              }}
              onBlur={() => setTimeout(() => setSuggestions([]), 200)}
              placeholder="e.g. NVDA"
              placeholderTextColor={C.fgMuted}
              autoCapitalize="characters"
              autoCorrect={false}
              editable={status !== 'adding'}
              style={{ flex: 1, paddingVertical: 11, fontSize: 14, color: C.fg }}
            />
            {query.length > 0 && (
              <Pressable onPress={() => { setQuery(''); setSuggestions([]) }} hitSlop={8}>
                <X size={13} color={C.fgMuted} />
              </Pressable>
            )}
          </View>

          {suggestions.length > 0 && (
            <View style={{
              position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 50,
              backgroundColor: C.surface, borderWidth: 1, borderColor: C.border,
              borderRadius: 10, marginTop: 4, overflow: 'hidden',
              shadowColor: '#000', shadowOffset: { width: 0, height: 2 },
              shadowOpacity: 0.08, shadowRadius: 6, elevation: 4,
            }}>
              {suggestions.map((s) => (
                <Pressable
                  key={s.symbol}
                  onPress={() => { setQuery(s.symbol); setSuggestions([]) }}
                  style={({ pressed }) => ({
                    flexDirection: 'row', alignItems: 'center', gap: 10,
                    paddingHorizontal: 14, paddingVertical: 10,
                    backgroundColor: pressed ? C.bg : C.surface,
                  })}
                >
                  <Text style={{ fontWeight: '700', fontSize: 12, color: C.brand, width: 48 }}>
                    {s.symbol}
                  </Text>
                  <Text style={{ fontSize: 12, color: C.fgMuted, flex: 1 }} numberOfLines={1}>
                    {s.name}
                  </Text>
                </Pressable>
              ))}
            </View>
          )}
        </View>

        <Pressable
          onPress={handleAdd}
          disabled={!query.trim() || status === 'adding' || status === 'done'}
          style={({ pressed }) => ({
            backgroundColor: pressed ? '#c24d08' : C.brand, borderRadius: 10,
            paddingHorizontal: 14, flexDirection: 'row', alignItems: 'center', gap: 6,
          })}
        >
          {status === 'adding'
            ? <LoadingSpinner size="sm" color="#fff" />
            : status === 'done'
              ? <CheckCircle2 size={16} color="#fff" />
              : <Plus size={16} color="#fff" />}
          <Text style={{ color: '#fff', fontWeight: '600', fontSize: 13 }}>
            {status === 'adding' ? 'Adding…' : status === 'done' ? 'Added!' : 'Add'}
          </Text>
        </Pressable>
      </View>

      {status === 'done' && (
        <Text style={{ fontSize: 11, color: '#16a34a', marginTop: 8 }}>
          Ticker added — scan again in ~30s.
        </Text>
      )}
      {status === 'error' && (
        <Text style={{ fontSize: 11, color: '#ef4444', marginTop: 8 }}>{errorMsg}</Text>
      )}
    </View>
  )
}

// ── Section header ────────────────────────────────────────────────────────────

function SectionHeader({ title, count, countBg, countText }: {
  title: string; count: number; countBg: string; countText: string
}) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 10 }}>
      <Text style={{ fontSize: 16, fontWeight: '600', color: C.fg }}>{title}</Text>
      <View style={{ backgroundColor: countBg, paddingHorizontal: 8, paddingVertical: 2, borderRadius: 20 }}>
        <Text style={{ fontSize: 11, fontWeight: '700', color: countText }}>{count}</Text>
      </View>
    </View>
  )
}

// ── Alpha Radar Screen ────────────────────────────────────────────────────────

export default function RadarScreen() {
  const [scan, setScan] = useState<DipBuyScanResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [lastScan, setLastScan] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showCriteria, setShowCriteria] = useState(false)

  const runScan = useCallback(async (showSpinner = false) => {
    if (showSpinner) setScanning(true)
    setError(null)
    try {
      const res = await radarApi.scan()
      setScan(res.data)
      setLastScan(new Date().toISOString())
    } catch {
      setError('Scan failed — check your connection.')
    } finally {
      setScanning(false)
      setLoading(false)
    }
  }, [])

  useEffect(() => { runScan() }, [runScan])

  const handleRemove = (ticker: string) => {
    if (!scan) return
    setScan({
      ...scan,
      entry_candidates: scan.entry_candidates.filter((c) => c.ticker !== ticker),
      exit_alerts: scan.exit_alerts.filter((c) => c.ticker !== ticker),
      neutral_tickers: scan.neutral_tickers.filter((c) => c.ticker !== ticker),
      unanalyzed_tickers: scan.unanalyzed_tickers.filter((t) => t !== ticker),
      scanned: scan.scanned - 1,
    })
  }

  const navigate = (t: string) => router.push(`/ticker/${t}`)

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.bg }} edges={['top']}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
        <ScrollView
          contentContainerStyle={{ paddingHorizontal: 16, paddingTop: 20, paddingBottom: 100 }}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          {/* Header */}
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
            <View>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 4 }}>
                <View style={{
                  width: 36, height: 36, borderRadius: 10,
                  backgroundColor: 'rgba(242,96,12,0.1)', alignItems: 'center', justifyContent: 'center',
                }}>
                  <Crosshair size={20} color={C.brand} />
                </View>
                <Text style={{ fontSize: 22, fontWeight: '700', color: C.fg }}>Alpha Radar</Text>
              </View>
              <Text style={{ fontSize: 13, color: C.fgMuted }}>
                Dip-buy entries and profit-taking alerts
              </Text>
            </View>
            <Pressable
              onPress={() => runScan(true)}
              disabled={scanning || loading}
              style={({ pressed }) => ({
                flexDirection: 'row', alignItems: 'center', gap: 6,
                paddingHorizontal: 12, paddingVertical: 8, borderRadius: 10,
                backgroundColor: C.surface, borderWidth: 1, borderColor: C.border,
                opacity: pressed ? 0.7 : 1,
              })}
            >
              {scanning ? <LoadingSpinner size="sm" /> : <RefreshCw size={14} color={C.fgMuted} />}
              <Text style={{ fontSize: 13, fontWeight: '600', color: C.fgMuted }}>
                {scanning ? 'Scanning…' : 'Scan'}
              </Text>
            </Pressable>
          </View>

          {lastScan && (
            <Text style={{ fontSize: 11, color: C.fgMuted, marginBottom: 16 }}>
              Last scan {relativeTime(lastScan)}
            </Text>
          )}

          {/* Stats strip */}
          {scan && (
            <View style={{ flexDirection: 'row', gap: 8, marginBottom: 16 }}>
              {[
                { value: scan.scanned + scan.unanalyzed_tickers.length, label: 'Watching', color: C.fg },
                { value: scan.entry_candidates.length, label: 'Entries', color: '#22c55e' },
                { value: scan.exit_alerts.length, label: 'Exits', color: '#f59e0b' },
                { value: scan.neutral_tickers.length, label: 'Neutral', color: C.fgMuted },
              ].map(({ value, label, color }) => (
                <View key={label} style={{
                  flex: 1, backgroundColor: C.surface, borderRadius: 10,
                  borderWidth: 1, borderColor: C.border, padding: 10, alignItems: 'center',
                }}>
                  <Text style={{ fontSize: 20, fontWeight: '700', color }}>{value}</Text>
                  <Text style={{ fontSize: 10, color: C.fgMuted, marginTop: 2 }}>{label}</Text>
                </View>
              ))}
            </View>
          )}

          {/* Criteria legend */}
          <Pressable
            onPress={() => setShowCriteria((v) => !v)}
            style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 8 }}
          >
            {showCriteria ? <ChevronUp size={13} color={C.fgMuted} /> : <ChevronDown size={13} color={C.fgMuted} />}
            <Text style={{ fontSize: 12, color: C.fgMuted }}>How signals are detected</Text>
          </Pressable>

          {showCriteria && (
            <View style={{
              backgroundColor: C.surface, borderRadius: 12,
              borderWidth: 1, borderColor: C.border, padding: 14, marginBottom: 16, gap: 12,
            }}>
              <View>
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                  <TrendingDown size={13} color="#16a34a" />
                  <Text style={{ fontSize: 11, fontWeight: '700', color: '#16a34a' }}>
                    Entry criteria (all must hold)
                  </Text>
                </View>
                {['RSI-14 ≤ 45', 'Stochastic RSI ≤ 20%', 'Bollinger Band position ≤ 35%'].map((t) => (
                  <Text key={t} style={{ fontSize: 11, color: C.fgMuted, marginBottom: 2 }}>• {t}</Text>
                ))}
              </View>
              <View>
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                  <TrendingUp size={13} color="#d97706" />
                  <Text style={{ fontSize: 11, fontWeight: '700', color: '#d97706' }}>
                    Exit alert criteria (either fires)
                  </Text>
                </View>
                {['RSI-14 ≥ 70', 'Bollinger Band position ≥ 90%'].map((t) => (
                  <Text key={t} style={{ fontSize: 11, color: C.fgMuted, marginBottom: 2 }}>• {t}</Text>
                ))}
              </View>
            </View>
          )}

          <AddTickerForm onAdded={() => {}} />

          {error && (
            <View style={{
              flexDirection: 'row', alignItems: 'center', gap: 8,
              padding: 12, borderRadius: 10, backgroundColor: 'rgba(239,68,68,0.08)', marginBottom: 16,
            }}>
              <AlertTriangle size={14} color="#ef4444" />
              <Text style={{ fontSize: 13, color: '#ef4444' }}>{error}</Text>
            </View>
          )}

          {loading && (
            <View style={{ alignItems: 'center', paddingVertical: 60 }}>
              <LoadingSpinner size="lg" />
            </View>
          )}

          {!loading && scan && (
            <>
              {/* Entry setups */}
              <SectionHeader
                title="Entry Setups" count={scan.entry_candidates.length}
                countBg="rgba(34,197,94,0.15)" countText="#16a34a"
              />
              {scan.entry_candidates.length === 0 ? (
                <View style={{
                  backgroundColor: C.surface, borderRadius: 12, borderWidth: 1, borderColor: C.border,
                  padding: 24, alignItems: 'center', marginBottom: 24,
                }}>
                  <Crosshair size={28} color={C.fgMuted} style={{ opacity: 0.4, marginBottom: 8 }} />
                  <Text style={{ fontSize: 13, color: C.fgMuted }}>No dip-buy setups right now.</Text>
                </View>
              ) : (
                <View style={{ marginBottom: 24 }}>
                  {scan.entry_candidates.map((c) => (
                    <CandidateCard
                      key={c.ticker} c={c}
                      borderColor="#22c55e" tag="DIP ENTRY"
                      tagBg="rgba(34,197,94,0.15)" tagText="#16a34a"
                      tagIcon={TrendingDown}
                      onNavigate={navigate} onRemove={handleRemove}
                    />
                  ))}
                </View>
              )}

              {/* Exit alerts */}
              <SectionHeader
                title="Exit Alerts" count={scan.exit_alerts.length}
                countBg="rgba(245,158,11,0.15)" countText="#d97706"
              />
              {scan.exit_alerts.length === 0 ? (
                <View style={{
                  backgroundColor: C.surface, borderRadius: 12, borderWidth: 1, borderColor: C.border,
                  padding: 24, alignItems: 'center', marginBottom: 24,
                }}>
                  <CheckCircle2 size={28} color={C.fgMuted} style={{ opacity: 0.4, marginBottom: 8 }} />
                  <Text style={{ fontSize: 13, color: C.fgMuted }}>No overbought signals.</Text>
                </View>
              ) : (
                <View style={{ marginBottom: 24 }}>
                  {scan.exit_alerts.map((c) => (
                    <CandidateCard
                      key={c.ticker} c={c}
                      borderColor="#f59e0b" tag="TAKE PROFIT"
                      tagBg="rgba(245,158,11,0.15)" tagText="#d97706"
                      tagIcon={TrendingUp}
                      onNavigate={navigate} onRemove={handleRemove}
                    />
                  ))}
                </View>
              )}

              {/* Neutral */}
              {scan.neutral_tickers.length > 0 && (
                <>
                  <SectionHeader
                    title="Watching" count={scan.neutral_tickers.length}
                    countBg={`${C.border}80`} countText={C.fgMuted}
                  />
                  <Text style={{ fontSize: 11, color: C.fgMuted, marginBottom: 10 }}>
                    No entry/exit threshold met.
                  </Text>
                  <View style={{ marginBottom: 24 }}>
                    {scan.neutral_tickers.map((c) => (
                      <CandidateCard
                        key={c.ticker} c={c}
                        borderColor={C.border} tag="WATCHING"
                        tagBg={`${C.border}80`} tagText={C.fgMuted}
                        tagIcon={Minus}
                        onNavigate={navigate} onRemove={handleRemove}
                      />
                    ))}
                  </View>
                </>
              )}

              {/* Pending */}
              {scan.unanalyzed_tickers.length > 0 && (
                <>
                  <SectionHeader
                    title="Pending Analysis" count={scan.unanalyzed_tickers.length}
                    countBg={`${C.border}80`} countText={C.fgMuted}
                  />
                  <View style={{ marginBottom: 24 }}>
                    {scan.unanalyzed_tickers.map((ticker) => (
                      <PendingCard
                        key={ticker} ticker={ticker}
                        onNavigate={navigate} onRemove={handleRemove}
                      />
                    ))}
                  </View>
                </>
              )}
            </>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  )
}
