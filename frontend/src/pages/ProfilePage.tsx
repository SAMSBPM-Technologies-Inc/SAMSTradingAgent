import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, Bell, Bot, Check, ExternalLink, Eye, EyeOff, Key, LogOut, Pencil, User, Wifi, WifiOff, X } from 'lucide-react'
import { alertsApi, authApi, ibkrApi, tradingApi } from '../lib/api'
import type { AlertSettings, AutoTradeSettings } from '../types'
import { useAuth } from '../lib/auth-context'
import Layout from '../components/Layout'
import LoadingSpinner from '../components/LoadingSpinner'

// ── Alert Settings section ────────────────────────────────────────────────────

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className="flex items-center justify-between gap-4 cursor-pointer select-none">
      <span className="text-sm text-[var(--color-fg)]">{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative w-10 h-6 rounded-full transition-colors duration-200 flex-shrink-0
          ${checked ? 'bg-brand-500' : 'bg-[var(--color-border)]'}`}
      >
        <span className={`absolute top-1 left-1 w-4 h-4 rounded-full bg-white shadow transition-transform duration-200
          ${checked ? 'translate-x-4' : 'translate-x-0'}`} />
      </button>
    </label>
  )
}

function AlertSettingsCard() {
  const [settings, setSettings] = useState<AlertSettings>({
    slack_webhook_url: '',
    whatsapp_phone: '',
    whatsapp_apikey: '',
    notify_on_signal_flip: true,
    notify_on_high_conviction: true,
    daily_digest: false,
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
    setIsSaving(true)
    setError(null)
    try {
      const payload = {
        ...settings,
        slack_webhook_url: settings.slack_webhook_url?.trim() || undefined,
        whatsapp_phone: settings.whatsapp_phone?.trim() || undefined,
        whatsapp_apikey: settings.whatsapp_apikey?.trim() || undefined,
      }
      await alertsApi.updateSettings(payload)
      setSavedOk(true)
      setTimeout(() => setSavedOk(false), 2500)
    } catch {
      setError('Failed to save. Please try again.')
    } finally {
      setIsSaving(false)
    }
  }

  const sendTest = async () => {
    setIsTesting(true)
    setError(null)
    try {
      await alertsApi.sendTest()
      setTestOk(true)
      setTimeout(() => setTestOk(false), 3000)
    } catch {
      setError('Test failed. Check your channel settings.')
    } finally {
      setIsTesting(false)
    }
  }

  if (isLoading) return (
    <div className="card p-5 flex items-center justify-center h-32">
      <LoadingSpinner size="sm" />
    </div>
  )

  const hasChannel = !!(
    settings.slack_webhook_url?.trim() ||
    (settings.whatsapp_phone?.trim() && settings.whatsapp_apikey?.trim())
  )

  return (
    <div className="card p-5">
      <h3 className="text-sm font-medium text-[var(--color-fg-muted)] mb-4 uppercase tracking-wide flex items-center gap-2">
        <Bell className="w-3.5 h-3.5" />
        Alerts
      </h3>

      <div className="flex flex-col gap-4">
        {/* Slack */}
        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium text-[var(--color-fg)]">Slack Webhook URL</label>
          <input
            type="url"
            value={settings.slack_webhook_url ?? ''}
            onChange={(e) => setSettings((s) => ({ ...s, slack_webhook_url: e.target.value }))}
            placeholder="https://hooks.slack.com/services/..."
            className="input text-sm"
          />
          <a
            href="https://api.slack.com/messaging/webhooks"
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-brand-500 flex items-center gap-1 hover:underline"
          >
            How to create a Slack webhook <ExternalLink className="w-3 h-3" />
          </a>
        </div>

        {/* WhatsApp */}
        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium text-[var(--color-fg)]">WhatsApp (via CallMeBot)</label>
          <input
            type="tel"
            value={settings.whatsapp_phone ?? ''}
            onChange={(e) => setSettings((s) => ({ ...s, whatsapp_phone: e.target.value }))}
            placeholder="+1234567890 (international format)"
            className="input text-sm"
          />
          <input
            type="text"
            value={settings.whatsapp_apikey ?? ''}
            onChange={(e) => setSettings((s) => ({ ...s, whatsapp_apikey: e.target.value }))}
            placeholder="CallMeBot API key"
            className="input text-sm"
          />
          <a
            href="https://www.callmebot.com/blog/free-api-whatsapp-messages/"
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-brand-500 flex items-center gap-1 hover:underline"
          >
            How to get your CallMeBot API key <ExternalLink className="w-3 h-3" />
          </a>
        </div>

        {/* Toggles */}
        <div className="flex flex-col gap-3 pt-1 border-t border-[var(--color-border)]">
          <Toggle
            checked={settings.notify_on_signal_flip}
            onChange={(v) => setSettings((s) => ({ ...s, notify_on_signal_flip: v }))}
            label="Notify when signal flips (e.g. HOLD → BUY)"
          />
          <Toggle
            checked={settings.notify_on_high_conviction}
            onChange={(v) => setSettings((s) => ({ ...s, notify_on_high_conviction: v }))}
            label="Notify on Strong Signal conviction"
          />
          <Toggle
            checked={settings.daily_digest}
            onChange={(v) => setSettings((s) => ({ ...s, daily_digest: v }))}
            label="Daily digest at 9 AM ET (weekdays)"
          />
        </div>

        {/* Actions */}
        <div className="flex gap-2">
          <button
            onClick={save}
            disabled={isSaving}
            className="btn-primary flex-1"
          >
            {isSaving ? <LoadingSpinner size="sm" /> : <Check className="w-4 h-4" />}
            {isSaving ? 'Saving…' : savedOk ? 'Saved!' : 'Save'}
          </button>
          <button
            onClick={sendTest}
            disabled={isTesting || !hasChannel}
            className="btn-secondary flex-1"
            title={hasChannel ? 'Send a test alert to configured channels' : 'Configure a channel first'}
          >
            {isTesting ? <LoadingSpinner size="sm" /> : <Bell className="w-4 h-4" />}
            {isTesting ? 'Sending…' : testOk ? 'Sent!' : 'Test'}
          </button>
        </div>

        {error && <p className="text-xs text-red-500">{error}</p>}
      </div>
    </div>
  )
}

// ── IBKR Credentials section ──────────────────────────────────────────────────

function IbkrCredentialsCard() {
  const [status, setStatus] = useState<{ has_credentials: boolean; ibkr_username: string | null }>({
    has_credentials: false,
    ibkr_username: null,
  })
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)
  const [savedOk, setSavedOk] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isEditing, setIsEditing] = useState(false)

  useEffect(() => {
    ibkrApi.getStatus()
      .then((res) => setStatus(res.data))
      .catch(() => {})
      .finally(() => setIsLoading(false))
  }, [])

  const save = async () => {
    if (!username.trim() || !password.trim()) {
      setError('Username and password are required.')
      return
    }
    setIsSaving(true)
    setError(null)
    try {
      const res = await ibkrApi.saveCredentials(username.trim(), password)
      setStatus(res.data)
      setIsEditing(false)
      setPassword('')
      setSavedOk(true)
      setTimeout(() => setSavedOk(false), 2500)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Failed to save credentials.')
    } finally {
      setIsSaving(false)
    }
  }

  const remove = async () => {
    if (!confirm('Remove stored IBKR credentials? Auto-trading will stop working until you re-enter them.')) return
    setIsDeleting(true)
    setError(null)
    try {
      await ibkrApi.deleteCredentials()
      setStatus({ has_credentials: false, ibkr_username: null })
      setUsername('')
      setPassword('')
    } catch {
      setError('Failed to remove credentials.')
    } finally {
      setIsDeleting(false)
    }
  }

  if (isLoading) return (
    <div className="card p-5 flex items-center justify-center h-32">
      <LoadingSpinner size="sm" />
    </div>
  )

  return (
    <div className="card p-5">
      <h3 className="text-sm font-medium text-[var(--color-fg-muted)] mb-4 uppercase tracking-wide flex items-center gap-2">
        <Key className="w-3.5 h-3.5" />
        IBKR Credentials
      </h3>

      <div className="flex items-start gap-2 p-3 rounded-xl bg-blue-500/10 text-blue-700 dark:text-blue-400 text-xs mb-4">
        <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
        <span>
          Encrypted at rest using AES-128 (Fernet). Never logged, never returned by the API.
          Required for automated trade execution via IB Gateway.
        </span>
      </div>

      {status.has_credentials && !isEditing ? (
        <div className="flex flex-col gap-3">
          <div className="flex justify-between items-center">
            <span className="text-sm text-[var(--color-fg-muted)]">Username</span>
            <span className="text-sm font-medium text-[var(--color-fg)]">{status.ibkr_username}</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-sm text-[var(--color-fg-muted)]">Password</span>
            <span className="text-sm font-medium text-[var(--color-fg)] tracking-widest">••••••••</span>
          </div>
          <div className="flex gap-2 pt-1">
            <button
              onClick={() => { setUsername(status.ibkr_username ?? ''); setIsEditing(true) }}
              className="btn-secondary flex-1 text-sm"
            >
              Update
            </button>
            <button
              onClick={remove}
              disabled={isDeleting}
              className="btn-secondary flex-1 text-sm text-red-500 border-red-500/20 hover:bg-red-500/10"
            >
              {isDeleting ? <LoadingSpinner size="sm" /> : 'Remove'}
            </button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-[var(--color-fg)]">IBKR Username</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="Your IBKR login username"
              className="input text-sm"
              autoComplete="username"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-[var(--color-fg)]">IBKR Password</label>
            <div className="relative">
              <input
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && save()}
                placeholder="Your IBKR account password"
                className="input text-sm pr-10"
                autoComplete="current-password"
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--color-fg-muted)] hover:text-[var(--color-fg)]"
                aria-label={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>
          <div className="flex gap-2">
            <button onClick={save} disabled={isSaving} className="btn-primary flex-1">
              {isSaving ? <LoadingSpinner size="sm" /> : <Check className="w-4 h-4" />}
              {isSaving ? 'Saving…' : savedOk ? 'Saved!' : 'Save'}
            </button>
            {isEditing && (
              <button onClick={() => { setIsEditing(false); setPassword('') }} className="btn-secondary px-4">
                Cancel
              </button>
            )}
          </div>
        </div>
      )}

      {error && <p className="text-xs text-red-500 mt-2">{error}</p>}
      {savedOk && !error && <p className="text-xs text-green-500 mt-2">Credentials saved securely.</p>}
    </div>
  )
}

// ── Auto Trading Settings section ─────────────────────────────────────────────

const DEFAULT_TRADE_SETTINGS: AutoTradeSettings = {
  enabled: false,
  paper_trading: true,
  min_signal_score: 0.75,
  position_size_pct: 0.05,
  max_open_positions: 5,
  max_daily_loss_pct: 0.02,
  allowed_tickers: [],
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
        setSettings(s)
        setConnected(conn)
      })
      .catch(() => {})
      .finally(() => setIsLoading(false))
  }, [])

  const save = async () => {
    setIsSaving(true)
    setError(null)
    try {
      const res = await tradingApi.updateSettings(settings)
      setConnected(res.data.connected)
      setSavedOk(true)
      setTimeout(() => setSavedOk(false), 2500)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Failed to save settings.')
    } finally {
      setIsSaving(false)
    }
  }

  const addTicker = () => {
    const t = tickerInput.trim().toUpperCase()
    if (!t || settings.allowed_tickers.includes(t)) return
    setSettings((s) => ({ ...s, allowed_tickers: [...s.allowed_tickers, t] }))
    setTickerInput('')
  }

  const removeTicker = (t: string) =>
    setSettings((s) => ({ ...s, allowed_tickers: s.allowed_tickers.filter((x) => x !== t) }))

  if (isLoading) return (
    <div className="card p-5 flex items-center justify-center h-32">
      <LoadingSpinner size="sm" />
    </div>
  )

  return (
    <div className="card p-5">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-medium text-[var(--color-fg-muted)] uppercase tracking-wide flex items-center gap-2">
          <Bot className="w-3.5 h-3.5" />
          Auto Trading
        </h3>
        <span className={`flex items-center gap-1 text-xs font-medium ${connected ? 'text-green-500' : 'text-[var(--color-fg-muted)]'}`}>
          {connected ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
          {connected ? 'IB Gateway connected' : 'IB Gateway offline'}
        </span>
      </div>

      {/* Warning banner */}
      <div className="flex items-start gap-2 p-3 rounded-xl bg-amber-500/10 text-amber-700 dark:text-amber-400 text-xs mb-4">
        <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
        <div>
          <span className="font-semibold">Paper trading mode by default.</span> Auto trading places real orders in your IBKR account.
          Requires Interactive Brokers account + IB Gateway running on the server.{' '}
          <span className="font-semibold">Only US-listed stocks are supported</span> (CIRO regulation for Canadian residents).
        </div>
      </div>

      <div className="flex flex-col gap-4">
        {/* Master toggle */}
        <Toggle
          checked={settings.enabled}
          onChange={(v) => setSettings((s) => ({ ...s, enabled: v }))}
          label="Enable automated trading"
        />

        {settings.enabled && (
          <>
            {/* Paper / Live */}
            <div className="flex flex-col gap-1.5">
              <span className="text-sm font-medium text-[var(--color-fg)]">Trading mode</span>
              <div className="flex gap-3">
                {([true, false] as const).map((isPaper) => (
                  <label key={String(isPaper)} className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="radio"
                      checked={settings.paper_trading === isPaper}
                      onChange={() => setSettings((s) => ({ ...s, paper_trading: isPaper }))}
                      className="accent-brand-500"
                    />
                    <span className="text-sm text-[var(--color-fg)]">
                      {isPaper ? 'Paper (simulated)' : 'Live (real money)'}
                    </span>
                  </label>
                ))}
              </div>
              {!settings.paper_trading && (
                <p className="text-xs text-red-500 mt-1">
                  Live trading must also be enabled server-side (AUTO_TRADE_LIVE_ALLOWED=true).
                </p>
              )}
            </div>

            {/* Score threshold */}
            <div className="flex flex-col gap-1.5">
              <div className="flex justify-between">
                <label className="text-sm font-medium text-[var(--color-fg)]">Minimum signal score</label>
                <span className="text-sm font-semibold text-brand-500">{(settings.min_signal_score * 100).toFixed(0)}%</span>
              </div>
              <input
                type="range" min={0.5} max={1.0} step={0.05}
                value={settings.min_signal_score}
                onChange={(e) => setSettings((s) => ({ ...s, min_signal_score: parseFloat(e.target.value) }))}
                className="w-full accent-brand-500"
              />
              <p className="text-xs text-[var(--color-fg-muted)]">Only BUY signals scoring above this threshold trigger an order.</p>
            </div>

            {/* Position size */}
            <div className="flex flex-col gap-1.5">
              <div className="flex justify-between">
                <label className="text-sm font-medium text-[var(--color-fg)]">Position size</label>
                <span className="text-sm font-semibold text-brand-500">{(settings.position_size_pct * 100).toFixed(0)}% of equity</span>
              </div>
              <input
                type="range" min={0.01} max={0.20} step={0.01}
                value={settings.position_size_pct}
                onChange={(e) => setSettings((s) => ({ ...s, position_size_pct: parseFloat(e.target.value) }))}
                className="w-full accent-brand-500"
              />
            </div>

            {/* Max positions + daily loss */}
            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1.5">
                <label className="text-sm font-medium text-[var(--color-fg)]">Max open positions</label>
                <input
                  type="number" min={1} max={20}
                  value={settings.max_open_positions}
                  onChange={(e) => setSettings((s) => ({ ...s, max_open_positions: parseInt(e.target.value) || 1 }))}
                  className="input text-sm"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="text-sm font-medium text-[var(--color-fg)]">Daily loss limit</label>
                <div className="relative">
                  <input
                    type="number" min={0.001} max={0.10} step={0.005}
                    value={settings.max_daily_loss_pct}
                    onChange={(e) => setSettings((s) => ({ ...s, max_daily_loss_pct: parseFloat(e.target.value) || 0.02 }))}
                    className="input text-sm pr-8"
                  />
                  <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-[var(--color-fg-muted)]">%</span>
                </div>
                <p className="text-xs text-[var(--color-fg-muted)]">Auto-trading pauses for the day when hit.</p>
              </div>
            </div>

            {/* Ticker whitelist */}
            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-medium text-[var(--color-fg)]">Ticker whitelist (optional)</label>
              <p className="text-xs text-[var(--color-fg-muted)]">Leave empty to allow all watchlist tickers. Add tickers to restrict.</p>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={tickerInput}
                  onChange={(e) => setTickerInput(e.target.value.toUpperCase())}
                  onKeyDown={(e) => e.key === 'Enter' && addTicker()}
                  placeholder="e.g. AAPL"
                  className="input text-sm flex-1"
                  maxLength={10}
                />
                <button onClick={addTicker} className="btn-secondary px-3 text-sm">Add</button>
              </div>
              {settings.allowed_tickers.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mt-1">
                  {settings.allowed_tickers.map((t) => (
                    <span key={t} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-brand-500/10 text-brand-500">
                      {t}
                      <button onClick={() => removeTicker(t)} className="hover:text-red-500"><X className="w-3 h-3" /></button>
                    </span>
                  ))}
                </div>
              )}
            </div>
          </>
        )}

        {/* Save */}
        <button onClick={save} disabled={isSaving} className="btn-primary w-full">
          {isSaving ? <LoadingSpinner size="sm" /> : <Check className="w-4 h-4" />}
          {isSaving ? 'Saving…' : savedOk ? 'Saved!' : 'Save'}
        </button>

        {error && <p className="text-xs text-red-500">{error}</p>}
      </div>
    </div>
  )
}

export default function ProfilePage() {
  const { user, logout } = useAuth()
  const [isEditing, setIsEditing] = useState(false)
  const [displayName, setDisplayName] = useState(user?.display_name ?? '')
  const [isSaving, setIsSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [savedOk, setSavedOk] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  // Sync if user changes
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
    if (!trimmed || trimmed === user?.display_name) {
      cancelEdit()
      return
    }
    setIsSaving(true)
    setSaveError(null)
    try {
      await authApi.updateProfile(trimmed)
      setSavedOk(true)
      setIsEditing(false)
      setTimeout(() => setSavedOk(false), 2500)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setSaveError(msg ?? 'Failed to save. Please try again.')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <Layout>
      {/* Header */}
      <div className="mb-6">
        <h1
          className="text-2xl font-light text-[var(--color-fg)]"
          style={{ fontFamily: 'Fraunces, Georgia, serif' }}
        >
          Profile
        </h1>
      </div>

      <div className="flex flex-col gap-4 max-w-md">
        {/* Avatar + info card */}
        <div className="card p-5 flex items-start gap-4">
          {/* Avatar */}
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-brand-500/20 to-brand-700/20
                          border border-brand-500/20 flex items-center justify-center flex-shrink-0">
            <User className="w-7 h-7 text-brand-500" />
          </div>

          {/* Info */}
          <div className="flex-1 min-w-0">
            {/* Display name row */}
            <div className="flex items-center gap-2 mb-1">
              {isEditing ? (
                <div className="flex items-center gap-2 flex-1">
                  <input
                    ref={inputRef}
                    type="text"
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') saveEdit()
                      if (e.key === 'Escape') cancelEdit()
                    }}
                    className="input py-1.5 text-sm flex-1"
                    maxLength={60}
                    disabled={isSaving}
                  />
                  <button
                    onClick={saveEdit}
                    disabled={isSaving}
                    aria-label="Save name"
                    className="btn-primary w-9 h-9 p-0 rounded-xl min-h-0 flex-shrink-0"
                  >
                    {isSaving ? <LoadingSpinner size="sm" /> : <Check className="w-4 h-4" />}
                  </button>
                  <button
                    onClick={cancelEdit}
                    disabled={isSaving}
                    aria-label="Cancel edit"
                    className="btn-secondary w-9 h-9 p-0 rounded-xl min-h-0 flex-shrink-0"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              ) : (
                <>
                  <span
                    className="text-lg font-medium text-[var(--color-fg)] truncate"
                    style={{ fontFamily: 'Fraunces, Georgia, serif' }}
                  >
                    {user?.display_name || 'Unnamed User'}
                  </span>
                  <button
                    onClick={startEdit}
                    aria-label="Edit display name"
                    className="btn-ghost w-8 h-8 p-0 rounded-lg flex-shrink-0 text-[var(--color-fg-muted)]"
                  >
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                </>
              )}
            </div>

            {/* Email */}
            <p className="text-sm text-[var(--color-fg-muted)] truncate">{user?.email}</p>

            {/* Feedback */}
            {saveError && (
              <p className="text-xs text-red-500 mt-1.5">{saveError}</p>
            )}
            {savedOk && (
              <p className="text-xs text-green-500 mt-1.5">Name updated successfully.</p>
            )}
          </div>
        </div>

        {/* Account details */}
        <div className="card p-5">
          <h3
            className="text-sm font-medium text-[var(--color-fg-muted)] mb-3 uppercase tracking-wide"
          >
            Account
          </h3>
          <div className="flex flex-col gap-3">
            <div className="flex justify-between">
              <span className="text-sm text-[var(--color-fg-muted)]">Email</span>
              <span className="text-sm text-[var(--color-fg)] font-medium truncate ml-4 max-w-[14rem]">
                {user?.email}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-[var(--color-fg-muted)]">User ID</span>
              <span className="text-xs text-[var(--color-fg-muted)] font-mono ml-4 truncate max-w-[14rem]">
                {user?.id}
              </span>
            </div>
          </div>
        </div>

        {/* Alert settings */}
        <AlertSettingsCard />

        {/* IBKR credentials */}
        <IbkrCredentialsCard />

        {/* Auto trading */}
        <AutoTradingCard />

        {/* Danger zone */}
        <div className="card p-5 border-red-500/20">
          <h3
            className="text-sm font-medium text-[var(--color-fg-muted)] mb-3 uppercase tracking-wide"
          >
            Session
          </h3>
          <button
            onClick={logout}
            className="btn-secondary text-red-500 border-red-500/20 hover:bg-red-500/10 w-full"
          >
            <LogOut className="w-4 h-4" />
            Sign Out
          </button>
        </div>
      </div>
    </Layout>
  )
}
