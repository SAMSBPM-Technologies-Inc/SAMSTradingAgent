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
import { AlertCircle, ArrowRight, Plus, Search, Trash2, TrendingUp } from 'lucide-react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { watchlistApi, analyzeApi } from '../../src/lib/api'
import type { Signal, WatchlistItem } from '../../src/types'
import SignalBadge from '../../src/components/SignalBadge'
import ConvictionBadge from '../../src/components/ConvictionBadge'
import LoadingSpinner from '../../src/components/LoadingSpinner'

type Filter = 'ALL' | Signal
const FILTERS: Filter[] = ['ALL', 'BUY', 'HOLD', 'SELL']

const C = {
  bg: '#f5f2ed', surface: '#ffffff', fg: '#14110c',
  fgMuted: '#83786a', border: '#e7e2d8', brand: '#f2600c',
}

// ── Filter bar ────────────────────────────────────────────────────────────────

function FilterBar({
  active, onChange, counts,
}: {
  active: Filter; onChange: (f: Filter) => void; counts: Record<Filter, number>
}) {
  return (
    <View style={{ flexDirection: 'row', gap: 6, flexWrap: 'wrap' }}>
      {FILTERS.map((f) => (
        <Pressable
          key={f}
          onPress={() => onChange(f)}
          style={{
            paddingHorizontal: 10, paddingVertical: 5, borderRadius: 8,
            backgroundColor: active === f ? C.brand : `${C.border}80`,
          }}
        >
          <Text style={{
            fontSize: 11, fontWeight: '600',
            color: active === f ? '#fff' : C.fgMuted,
          }}>
            {f} {counts[f]}
          </Text>
        </Pressable>
      ))}
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

function WatchlistRow({ item, onRemove }: { item: WatchlistItem; onRemove: (t: string) => void }) {
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

  return (
    <Pressable
      onPress={() => router.push(`/ticker/${item.ticker}`)}
      style={({ pressed }) => ({
        flexDirection: 'row', alignItems: 'center', gap: 10,
        paddingHorizontal: 16, paddingVertical: 13,
        borderBottomWidth: 1, borderBottomColor: C.border,
        backgroundColor: pressed ? C.bg : C.surface,
      })}
    >
      {/* Ticker */}
      <Text style={{
        width: 44, fontSize: 13, fontWeight: '700', color: C.fg, flexShrink: 0,
      }}>
        {item.ticker}
      </Text>

      {/* Signal */}
      <View style={{ width: 42, flexShrink: 0 }}>
        <SignalBadge signal={item.signal} />
      </View>

      {/* Score bar */}
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4, width: 70, flexShrink: 0 }}>
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
                color: item.day_change_pct >= 0 ? '#22c55e' : '#ef4444',
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

      <ArrowRight size={14} color={C.fgMuted} />
    </Pressable>
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

export default function DashboardScreen() {
  const [items, setItems] = useState<WatchlistItem[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<Filter>('ALL')

  const fetchWatchlist = async () => {
    setError(null)
    try {
      const res = await watchlistApi.get()
      const data = res.data
      setItems(Array.isArray(data) ? data : (data.items ?? []))
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Failed to load watchlist.')
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => { fetchWatchlist() }, [])

  const handleRemove = (ticker: string) =>
    setItems((prev) => prev.filter((i) => i.ticker !== ticker))

  const counts: Record<Filter, number> = {
    ALL: items.length,
    BUY: items.filter((i) => i.signal === 'BUY').length,
    HOLD: items.filter((i) => i.signal === 'HOLD').length,
    SELL: items.filter((i) => i.signal === 'SELL').length,
  }

  const filtered = filter === 'ALL' ? items : items.filter((i) => i.signal === filter)

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
          renderItem={({ item }) => (
            <WatchlistRow item={item} onRemove={handleRemove} />
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
                        width: h === 'Ticker' ? 44 : h === 'Signal' ? 42 : h === 'Score' ? 70 : undefined,
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
                <View style={{ paddingVertical: 40, alignItems: 'center' }}>
                  <Text style={{ fontSize: 13, color: C.fgMuted }}>
                    No {filter} signals in your watchlist.
                  </Text>
                </View>
              )}
            </View>
          }
          contentContainerStyle={{ paddingBottom: 100 }}
          style={{ backgroundColor: C.bg }}
        />
      </KeyboardAvoidingView>
    </SafeAreaView>
  )
}
