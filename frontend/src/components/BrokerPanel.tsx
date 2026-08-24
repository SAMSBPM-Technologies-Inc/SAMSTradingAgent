import { useCallback, useEffect, useState } from 'react'
import { Plug, PlugZap, RefreshCw, RotateCcw, Smartphone } from 'lucide-react'
import { tradingApi } from '../lib/api'
import { useToast } from '../lib/toast-context'
import type { BrokerStatus } from '../types'
import LoadingSpinner from './LoadingSpinner'

/**
 * Broker session state, and the two ways to get it back.
 *
 * The distinction matters and is surfaced rather than hidden behind one button:
 *
 *   Reconnect  — asks for a session now instead of waiting out the backoff.
 *                Fixes a stale socket. Always available, no privileges.
 *   Restart    — restarts the gateway container. The only thing that helps when
 *                the gateway is up but unauthenticated, which is what IBKR's
 *                weekend maintenance leaves behind. Off unless the server was
 *                deliberately configured for it.
 *
 * A restart usually triggers a 2FA push. If nobody approves it on their phone,
 * the session never comes back and the button looks broken — so that is stated
 * before it is pressed, not after.
 */

/** Poll while a restart is in flight; IBC login takes ~2 minutes. */
const RECOVERY_POLL_MS = 10_000

export default function BrokerPanel() {
  const { toast } = useToast()
  const [status, setStatus] = useState<BrokerStatus | null>(null)
  const [busy, setBusy] = useState<'reconnect' | 'restart' | null>(null)
  const [waiting, setWaiting] = useState(false)
  const [note, setNote] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const { data } = await tradingApi.brokerStatus()
      setStatus(data)
      return data
    } catch {
      return null
    }
  }, [])

  useEffect(() => { load() }, [load])

  // While a restart is coming up, poll until the session returns rather than
  // leaving the user to guess when to refresh.
  useEffect(() => {
    if (!waiting) return
    const id = setInterval(async () => {
      const data = await load()
      if (data?.connected) {
        setWaiting(false)
        setNote(null)
        toast('IB Gateway reconnected.', 'success')
      }
    }, RECOVERY_POLL_MS)
    return () => clearInterval(id)
  }, [waiting, load, toast])

  const reconnect = async () => {
    setBusy('reconnect')
    setNote(null)
    try {
      const { data } = await tradingApi.brokerReconnect()
      setNote(data.detail)
      toast(data.detail, data.connected ? 'success' : 'error')
      await load()
    } catch {
      toast('Could not reach the server to reconnect.', 'error')
    } finally {
      setBusy(null)
    }
  }

  const restart = async () => {
    setBusy('restart')
    setNote(null)
    try {
      const { data } = await tradingApi.brokerRestart()
      setNote(data.detail)
      // pending means "expect to wait", not "failed" — poll instead of
      // reporting the still-false connected flag as an error.
      if (data.pending) {
        setWaiting(true)
        toast('Gateway restarting — watch for a 2FA prompt.', 'info')
      } else {
        toast(data.detail, data.connected ? 'success' : 'error')
      }
      await load()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setNote(detail ?? 'Restart failed.')
      toast(detail ?? 'Could not restart the gateway.', 'error')
    } finally {
      setBusy(null)
    }
  }

  if (!status) {
    return (
      <div className="card flex items-center justify-center h-24">
        <LoadingSpinner size="sm" />
      </div>
    )
  }

  const connected = status.connected

  return (
    <div className="card flex flex-col gap-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2.5">
          {connected
            ? <PlugZap className="w-4 h-4 text-[var(--accent-buy)]" />
            : <Plug className="w-4 h-4 text-[var(--accent-sell)]" />}
          <div>
            <span className={`text-sm font-semibold ${
              connected ? 'text-[var(--accent-buy)]' : 'text-[var(--accent-sell)]'
            }`}>
              {connected ? 'IB Gateway connected' : 'IB Gateway disconnected'}
            </span>
            <p className="text-[0.65rem] text-[var(--color-fg-muted)] mt-0.5 tabular-nums">
              {status.provider} · {status.host}:{status.port} · {status.trading_mode}
            </p>
          </div>
        </div>

        <button
          onClick={() => load()}
          aria-label="Refresh broker status"
          className="btn-secondary text-xs px-2 py-1 h-auto min-h-0"
        >
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
      </div>

      {!connected && (
        <p className="text-xs text-[var(--color-fg-muted)] leading-relaxed">
          Orders are being refused while this is down — nothing is silently lost.
          Most Monday-morning outages are IBKR&rsquo;s weekend maintenance leaving the
          gateway running but unauthenticated, which only a restart clears.
        </p>
      )}

      {note && (
        <p className="text-xs text-[var(--color-fg)] leading-relaxed
                      px-3 py-2 rounded-lg bg-[var(--color-bg)]" aria-live="polite">
          {note}
        </p>
      )}

      {waiting && (
        <div className="flex items-start gap-2 px-3 py-2 rounded-lg
                        bg-amber-500/10 text-amber-700 dark:text-amber-400">
          <Smartphone className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
          <p className="text-xs leading-relaxed">
            Waiting for the gateway (about {Math.round(status.login_seconds / 60)} min).
            <strong> If IBKR sends a two-factor prompt, approve it on your phone</strong> —
            the session will not come up otherwise. This panel updates itself.
          </p>
        </div>
      )}

      <div className="flex gap-2 flex-wrap">
        <button
          onClick={reconnect}
          disabled={busy !== null || connected}
          className="btn-secondary flex-1 min-w-[8rem]"
          title={connected ? 'Already connected' : 'Try a session now'}
        >
          {busy === 'reconnect' ? <LoadingSpinner size="sm" /> : <RefreshCw className="w-4 h-4" />}
          Reconnect
        </button>

        <button
          onClick={restart}
          disabled={busy !== null || !status.restart_available}
          className="btn-secondary flex-1 min-w-[8rem]"
          title={status.restart_unavailable_reason ?? 'Restart the gateway container'}
        >
          {busy === 'restart' ? <LoadingSpinner size="sm" /> : <RotateCcw className="w-4 h-4" />}
          Restart gateway
        </button>
      </div>

      {/* Say why the button is dead rather than leaving it mysteriously greyed. */}
      {!status.restart_available && status.restart_unavailable_reason && (
        <p className="text-[0.65rem] text-[var(--color-fg-muted)] leading-relaxed">
          {status.restart_unavailable_reason}{' '}
          See <code className="font-mono">runbooks/ib-gateway-offline.md</code>.
        </p>
      )}
    </div>
  )
}
