import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { KeyRound } from 'lucide-react'
import { AuthShell } from './AuthPage'
import LoadingSpinner from '../components/LoadingSpinner'
import { authApi } from '../lib/api'
import { useAuth } from '../lib/auth-context'

/**
 * Redeem a reset link.
 *
 * The token arrives in the query string, which is where a link can carry it
 * and nowhere better — it is single-use and expires in an hour precisely
 * because a URL ends up in history, in a mail archive, and occasionally in a
 * referrer header.
 *
 * On success the server returns a token, so the person who just proved they
 * control the mailbox lands signed in rather than on a form typing the
 * password they set ten seconds ago. Every other session for that account is
 * already dead, which is what makes this recovery rather than a second door
 * beside whoever locked them out.
 */
export default function ResetPasswordPage() {
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const navigate = useNavigate()
  const { login } = useAuth()

  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (password !== confirm) {
      setError('Those two passwords do not match.')
      return
    }
    setError(null)
    setBusy(true)
    try {
      const { data } = await authApi.resetPassword(token, password)
      await login(data.access_token)
      navigate('/', { replace: true })
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })
        ?.response?.data?.detail
      setError(
        typeof detail === 'string'
          ? detail
          : 'That reset link is no longer valid. Request a new one.',
      )
    } finally {
      setBusy(false)
    }
  }

  if (!token) {
    return (
      <AuthShell title="Something is missing" subtitle="That link has no token in it">
        <p className="text-sm leading-relaxed text-[var(--color-fg-muted)]">
          Reset links carry a one-time token. If yours was split across two
          lines by a mail client, copy the whole thing into the address bar —
          otherwise request a new one.
        </p>
        <Link to="/forgot-password" className="btn-primary mt-4">
          Request a new link
        </Link>
      </AuthShell>
    )
  }

  return (
    <AuthShell title="Set a new password" subtitle="This link works once">
      <form onSubmit={submit} className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <label htmlFor="reset-password" className="text-sm font-medium text-[var(--color-fg)]">
            New password
          </label>
          <input
            id="reset-password"
            type="password"
            className="input"
            autoComplete="new-password"
            minLength={12}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <p className="text-xs text-[var(--color-fg-muted)]">
            At least 12 characters.
          </p>
        </div>

        <div className="flex flex-col gap-1.5">
          <label htmlFor="reset-confirm" className="text-sm font-medium text-[var(--color-fg)]">
            Confirm
          </label>
          <input
            id="reset-confirm"
            type="password"
            className="input"
            autoComplete="new-password"
            minLength={12}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
          />
        </div>

        {error && (
          <p role="alert" className="text-xs text-[var(--accent-sell)]">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={busy || password.length < 12 || !confirm}
          className="btn-primary mt-1"
        >
          {busy ? <LoadingSpinner size="sm" /> : <KeyRound className="h-4 w-4" aria-hidden="true" />}
          {busy ? 'Setting…' : 'Set password and sign in'}
        </button>

        <Link
          to="/auth"
          className="self-center text-xs text-[var(--color-fg-muted)] hover:text-[var(--color-fg)]"
        >
          Back to sign in
        </Link>
      </form>
    </AuthShell>
  )
}
