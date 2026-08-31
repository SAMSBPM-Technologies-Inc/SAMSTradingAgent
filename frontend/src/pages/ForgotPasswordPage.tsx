import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Check, Mail } from 'lucide-react'
import { AuthShell } from './AuthPage'
import LoadingSpinner from '../components/LoadingSpinner'
import { authApi } from '../lib/api'

/**
 * Ask for a reset link.
 *
 * **The confirmation is unconditional, and that is the whole design.** The
 * server answers identically whether the address has an account, whether the
 * mail sent, and whether it was never real — there is no self-serve signup
 * here, so an address with an account is one the operator chose to let in, and
 * confirming which is worth having for anyone probing the system.
 *
 * So this screen must not help either. It shows the same panel on success as
 * it would for an unknown address, and the copy is written to be true in both
 * cases: "if that address has an account". Anything warmer — "check your
 * inbox", a different heading when it worked — would leak through the UI what
 * the API was careful not to leak.
 */
export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [sending, setSending] = useState(false)
  const [asked, setAsked] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSending(true)
    try {
      await authApi.forgotPassword(email)
      setAsked(true)
    } catch (err) {
      // Only genuine outages reach here — a deployment with no mail
      // configured, or a server that could not store the token. Neither
      // depends on the address, so reporting them leaks nothing.
      const detail = (err as { response?: { data?: { detail?: unknown } } })
        ?.response?.data?.detail
      setError(
        typeof detail === 'string'
          ? detail
          : 'Could not start a reset just now. Please try again shortly.',
      )
    } finally {
      setSending(false)
    }
  }

  if (asked) {
    return (
      <AuthShell title="Check your email" subtitle="If that address has an account">
        <div role="status" className="flex flex-col gap-3">
          <Check className="h-5 w-5 text-[var(--accent-buy)]" aria-hidden="true" />
          <p className="text-sm leading-relaxed text-[var(--color-fg)]">
            If <strong>{email}</strong> has an account, a link to set a new
            password is on its way. It works once and expires in an hour.
          </p>
          <p className="text-xs leading-relaxed text-[var(--color-fg-muted)]">
            Nothing has changed yet — your current password still works until
            you use the link.
          </p>
          <Link to="/auth" className="btn-secondary mt-1">
            Back to sign in
          </Link>
        </div>
      </AuthShell>
    )
  }

  return (
    <AuthShell title="Reset your password" subtitle="We will email you a one-time link">
      <form onSubmit={submit} className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <label htmlFor="forgot-email" className="text-sm font-medium text-[var(--color-fg)]">
            Email
          </label>
          <input
            id="forgot-email"
            type="email"
            className="input"
            placeholder="you@example.com"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            maxLength={254}
          />
        </div>

        {error && (
          <p role="alert" className="text-xs text-[var(--accent-sell)]">
            {error}
          </p>
        )}

        <button type="submit" disabled={sending || !email} className="btn-primary mt-1">
          {sending ? <LoadingSpinner size="sm" /> : <Mail className="h-4 w-4" aria-hidden="true" />}
          {sending ? 'Sending…' : 'Send reset link'}
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
