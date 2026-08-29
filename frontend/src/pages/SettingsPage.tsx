import { useEffect, useRef, useState } from 'react'
import {
  AlertTriangle,
  Check,
  ExternalLink,
  LogOut,
  Pencil,
  X,
} from 'lucide-react'
import { alertsApi, authApi, llmApi, watchlistApi } from '../lib/api'
import { useAuth } from '../lib/auth-context'
import { useToast } from '../lib/toast-context'
import { useTradingSettings } from '../lib/trading-context'
import type {
  AlertSettings,
  AutoTradeSettings,
  Conviction,
  LLMRole,
  LLMSettings,
  ScoringWeights,
  TradingMode,
} from '../types'
import Layout from '../components/Layout'
import LoadingSpinner from '../components/LoadingSpinner'
import BrokerPanel from '../components/BrokerPanel'

/**
 * Settings — autonomy, risk limits, signal weights, broker and alerts.
 *
 * Replaces the Profile page. The 1.7 reorganisation is not cosmetic: the old
 * page stacked seven unrelated cards in one column, with the autonomy ladder
 * buried below alert webhooks and the risk limits that bound every order
 * hidden behind a master toggle. Autonomy now leads, because it is the setting
 * that decides whether anything else on this screen can spend money unattended.
 *
 * Auto-trade settings come from the shared context so the header pill, the
 * order ticket and this screen cannot disagree about the mode or the routing.
 */

const usd = new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', maximumFractionDigits: 0,
})

// ── Shared bits ───────────────────────────────────────────────────────────────

function Card({ title, blurb, children, span = false }: {
  title: string
  blurb?: string
  children: React.ReactNode
  span?: boolean
}) {
  return (
    <section
      className={`rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-3.5
                  ${span ? 'lg:col-span-2' : ''}`}
    >
      <h2
        className="m-0 text-[13px] font-bold uppercase tracking-[0.06em]"
        style={{ fontFamily: 'Archivo, system-ui, sans-serif' }}
      >
        {title}
      </h2>
      {blurb && (
        <p className="mb-2.5 mt-1 max-w-[70ch] text-[11.5px] leading-snug text-[var(--color-fg-muted)]">
          {blurb}
        </p>
      )}
      {children}
    </section>
  )
}

/**
 * A `<label>` cannot name a `<button>` — the implicit association only works
 * for form controls, so this switch previously announced as an unnamed toggle.
 * The text is bound explicitly via aria-labelledby instead, and the wrapper is
 * a div because label-wrapping-button is invalid markup.
 */
function Toggle({ checked, onChange, label, note }: {
  checked: boolean
  onChange: (v: boolean) => void
  label: string
  note?: string
}) {
  const labelId = `toggle-${label.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 40)}`
  return (
    <div className="flex select-none items-start justify-between gap-4 border-t border-[var(--color-border)] py-2 first:border-t-0">
      <span className="min-w-0">
        <span id={labelId} className="block text-[12px] text-[var(--color-fg)]">{label}</span>
        {note && <span className="block text-[10.5px] leading-snug text-[var(--color-fg-muted)]">{note}</span>}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby={labelId}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 h-5 w-9 flex-shrink-0 rounded-full transition-colors duration-200
                    focus:outline-none focus:ring-2 focus:ring-brand-500/50
                    ${checked ? 'bg-brand-500' : 'bg-[var(--color-border)]'}`}
      >
        <span
          className={`absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform
                      duration-200 ${checked ? 'translate-x-4' : 'translate-x-0'}`}
        />
      </button>
    </div>
  )
}

function Slider({ id, label, value, display, note, min, max, step, onChange }: {
  id: string
  label: string
  value: number
  display: string
  note: string
  min: number
  max: number
  step: number
  onChange: (v: number) => void
}) {
  return (
    <div className="border-t border-[var(--color-border)] py-2">
      <div className="flex items-baseline justify-between gap-3">
        <label htmlFor={id} className="text-[12px] text-[var(--color-fg)]">{label}</label>
        <span className="num text-[13px] font-semibold">{display}</span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="mt-1.5 w-full accent-brand-500"
      />
      <p className="text-[10.5px] leading-snug text-[var(--color-fg-muted)]">{note}</p>
    </div>
  )
}

function SaveRow({ onSave, saving, saved, error, disabled, children }: {
  onSave: () => void
  saving: boolean
  saved: boolean
  error: string | null
  disabled?: boolean
  children?: React.ReactNode
}) {
  return (
    <>
      <div className="mt-3 flex gap-2">
        <button onClick={onSave} disabled={saving || disabled} className="btn-primary flex-1">
          {saving ? <LoadingSpinner size="sm" /> : <Check className="h-4 w-4" aria-hidden="true" />}
          {saving ? 'Saving…' : saved ? 'Saved' : 'Save'}
        </button>
        {children}
      </div>
      {error && <p className="mt-1.5 text-[11px] text-[var(--accent-sell)]">{error}</p>}
    </>
  )
}

/** Shared save-state bookkeeping — six cards on this screen all need it. */
function useSaveState() {
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = async (fn: () => Promise<void>, fallback: string) => {
    setSaving(true)
    setError(null)
    try {
      await fn()
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? fallback)
    } finally {
      setSaving(false)
    }
  }

  return { saving, saved, error, run }
}

// ── Autonomy + risk limits ────────────────────────────────────────────────────

const MODE_OPTIONS: { value: TradingMode; label: string; blurb: string }[] = [
  { value: 'MANUAL', label: 'Manual', blurb: 'The agent proposes every entry and places none. You approve each one.' },
  { value: 'SEMI_AUTO', label: 'Semi-auto', blurb: 'The agent places high-conviction entries itself and queues the rest for you.' },
  { value: 'AUTO', label: 'Auto', blurb: 'The agent places every entry that clears its risk guards, unattended.' },
]

function AutonomyCard({ equity, aboveScore, watched }: {
  equity: number | null
  aboveScore: number
  watched: number
}) {
  const { settings, save } = useTradingSettings()
  const [draft, setDraft] = useState<AutoTradeSettings | null>(null)
  const { saving, saved, error, run } = useSaveState()
  const [tickerInput, setTickerInput] = useState('')

  useEffect(() => {
    if (settings) {
      const { connected: _c, ...rest } = settings
      setDraft(rest)
    }
  }, [settings])

  if (!draft) {
    return (
      <Card title="Autonomy" span>
        <div className="flex h-24 items-center justify-center"><LoadingSpinner size="sm" /></div>
      </Card>
    )
  }

  const set = <K extends keyof AutoTradeSettings>(k: K, v: AutoTradeSettings[K]) =>
    setDraft((d) => (d ? { ...d, [k]: v } : d))

  const commit = () => run(async () => { await save(draft) }, 'Failed to save settings.')

  const perPosition = equity != null ? equity * draft.position_size_pct : null
  const maxCommitted = draft.position_size_pct * draft.max_open_positions
  const lossCap = equity != null ? equity * draft.max_daily_loss_pct : null

  const addTicker = () => {
    const t = tickerInput.trim().toUpperCase()
    if (!t || draft.allowed_tickers.includes(t)) return
    set('allowed_tickers', [...draft.allowed_tickers, t])
    setTickerInput('')
  }

  return (
    <>
      <Card
        title="Autonomy"
        blurb="The ladder is suggest → confirm → automate. Nothing moves money until you climb it."
        span
      >
        <Toggle
          checked={draft.enabled}
          onChange={(v) => set('enabled', v)}
          label="Enable automated trading"
          note="Off, the agent still scores and proposes — it simply never places an order."
        />

        <div className="mt-2.5 grid gap-2 sm:grid-cols-3">
          {MODE_OPTIONS.map((opt) => {
            const active = draft.mode === opt.value
            return (
              <label
                key={opt.value}
                htmlFor={`mode-${opt.value}`}
                className={`flex cursor-pointer flex-col gap-1.5 rounded-lg border p-2.5 transition-colors
                            ${active
                  ? 'border-brand-500 bg-brand-500/5'
                  : 'border-[var(--color-border)] hover:bg-[var(--color-hover)]'}`}
              >
                <span className="flex items-center gap-2">
                  <input
                    id={`mode-${opt.value}`}
                    type="radio"
                    name="trading-mode"
                    checked={active}
                    onChange={() => set('mode', opt.value)}
                    aria-describedby={`mode-${opt.value}-desc`}
                    className="accent-brand-500"
                  />
                  <span
                    className="text-[12.5px] font-semibold"
                    style={{ fontFamily: 'Archivo, system-ui, sans-serif' }}
                  >
                    {opt.label}
                  </span>
                </span>
                <span
                  id={`mode-${opt.value}-desc`}
                  className="text-[11px] leading-snug text-[var(--color-fg-muted)]"
                >
                  {opt.blurb}
                </span>
              </label>
            )
          })}
        </div>

        {draft.mode === 'SEMI_AUTO' && (
          <div className="mt-2.5 flex flex-wrap items-center gap-2.5 border-t border-[var(--color-border)] pt-2.5">
            {/* A labelled group of pressed-state buttons, not a select plus a
                visually-hidden twin — two controls bound to one value is a
                worse experience for a screen reader than either alone. */}
            <div
              role="group"
              aria-label="Act unattended only at analyst conviction"
              className="flex flex-wrap items-center gap-2.5"
            >
              <span className="text-[11.5px] text-[var(--color-fg-muted)]">
                Act unattended only at analyst conviction
              </span>
              <span className="flex gap-1">
                {(['HIGH', 'MEDIUM', 'LOW'] as Conviction[]).map((c) => (
                  <button
                    key={c}
                    onClick={() => set('auto_execute_conviction', c)}
                    aria-pressed={draft.auto_execute_conviction === c}
                    className="chip"
                  >
                    {c === 'HIGH' ? 'High only' : c === 'MEDIUM' ? 'Medium and above' : 'Any conviction'}
                  </button>
                ))}
              </span>
            </div>
            <p className="w-full text-[10.5px] text-[var(--color-fg-muted)]">
              Anything weaker queues for your approval on Trade. An entry with no analyst conviction
              attached — the analyst may not have run — always queues.
            </p>
          </div>
        )}

        <SaveRow onSave={commit} saving={saving} saved={saved} error={error} />
      </Card>

      <Card
        title="Risk limits"
        blurb="Enforced server-side on every order, agent or manual. Changing them here does not loosen anything the server refuses."
      >
        <Slider
          id="min-signal-score"
          label="Minimum score to act"
          value={draft.min_signal_score}
          display={`${(draft.min_signal_score * 100).toFixed(0)}`}
          min={0.5} max={1} step={0.05}
          onChange={(v) => set('min_signal_score', v)}
          note={watched > 0
            ? `${aboveScore} of your ${watched} watched ${watched === 1 ? 'ticker scores' : 'tickers score'} at or above this right now.`
            : 'Only BUY signals at or above this trigger an agent order.'}
        />
        <Slider
          id="position-size"
          label="Position size"
          value={draft.position_size_pct}
          display={`${(draft.position_size_pct * 100).toFixed(0)}%`}
          min={0.01} max={0.2} step={0.01}
          onChange={(v) => set('position_size_pct', v)}
          note={perPosition != null
            ? `About ${usd.format(perPosition)} per position at current equity. Measured on cost basis, so a falling price cannot free up room to average down.`
            : 'Measured on cost basis, so a falling price cannot free up room to average down.'}
        />
        <Slider
          id="max-open-positions"
          label="Max open positions"
          value={draft.max_open_positions}
          display={String(draft.max_open_positions)}
          min={1} max={20} step={1}
          onChange={(v) => set('max_open_positions', Math.round(v))}
          note={`At ${(draft.position_size_pct * 100).toFixed(0)}% each, ${draft.max_open_positions} positions commit at most ${(maxCommitted * 100).toFixed(0)}% of equity.`}
        />
        <Slider
          id="daily-loss-limit"
          label="Daily loss cap"
          value={draft.max_daily_loss_pct}
          display={`${(draft.max_daily_loss_pct * 100).toFixed(1)}%`}
          min={0.005} max={0.1} step={0.005}
          onChange={(v) => set('max_daily_loss_pct', v)}
          note={lossCap != null
            ? `The kill switch pauses new entries for the day after about ${usd.format(lossCap)} of losses. Exits are never blocked.`
            : 'The kill switch pauses new entries for the day when hit. Exits are never blocked.'}
        />

        <div className="mt-2.5 border-t border-[var(--color-border)] pt-2.5">
          <label htmlFor="ticker-whitelist" className="text-[12px] text-[var(--color-fg)]">
            Ticker whitelist
          </label>
          <p className="mb-1.5 text-[10.5px] text-[var(--color-fg-muted)]">
            Empty allows every watchlist ticker. This restricts what the <em>agent</em> may
            pick — it never restricts an order you place yourself.
          </p>
          <div className="flex gap-1.5">
            <input
              id="ticker-whitelist"
              type="text"
              value={tickerInput}
              onChange={(e) => setTickerInput(e.target.value.toUpperCase())}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addTicker() } }}
              placeholder="e.g. AAPL"
              maxLength={10}
              className="input flex-1 text-sm"
            />
            <button onClick={addTicker} className="btn-secondary px-3">Add</button>
          </div>
          {draft.allowed_tickers.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {draft.allowed_tickers.map((t) => (
                <span
                  key={t}
                  className="num inline-flex items-center gap-1 rounded-full bg-brand-500/10 px-2 py-0.5
                             text-[11px] font-semibold text-brand-500"
                >
                  {t}
                  <button
                    onClick={() => set('allowed_tickers', draft.allowed_tickers.filter((x) => x !== t))}
                    aria-label={`Remove ${t} from the whitelist`}
                    className="hover:text-[var(--accent-sell)]"
                  >
                    <X className="h-3 w-3" aria-hidden="true" />
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>

        <SaveRow onSave={commit} saving={saving} saved={saved} error={error} />
      </Card>
    </>
  )
}

// ── Broker ────────────────────────────────────────────────────────────────────

function BrokerCard() {
  const { settings, save } = useTradingSettings()
  const { toast } = useToast()
  const [busy, setBusy] = useState(false)

  const setPaper = async (paper: boolean) => {
    if (!settings || busy || settings.paper_trading === paper) return
    if (!paper) {
      const ok = window.confirm(
        'Route orders to your LIVE account?\n\n'
        + 'Every order the agent places — and every order you place — will spend real '
        + 'money. Live routing must also be enabled server-side '
        + '(AUTO_TRADE_LIVE_ALLOWED=true) or orders will be refused.',
      )
      if (!ok) return
    }
    setBusy(true)
    try {
      await save({ paper_trading: paper })
      toast(paper ? 'Orders now route to the paper account.' : 'Orders now route to LIVE money.', paper ? 'success' : 'info')
    } catch {
      toast('Could not change order routing.', 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card title="Broker" blurb="Interactive Brokers via IB Gateway.">
      <BrokerPanel />

      <div className="mt-2.5 flex flex-wrap items-center gap-2.5 border-t border-[var(--color-border)] pt-2.5">
        <span className="text-[12px]">Routing</span>
        <div className="flex gap-1">
          {([true, false] as const).map((paper) => (
            <button
              key={String(paper)}
              onClick={() => setPaper(paper)}
              disabled={busy || !settings}
              aria-pressed={settings?.paper_trading === paper}
              className="chip disabled:opacity-40"
            >
              {paper ? 'Paper' : 'Live'}
            </button>
          ))}
        </div>
        <span className="min-w-[180px] flex-1 text-[10.5px] text-[var(--color-fg-muted)]">
          {settings?.paper_trading === false
            ? 'Live money. Orders you place require typing the ticker back to confirm.'
            : 'Simulated fills against the paper account. Nothing here spends money.'}
        </span>
      </div>

      <p className="mt-2 flex items-start gap-2 rounded-md px-2.5 py-2 text-[10.5px] leading-snug"
         style={{ background: 'var(--tint-hold)', color: 'var(--accent-hold)' }}>
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
        <span>
          Only US-listed stocks are supported, under CIRO rules for Canadian residents.
          IB Gateway must be running on the server for any order to reach the venue.
        </span>
      </p>
    </Card>
  )
}

// ── Signal weights ────────────────────────────────────────────────────────────

/**
 * Must mirror `backend/app/config.py` (weight_technical … weight_alternative_data).
 * These used to disagree — Reset handed out 0.25/0.15/0.20/0.15/0.10/0.15 while
 * the server ran 0.30/0.20/0.20/0.15/0.00/0.15 — so "Reset" silently moved the
 * user off the engine's own defaults.
 */
const DEFAULT_WEIGHTS: ScoringWeights = {
  technical: 0.30,
  fundamental: 0.20,
  sentiment: 0.20,
  macro: 0.15,
  volatility: 0.00,
  catalyst: 0.15,
  alternative_data: 0.10,
}

const WEIGHT_LABELS: Record<keyof ScoringWeights, string> = {
  technical: 'Technical',
  fundamental: 'Fundamental',
  sentiment: 'Sentiment',
  macro: 'Macro',
  volatility: 'Volatility',
  catalyst: 'Catalyst',
  alternative_data: 'Alternative data',
}

/** Only where the number needs defending. Most weights are self-explanatory. */
const WEIGHT_HINTS: Partial<Record<keyof ScoringWeights, string>> = {
  volatility:
    'Defaults to 0 — volatility is priced at the risk gate, which vetoes BUY above a '
    + 'risk score of 6. Raising this charges volatility twice.',
}

const BASE_KEYS: (keyof ScoringWeights)[] =
  ['technical', 'fundamental', 'sentiment', 'macro', 'volatility', 'catalyst']

function WeightsCard() {
  const { user, fetchUser } = useAuth()
  const [weights, setWeights] = useState<ScoringWeights>(user?.scoring_weights ?? DEFAULT_WEIGHTS)
  const { saving, saved, error, run } = useSaveState()

  useEffect(() => {
    if (user?.scoring_weights) setWeights(user.scoring_weights)
  }, [user?.scoring_weights])

  const baseSum = +(BASE_KEYS.reduce((s, k) => s + weights[k], 0)).toFixed(4)
  const sumOk = Math.abs(baseSum - 1.0) < 0.01

  const update = (key: keyof ScoringWeights, val: number) =>
    setWeights((w) => ({ ...w, [key]: Math.round(val * 100) / 100 }))

  const commit = () => run(async () => {
    await authApi.updateProfile({ scoring_weights: weights })
    await fetchUser()
  }, 'Failed to save weights.')

  return (
    <Card
      title="Signal weights"
      blurb="How the six sub-scores blend into your verdict. They must sum to 100%. Alternative data sits outside that sum as an additive modifier."
    >
      {BASE_KEYS.map((key) => (
        <div key={key} className="border-t border-[var(--color-border)] py-1.5">
          <div className="grid items-center gap-2" style={{ gridTemplateColumns: '6.4rem 1fr 2.6rem' }}>
            <label
              htmlFor={`weight-${key}`}
              className={`text-[11.5px] ${weights[key] === 0 ? 'text-[var(--color-fg-muted)]' : 'text-[var(--color-fg)]'}`}
            >
              {WEIGHT_LABELS[key]}
            </label>
            <input
              id={`weight-${key}`}
              type="range" min={0} max={1} step={0.01}
              value={weights[key]}
              onChange={(e) => update(key, parseFloat(e.target.value))}
              className="w-full accent-brand-500"
            />
            <span className="num text-right text-[12px]">{(weights[key] * 100).toFixed(0)}%</span>
          </div>
          {WEIGHT_HINTS[key] && (
            <p className="mt-0.5 text-[10.5px] leading-snug text-[var(--color-fg-muted)]">
              {WEIGHT_HINTS[key]}
            </p>
          )}
        </div>
      ))}

      <div className="border-t border-[var(--color-border)] py-1.5">
        <div className="grid items-center gap-2" style={{ gridTemplateColumns: '6.4rem 1fr 2.6rem' }}>
          <label htmlFor="weight-alternative_data" className="text-[11.5px] text-[var(--color-fg)]">
            {WEIGHT_LABELS.alternative_data}
            <span className="block text-[9.5px] text-[var(--color-fg-muted)]">modifier</span>
          </label>
          <input
            id="weight-alternative_data"
            type="range" min={0} max={0.5} step={0.01}
            value={weights.alternative_data}
            onChange={(e) => update('alternative_data', parseFloat(e.target.value))}
            className="w-full accent-brand-500"
          />
          <span className="num text-right text-[12px]">
            {(weights.alternative_data * 100).toFixed(0)}%
          </span>
        </div>
      </div>

      <div
        className="mt-2 flex items-center gap-2 rounded-md px-2.5 py-2 text-[11px]"
        style={sumOk
          ? { background: 'var(--tint-buy)', color: 'var(--accent-buy)' }
          : { background: 'var(--tint-sell)', color: 'var(--accent-sell)' }}
      >
        {sumOk
          ? <Check className="h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
          : <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />}
        Base weights sum to {(baseSum * 100).toFixed(0)}%{!sumOk && ' — must equal 100% to save'}
      </div>

      <p className="mt-1.5 text-[10.5px] leading-snug text-[var(--color-fg-muted)]">
        Saved weights apply the next time a ticker is scored — they do not retroactively
        change a verdict already on screen. Re-analyse a ticker on Trade to see them applied.
      </p>

      <SaveRow onSave={commit} saving={saving} saved={saved} error={error} disabled={!sumOk}>
        <button onClick={() => setWeights(DEFAULT_WEIGHTS)} className="btn-secondary px-3">
          Reset to default
        </button>
      </SaveRow>
    </Card>
  )
}

// ── Alerts ────────────────────────────────────────────────────────────────────

function AlertsCard() {
  const [settings, setSettings] = useState<AlertSettings | null>(null)
  const [testing, setTesting] = useState(false)
  const [testOk, setTestOk] = useState(false)
  const { saving, saved, error, run } = useSaveState()

  useEffect(() => {
    alertsApi.getSettings()
      .then((res) => setSettings({
        ...res.data,
        slack_webhook_url: res.data.slack_webhook_url ?? '',
        whatsapp_phone: res.data.whatsapp_phone ?? '',
        whatsapp_apikey: res.data.whatsapp_apikey ?? '',
      }))
      .catch(() => setSettings({
        slack_webhook_url: '', whatsapp_phone: '', whatsapp_apikey: '',
        notify_on_signal_flip: true, notify_on_high_conviction: true, daily_digest: false,
      }))
  }, [])

  if (!settings) {
    return (
      <Card title="Alerts">
        <div className="flex h-24 items-center justify-center"><LoadingSpinner size="sm" /></div>
      </Card>
    )
  }

  const set = <K extends keyof AlertSettings>(k: K, v: AlertSettings[K]) =>
    setSettings((s) => (s ? { ...s, [k]: v } : s))

  const commit = () => run(async () => {
    await alertsApi.updateSettings({
      ...settings,
      slack_webhook_url: settings.slack_webhook_url?.trim() || undefined,
      whatsapp_phone: settings.whatsapp_phone?.trim() || undefined,
      whatsapp_apikey: settings.whatsapp_apikey?.trim() || undefined,
    })
  }, 'Failed to save alert settings.')

  const hasChannel = !!(
    settings.slack_webhook_url?.trim()
    || (settings.whatsapp_phone?.trim() && settings.whatsapp_apikey?.trim())
  )

  const sendTest = async () => {
    setTesting(true)
    try {
      await alertsApi.sendTest()
      setTestOk(true)
      setTimeout(() => setTestOk(false), 3000)
    } catch {
      // Surfaced by the button label reverting; the save error slot belongs to save.
    } finally {
      setTesting(false)
    }
  }

  return (
    <Card
      title="Alerts"
      blurb="Slack and WhatsApp are wired; email falls back to the account address. Alerts fire on published signal changes only — an unconfirmed candidate is not news."
    >
      <div className="flex flex-col gap-1.5">
        <label className="text-[12px] text-[var(--color-fg)]" htmlFor="slack-webhook">
          Slack webhook URL
        </label>
        <input
          id="slack-webhook"
          type="url"
          value={settings.slack_webhook_url ?? ''}
          onChange={(e) => set('slack_webhook_url', e.target.value)}
          placeholder="https://hooks.slack.com/services/…"
          className="input text-sm"
        />
        <a
          href="https://api.slack.com/messaging/webhooks"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 text-[11px] text-brand-500 hover:underline"
        >
          How to create a Slack webhook <ExternalLink className="h-3 w-3" aria-hidden="true" />
        </a>
      </div>

      <div className="mt-2.5 flex flex-col gap-1.5">
        <label className="text-[12px] text-[var(--color-fg)]" htmlFor="whatsapp-phone">
          WhatsApp (via CallMeBot)
        </label>
        <input
          id="whatsapp-phone"
          type="tel"
          value={settings.whatsapp_phone ?? ''}
          onChange={(e) => set('whatsapp_phone', e.target.value)}
          placeholder="+1234567890 (international format)"
          className="input text-sm"
        />
        <input
          type="text"
          aria-label="CallMeBot API key"
          value={settings.whatsapp_apikey ?? ''}
          onChange={(e) => set('whatsapp_apikey', e.target.value)}
          placeholder="CallMeBot API key"
          className="input text-sm"
        />
        <a
          href="https://www.callmebot.com/blog/free-api-whatsapp-messages/"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 text-[11px] text-brand-500 hover:underline"
        >
          How to get your CallMeBot API key <ExternalLink className="h-3 w-3" aria-hidden="true" />
        </a>
      </div>

      <div className="mt-2.5">
        <Toggle
          checked={settings.notify_on_signal_flip}
          onChange={(v) => set('notify_on_signal_flip', v)}
          label="Signal flips"
          note="A published change of verdict, e.g. HOLD → BUY."
        />
        <Toggle
          checked={settings.notify_on_high_conviction}
          onChange={(v) => set('notify_on_high_conviction', v)}
          label="High conviction"
          note="Only when analyst conviction becomes HIGH — not every cycle it stays there."
        />
        <Toggle
          checked={settings.notify_on_trade ?? false}
          onChange={(v) => set('notify_on_trade', v)}
          label="Order submitted"
          note="The agent has sent an order to the venue."
        />
        <Toggle
          checked={settings.notify_on_fill ?? false}
          onChange={(v) => set('notify_on_fill', v)}
          label="Fills and closes"
          note="An order executed, or a position closed with its realised P&L."
        />
        <Toggle
          checked={settings.daily_digest}
          onChange={(v) => set('daily_digest', v)}
          label="Daily digest"
          note="9 AM ET, weekdays."
        />
      </div>

      <SaveRow onSave={commit} saving={saving} saved={saved} error={error}>
        <button
          onClick={sendTest}
          disabled={testing || !hasChannel}
          className="btn-secondary flex-1"
          title={hasChannel ? 'Send a test alert to configured channels' : 'Configure a channel first'}
        >
          {testing ? <LoadingSpinner size="sm" /> : null}
          {testing ? 'Sending…' : testOk ? 'Sent' : 'Send test'}
        </button>
      </SaveRow>
    </Card>
  )
}

// ── Account ───────────────────────────────────────────────────────────────────

// ── Models ────────────────────────────────────────────────────────────────────
// A trader brings their own keys and decides which model reads which part of a
// company. Two rules shape this card and both are visible in the copy:
//
// A key goes in and never comes back. The server has no response field capable
// of holding one, so there is nothing here that could render a key even by
// mistake — what is shown is a fingerprint and a status.
//
// Order is priority. There is no rank control because the list order *is* the
// rank; two representations of one fact drift.

const ROLE_BLURBS: { role: LLMRole; label: string; blurb: string }[] = [
  {
    role: 'orchestrator',
    label: 'Judgement',
    blurb: 'The risk agent, the rebuttal, and the synthesis — the calls that decide the verdict.',
  },
  {
    role: 'specialist',
    label: 'Description',
    blurb: 'Fundamentals, technicals, and news. More reading than judgement, so a cheaper model often holds up.',
  },
  {
    role: 'analyst',
    label: 'Fast path',
    blurb: 'The per-signal analyst. Runs far more often than research does, so this is where model cost adds up.',
  },
]

function ModelsCard() {
  const [state, setState] = useState<LLMSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [provider, setProvider] = useState('anthropic')
  const [apiKey, setApiKey] = useState('')
  const [label, setLabel] = useState('')
  const [adding, setAdding] = useState(false)
  const [addError, setAddError] = useState<string | null>(null)
  const { saving, saved, error, run } = useSaveState()
  const { toast } = useToast()

  useEffect(() => {
    llmApi.settings()
      .then(({ data }) => setState(data))
      .catch(() => setState(null))
      .finally(() => setLoading(false))
  }, [])

  const addKey = async () => {
    setAdding(true)
    setAddError(null)
    try {
      const { data } = await llmApi.addKey(provider, apiKey.trim(), label.trim())
      setState(data)
      setApiKey('')
      setLabel('')
      toast('Key added and verified')
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setAddError(detail ?? 'That key could not be added.')
    } finally {
      setAdding(false)
    }
  }

  const removeKey = async (keyId: string) => {
    try {
      const { data } = await llmApi.deleteKey(keyId)
      setState(data)
      toast('Key removed')
    } catch {
      toast('Could not remove that key')
    }
  }

  const testKey = async (keyId: string) => {
    try {
      const { data } = await llmApi.testKey(keyId)
      toast(data.ok ? 'Key works' : `Key failed (${data.error_kind}): ${data.error}`)
      const refreshed = await llmApi.settings()
      setState(refreshed.data)
    } catch {
      toast('Could not reach that provider')
    }
  }

  const move = (role: LLMRole, index: number, delta: number) => {
    if (!state) return
    const entries = [...state.roles[role]]
    const target = index + delta
    if (target < 0 || target >= entries.length) return
    ;[entries[index], entries[target]] = [entries[target], entries[index]]
    setState({ ...state, roles: { ...state.roles, [role]: entries } })
  }

  const removeEntry = (role: LLMRole, index: number) => {
    if (!state) return
    const entries = state.roles[role].filter((_, i) => i !== index)
    setState({ ...state, roles: { ...state.roles, [role]: entries } })
  }

  const addEntry = (role: LLMRole, keyId: string) => {
    if (!state || !keyId) return
    const entries = [...state.roles[role], { key_id: keyId, model: '' }]
    setState({ ...state, roles: { ...state.roles, [role]: entries } })
  }

  const setModel = (role: LLMRole, index: number, model: string) => {
    if (!state) return
    const entries = state.roles[role].map((e, i) => (i === index ? { ...e, model } : e))
    setState({ ...state, roles: { ...state.roles, [role]: entries } })
  }

  const save = () => {
    if (!state) return
    run(async () => {
      const { data } = await llmApi.save(state.roles, state.research_enabled)
      setState(data)
    }, 'Could not save your model settings.')
  }

  if (loading) {
    return (
      <Card title="Models" blurb="Which model reads which part of a company.">
        <LoadingSpinner size="sm" />
      </Card>
    )
  }
  if (!state) {
    return (
      <Card title="Models" blurb="Which model reads which part of a company.">
        <p className="text-[11.5px] text-[var(--color-fg-muted)]">
          Model settings could not be loaded.
        </p>
      </Card>
    )
  }

  const keyLabel = (keyId: string) => {
    const key = state.keys.find((k) => k.id === keyId)
    return key ? `${key.provider} · ${key.fingerprint}` : keyId
  }

  return (
    <Card
      span
      title="Models"
      blurb="Your own provider keys, and which model reads which part of a company. Keys are stored encrypted, never shown again, and never leave this server."
    >
      {/* ── Keys ── */}
      <div className="label-micro">Your keys</div>
      {state.keys.length === 0 ? (
        <p className="mt-1 text-[11.5px] leading-snug text-[var(--color-fg-muted)]">
          No keys yet. Everything runs on this deployment&rsquo;s own key
          {state.server_fallback ? <> ({state.server_fallback})</> : null} until you add one.
        </p>
      ) : (
        <ul className="mt-1.5 flex flex-col gap-1.5">
          {state.keys.map((key) => (
            <li
              key={key.id}
              className="flex flex-wrap items-center gap-2 rounded border border-[var(--color-border)] px-2 py-1.5"
            >
              <span className="text-[12px] font-medium text-[var(--color-fg)]">
                {key.label || key.provider}
              </span>
              <span className="font-mono text-[11px] text-[var(--color-fg-muted)]">
                {key.fingerprint}
              </span>
              {key.last_error ? (
                <span className="text-[10.5px]" style={{ color: 'var(--accent-sell)' }}>
                  last call failed
                </span>
              ) : key.last_ok_at ? (
                <span className="text-[10.5px]" style={{ color: 'var(--accent-buy)' }}>
                  working
                </span>
              ) : null}
              <span className="ml-auto flex gap-1.5">
                <button
                  onClick={() => testKey(key.id)}
                  className="text-[11px] text-[var(--color-fg-muted)] underline"
                >
                  Test
                </button>
                <button
                  onClick={() => removeKey(key.id)}
                  className="text-[11px] underline"
                  style={{ color: 'var(--accent-sell)' }}
                >
                  Remove
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}

      {/* ── Add a key ── */}
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <div className="flex flex-col gap-1">
          <label htmlFor="llm-provider" className="label-micro">Provider</label>
          <select
            id="llm-provider"
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            className="input-base"
          >
            <option value="anthropic">Anthropic</option>
            <option value="openai">OpenAI</option>
            <option value="google">Google</option>
          </select>
        </div>
        <div className="flex flex-1 flex-col gap-1">
          <label htmlFor="llm-key" className="label-micro">API key</label>
          <input
            id="llm-key"
            type="password"
            autoComplete="off"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="Pasted once, never shown again"
            className="input-base"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="llm-label" className="label-micro">Label</label>
          <input
            id="llm-label"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="optional"
            className="input-base"
          />
        </div>
        <button
          onClick={addKey}
          disabled={adding || apiKey.trim().length < 8}
          className="btn-secondary"
        >
          {adding ? 'Checking…' : 'Add key'}
        </button>
      </div>
      <p className="mt-1 text-[10.5px] leading-snug text-[var(--color-fg-muted)]">
        A key is checked with one real call before it is stored. A key that
        does not work is refused here rather than skipped silently every night.
      </p>
      {addError && (
        <p className="mt-1 text-[11px]" style={{ color: 'var(--accent-sell)' }}>
          {addError}
        </p>
      )}

      {/* ── Role assignment ── */}
      <div className="mt-4 flex flex-col gap-3">
        {ROLE_BLURBS.map(({ role, label: roleLabel, blurb }) => (
          <div key={role}>
            <div className="label-micro">{roleLabel}</div>
            <p className="mt-0.5 text-[10.5px] leading-snug text-[var(--color-fg-muted)]">
              {blurb}
            </p>
            {state.roles[role].length === 0 ? (
              <p className="mt-1 text-[11px] text-[var(--color-fg-muted)]">
                Falls back to {state.server_fallback ?? 'this deployment\u2019s key'}.
              </p>
            ) : (
              <ol className="mt-1.5 flex flex-col gap-1.5">
                {state.roles[role].map((entry, index) => (
                  <li
                    key={`${role}-${index}`}
                    className="flex flex-wrap items-center gap-2 rounded border border-[var(--color-border)] px-2 py-1.5"
                  >
                    <span className="text-[10.5px] text-[var(--color-fg-muted)]">
                      {index + 1}
                    </span>
                    <span className="text-[11.5px] text-[var(--color-fg)]">
                      {keyLabel(entry.key_id)}
                    </span>
                    <input
                      aria-label={`${roleLabel} model, priority ${index + 1}`}
                      value={entry.model}
                      onChange={(e) => setModel(role, index, e.target.value)}
                      placeholder="model id"
                      className="input-base flex-1 min-w-[10rem]"
                    />
                    <span className="ml-auto flex gap-1">
                      <button
                        aria-label={`Move up, priority ${index + 1}`}
                        onClick={() => move(role, index, -1)}
                        disabled={index === 0}
                        className="text-[11px] text-[var(--color-fg-muted)] disabled:opacity-40"
                      >
                        ↑
                      </button>
                      <button
                        aria-label={`Move down, priority ${index + 1}`}
                        onClick={() => move(role, index, 1)}
                        disabled={index === state.roles[role].length - 1}
                        className="text-[11px] text-[var(--color-fg-muted)] disabled:opacity-40"
                      >
                        ↓
                      </button>
                      <button
                        aria-label={`Remove priority ${index + 1}`}
                        onClick={() => removeEntry(role, index)}
                        className="text-[11px] underline"
                        style={{ color: 'var(--accent-sell)' }}
                      >
                        Remove
                      </button>
                    </span>
                  </li>
                ))}
              </ol>
            )}
            {state.keys.length > 0 && (
              <select
                aria-label={`Add a key to ${roleLabel}`}
                value=""
                onChange={(e) => addEntry(role, e.target.value)}
                className="input-base mt-1.5 text-[11.5px]"
              >
                <option value="">Add a key…</option>
                {state.keys.map((key) => (
                  <option key={key.id} value={key.id}>
                    {key.label || key.provider} · {key.fingerprint}
                  </option>
                ))}
              </select>
            )}
          </div>
        ))}
      </div>

      <p className="mt-2 text-[10.5px] leading-snug text-[var(--color-fg-muted)]">
        Order is priority. If the first key is rate-limited or rejected, the
        next one runs; a request this server rejected as malformed does not
        fall through, because the next provider would reject it identically.
      </p>

      <div className="mt-3">
        <Toggle
          checked={state.research_enabled}
          onChange={(v) => setState({ ...state, research_enabled: v })}
          label="Build deep research daily"
          note="Five to seven model calls per watched ticker per day, on your own key. Off until you ask for it."
        />
      </div>

      <SaveRow onSave={save} saving={saving} saved={saved} error={error} />
    </Card>
  )
}

function AccountCard() {
  const { user, logout, fetchUser } = useAuth()
  const [editing, setEditing] = useState(false)
  const [displayName, setDisplayName] = useState(user?.display_name ?? '')
  const { saving, saved, error, run } = useSaveState()
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (user?.display_name) setDisplayName(user.display_name)
  }, [user])

  const commit = () => {
    const trimmed = displayName.trim()
    if (!trimmed || trimmed === user?.display_name) {
      setEditing(false)
      setDisplayName(user?.display_name ?? '')
      return
    }
    run(async () => {
      await authApi.updateProfile({ display_name: trimmed })
      await fetchUser()
      setEditing(false)
    }, 'Failed to save your name.')
  }

  return (
    <Card title="Account">
      <div className="flex items-center gap-2 border-t border-[var(--color-border)] py-2">
        <span className="flex-1 text-[12px] text-[var(--color-fg-muted)]">Display name</span>
        {editing ? (
          <span className="flex flex-1 items-center gap-1.5">
            <input
              ref={inputRef}
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') commit()
                if (e.key === 'Escape') { setEditing(false); setDisplayName(user?.display_name ?? '') }
              }}
              maxLength={60}
              disabled={saving}
              aria-label="Display name"
              className="input flex-1 text-sm"
            />
            <button onClick={commit} disabled={saving} aria-label="Save name" className="chip">
              {saving ? <LoadingSpinner size="sm" /> : <Check className="h-3 w-3" aria-hidden="true" />}
            </button>
            <button
              onClick={() => { setEditing(false); setDisplayName(user?.display_name ?? '') }}
              aria-label="Cancel"
              className="chip"
            >
              <X className="h-3 w-3" aria-hidden="true" />
            </button>
          </span>
        ) : (
          <>
            <span className="text-[12px] font-medium">{user?.display_name || 'Unnamed'}</span>
            <button
              onClick={() => { setEditing(true); setTimeout(() => inputRef.current?.focus(), 50) }}
              aria-label="Edit display name"
              className="chip"
            >
              <Pencil className="h-3 w-3" aria-hidden="true" />
            </button>
          </>
        )}
      </div>

      <div className="flex justify-between gap-4 border-t border-[var(--color-border)] py-2">
        <span className="text-[12px] text-[var(--color-fg-muted)]">Email</span>
        <span className="truncate text-[12px]">{user?.email}</span>
      </div>
      <div className="flex justify-between gap-4 border-t border-[var(--color-border)] py-2">
        <span className="text-[12px] text-[var(--color-fg-muted)]">User ID</span>
        <span className="truncate font-mono text-[11px] text-[var(--color-fg-muted)]">{user?.id}</span>
      </div>

      {error && <p className="mt-1.5 text-[11px] text-[var(--accent-sell)]">{error}</p>}
      {saved && <p className="mt-1.5 text-[11px] text-[var(--accent-buy)]">Saved.</p>}

      <button
        onClick={logout}
        className="btn-secondary mt-3 w-full border-[var(--accent-sell)]/30 text-[var(--accent-sell)]
                   hover:bg-[var(--tint-sell)]"
      >
        <LogOut className="h-4 w-4" aria-hidden="true" />
        Sign out
      </button>
    </Card>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function SettingsPage() {
  // Equity comes from the shared account copy — the same one the strip and the
  // order ticket read, so the dollar figures under these sliders describe the
  // account the rest of the app is showing.
  const { settings, account } = useTradingSettings()
  const equity = account?.connected ? account.net_liquidation : null
  const [scores, setScores] = useState<number[]>([])

  // Feeds the live notes under the risk sliders. A cap expressed only as a
  // percentage is hard to argue with; the same cap in dollars is not.
  useEffect(() => {
    watchlistApi.get()
      .then(({ data }) => setScores((data.items ?? []).map((i) => i.score)))
      .catch(() => setScores([]))
  }, [])

  const threshold = settings?.min_signal_score ?? 0.75
  const aboveScore = scores.filter((s) => s >= threshold).length

  return (
    <Layout>
      <div className="mb-4">
        <h1
          className="text-2xl font-light text-[var(--color-fg)]"
          style={{ fontFamily: 'Fraunces, Georgia, serif' }}
        >
          Settings
        </h1>
        <p className="mt-0.5 text-sm text-[var(--color-fg-muted)]">
          How much the agent may do alone, what bounds it, and how it scores.
        </p>
      </div>

      <div className="grid items-start gap-3.5 lg:grid-cols-2">
        <AutonomyCard equity={equity} aboveScore={aboveScore} watched={scores.length} />
        <WeightsCard />
        <BrokerCard />
        <AlertsCard />
        <ModelsCard />
        <AccountCard />
      </div>
    </Layout>
  )
}
