import { Check, ShieldAlert, X } from 'lucide-react'
import type { RiskAssessment, Signal, SignalGate } from '../types'

/**
 * Risk, and the gate it feeds.
 *
 * `risk` is a required field on every AnalyzeResponse and was rendered nowhere.
 * That matters more than a missing panel usually would: risk is half the BUY
 * rule, so a high-scoring name could be refused for reasons the UI never
 * showed. The gate rows exist to answer "why isn't this a BUY?" on the page
 * where the question gets asked.
 *
 * Thresholds come from the API, not from constants here — the dashboard's setup
 * legend hardcodes its own copies and will drift from `setup_scan.py`.
 */

const LEVEL_TONE: Record<RiskAssessment['risk_level'], { bar: string; text: string }> = {
  LOW:    { bar: 'var(--accent-buy)',  text: 'text-[var(--accent-buy)]' },
  MEDIUM: { bar: 'var(--accent-hold)', text: 'text-[var(--accent-hold)]' },
  HIGH:   { bar: 'var(--accent-sell)', text: 'text-[var(--accent-sell)]' },
}

function GateRow({ label, passed, detail }: { label: string; passed: boolean; detail: string }) {
  return (
    <div className="flex items-start gap-2">
      {passed
        ? <Check className="w-3.5 h-3.5 flex-shrink-0 mt-0.5 text-[var(--accent-buy)]" />
        : <X className="w-3.5 h-3.5 flex-shrink-0 mt-0.5 text-[var(--accent-sell)]" />}
      <div className="min-w-0">
        <span className="text-xs text-[var(--color-fg)]">{label}</span>
        <span className="text-xs text-[var(--color-fg-muted)] ml-1.5 tabular-nums">{detail}</span>
      </div>
    </div>
  )
}

export default function RiskPanel({
  risk,
  gate,
  signal,
  score,
}: {
  risk: RiskAssessment
  gate?: SignalGate | null
  signal: Signal
  score: number
}) {
  const tone = LEVEL_TONE[risk.risk_level] ?? LEVEL_TONE.MEDIUM
  const pct = Math.min(100, Math.max(0, (risk.risk_score / 10) * 100))

  return (
    <div className="flex flex-col gap-4">
      {/* Risk score */}
      <div className="flex flex-col gap-1.5">
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-xs text-[var(--color-fg-muted)]">Risk score</span>
          <span className="text-sm tabular-nums">
            <span className="font-semibold text-[var(--color-fg)]">
              {risk.risk_score.toFixed(1)}
            </span>
            <span className="text-[var(--color-fg-muted)]"> / 10</span>
            <span className={`ml-2 font-semibold ${tone.text}`}>{risk.risk_level}</span>
          </span>
        </div>
        <div className="relative h-2 rounded-full bg-[var(--color-border)] overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{ width: `${pct}%`, background: tone.bar }}
          />
          {/* The veto line, drawn where the engine actually puts it. */}
          {gate && (
            <div
              className="absolute top-0 bottom-0 w-px bg-[var(--color-fg)]"
              style={{ left: `${(gate.risk_max_for_buy / 10) * 100}%` }}
              title={`BUY vetoed at or above ${gate.risk_max_for_buy}`}
            />
          )}
        </div>
        {gate && (
          <span className="text-[0.65rem] text-[var(--color-fg-muted)]">
            The marker is {gate.risk_max_for_buy} — at or above it, BUY is vetoed
            regardless of score.
          </span>
        )}
      </div>

      <p className="text-xs text-[var(--color-fg-muted)] leading-relaxed">
        {risk.explanation}
      </p>

      {/* The gate */}
      {gate && (
        <div className="flex flex-col gap-2 pt-3 border-t border-[var(--color-border)]">
          <span className="text-[0.65rem] uppercase tracking-widest text-[var(--color-fg-muted)]">
            BUY gate
          </span>
          <GateRow
            label="Score above threshold"
            passed={gate.score_passes_buy}
            detail={`${score.toFixed(2)} vs ${gate.buy_threshold.toFixed(2)}`}
          />
          <GateRow
            label="Risk below veto"
            passed={gate.risk_passes_buy}
            detail={`${risk.risk_score.toFixed(1)} vs ${gate.risk_max_for_buy.toFixed(1)}`}
          />

          {/* The case the invisible risk score used to hide entirely. */}
          {gate.score_passes_buy && !gate.risk_passes_buy && signal !== 'BUY' && (
            <div className="flex items-start gap-2 mt-1 px-3 py-2 rounded-lg
                            bg-amber-500/10 text-amber-700 dark:text-amber-400">
              <ShieldAlert className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
              <p className="text-xs leading-relaxed">
                Scored high enough to buy, but the risk gate refused it. This is the
                gate doing its job, not a weak signal.
              </p>
            </div>
          )}

          <p className="text-[0.65rem] text-[var(--color-fg-muted)] leading-relaxed mt-1">
            Only BUY is risk-gated. Refusing to exit a position because conditions
            look dangerous would be backwards, so SELL below {gate.sell_threshold.toFixed(2)}
            {' '}is unconditional.
          </p>
        </div>
      )}
    </div>
  )
}
