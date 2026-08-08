import { useEffect, useRef, useState } from 'react'
import { Bell, Check, ExternalLink, LogOut, Pencil, User, X } from 'lucide-react'
import { alertsApi, authApi } from '../lib/api'
import type { AlertSettings } from '../types'
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
    notify_on_signal_flip: true,
    notify_on_high_conviction: true,
    daily_digest: false,
  })
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [savedOk, setSavedOk] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    alertsApi.getSettings()
      .then((res) => setSettings({ ...res.data, slack_webhook_url: res.data.slack_webhook_url ?? '' }))
      .catch(() => {})
      .finally(() => setIsLoading(false))
  }, [])

  const save = async () => {
    setIsSaving(true)
    setError(null)
    try {
      const payload = { ...settings, slack_webhook_url: settings.slack_webhook_url?.trim() || undefined }
      await alertsApi.updateSettings(payload)
      setSavedOk(true)
      setTimeout(() => setSavedOk(false), 2500)
    } catch {
      setError('Failed to save. Please try again.')
    } finally {
      setIsSaving(false)
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
        <Bell className="w-3.5 h-3.5" />
        Alerts
      </h3>

      <div className="flex flex-col gap-4">
        {/* Webhook URL */}
        <div className="flex flex-col gap-1.5">
          <label className="text-sm text-[var(--color-fg)]">
            Slack Webhook URL
          </label>
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

        {/* Save */}
        <button
          onClick={save}
          disabled={isSaving}
          className="btn-primary w-full"
        >
          {isSaving ? <LoadingSpinner size="sm" /> : <Check className="w-4 h-4" />}
          {isSaving ? 'Saving…' : savedOk ? 'Saved!' : 'Save Alert Settings'}
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
