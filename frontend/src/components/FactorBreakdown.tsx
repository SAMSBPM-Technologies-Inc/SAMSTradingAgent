import { Info } from 'lucide-react'
import type { ScoreBreakdown, SignalInputs } from '../types'

/**
 * Where the composite score came from, factor by factor.
 *
 * The six sub-scores have always been computed and stored, and nothing ever
 * showed them: the product displayed a 0–100 number with no attribution while
 * offering sliders to reweight it. Two bars per row answer the two questions
 * that number raises — how did this factor score, and how much did it matter?
 *
 * Contribution is the honest measure of "mattered": a factor can score 0.9 and
 * contribute nothing if its weight is zero, which is exactly the case for
 * Volatility under default settings.
 */

function pct(value: number): string {
  return `${Math.round(value * 100)}`
}

/** Sub-score colouring matches the gauge on the page: green good, red weak. */
function scoreTone(score: number): string {
  if (score >= 0.7) return 'var(--accent-buy)'
  if (score >= 0.4) return '#f97316'
  return 'var(--accent-sell)'
}

function FactorRow({
  label,
  score,
  weight,
  contribution,
  maxContribution,
  modifier = false,
}: {
  label: string
  score: number
  weight: number
  contribution: number
  maxContribution: number
  modifier?: boolean
}) {
  const inactive = weight === 0
  // Bars are scaled against the largest contribution rather than against 1.0,
  // otherwise every row renders as a barely-visible sliver.
  const contribWidth = maxContribution > 0
    ? Math.min(100, (Math.abs(contribution) / maxContribution) * 100)
    : 0

  return (
    <div className={`grid grid-cols-[7.5rem_1fr_auto] items-center gap-3 py-2
                     border-b border-[var(--color-border)] last:border-b-0
                     ${inactive ? 'opacity-45' : ''}`}>
      <div className="min-w-0">
        <span className="text-xs font-medium text-[var(--color-fg)] truncate block">
          {label}
        </span>
        <span className="text-[0.65rem] text-[var(--color-fg-muted)] tabular-nums">
          {inactive ? 'weight 0 — excluded' : `weight ${pct(weight)}%`}
        </span>
      </div>

      <div className="flex flex-col gap-1 min-w-0">
        {/* Sub-score: how this factor rated, independent of how much it counts. */}
        <div className="flex items-center gap-2">
          <div className="flex-1 h-1.5 rounded-full bg-[var(--color-border)] overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{ width: `${score * 100}%`, background: scoreTone(score) }}
            />
          </div>
          <span className="text-[0.65rem] tabular-nums text-[var(--color-fg-muted)] w-7 text-right">
            {pct(score)}
          </span>
        </div>

        {/* Contribution: how many points of the composite this actually supplied. */}
        <div className="flex items-center gap-2">
          <div className="flex-1 h-1 rounded-full bg-[var(--color-border)]/60 overflow-hidden
                          flex justify-start">
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width: `${contribWidth}%`,
                background: modifier && contribution < 0
                  ? 'var(--accent-sell)'
                  : 'var(--color-fg-muted)',
              }}
            />
          </div>
          <span className="text-[0.65rem] tabular-nums text-[var(--color-fg-muted)] w-7 text-right">
            &nbsp;
          </span>
        </div>
      </div>

      <span className="text-xs tabular-nums font-medium text-[var(--color-fg)] w-14 text-right">
        {modifier && contribution >= 0 ? '+' : ''}
        {contribution.toFixed(3)}
      </span>
    </div>
  )
}

/**
 * How much of this score was measured, stated above the factors themselves.
 *
 * A 0.50 sub-score in the table below is ambiguous in a way nothing on this
 * panel could previously resolve: it means either "measured, and genuinely
 * neutral" or "we never found out". Those are not the same fact, and one of
 * them should make a reader trust the composite less.
 *
 * Renders nothing at full completeness — a banner that is always present stops
 * being read, and "everything arrived" is the expected case.
 */
function InputCompleteness({ inputs }: { inputs: SignalInputs }) {
  if (inputs.completeness == null || inputs.completeness >= 0.999) return null

  const measured = Math.round(inputs.completeness * 100)
  const named = inputs.fallback_factors
  return (
    <div
      className="flex items-start gap-2 rounded-md border border-[var(--color-border)]
                 bg-[var(--color-hover)] px-2.5 py-2 text-[0.7rem] leading-relaxed
                 text-[var(--color-fg-muted)]"
    >
      <Info className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
      <p>
        <strong className="text-[var(--color-fg)]">{measured}% of this score
        came from measured data.</strong>{' '}
        {named.length > 0 ? (
          <>
            {named.join(' and ')} {named.length === 1 ? 'was' : 'were'} unavailable,
            so {named.length === 1 ? 'it sits' : 'they sit'} at a neutral 0.50 and
            {named.length === 1 ? ' says' : ' say'} nothing about this company.
          </>
        ) : (
          <>Some factors were built from partial data and are blended toward neutral.</>
        )}
      </p>
    </div>
  )
}

export default function FactorBreakdown({
  breakdown,
  inputs,
}: {
  breakdown: ScoreBreakdown
  inputs?: SignalInputs | null
}) {
  // The ML path did not compute this score from these weights. Showing a
  // weighted decomposition next to it would be a fabrication, so say so.
  if (!breakdown.attributable) {
    return (
      <div className="flex items-start gap-2 text-xs text-[var(--color-fg-muted)]">
        <Info className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
        <p>
          This score came from the <strong>{breakdown.method}</strong> model, not the
          weighted composite. A factor breakdown would not describe how it was
          produced, so none is shown.
        </p>
      </div>
    )
  }

  const alt = breakdown.alternative_data
  const maxContribution = Math.max(
    ...breakdown.factors.map((f) => Math.abs(f.contribution)),
    alt ? Math.abs(alt.contribution) : 0,
  )

  return (
    <div className="flex flex-col gap-3">
      {inputs && <InputCompleteness inputs={inputs} />}
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[0.65rem] uppercase tracking-widest text-[var(--color-fg-muted)]">
          Factor · sub-score / contribution
        </span>
        {breakdown.personalized && (
          <span className="text-[0.65rem] text-brand-500">Your weights</span>
        )}
      </div>

      <div>
        {breakdown.factors.map((f) => (
          <FactorRow
            key={f.key}
            label={f.label}
            score={f.score}
            weight={f.weight}
            contribution={f.contribution}
            maxContribution={maxContribution}
          />
        ))}
      </div>

      {/* Totals — the arithmetic has to be checkable, or the panel is decoration. */}
      <div className="flex flex-col gap-1 pt-2 border-t border-[var(--color-border)] text-xs">
        <div className="flex justify-between">
          <span className="text-[var(--color-fg-muted)]">Weighted base</span>
          <span className="tabular-nums text-[var(--color-fg)]">
            {breakdown.base_total.toFixed(3)}
          </span>
        </div>
        {alt && (
          <div className="flex justify-between">
            <span className="text-[var(--color-fg-muted)]">
              {alt.label} modifier
              <span className="ml-1 text-[0.65rem]">
                ({pct(alt.score)} vs 50 neutral, weight {pct(alt.weight)}%)
              </span>
            </span>
            <span className={`tabular-nums ${
              alt.contribution > 0 ? 'text-[var(--accent-buy)]'
              : alt.contribution < 0 ? 'text-[var(--accent-sell)]'
              : 'text-[var(--color-fg)]'
            }`}>
              {alt.contribution >= 0 ? '+' : ''}{alt.contribution.toFixed(3)}
            </span>
          </div>
        )}
        <div className="flex justify-between pt-1 border-t border-[var(--color-border)] font-semibold">
          <span className="text-[var(--color-fg)]">Composite</span>
          <span className="tabular-nums text-[var(--color-fg)]">
            {breakdown.composite.toFixed(3)}
            <span className="ml-1.5 text-[var(--color-fg-muted)] font-normal">
              = {pct(breakdown.composite)}/100
            </span>
          </span>
        </div>
      </div>

      <p className="text-[0.65rem] text-[var(--color-fg-muted)] leading-relaxed">
        The top bar is how the factor scored; the thin bar beneath is how many points
        of the composite it supplied. A factor with weight 0 is excluded from the
        score no matter how it rates — Volatility is priced at the risk gate instead.
        Weights are editable in <span className="text-[var(--color-fg)]">Profile → Signal Weights</span>.
      </p>
    </div>
  )
}
