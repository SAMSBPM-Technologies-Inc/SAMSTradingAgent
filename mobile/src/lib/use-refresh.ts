import { useCallback, useEffect, useRef, useState } from 'react'
import { AppState, type AppStateStatus } from 'react-native'
import { useFocusEffect } from 'expo-router'

/**
 * Keep a screen's data current while it is actually in front of someone.
 *
 * The mobile client fetched everything once on mount and never again. On a
 * phone that is worse than it sounds: an app is backgrounded rather than
 * closed, so the screen you return to two hours later is showing prices from
 * two hours ago, with a Buy button under them. The web client had the same
 * defect and this is the same fix, translated — `visibilitychange` becomes
 * `AppState`, and a tab being hidden becomes a screen losing focus.
 *
 * Three triggers, all of them the same moment in different clothes: the screen
 * gains focus, the app returns to the foreground, or the interval elapses while
 * both are true. The first two refetch immediately, because returning to a
 * screen is exactly when stale data is about to be acted on.
 *
 * Not used for `/analyze`: on a cache miss that runs the whole pipeline
 * including a paid model call. Freshness there is offered, not imposed.
 */
export function useRefreshOnFocus(fn: () => void, intervalMs = 60_000) {
  const saved = useRef(fn)
  saved.current = fn

  const focused = useRef(false)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)

  const stop = useCallback(() => {
    if (timer.current !== null) {
      clearInterval(timer.current)
      timer.current = null
    }
  }, [])

  const start = useCallback(() => {
    stop()
    timer.current = setInterval(() => {
      if (focused.current && AppState.currentState === 'active') saved.current()
    }, intervalMs)
  }, [intervalMs, stop])

  // Screen focus. Runs on every navigation back to this tab, not just on mount.
  useFocusEffect(
    useCallback(() => {
      focused.current = true
      saved.current()
      start()
      return () => {
        focused.current = false
        stop()
      }
    }, [start, stop]),
  )

  // App foreground/background, which focus alone does not see: a screen keeps
  // its focus while the whole app is in the background.
  useEffect(() => {
    const onChange = (state: AppStateStatus) => {
      if (state === 'active') {
        if (focused.current) {
          saved.current()
          start()
        }
      } else {
        stop()
      }
    }
    const sub = AppState.addEventListener('change', onChange)
    return () => sub.remove()
  }, [start, stop])
}

/**
 * A clock that ticks so relative timestamps stay honest.
 *
 * "scored 2m ago" rendered once and then stood still for as long as the screen
 * was mounted — which on a phone can be days.
 */
export function useNow(ms = 30_000): number {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms)
    const sub = AppState.addEventListener('change', (s) => {
      if (s === 'active') setNow(Date.now())
    })
    return () => {
      clearInterval(id)
      sub.remove()
    }
  }, [ms])

  return now
}
