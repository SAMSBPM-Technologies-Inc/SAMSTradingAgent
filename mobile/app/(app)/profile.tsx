import React, { useEffect, useRef, useState } from 'react'
import {
  View, Text, TextInput, Pressable, ScrollView, Switch, Linking,
} from 'react-native'
import Slider from '@react-native-community/slider'
import {
  AlertTriangle, Bell, Bot, Check, ExternalLink, LogOut,
  Pencil, User, Wifi, WifiOff, X, BookOpen,
} from 'lucide-react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { router } from 'expo-router'
import { alertsApi, authApi, tradingApi } from '../../src/lib/api'
import type { AlertSettings, AutoTradeSettings } from '../../src/types'
import { useAuth } from '../../src/lib/auth-context'
import LoadingSpinner from '../../src/components/LoadingSpinner'

const C = {
  bg: '#f5f2ed', surface: '#ffffff', fg: '#14110c',
  fgMuted: '#83786a', border: '#e7e2d8', brand: '#f2600c',
}

const card = {
  backgroundColor: C.surface, borderRadius: 12,
  borderWidth: 1, borderColor: C.border, padding: 16, marginBottom: 12,
}

// ── Alert settings ────────────────────────────────────────────────────────────

function AlertSettingsCard() {
  const [settings, setSettings] = useState<AlertSettings>({
    slack_webhook_url: '', whatsapp_phone: '', whatsapp_apikey: '',
    notify_on_signal_flip: true, notify_on_high_conviction: true, daily_digest: false,
  })
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [isTesting, setIsTesting] = useState(false)
  const [savedOk, setSavedOk] = useState(false)
  const [testOk, setTestOk] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    alertsApi.getSettings()
      .then((res) => setSettings({
        ...res.data,
        slack_webhook_url: res.data.slack_webhook_url ?? '',
        whatsapp_phone: res.data.whatsapp_phone ?? '',
        whatsapp_apikey: res.data.whatsapp_apikey ?? '',
      }))
      .catch(() => {})
      .finally(() => setIsLoading(false))
  }, [])

  const save = async () => {
    setIsSaving(true); setError(null)
    try {
      await alertsApi.updateSettings({
        ...settings,
        slack_webhook_url: settings.slack_webhook_url?.trim() || undefined,
        whatsapp_phone: settings.whatsapp_phone?.trim() || undefined,
        whatsapp_apikey: settings.whatsapp_apikey?.trim() || undefined,
      })
      setSavedOk(true)
      setTimeout(() => setSavedOk(false), 2500)
    } catch { setError('Failed to save. Please try again.') }
    finally { setIsSaving(false) }
  }

  const sendTest = async () => {
    setIsTesting(true); setError(null)
    try {
      await alertsApi.sendTest()
      setTestOk(true)
      setTimeout(() => setTestOk(false), 3000)
    } catch { setError('Test failed. Check your channel settings.') }
    finally { setIsTesting(false) }
  }

  const hasChannel = !!(
    settings.slack_webhook_url?.trim() ||
    (settings.whatsapp_phone?.trim() && settings.whatsapp_apikey?.trim())
  )

  if (isLoading) return (
    <View style={{ ...card, height: 80, alignItems: 'center', justifyContent: 'center' }}>
      <LoadingSpinner size="sm" />
    </View>
  )

  return (
    <View style={card}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 16 }}>
        <Bell size={13} color={C.fgMuted} />
        <Text style={{ fontSize: 11, fontWeight: '700', color: C.fgMuted, textTransform: 'uppercase', letterSpacing: 0.8 }}>
          Alerts
        </Text>
      </View>

      {/* Slack */}
      <View style={{ marginBottom: 14 }}>
        <Text style={{ fontSize: 13, fontWeight: '500', color: C.fg, marginBottom: 6 }}>Slack Webhook URL</Text>
        <TextInput
          value={settings.slack_webhook_url ?? ''}
          onChangeText={(v) => setSettings((s) => ({ ...s, slack_webhook_url: v }))}
          placeholder="https://hooks.slack.com/services/..."
          placeholderTextColor={C.fgMuted}
          autoCapitalize="none"
          autoCorrect={false}
          style={{
            borderWidth: 1, borderColor: C.border, borderRadius: 10,
            paddingHorizontal: 12, paddingVertical: 10, fontSize: 13, color: C.fg,
            backgroundColor: C.bg, marginBottom: 4,
          }}
        />
        <Pressable
          onPress={() => Linking.openURL('https://api.slack.com/messaging/webhooks')}
          style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}
        >
          <Text style={{ fontSize: 11, color: C.brand }}>How to create a Slack webhook</Text>
          <ExternalLink size={11} color={C.brand} />
        </Pressable>
      </View>

      {/* WhatsApp */}
      <View style={{ marginBottom: 14 }}>
        <Text style={{ fontSize: 13, fontWeight: '500', color: C.fg, marginBottom: 6 }}>WhatsApp (via CallMeBot)</Text>
        <TextInput
          value={settings.whatsapp_phone ?? ''}
          onChangeText={(v) => setSettings((s) => ({ ...s, whatsapp_phone: v }))}
          placeholder="+1234567890 (international format)"
          placeholderTextColor={C.fgMuted}
          keyboardType="phone-pad"
          style={{
            borderWidth: 1, borderColor: C.border, borderRadius: 10,
            paddingHorizontal: 12, paddingVertical: 10, fontSize: 13, color: C.fg,
            backgroundColor: C.bg, marginBottom: 6,
          }}
        />
        <TextInput
          value={settings.whatsapp_apikey ?? ''}
          onChangeText={(v) => setSettings((s) => ({ ...s, whatsapp_apikey: v }))}
          placeholder="CallMeBot API key"
          placeholderTextColor={C.fgMuted}
          autoCapitalize="none"
          autoCorrect={false}
          style={{
            borderWidth: 1, borderColor: C.border, borderRadius: 10,
            paddingHorizontal: 12, paddingVertical: 10, fontSize: 13, color: C.fg,
            backgroundColor: C.bg, marginBottom: 4,
          }}
        />
        <Pressable
          onPress={() => Linking.openURL('https://www.callmebot.com/blog/free-api-whatsapp-messages/')}
          style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}
        >
          <Text style={{ fontSize: 11, color: C.brand }}>How to get your CallMeBot API key</Text>
          <ExternalLink size={11} color={C.brand} />
        </Pressable>
      </View>

      {/* Toggles */}
      <View style={{ borderTopWidth: 1, borderTopColor: C.border, paddingTop: 14, gap: 14 }}>
        {[
          { key: 'notify_on_signal_flip' as const, label: 'Notify when signal flips (e.g. HOLD → BUY)' },
          { key: 'notify_on_high_conviction' as const, label: 'Notify on Strong Signal conviction' },
          { key: 'daily_digest' as const, label: 'Daily digest at 9 AM ET (weekdays)' },
        ].map(({ key, label }) => (
          <View key={key} style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
            <Text style={{ fontSize: 13, color: C.fg, flex: 1, paddingRight: 16 }}>{label}</Text>
            <Switch
              value={settings[key]}
              onValueChange={(v) => setSettings((s) => ({ ...s, [key]: v }))}
              trackColor={{ false: C.border, true: C.brand }}
              thumbColor="#ffffff"
            />
          </View>
        ))}
      </View>

      {/* Actions */}
      <View style={{ flexDirection: 'row', gap: 10, marginTop: 14 }}>
        <Pressable
          onPress={save} disabled={isSaving}
          style={({ pressed }) => ({
            flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6,
            backgroundColor: pressed ? '#c24d08' : C.brand, borderRadius: 10, paddingVertical: 12,
          })}
        >
          {isSaving ? <LoadingSpinner size="sm" color="#fff" /> : <Check size={14} color="#fff" />}
          <Text style={{ color: '#fff', fontWeight: '600', fontSize: 13 }}>
            {isSaving ? 'Saving…' : savedOk ? 'Saved!' : 'Save'}
          </Text>
        </Pressable>
        <Pressable
          onPress={sendTest} disabled={isTesting || !hasChannel}
          style={({ pressed }) => ({
            flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6,
            backgroundColor: C.surface, borderRadius: 10, paddingVertical: 12,
            borderWidth: 1, borderColor: C.border,
            opacity: !hasChannel ? 0.5 : pressed ? 0.7 : 1,
          })}
        >
          {isTesting ? <LoadingSpinner size="sm" /> : <Bell size={14} color={C.fgMuted} />}
          <Text style={{ color: C.fg, fontWeight: '600', fontSize: 13 }}>
            {isTesting ? 'Sending…' : testOk ? 'Sent!' : 'Test'}
          </Text>
        </Pressable>
      </View>

      {error && <Text style={{ fontSize: 12, color: '#ef4444', marginTop: 8 }}>{error}</Text>}
    </View>
  )
}

// ── Auto trading card ─────────────────────────────────────────────────────────

const DEFAULT_TRADE_SETTINGS: AutoTradeSettings = {
  enabled: false, paper_trading: true, min_signal_score: 0.75,
  position_size_pct: 0.05, max_open_positions: 5, max_daily_loss_pct: 0.02, allowed_tickers: [],
}

function AutoTradingCard() {
  const [settings, setSettings] = useState<AutoTradeSettings>(DEFAULT_TRADE_SETTINGS)
  const [connected, setConnected] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [savedOk, setSavedOk] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tickerInput, setTickerInput] = useState('')

  useEffect(() => {
    tradingApi.getSettings()
      .then((res) => {
        const { connected: conn, ...s } = res.data
        setSettings(s); setConnected(conn)
      })
      .catch(() => {})
      .finally(() => setIsLoading(false))
  }, [])

  const save = async () => {
    setIsSaving(true); setError(null)
    try {
      const res = await tradingApi.updateSettings(settings)
      setConnected(res.data.connected)
      setSavedOk(true)
      setTimeout(() => setSavedOk(false), 2500)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Failed to save settings.')
    } finally { setIsSaving(false) }
  }

  const addTicker = () => {
    const t = tickerInput.trim().toUpperCase()
    if (!t || settings.allowed_tickers.includes(t)) return
    setSettings((s) => ({ ...s, allowed_tickers: [...s.allowed_tickers, t] }))
    setTickerInput('')
  }

  if (isLoading) return (
    <View style={{ ...card, height: 80, alignItems: 'center', justifyContent: 'center' }}>
      <LoadingSpinner size="sm" />
    </View>
  )

  return (
    <View style={card}>
      {/* Header */}
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
          <Bot size={13} color={C.fgMuted} />
          <Text style={{ fontSize: 11, fontWeight: '700', color: C.fgMuted, textTransform: 'uppercase', letterSpacing: 0.8 }}>
            Auto Trading
          </Text>
        </View>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
          {connected ? <Wifi size={12} color="#22c55e" /> : <WifiOff size={12} color={C.fgMuted} />}
          <Text style={{ fontSize: 11, fontWeight: '600', color: connected ? '#22c55e' : C.fgMuted }}>
            {connected ? 'IB Gateway connected' : 'IB Gateway offline'}
          </Text>
        </View>
      </View>

      {/* Warning */}
      <View style={{
        flexDirection: 'row', alignItems: 'flex-start', gap: 8,
        padding: 12, borderRadius: 10, backgroundColor: 'rgba(245,158,11,0.1)', marginBottom: 16,
      }}>
        <AlertTriangle size={13} color="#d97706" style={{ marginTop: 1 }} />
        <Text style={{ fontSize: 11, color: '#d97706', flex: 1 }}>
          <Text style={{ fontWeight: '700' }}>Paper trading mode by default.</Text>
          {' '}Auto trading places real orders in your IBKR account. Only US-listed stocks are supported.
        </Text>
      </View>

      {/* Master toggle */}
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Text style={{ fontSize: 13, color: C.fg }}>Enable automated trading</Text>
        <Switch
          value={settings.enabled}
          onValueChange={(v) => setSettings((s) => ({ ...s, enabled: v }))}
          trackColor={{ false: C.border, true: C.brand }}
          thumbColor="#ffffff"
        />
      </View>

      {settings.enabled && (
        <>
          {/* Paper / Live radio */}
          <View style={{ marginBottom: 16 }}>
            <Text style={{ fontSize: 13, fontWeight: '500', color: C.fg, marginBottom: 8 }}>Trading mode</Text>
            <View style={{ flexDirection: 'row', gap: 16 }}>
              {([true, false] as const).map((isPaper) => (
                <Pressable
                  key={String(isPaper)}
                  onPress={() => setSettings((s) => ({ ...s, paper_trading: isPaper }))}
                  style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}
                >
                  <View style={{
                    width: 18, height: 18, borderRadius: 9,
                    borderWidth: 2, borderColor: settings.paper_trading === isPaper ? C.brand : C.border,
                    alignItems: 'center', justifyContent: 'center',
                  }}>
                    {settings.paper_trading === isPaper && (
                      <View style={{ width: 9, height: 9, borderRadius: 5, backgroundColor: C.brand }} />
                    )}
                  </View>
                  <Text style={{ fontSize: 13, color: C.fg }}>
                    {isPaper ? 'Paper (simulated)' : 'Live (real money)'}
                  </Text>
                </Pressable>
              ))}
            </View>
            {!settings.paper_trading && (
              <Text style={{ fontSize: 11, color: '#ef4444', marginTop: 6 }}>
                Live trading must also be enabled server-side (AUTO_TRADE_LIVE_ALLOWED=true).
              </Text>
            )}
          </View>

          {/* Min signal score slider */}
          <View style={{ marginBottom: 16 }}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginBottom: 4 }}>
              <Text style={{ fontSize: 13, fontWeight: '500', color: C.fg }}>Minimum signal score</Text>
              <Text style={{ fontSize: 13, fontWeight: '700', color: C.brand }}>
                {(settings.min_signal_score * 100).toFixed(0)}%
              </Text>
            </View>
            <Slider
              minimumValue={0.5} maximumValue={1.0} step={0.05}
              value={settings.min_signal_score}
              onValueChange={(v) => setSettings((s) => ({ ...s, min_signal_score: v }))}
              minimumTrackTintColor={C.brand}
              maximumTrackTintColor={C.border}
              thumbTintColor={C.brand}
            />
            <Text style={{ fontSize: 11, color: C.fgMuted }}>
              Only BUY signals scoring above this threshold trigger an order.
            </Text>
          </View>

          {/* Position size slider */}
          <View style={{ marginBottom: 16 }}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginBottom: 4 }}>
              <Text style={{ fontSize: 13, fontWeight: '500', color: C.fg }}>Position size</Text>
              <Text style={{ fontSize: 13, fontWeight: '700', color: C.brand }}>
                {(settings.position_size_pct * 100).toFixed(0)}% of equity
              </Text>
            </View>
            <Slider
              minimumValue={0.01} maximumValue={0.20} step={0.01}
              value={settings.position_size_pct}
              onValueChange={(v) => setSettings((s) => ({ ...s, position_size_pct: v }))}
              minimumTrackTintColor={C.brand}
              maximumTrackTintColor={C.border}
              thumbTintColor={C.brand}
            />
          </View>

          {/* Max positions + daily loss */}
          <View style={{ flexDirection: 'row', gap: 10, marginBottom: 16 }}>
            <View style={{ flex: 1 }}>
              <Text style={{ fontSize: 13, fontWeight: '500', color: C.fg, marginBottom: 6 }}>
                Max open positions
              </Text>
              <TextInput
                value={String(settings.max_open_positions)}
                onChangeText={(v) => setSettings((s) => ({ ...s, max_open_positions: parseInt(v) || 1 }))}
                keyboardType="number-pad"
                style={{
                  borderWidth: 1, borderColor: C.border, borderRadius: 10,
                  paddingHorizontal: 12, paddingVertical: 10, fontSize: 14, color: C.fg,
                }}
              />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={{ fontSize: 13, fontWeight: '500', color: C.fg, marginBottom: 6 }}>
                Daily loss limit
              </Text>
              <TextInput
                value={String(settings.max_daily_loss_pct)}
                onChangeText={(v) => setSettings((s) => ({ ...s, max_daily_loss_pct: parseFloat(v) || 0.02 }))}
                keyboardType="decimal-pad"
                style={{
                  borderWidth: 1, borderColor: C.border, borderRadius: 10,
                  paddingHorizontal: 12, paddingVertical: 10, fontSize: 14, color: C.fg,
                }}
              />
            </View>
          </View>

          {/* Ticker whitelist */}
          <View style={{ marginBottom: 16 }}>
            <Text style={{ fontSize: 13, fontWeight: '500', color: C.fg, marginBottom: 4 }}>
              Ticker whitelist (optional)
            </Text>
            <Text style={{ fontSize: 11, color: C.fgMuted, marginBottom: 8 }}>
              Leave empty to allow all watchlist tickers.
            </Text>
            <View style={{ flexDirection: 'row', gap: 8 }}>
              <TextInput
                value={tickerInput}
                onChangeText={(v) => setTickerInput(v.toUpperCase())}
                onSubmitEditing={addTicker}
                placeholder="e.g. AAPL"
                placeholderTextColor={C.fgMuted}
                autoCapitalize="characters"
                maxLength={10}
                style={{
                  flex: 1, borderWidth: 1, borderColor: C.border, borderRadius: 10,
                  paddingHorizontal: 12, paddingVertical: 10, fontSize: 14, color: C.fg,
                }}
              />
              <Pressable
                onPress={addTicker}
                style={({ pressed }) => ({
                  backgroundColor: pressed ? C.bg : C.surface, borderRadius: 10,
                  paddingHorizontal: 14, alignItems: 'center', justifyContent: 'center',
                  borderWidth: 1, borderColor: C.border,
                })}
              >
                <Text style={{ fontSize: 13, fontWeight: '600', color: C.fg }}>Add</Text>
              </Pressable>
            </View>
            {settings.allowed_tickers.length > 0 && (
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
                {settings.allowed_tickers.map((t) => (
                  <View key={t} style={{
                    flexDirection: 'row', alignItems: 'center', gap: 4,
                    backgroundColor: 'rgba(242,96,12,0.1)', paddingHorizontal: 8, paddingVertical: 4, borderRadius: 20,
                  }}>
                    <Text style={{ fontSize: 11, fontWeight: '700', color: C.brand }}>{t}</Text>
                    <Pressable
                      onPress={() => setSettings((s) => ({ ...s, allowed_tickers: s.allowed_tickers.filter((x) => x !== t) }))}
                      hitSlop={6}
                    >
                      <X size={12} color={C.brand} />
                    </Pressable>
                  </View>
                ))}
              </View>
            )}
          </View>
        </>
      )}

      {/* Save */}
      <Pressable
        onPress={save} disabled={isSaving}
        style={({ pressed }) => ({
          flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6,
          backgroundColor: pressed ? '#c24d08' : C.brand, borderRadius: 10, paddingVertical: 13,
        })}
      >
        {isSaving ? <LoadingSpinner size="sm" color="#fff" /> : <Check size={14} color="#fff" />}
        <Text style={{ color: '#fff', fontWeight: '600', fontSize: 14 }}>
          {isSaving ? 'Saving…' : savedOk ? 'Saved!' : 'Save'}
        </Text>
      </Pressable>

      {error && <Text style={{ fontSize: 12, color: '#ef4444', marginTop: 8 }}>{error}</Text>}
    </View>
  )
}

// ── Profile Screen ────────────────────────────────────────────────────────────

export default function ProfileScreen() {
  const { user, logout } = useAuth()
  const [isEditing, setIsEditing] = useState(false)
  const [displayName, setDisplayName] = useState(user?.display_name ?? '')
  const [isSaving, setIsSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [savedOk, setSavedOk] = useState(false)
  const inputRef = useRef<TextInput>(null)

  useEffect(() => {
    if (user?.display_name) setDisplayName(user.display_name)
  }, [user])

  const startEdit = () => {
    setIsEditing(true)
    setSaveError(null)
    setSavedOk(false)
    setTimeout(() => inputRef.current?.focus(), 50)
  }

  const cancelEdit = () => {
    setIsEditing(false)
    setDisplayName(user?.display_name ?? '')
    setSaveError(null)
  }

  const saveEdit = async () => {
    const trimmed = displayName.trim()
    if (!trimmed || trimmed === user?.display_name) { cancelEdit(); return }
    setIsSaving(true); setSaveError(null)
    try {
      await authApi.updateProfile(trimmed)
      setSavedOk(true)
      setIsEditing(false)
      setTimeout(() => setSavedOk(false), 2500)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setSaveError(msg ?? 'Failed to save. Please try again.')
    } finally { setIsSaving(false) }
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.bg }} edges={['top']}>
      <ScrollView
        contentContainerStyle={{ paddingHorizontal: 16, paddingTop: 20, paddingBottom: 100 }}
        showsVerticalScrollIndicator={false}
      >
        <Text style={{ fontSize: 24, fontWeight: '300', color: C.fg, marginBottom: 20 }}>Profile</Text>

        {/* Avatar + name card */}
        <View style={{ ...card, flexDirection: 'row', alignItems: 'flex-start', gap: 14 }}>
          <View style={{
            width: 56, height: 56, borderRadius: 16,
            backgroundColor: 'rgba(242,96,12,0.12)',
            borderWidth: 1, borderColor: 'rgba(242,96,12,0.2)',
            alignItems: 'center', justifyContent: 'center',
          }}>
            <User size={28} color={C.brand} />
          </View>

          <View style={{ flex: 1 }}>
            {isEditing ? (
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                <TextInput
                  ref={inputRef}
                  value={displayName}
                  onChangeText={setDisplayName}
                  onSubmitEditing={saveEdit}
                  maxLength={60}
                  editable={!isSaving}
                  style={{
                    flex: 1, borderWidth: 1, borderColor: C.border, borderRadius: 10,
                    paddingHorizontal: 10, paddingVertical: 8, fontSize: 14, color: C.fg,
                  }}
                />
                <Pressable
                  onPress={saveEdit} disabled={isSaving}
                  style={{
                    width: 36, height: 36, borderRadius: 10,
                    backgroundColor: C.brand, alignItems: 'center', justifyContent: 'center',
                  }}
                >
                  {isSaving ? <LoadingSpinner size="sm" color="#fff" /> : <Check size={14} color="#fff" />}
                </Pressable>
                <Pressable
                  onPress={cancelEdit} disabled={isSaving}
                  style={{
                    width: 36, height: 36, borderRadius: 10,
                    backgroundColor: C.surface, borderWidth: 1, borderColor: C.border,
                    alignItems: 'center', justifyContent: 'center',
                  }}
                >
                  <X size={14} color={C.fg} />
                </Pressable>
              </View>
            ) : (
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                <Text style={{ fontSize: 17, fontWeight: '500', color: C.fg, flex: 1 }}>
                  {user?.display_name || 'Unnamed User'}
                </Text>
                <Pressable onPress={startEdit} hitSlop={8}>
                  <Pencil size={14} color={C.fgMuted} />
                </Pressable>
              </View>
            )}

            <Text style={{ fontSize: 13, color: C.fgMuted, marginTop: 3 }}>{user?.email}</Text>

            {saveError && <Text style={{ fontSize: 11, color: '#ef4444', marginTop: 6 }}>{saveError}</Text>}
            {savedOk && <Text style={{ fontSize: 11, color: '#16a34a', marginTop: 6 }}>Name updated successfully.</Text>}
          </View>
        </View>

        {/* Account details */}
        <View style={card}>
          <Text style={{
            fontSize: 11, fontWeight: '700', color: C.fgMuted,
            textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 12,
          }}>
            Account
          </Text>
          {[
            { label: 'Email', value: user?.email ?? '—' },
            { label: 'User ID', value: user?.id ?? '—', mono: true },
          ].map(({ label, value, mono }) => (
            <View key={label} style={{
              flexDirection: 'row', justifyContent: 'space-between',
              marginBottom: 10, gap: 16,
            }}>
              <Text style={{ fontSize: 13, color: C.fgMuted }}>{label}</Text>
              <Text style={{
                fontSize: mono ? 11 : 13, color: C.fg, fontWeight: '500',
                fontFamily: mono ? 'monospace' : undefined,
                flex: 1, textAlign: 'right',
              }} numberOfLines={1}>
                {value}
              </Text>
            </View>
          ))}
        </View>

        {/* Trading guide link */}
        <Pressable
          onPress={() => router.push('/(app)/guide')}
          style={({ pressed }) => ({
            ...card,
            flexDirection: 'row', alignItems: 'center', gap: 12,
            opacity: pressed ? 0.7 : 1,
          })}
        >
          <View style={{
            width: 36, height: 36, borderRadius: 10,
            backgroundColor: 'rgba(242,96,12,0.1)',
            alignItems: 'center', justifyContent: 'center',
          }}>
            <BookOpen size={18} color={C.brand} />
          </View>
          <Text style={{ fontSize: 14, fontWeight: '500', color: C.fg, flex: 1 }}>Trading Guide</Text>
          <ExternalLink size={14} color={C.fgMuted} />
        </Pressable>

        <AlertSettingsCard />
        <AutoTradingCard />

        {/* Sign out */}
        <View style={card}>
          <Text style={{
            fontSize: 11, fontWeight: '700', color: C.fgMuted,
            textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 12,
          }}>
            Session
          </Text>
          <Pressable
            onPress={logout}
            style={({ pressed }) => ({
              flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8,
              paddingVertical: 12, borderRadius: 10,
              backgroundColor: pressed ? 'rgba(239,68,68,0.08)' : C.surface,
              borderWidth: 1, borderColor: 'rgba(239,68,68,0.2)',
            })}
          >
            <LogOut size={15} color="#ef4444" />
            <Text style={{ color: '#ef4444', fontWeight: '600', fontSize: 14 }}>Sign Out</Text>
          </Pressable>
        </View>
      </ScrollView>
    </SafeAreaView>
  )
}
