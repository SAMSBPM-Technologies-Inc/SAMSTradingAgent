import React, { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'
import { AccessibilityInfo, Animated, Pressable, Text, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'

/**
 * Toasts for the mobile app, mirroring the web `toast-context`.
 *
 * Order outcomes need somewhere to land that is not an inline string cleared by
 * a `setTimeout` — on a phone the button you pressed is often already scrolled
 * away by the time the answer arrives.
 *
 * Announced via `AccessibilityInfo` so VoiceOver and TalkBack speak the result;
 * a visual-only confirmation of a placed order is not good enough.
 */

type ToastKind = 'success' | 'error' | 'info'

interface Toast {
  id: number
  kind: ToastKind
  message: string
  action?: { label: string; onAct: () => void }
}

interface ToastContextValue {
  toast: (message: string, kind?: ToastKind) => void
  /**
   * Show a toast with an undo button and defer `commit` until it expires.
   * `commit` runs exactly once — on timeout, or never if undone.
   */
  toastWithUndo: (message: string, commit: () => void, onUndo?: () => void) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

const DEFAULT_MS = 4000
/** Undo needs longer — the user has to notice it, read it, and decide. */
const UNDO_MS = 7000

const TONE: Record<ToastKind, { bg: string; fg: string }> = {
  success: { bg: '#0f2f1c', fg: '#4ade80' },
  error: { bg: '#2f1414', fg: '#f87171' },
  info: { bg: '#1c1a16', fg: '#e7e2d8' },
}

function ToastRow({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  const opacity = useRef(new Animated.Value(0)).current

  React.useEffect(() => {
    Animated.timing(opacity, {
      toValue: 1, duration: 160, useNativeDriver: true,
    }).start()
  }, [opacity])

  const tone = TONE[toast.kind]

  return (
    <Animated.View
      style={{
        opacity,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        backgroundColor: tone.bg,
        borderRadius: 12,
        paddingHorizontal: 14,
        paddingVertical: 12,
        shadowColor: '#000',
        shadowOpacity: 0.25,
        shadowRadius: 12,
        shadowOffset: { width: 0, height: 4 },
        elevation: 6,
      }}
    >
      <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: tone.fg }} />
      <Text style={{ flex: 1, color: '#f0ece4', fontSize: 13 }}>{toast.message}</Text>
      {toast.action && (
        <Pressable
          onPress={toast.action.onAct}
          accessibilityRole="button"
          hitSlop={8}
        >
          <Text style={{ color: '#f2600c', fontSize: 13, fontWeight: '700' }}>
            {toast.action.label}
          </Text>
        </Pressable>
      )}
      <Pressable onPress={onDismiss} accessibilityLabel="Dismiss" hitSlop={8}>
        <Text style={{ color: '#9a8f82', fontSize: 16 }}>×</Text>
      </Pressable>
    </Animated.View>
  )
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const nextId = useRef(1)
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>())
  const insets = useSafeAreaInsets()

  const dismiss = useCallback((id: number) => {
    const t = timers.current.get(id)
    if (t) {
      clearTimeout(t)
      timers.current.delete(id)
    }
    setToasts((list) => list.filter((x) => x.id !== id))
  }, [])

  const push = useCallback((
    toast: Omit<Toast, 'id'>,
    ms: number,
    onExpire?: () => void,
  ) => {
    const id = nextId.current++
    setToasts((list) => [...list, { ...toast, id }])
    AccessibilityInfo.announceForAccessibility?.(toast.message)
    timers.current.set(id, setTimeout(() => {
      timers.current.delete(id)
      setToasts((list) => list.filter((x) => x.id !== id))
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
    // tapping Undo — without it a tap landing on the same tick as expiry would
    // both commit and undo.
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

  const value = useMemo(() => ({ toast, toastWithUndo }), [toast, toastWithUndo])

  return (
    <ToastContext.Provider value={value}>
      {children}
      {toasts.length > 0 && (
        <View
          pointerEvents="box-none"
          style={{
            position: 'absolute',
            left: 16,
            right: 16,
            // Clears the tab bar, which is 60pt plus the home indicator.
            bottom: insets.bottom + 72,
            gap: 8,
          }}
        >
          {toasts.map((t) => (
            <ToastRow key={t.id} toast={t} onDismiss={() => dismiss(t.id)} />
          ))}
        </View>
      )}
    </ToastContext.Provider>
  )
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within ToastProvider')
  return ctx
}
