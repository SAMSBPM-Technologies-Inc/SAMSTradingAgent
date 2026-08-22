import React, { useCallback, useEffect, useRef, useState } from 'react'
import {
  View,
  Text,
  TextInput,
  Pressable,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  ActivityIndicator,
} from 'react-native'
import { router } from 'expo-router'
import {
  AlertCircle,
  ChevronDown,
  ChevronUp,
  Clock,
  Plus,
  Search,
  Trash2,
  TrendingDown,
  TrendingUp,
} from 'lucide-react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { watchlistApi, analyzeApi } from '../../src/lib/api'
import type { Signal, Trigger, WatchlistItem, WatchlistSetupCounts } from '../../src/types'
import SignalBadge from '../../src/components/SignalBadge'
import LoadingSpinner from '../../src/components/LoadingSpinner'
import Disclaimer from '../../src/components/Disclaimer'

// One filter bar mixes two axes deliberately: the verdict (BUY/HOLD/SELL) and
// the timing setup (DIP/PROFIT). They were separate tabs answering the same
// question about the same tickers.
type Filter = 'ALL' | Signal | 'ENTRY' | 'EXIT_ALERT'
const FILTERS: Filter[] = ['ALL', 'ENTRY', 'EXIT_ALERT', 'BUY', 'HOLD', 'SELL']

const FILTER_LABEL: Record<Filter, string> = {
  ALL: 'All',
  ENTRY: 'Dip',
  EXIT_ALERT: 'Profit',
  BUY: 'Buy',
  HOLD: 'Hold',
  SELL: 'Sell',
}

const C = {
  bg: '#f5f2ed', surface: '#ffffff', fg: '#14110c',
  fgMuted: '#83786a', border: '#e7e2d8', brand: '#f2600c',
  green: '#16a34a', amber: '#d97706', red: '#ef4444',
}

function matchesFilter(item: WatchlistItem, f: Filter): boolean {
  if (f === 'ALL') return true
  if (f === 'ENTRY' || f === 'EXIT_ALERT') return item.trigger === f
  return item.signal === f
}

// ── Filter bar ────────────────────────────────────────────────────────────────

function FilterBar({
  active, onChange, counts,
}: {
  active: Filter; onChange: (f: Filter) => void; counts: Record<Filter, number>
}) {
  return (
    <View style={{ flexDirection: 'row', gap: 6, flexWrap: 'wrap' }}>
      {FILTERS.map((f) => {
        const isSetup = f === 'ENTRY' || f === 'EXIT_ALERT'
        const setupColor = f === 'ENTRY' ? C.green : C.amber
        const activeBg = isSetup ? setupColor : C.brand
        const idleBg = isSetup && counts[f] > 0
          ? f === 'ENTRY' ? 'rgba(22,163,74,0.12)' : 'rgba(217,119,6,0.12)'
          : `${C.border}80`
        const idleFg = isSetup && counts[f] > 0 ? setupColor : C.fgMuted

        return (
          <Pressable
            key={f}
            onPress={() => onChange(f)}
            style={{
              paddingHorizontal: 10, paddingVertical: 5, borderRadius: 8,
              backgroundColor: active === f ? activeBg : idleBg,
            }}
          >
            <Text style={{
              fontSize: 11, fontWeight: '600',
              color: active === f ? '#fff' : idleFg,
            }}>
              {FILTER_LABEL[f]} {counts[f]}
            </Text>
          </Pressable>
        )
      })}
    </View>
  )
}

// ── Setup badge ───────────────────────────────────────────────────────────────

function SetupBadge({ trigger }: { trigger: Trigger }) {
  if (trigger === 'NEUTRAL') {
    return <Text style={{ fontSize: 11, color: C.fgMuted }}>—</Text>
  }

  const cfg = trigger === 'ENTRY'
    ? { bg: 'rgba(22,163,74,0.14)', fg: C.green, label: 'DIP', Icon: TrendingDown }
    : trigger === 'EXIT_ALERT'
      ? { bg: 'rgba(217,119,6,0.14)', fg: C.amber, label: 'PROFIT', Icon: TrendingUp }
      : { bg: `${C.border}99`, fg: C.fgMuted, label: 'WAIT', Icon: Clock }

  const { bg, fg, label, Icon } = cfg
  return (
    <View style={{
      flexDirection: 'row', alignItems: 'center', gap: 3,
      backgroundColor: bg, paddingHorizontal: 6, paddingVertical: 2,
      borderRadius: 999, alignSelf: 'flex-start',
    }}>
      <Icon size={9} color={fg} />
      <Text style={{ fontSize: 9, fontWeight: '700', color: fg, letterSpacing: 0.3 }}>
        {label}
      </Text>
    </View>
  )
}

// ── Indicator bar (from the old radar cards) ─────────────────────────────────

function IndicatorBar({ label, value, format }: {
  label: string
  value?: number
  format?: (v: number) => string
}) {
  if (value == null) return null
  const pct = Math.min(100, Math.max(0, value))
  // High is the danger end for all three: overbought means the dip has passed.
  const color = pct > 75 ? C.red : pct > 50 ? '#f59e0b' : C.green

  return (
    <View style={{ gap: 3 }}>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
        <Text style={{ fontSize: 11, color: C.fgMuted }}>{label}</Text>
        <Text style={{ fontSize: 11, fontWeight: '600', color: C.fg }}>
          {format ? format(value) : value.toFixed(1)}
        </Text>
      </View>
      <View style={{ height: 4, borderRadius: 2, backgroundColor: C.border, overflow: 'hidden' }}>
        <View style={{ height: '100%', width: `${pct}%`, backgroundColor: color, borderRadius: 2 }} />
      </View>
    </View>
  )
}

// ── Expanded row detail ───────────────────────────────────────────────────────

function RowDetail({ item }: { item: WatchlistItem }) {
  const hasIndicators = item.rsi_14 != null || item.stoch_rsi != null || item.bb_pct != null

  return (
    <View style={{
      paddingHorizontal: 16, paddingVertical: 14, gap: 10,
      backgroundColor: C.bg,
      borderBottomWidth: 1, borderBottomColor: C.border,
    }}>
      {!hasIndicators ? (
        <Text style={{ fontSize: 12, color: C.fgMuted }}>
          No indicator data yet — analysis is still running in the background.
        </Text>
      ) : (
        <>
          <IndicatorBar label="RSI-14" value={item.rsi_14} />
          <IndicatorBar
            label="Stoch RSI"
            value={item.stoch_rsi != null ? item.stoch_rsi * 100 : undefined}
            format={(v) => `${v.toFixed(0)}%`}
          />
          <IndicatorBar
            label="BB Position"
            value={item.bb_pct != null ? item.bb_pct * 100 : undefined}
            format={(v) => `${v.toFixed(0)}%`}
          />

          {item.pct_from_ma20 != null && (
            <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
              <Text style={{ fontSize: 11, color: C.fgMuted }}>Distance from MA-20</Text>
              <Text style={{
                fontSize: 11, fontWeight: '600',
                color: item.pct_from_ma20 >= 0 ? C.amber : C.green,
              }}>
                {item.pct_from_ma20 > 0 ? '+' : ''}{item.pct_from_ma20.toFixed(1)}%
              </Text>
            </View>
          )}
          {item.volume_anomaly != null && (
            <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
              <Text style={{ fontSize: 11, color: C.fgMuted }}>Volume vs avg</Text>
              <Text style={{
                fontSize: 11, fontWeight: '600',
                color: item.volume_anomaly >= 1.2 ? C.green : C.fg,
              }}>
                {item.volume_anomaly.toFixed(2)}x
              </Text>
            </View>
          )}
          {item.conviction && (
            <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
              <Text style={{ fontSize: 11, color: C.fgMuted }}>Conviction</Text>
              <Text style={{ fontSize: 11, fontWeight: '600', color: C.fg }}>{item.conviction}</Text>
            </View>
          )}
          {item.thesis && (
            <Text style={{ fontSize: 12, color: C.fgMuted, lineHeight: 17 }}>{item.thesis}</Text>
          )}
        </>
      )}

      <Pressable
        onPress={() => router.push(`/ticker/${item.ticker}`)}
        style={{ paddingTop: 2 }}
      >
        <Text style={{ fontSize: 12, fontWeight: '600', color: C.brand }}>
          View full analysis →
        </Text>
      </Pressable>
    </View>
  )
}

// ── Skeleton row ──────────────────────────────────────────────────────────────

function SkeletonRow() {
  return (
    <View style={{
      flexDirection: 'row', alignItems: 'center', gap: 12,
      paddingHorizontal: 16, paddingVertical: 14,
      borderBottomWidth: 1, borderBottomColor: C.border,
    }}>
      <View style={{ width: 44, height: 14, borderRadius: 4, backgroundColor: C.border }} />
      <View style={{ width: 40, height: 20, borderRadius: 6, backgroundColor: C.border }} />
      <View style={{ flex: 1, height: 12, borderRadius: 4, backgroundColor: C.border }} />
      <View style={{ width: 52, height: 14, borderRadius: 4, backgroundColor: C.border }} />
    </View>
  )
}

// ── Watchlist row ─────────────────────────────────────────────────────────────

function WatchlistRow({ item, expanded, onToggle, onRemove }: {
  item: WatchlistItem
  expanded: boolean
  onToggle: () => void
  onRemove: (t: string) => void
}) {
  const [removing, setRemoving] = useState(false)
  const scorePct = Math.round(item.score * 100)

  const handleRemove = async () => {
    if (removing) return
    setRemoving(true)
    try {
      await watchlistApi.remove(item.ticker)
      onRemove(item.ticker)
    } catch {
      setRemoving(false)
    }
  }

  const accent =
    item.trigger === 'ENTRY' ? C.green
    : item.trigger === 'EXIT_ALERT' ? C.amber
    : 'transparent'

  return (
    <>
      <Pressable
        onPress={onToggle}
        style={({ pressed }) => ({
          flexDirection: 'row', alignItems: 'center', gap: 10,
          paddingLeft: 13, paddingRight: 16, paddingVertical: 13,
          borderBottomWidth: 1, borderBottomColor: C.border,
          borderLeftWidth: 3, borderLeftColor: accent,
          backgroundColor: pressed ? C.bg : C.surface,
        })}
      >
        {/* Ticker + setup */}
        <View style={{ width: 52, flexShrink: 0, gap: 3 }}>
          <Text style={{ fontSize: 13, fontWeight: '700', color: C.fg }}>
            {item.ticker}
          </Text>
          <SetupBadge trigger={item.trigger} />
        </View>

        {/* Signal */}
        <View style={{ width: 42, flexShrink: 0 }}>
          <SignalBadge signal={item.signal} />
        </View>

        {/* Score bar */}
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4, width: 64, flexShrink: 0 }}>
          <View style={{
            flex: 1, height: 4, borderRadius: 2, backgroundColor: C.border, overflow: 'hidden',
          }}>
            <View style={{ height: '100%', width: `${scorePct}%`, backgroundColor: C.brand, borderRadius: 2 }} />
          </View>
          <Text style={{ fontSize: 10, color: C.fgMuted, width: 20, textAlign: 'right' }}>{scorePct}</Text>
        </View>

        {/* Price */}
        <View style={{ flexDirection: 'row', alignItems: 'baseline', gap: 3, flex: 1 }}>
          {item.current_price != null ? (
            <>
              <Text style={{ fontSize: 13, fontWeight: '600', color: C.fg }}>
                ${item.current_price.toFixed(2)}
              </Text>
              {item.day_change_pct != null && (
                <Text style={{
                  fontSize: 10,
                  color: item.day_change_pct >= 0 ? '#22c55e' : C.red,
                }}>
                  {item.day_change_pct >= 0 ? '+' : ''}{item.day_change_pct.toFixed(2)}%
                </Text>
              )}
            </>
          ) : (
            <Text style={{ fontSize: 11, color: C.fgMuted }}>—</Text>
          )}
        </View>

        {/* Remove */}
        <Pressable onPress={handleRemove} disabled={removing} hitSlop={8}>
          {removing
            ? <ActivityIndicator size={14} color={C.fgMuted} />
            : <Trash2 size={14} color={C.fgMuted} />}
        </Pressable>

        {expanded
          ? <ChevronUp size={14} color={C.fgMuted} />
          : <ChevronDown size={14} color={C.fgMuted} />}
      </Pressable>

      {expanded && <RowDetail item={item} />}
    </>
  )
}

// ── Add ticker form ───────────────────────────────────────────────────────────

function AddTickerForm({ onAdded }: { onAdded: () => void }) {
  const [value, setValue] = useState('')
  const [suggestions, setSuggestions] = useState<{ symbol: string; name: string }[]>([])
  const [isSearching, setIsSearching] = useState(false)
  const [isAdding, setIsAdding] = useState(false)
  const [analyzingTicker, setAnalyzingTicker] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const search = useCallback((q: string) => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (!q) { setSuggestions([]); setOpen(false); return }
    debounceRef.current = setTimeout(async () => {
      setIsSearching(true)
      try {
        const res = await analyzeApi.search(q)
        setSuggestions(res.data)
        setOpen(res.data.length > 0)
      } catch {
        setSuggestions([]); setOpen(false)
      } finally {
        setIsSearching(false)
      }
    }, 300)
  }, [])

  const addTicker = async (ticker: string) => {
    const t = ticker.trim().toUpperCase()
    if (!t) return
    setIsAdding(true)
    setError(null)
    setSuggestions([])
    setOpen(false)
    try {
      await watchlistApi.add(t)
      setValue('')
      onAdded()
      setAnalyzingTicker(t)
      analyzeApi.get(t, true)
        .then(() => onAdded())
        .catch(() => {})
        .finally(() => setAnalyzingTicker(null))
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Failed to add ticker.')
    } finally {
      setIsAdding(false)
    }
  }

  return (
    <View style={{ marginBottom: 16 }}>
      <View style={{ flexDirection: 'row', gap: 8 }}>
        {/* Input */}
        <View style={{ flex: 1 }}>
          <View style={{
            flexDirection: 'row', alignItems: 'center',
            borderWidth: 1, borderColor: C.border, borderRadius: 10,
            backgroundColor: C.surface, paddingHorizontal: 12,
          }}>
            {isSearching
              ? <ActivityIndicator size={14} color={C.fgMuted} />
              : <Search size={14} color={C.fgMuted} />}
            <TextInput
              value={value}
              onChangeText={(v) => { setValue(v); setError(null); search(v) }}
              onBlur={() => setTimeout(() => setOpen(false), 150)}
              placeholder="Search ticker or company…"
              placeholderTextColor={C.fgMuted}
              autoCapitalize="characters"
              autoCorrect={false}
              maxLength={20}
              editable={!isAdding}
              style={{ flex: 1, paddingVertical: 12, paddingLeft: 8, fontSize: 14, color: C.fg }}
            />
          </View>

          {/* Suggestions dropdown */}
          {open && suggestions.length > 0 && (
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
                  onPress={() => { setValue(s.symbol); setOpen(false); setSuggestions([]) }}
                  style={({ pressed }) => ({
                    flexDirection: 'row', alignItems: 'center', gap: 10,
                    paddingHorizontal: 14, paddingVertical: 11,
                    backgroundColor: pressed ? C.bg : C.surface,
                  })}
                >
                  <Text style={{ fontWeight: '700', fontSize: 13, color: C.brand, width: 52 }}>
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

        {/* Add button */}
        <Pressable
          onPress={() => addTicker(value)}
          disabled={isAdding || !value.trim()}
          style={({ pressed }) => ({
            backgroundColor: isAdding || !value.trim() ? '#f5803b' : pressed ? '#c24d08' : C.brand,
            borderRadius: 10, paddingHorizontal: 16,
            flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6,
          })}
        >
          {isAdding ? <LoadingSpinner size="sm" color="#fff" /> : <Plus size={16} color="#fff" />}
          <Text style={{ color: '#fff', fontWeight: '600', fontSize: 14 }}>
            {isAdding ? 'Adding…' : 'Add'}
          </Text>
        </Pressable>
      </View>

      {analyzingTicker && (
        <View style={{
          flexDirection: 'row', alignItems: 'center', gap: 10,
          paddingHorizontal: 14, paddingVertical: 12, borderRadius: 10,
          backgroundColor: 'rgba(242,96,12,0.08)', borderWidth: 1, borderColor: 'rgba(242,96,12,0.25)',
          marginTop: 10,
        }}>
          <LoadingSpinner size="sm" />
          <Text style={{ fontSize: 13, color: C.brand }}>
            Analysing <Text style={{ fontWeight: '700' }}>{analyzingTicker}</Text> — takes 5–10s…
          </Text>
        </View>
      )}

      {error && (
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 8 }}>
          <AlertCircle size={13} color="#ef4444" />
          <Text style={{ fontSize: 12, color: '#ef4444' }}>{error}</Text>
        </View>
      )}
    </View>
  )
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <View style={{ alignItems: 'center', paddingVertical: 64 }}>
      <View style={{
        width: 64, height: 64, borderRadius: 18,
        backgroundColor: 'rgba(242,96,12,0.1)',
        alignItems: 'center', justifyContent: 'center', marginBottom: 16,
      }}>
        <TrendingUp size={32} color={C.brand} />
      </View>
      <Text style={{ fontSize: 18, fontWeight: '400', color: C.fg, marginBottom: 8 }}>
        Your watchlist is empty
      </Text>
      <Text style={{ fontSize: 13, color: C.fgMuted, textAlign: 'center', maxWidth: 260 }}>
        Add tickers above to get AI-powered signal analysis.
      </Text>
    </View>
  )
}

// ── Dashboard Screen ──────────────────────────────────────────────────────────

const EMPTY_SETUPS: WatchlistSetupCounts = { entry: 0, exit_alert: 0, neutral: 0, pending: 0 }

export default function DashboardScreen() {
  const [items, setItems] = useState<WatchlistItem[]>([])
  const [setups, setSetups] = useState<WatchlistSetupCounts>(EMPTY_SETUPS)
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<Filter>('ALL')
  const [expanded, setExpanded] = useState<string | null>(null)

  const fetchWatchlist = useCallback(async () => {
    setError(null)
    try {
      const res = await watchlistApi.get()
      const data = res.data
      setItems(Array.isArray(data) ? data : (data.items ?? []))
      setSetups(Array.isArray(data) ? EMPTY_SETUPS : (data.setups ?? EMPTY_SETUPS))
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Failed to load watchlist.')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => { fetchWatchlist() }, [fetchWatchlist])

  const handleRefresh = useCallback(async () => {
    setIsRefreshing(true)
    await fetchWatchlist()
    setIsRefreshing(false)
  }, [fetchWatchlist])

  const handleRemove = (ticker: string) =>
    setItems((prev) => prev.filter((i) => i.ticker !== ticker))

  const counts: Record<Filter, number> = {
    ALL: items.length,
    ENTRY: setups.entry,
    EXIT_ALERT: setups.exit_alert,
    BUY: items.filter((i) => i.signal === 'BUY').length,
    HOLD: items.filter((i) => i.signal === 'HOLD').length,
    SELL: items.filter((i) => i.signal === 'SELL').length,
  }

  const filtered = items.filter((i) => matchesFilter(i, filter))
  const actionable = setups.entry + setups.exit_alert

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.bg }} edges={['top']}>
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      >
        <FlatList
          data={isLoading ? [] : filtered}
          keyExtractor={(item) => item.ticker}
          keyboardShouldPersistTaps="handled"
          refreshing={isRefreshing}
          onRefresh={handleRefresh}
          renderItem={({ item }) => (
            <WatchlistRow
              item={item}
              expanded={expanded === item.ticker}
              onToggle={() => setExpanded((cur) => (cur === item.ticker ? null : item.ticker))}
              onRemove={handleRemove}
            />
          )}
          ListHeaderComponent={
            <View style={{ paddingHorizontal: 16, paddingTop: 20 }}>
              {/* Page header */}
              <View style={{ marginBottom: 20 }}>
                <Text style={{ fontSize: 24, fontWeight: '300', color: C.fg }}>
                  Your Watchlist
                </Text>
                {!isLoading && (
                  <Text style={{ fontSize: 13, color: C.fgMuted, marginTop: 2 }}>
                    {items.length} {items.length === 1 ? 'ticker' : 'tickers'} tracked
                    {actionable > 0 && (
                      <Text style={{ color: C.fg, fontWeight: '600' }}>
                        {' · '}{actionable} {actionable === 1 ? 'setup' : 'setups'} live
                      </Text>
                    )}
                  </Text>
                )}
              </View>

              {/* Add ticker */}
              <AddTickerForm onAdded={fetchWatchlist} />

              {/* Error */}
              {error && (
                <View style={{
                  flexDirection: 'row', alignItems: 'center', gap: 10,
                  paddingHorizontal: 14, paddingVertical: 12, borderRadius: 10,
                  backgroundColor: 'rgba(239,68,68,0.08)', borderWidth: 1, borderColor: 'rgba(239,68,68,0.2)',
                  marginBottom: 16,
                }}>
                  <AlertCircle size={16} color="#ef4444" />
                  <Text style={{ fontSize: 13, color: '#ef4444', flex: 1 }}>{error}</Text>
                </View>
              )}

              {/* Loading skeletons */}
              {isLoading && (
                <View style={{
                  backgroundColor: C.surface, borderRadius: 12,
                  borderWidth: 1, borderColor: C.border, overflow: 'hidden',
                }}>
                  {[...Array(4)].map((_, i) => <SkeletonRow key={i} />)}
                </View>
              )}

              {/* Empty state */}
              {!isLoading && items.length === 0 && <EmptyState />}

              {/* Filter bar */}
              {!isLoading && items.length > 0 && (
                <View style={{
                  backgroundColor: C.surface, borderRadius: 12,
                  borderWidth: 1, borderColor: C.border, overflow: 'hidden',
                }}>
                  <View style={{
                    paddingHorizontal: 16, paddingVertical: 12,
                    borderBottomWidth: 1, borderBottomColor: C.border,
                  }}>
                    <FilterBar active={filter} onChange={setFilter} counts={counts} />
                  </View>

                  {/* Column headers */}
                  <View style={{
                    flexDirection: 'row', alignItems: 'center', gap: 10,
                    paddingHorizontal: 16, paddingVertical: 8,
                    borderBottomWidth: 1, borderBottomColor: C.border,
                  }}>
                    {['Ticker', 'Signal', 'Score', 'Price'].map((h) => (
                      <Text key={h} style={{
                        fontSize: 9, fontWeight: '700', color: C.fgMuted,
                        textTransform: 'uppercase', letterSpacing: 0.8,
                        width: h === 'Ticker' ? 52 : h === 'Signal' ? 42 : h === 'Score' ? 64 : undefined,
                        flex: h === 'Price' ? 1 : undefined,
                      }}>
                        {h}
                      </Text>
                    ))}
                  </View>
                </View>
              )}

              {/* No filtered results */}
              {!isLoading && items.length > 0 && filtered.length === 0 && (
                <View style={{ paddingVertical: 40, paddingHorizontal: 16, alignItems: 'center' }}>
                  <Text style={{ fontSize: 13, color: C.fgMuted, textAlign: 'center' }}>
                    {filter === 'ENTRY'
                      ? 'No dip-buy setups right now. Add more tickers or wait for a pullback.'
                      : filter === 'EXIT_ALERT'
                        ? 'Nothing overbought on your watchlist.'
                        : `No ${FILTER_LABEL[filter].toLowerCase()} signals in your watchlist.`}
                  </Text>
                </View>
              )}
            </View>
          }
          ListFooterComponent={<Disclaimer />}
          contentContainerStyle={{ paddingBottom: 100 }}
          style={{ backgroundColor: C.bg }}
        />
      </KeyboardAvoidingView>
    </SafeAreaView>
  )
}
