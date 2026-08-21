import React, { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'
import { AlertCircle, CheckCircle2, Info, Undo2, X } from 'lucide-react'

/**
 * Toasts, with an undo affordance.
 *
 * Every result in this app used to be inline text cleared by a `setTimeout` —
 * which meant a Save confirmation on the Profile page appeared far below the
 * fold, and a destructive action had no way to offer a second thought. Both
 * problems are the same missing piece.
 *
 * Toasts are announced to screen readers via a polite live region: the app had
 * zero `aria-live` regions, so async outcomes were silent to anyone not
 * watching the pixels.
 */

type ToastKind = 'success' | 'error' | 'info'

interface ToastAction {
  label: string
  onAct: () => void
}

interface Toast {
  id: number
  kind: ToastKind
  message: string
  action?: ToastAction
}

interface ToastContextValue {
  toast: (message: string, kind?: ToastKind) => void
  /**
   * Show a toast with an undo button and defer `commit` until it expires.
   * `commit` runs exactly once — on timeout, or never if undone.
   */
  toastWithUndo: (message: string, commit: () => void, onUndo?: () => void) => void
  dismiss: (id: number) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

const DEFAULT_MS = 4000
//: Undo needs longer — the user has to notice it, read it, and decide.
const UNDO_MS = 7000

const ICONS: Record<ToastKind, React.FC<{ className?: string }>> = {
  success: CheckCircle2,
  error: AlertCircle,
  info: Info,
}

const TONES: Record<ToastKind, string> = {
  success: 'border-green-500/30 text-[var(--accent-buy)]',
  error: 'border-red-500/30 text-[var(--accent-sell)]',
  info: 'border-[var(--color-border)] text-[var(--color-fg-muted)]',
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const nextId = useRef(1)
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>())

  const clearTimer = useCallback((id: number) => {
    const t = timers.current.get(id)
    if (t) {
      clearTimeout(t)
      timers.current.delete(id)
    }
  }, [])

  const dismiss = useCallback((id: number) => {
    clearTimer(id)
    setToasts((list) => list.filter((t) => t.id !== id))
  }, [clearTimer])

  const push = useCallback((toast: Omit<Toast, 'id'>, ms: number, onExpire?: () => void) => {
    const id = nextId.current++
    setToasts((list) => [...list, { ...toast, id }])
    timers.current.set(id, setTimeout(() => {
      timers.current.delete(id)
      setToasts((list) => list.filter((t) => t.id !== id))
      onExpire?.()
    }, ms))
    return id
  }, [])

  const toast = useCallback((message: string, kind: ToastKind = 'info') => {
    push({ kind, message }, DEFAULT_MS)
  }, [push])

  const toastWithUndo = useCallback((
    message: string,
    commit: () => void,
    onUndo?: () => void,
  ) => {
    // `committed` guards the race between the timeout firing and the user
    // clicking Undo — without it a click landing on the same tick as expiry
    // would both commit and undo.
    let committed = false
    const id = push(
      {
        kind: 'info',
        message,
        action: {
          label: 'Undo',
          onAct: () => {
            if (committed) return
            committed = true
            dismiss(id)
            onUndo?.()
          },
        },
      },
      UNDO_MS,
      () => {
        if (committed) return
        committed = true
        commit()
      },
    )
  }, [push, dismiss])

  const value = useMemo(
    () => ({ toast, toastWithUndo, dismiss }),
    [toast, toastWithUndo, dismiss],
  )

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        className="fixed z-50 bottom-20 md:bottom-6 left-1/2 -translate-x-1/2
                   flex flex-col gap-2 w-[min(24rem,calc(100vw-2rem))]"
        role="status"
        aria-live="polite"
      >
        {toasts.map((t) => {
          const Icon = ICONS[t.kind]
          return (
            <div
              key={t.id}
              className={`flex items-center gap-3 px-4 py-3 rounded-xl border
                          bg-[var(--color-surface)] shadow-lg ${TONES[t.kind]}`}
              style={{ boxShadow: '0 6px 20px rgba(0,0,0,0.12)' }}
            >
              <Icon className="w-4 h-4 flex-shrink-0" />
              <span className="text-sm text-[var(--color-fg)] flex-1 min-w-0">
                {t.message}
              </span>
              {t.action && (
                <button
                  onClick={t.action.onAct}
                  className="flex items-center gap-1 text-xs font-semibold text-brand-500
                             hover:underline flex-shrink-0"
                >
                  <Undo2 className="w-3 h-3" />
                  {t.action.label}
                </button>
              )}
              <button
                onClick={() => dismiss(t.id)}
                aria-label="Dismiss notification"
                className="text-[var(--color-fg-muted)] hover:text-[var(--color-fg)] flex-shrink-0"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within ToastProvider')
  return ctx
}
