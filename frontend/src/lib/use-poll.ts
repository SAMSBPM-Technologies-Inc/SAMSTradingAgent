import { useEffect, useRef, useState } from 'react'

/**
 * Run `fn` every `intervalMs`, but only while the tab is actually being looked
 * at.
 *
 * The Trade screen fetched its watchlist, proposals and orders once on mount
 * and never again. Prices, verdicts and the approvals queue were therefore as
 * old as the tab: leave it open over lunch and come back to a BUY at a price
 * from an hour ago, with nothing on screen saying so. On a screen that routes
 * orders that is the wrong default.
 *
 * Gated on `visibilityState` for two reasons. A background tab polling every
 * minute spends broker round-trips and API quota on nobody, and — more usefully
 * — a tab that has been hidden for an hour refetches the moment it is revealed,
 * which is exactly when the stale data was about to be acted on.
 *
 * Deliberately not used for `/analyze`: on a cache miss that runs the whole
 * pipeline, including a paid model call. Freshness there is offered, not
 * imposed — see the age indicator on the ticker header.
 */
export function usePoll(fn: () => void, intervalMs: number, enabled = true) {
  const saved = useRef(fn)
  saved.current = fn

  useEffect(() => {
    if (!enabled) return

    let timer: ReturnType<typeof setInterval> | null = null

    const stop = () => {
      if (timer !== null) {
        clearInterval(timer)
        timer = null
      }
    }

    const start = () => {
      stop()
      timer = setInterval(() => saved.current(), intervalMs)
    }

    const onVisibility = () => {
      if (document.visibilityState === 'visible') {
        // Catch up first, then resume the cadence. Waiting a full interval
        // after returning to the tab is the one moment staleness matters most.
        saved.current()
        start()
      } else {
        stop()
      }
    }

    if (document.visibilityState === 'visible') start()
    document.addEventListener('visibilitychange', onVisibility)

    return () => {
      stop()
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [intervalMs, enabled])
}

/**
 * Re-render on an interval so relative timestamps stay honest.
 *
 * "scored 2m ago" was rendered once and then silently lied for as long as the
 * tab stayed open. Returns the current time in ms, so a component reading it
 * re-renders on every tick.
 */
export function useNow(ms = 30_000): number {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms)
    const onVisibility = () => {
      if (document.visibilityState === 'visible') setNow(Date.now())
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      clearInterval(id)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [ms])

  return now
}
