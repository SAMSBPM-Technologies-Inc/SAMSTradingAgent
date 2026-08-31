import { useState, forwardRef } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Eye, EyeOff, LogIn } from 'lucide-react'
import { authApi } from '../lib/api'
import { useAuth } from '../lib/auth-context'
import { LogoLockup } from '../components/Logo'
import ThemeToggle from '../components/ThemeToggle'
import LoadingSpinner from '../components/LoadingSpinner'

// ── Schema ────────────────────────────────────────────────────────────────────

const loginSchema = z.object({
  email: z.string().email('Enter a valid email'),
  password: z.string().min(6, 'Password must be at least 6 characters'),
})

type LoginFormData = z.infer<typeof loginSchema>

// ── Password field ────────────────────────────────────────────────────────────

const PasswordField = forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string }
>(function PasswordField({ label, error, id, ...props }, ref) {
  const [show, setShow] = useState(false)
  // Derived from the label when no id is supplied, so the binding cannot be
  // forgotten at a call site.
  const fieldId = id ?? `field-${label.toLowerCase().replace(/\s+/g, '-')}`
  const errorId = `${fieldId}-error`

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={fieldId} className="text-sm font-medium text-[var(--color-fg)]">
        {label}
      </label>
      <div className="relative">
        <input
          ref={ref}
          {...props}
          id={fieldId}
          type={show ? 'text' : 'password'}
          className="input pr-12"
          aria-invalid={!!error}
          aria-describedby={error ? errorId : undefined}
        />
        <button
          type="button"
          onClick={() => setShow((v) => !v)}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--color-fg-muted)]
                     hover:text-[var(--color-fg)] transition-colors"
          aria-label={show ? 'Hide password' : 'Show password'}
          aria-pressed={show}
        >
          {show ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
        </button>
      </div>
      {error && (
        <p id={errorId} role="alert" className="text-xs text-red-500">{error}</p>
      )}
    </div>
  )
})

// ── Login form ────────────────────────────────────────────────────────────────

function LoginForm({ onSuccess }: { onSuccess: () => void }) {
  const { login } = useAuth()
  const [serverError, setServerError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormData>({ resolver: zodResolver(loginSchema) })

  const onSubmit = async (data: LoginFormData) => {
    setServerError(null)
    try {
      const res = await authApi.loginJson(data.email, data.password)
      await login(res.data.access_token)
      onSuccess()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setServerError(msg ?? 'Login failed. Please check your credentials.')
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <label htmlFor="login-email" className="text-sm font-medium text-[var(--color-fg)]">
          Email
        </label>
        <input
          {...register('email')}
          id="login-email"
          type="email"
          placeholder="you@example.com"
          autoComplete="email"
          className="input"
          aria-invalid={!!errors.email}
          aria-describedby={errors.email ? 'login-email-error' : undefined}
        />
        {/* Announced, not just shown — a validation message that only exists
            visually is invisible to a screen reader. */}
        {errors.email && (
          <p id="login-email-error" role="alert" className="text-xs text-red-500">
            {errors.email.message}
          </p>
        )}
      </div>

      <PasswordField
        label="Password"
        placeholder="••••••••"
        autoComplete="current-password"
        error={errors.password?.message}
        {...register('password')}
      />

      {serverError && (
        <div role="alert" className="px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-500 text-sm">
          {serverError}
        </div>
      )}

      <button type="submit" disabled={isSubmitting} className="btn-primary mt-2">
        {isSubmitting ? <LoadingSpinner size="sm" /> : <LogIn className="w-4 h-4" />}
        {isSubmitting ? 'Signing in…' : 'Sign In'}
      </button>

      {/* Two ways to be stuck at this screen, and both need a route out.
          There is no sign-up form — accounts are provisioned by hand — so
          somebody who arrives here without one has to be pointed at the
          contact form rather than left staring at a password box. */}
      <div className="flex flex-col items-center gap-2">
        <Link
          to="/forgot-password"
          className="text-xs text-[var(--color-fg-muted)] hover:text-[var(--color-fg)]"
        >
          Forgot your password?
        </Link>
        <p className="text-xs text-[var(--color-fg-muted)]">
          No account?{' '}
          <Link
            to="/home#contact"
            className="text-brand-500 underline-offset-4 hover:underline"
          >
            Request access
          </Link>
        </p>
      </div>
    </form>
  )
}

// ── Auth Page ─────────────────────────────────────────────────────────────────

/**
 * The chrome every signed-out screen shares.
 *
 * Exported so the password-recovery pages use *this* rather than drawing their
 * own approximation of it. That is not hypothetical tidiness — this page drew
 * its own gradient "S" and orange wordmark for long enough that signing in
 * looked like a different product from the app behind it, which is what the
 * comment below still records.
 */
export function AuthShell({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle: string
  children: React.ReactNode
}) {
  return (
    <div className="relative min-h-dvh flex flex-col overflow-hidden bg-[var(--color-bg)] transition-colors duration-200">
      {/* Ground for the page. Purely decorative and behind everything — see
          .auth-field in index.css for why it is drawn rather than photographed. */}
      <div className="auth-field" aria-hidden="true" />
      {/* Top bar. The shared lockup, not a local approximation of it — this
          page drew its own gradient "S" and orange wordmark for long enough
          that signing in looked like a different product from the app behind
          it. */}
      <div className="relative flex items-center justify-between px-4 h-14">
        <Link to="/" className="rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500/50">
          <LogoLockup />
        </Link>
        <ThemeToggle />
      </div>

      {/* Center card */}
      <div className="relative flex-1 flex items-center justify-center px-4 py-8">
        <div className="w-full max-w-sm">
          <div className="text-center mb-8">
            <h1
              className="text-3xl font-light text-[var(--color-fg)] mb-1"
              style={{ fontFamily: 'Fraunces, Georgia, serif' }}
            >
              {title}
            </h1>
            <p className="text-sm text-[var(--color-fg-muted)]">{subtitle}</p>
          </div>

          <div className="card p-6">{children}</div>
        </div>
      </div>
    </div>
  )
}

export default function AuthPage() {
  const navigate = useNavigate()
  const onSuccess = () => navigate('/', { replace: true })

  return (
    <AuthShell title="Welcome back" subtitle="Sign in to your trading dashboard">
      <LoginForm onSuccess={onSuccess} />
    </AuthShell>
  )
}
