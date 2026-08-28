import { useEffect, useState } from 'react'

/**
 * What a fresh analysis is doing, while it does it.
 *
 * A bare spinner on a call that can run for several seconds spends the reader's
 * attention and gives nothing back. This lists the work instead.
 *
 * **It does not claim to know which step is running.** `/analyze` is a single
 * synchronous request that reports nothing until it returns, so a stepper
 * ticking through these in order would be animation, not information — and it
 * would be wrong in the common case, where a recent analysis is served from
 * cache and none of this runs at all. Every stage is shown at once, dimmed and
 * pulsing together, with an elapsed counter that is the one genuinely live
 * number on the screen.
 *
 * Every row is a stage `run_pipeline` actually performs. The deep-research
 * agents — the orchestrator and the risk agent — are deliberately absent: they
 * belong to `/research/{ticker}`, which this path never calls, and listing them
 * would credit the system with work it did not do.
 *
 * The analyst's model is not named. It is `ANALYST_MODEL` in config and reaches
 * the UI through `AnalyzeResponse.analyst_model` — which does not exist yet at
 * this point in the request, and restating it here is exactly the drift that
 * rule exists to prevent.
 */

const STAGES: { label: string; source?: string }[] = [
  { label: 'Prices and volume', source: 'Yahoo' },
  { label: 'Headlines and sentiment', source: 'Finnhub · VADER' },
  { label: 'Fundamentals', source: 'Massive · Alpha Vantage' },
  { label: 'Macro backdrop', source: 'FRED' },
  { label: 'Options flow, short interest, insiders' },
  { label: 'Technical indicators', source: 'RSI · MACD · Bollinger · ATR · OBV' },
  { label: 'Weighted scoring', source: 'six factors' },
  { label: 'AI analyst', source: 'when the verdict is close enough to matter' },
]

export default function AnalysisProgress({ ticker }: { ticker: string }) {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    setElapsed(0)
    const started = Date.now()
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000)
    return () => clearInterval(id)
  }, [ticker])

  return (
    <div className="mx-auto w-full max-w-[440px] px-6 py-14">
      <div className="mb-5 flex items-baseline justify-between gap-3">
        <h2
          className="text-[15px] text-[var(--color-fg)]"
          style={{ fontFamily: 'Fraunces, Georgia, serif' }}
        >
          Analysing <span className="num font-semibold">{ticker}</span>
        </h2>
        {/* The counter is the only thing here that reflects live state, so it
            is the only thing allowed to look like it does. Kept out of the
            live region: announcing a new number every second is unusable. */}
        <span className="num text-xs text-[var(--color-fg-muted)]" aria-live="off">
          {elapsed}s
        </span>
      </div>

      <ul className="flex flex-col gap-0">
        {STAGES.map((s, i) => (
          <li
            key={s.label}
            className="flex items-baseline gap-2.5 border-b border-[var(--color-border)]/60
                       py-2 last:border-b-0"
          >
            <span
              className="mt-[1px] h-1.5 w-1.5 flex-shrink-0 animate-pulse rounded-full
                         bg-[var(--color-fg-muted)]"
              // Staggered so the column reads as work in flight rather than
              // eight lamps blinking in unison.
              style={{ animationDelay: `${i * 140}ms` }}
              aria-hidden="true"
            />
            <span className="min-w-0 flex-1 text-[13px] text-[var(--color-fg-muted)]">
              {s.label}
              {s.source && (
                <span className="ml-1.5 text-[11px] text-[var(--color-fg-muted)]/70">
                  {s.source}
                </span>
              )}
            </span>
          </li>
        ))}
      </ul>

      <p className="mt-4 text-[11px] leading-relaxed text-[var(--color-fg-muted)]">
        These are the steps a fresh analysis runs, not a live trace — a recent
        result is served from cache and returns straight away.
      </p>
    </div>
  )
}
