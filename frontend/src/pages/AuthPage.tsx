import { useState, forwardRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Eye, EyeOff, LogIn } from 'lucide-react'
import { authApi } from '../lib/api'
import { useAuth } from '../lib/auth-context'
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
>(function PasswordField({ label, error, ...props }, ref) {
  const [show, setShow] = useState(false)
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-sm font-medium text-[var(--color-fg)]">{label}</label>
      <div className="relative">
        <input
          ref={ref}
          {...props}
          type={show ? 'text' : 'password'}
          className="input pr-12"
        />
        <button
          type="button"
          onClick={() => setShow((v) => !v)}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--color-fg-muted)]
                     hover:text-[var(--color-fg)] transition-colors"
          aria-label={show ? 'Hide password' : 'Show password'}
        >
          {show ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
        </button>
      </div>
      {error && <p className="text-xs text-red-500">{error}</p>}
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
        <label className="text-sm font-medium text-[var(--color-fg)]">Email</label>
        <input
          {...register('email')}
          type="email"
          placeholder="you@example.com"
          autoComplete="email"
          className="input"
        />
        {errors.email && <p className="text-xs text-red-500">{errors.email.message}</p>}
      </div>

      <PasswordField
        label="Password"
        placeholder="••••••••"
        autoComplete="current-password"
        error={errors.password?.message}
        {...register('password')}
      />

      {serverError && (
        <div className="px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-500 text-sm">
          {serverError}
        </div>
      )}

      <button type="submit" disabled={isSubmitting} className="btn-primary mt-2">
        {isSubmitting ? <LoadingSpinner size="sm" /> : <LogIn className="w-4 h-4" />}
        {isSubmitting ? 'Signing in…' : 'Sign In'}
      </button>
    </form>
  )
}

// ── Auth Page ─────────────────────────────────────────────────────────────────

export default function AuthPage() {
  const navigate = useNavigate()
  const onSuccess = () => navigate('/', { replace: true })

  return (
    <div className="min-h-dvh flex flex-col bg-[var(--color-bg)] transition-colors duration-200">
      {/* Top bar */}
      <div className="flex items-center justify-between px-4 h-14">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 flex items-center justify-center">
            <span className="text-white font-bold text-sm" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>S</span>
          </div>
          <span className="font-bold text-brand-500 tracking-tight" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
            SAMSBPM
          </span>
        </div>
        <ThemeToggle />
      </div>

      {/* Center card */}
      <div className="flex-1 flex items-center justify-center px-4 py-8">
        <div className="w-full max-w-sm">
          <div className="text-center mb-8">
            <h1
              className="text-3xl font-light text-[var(--color-fg)] mb-1"
              style={{ fontFamily: 'Fraunces, Georgia, serif' }}
            >
              Welcome back
            </h1>
            <p className="text-sm text-[var(--color-fg-muted)]">
              Sign in to your trading dashboard
            </p>
          </div>

          <div className="card p-6">
            <LoginForm onSuccess={onSuccess} />
          </div>
        </div>
      </div>
    </div>
  )
}
