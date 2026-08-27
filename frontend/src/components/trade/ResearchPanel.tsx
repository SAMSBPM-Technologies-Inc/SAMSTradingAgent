import { useCallback, useEffect, useState } from 'react'
import { AlertCircle, ExternalLink, Loader2, RefreshCw } from 'lucide-react'

import { researchApi } from '../../lib/api'
import type { DimensionScore, EvidenceItem, ResearchDossier } from '../../types'

/**
 * Deep research dossier.
 *
 * Two things about this panel differ from everything else on the page, and both
 * are deliberate.
 *
 * It never loads itself beyond a cached read. Building a dossier is five model
 * calls and tens of seconds, so the button is the only thing that starts one —
 * a component that refreshed on mount would spend real money on every navigation.
 *
 * And every claim it renders carries a citation, because anything that did not
 * was deleted server-side before storage. The evidence list is the other half of
 * that: a reader who wants to check a number can find where it came from rather
 * than taking the sentence on trust.
 */

const ASSESSMENT_TONE: Record<string, { bg: string; fg: string }> = {
  BULLISH: { bg: 'var(--tint-buy)', fg: 'var(--accent-buy)' },
  NEUTRAL: { bg: 'var(--tint-hold)', fg: 'var(--accent-hold)' },
  BEARISH: { bg: 'var(--tint-sell)', fg: 'var(--accent-sell)' },
}

export function ResearchPanel({ ticker }: { ticker: string }) {
  const [dossier, setDossier] = useState<ResearchDossier | null>(null)
  const [loading, setLoading] = useState(true)
  const [building, setBuilding] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const { data } = await researchApi.get(ticker)
      setDossier(data)
    } catch {
      // A 404 is the ordinary state for a ticker nobody has researched yet,
      // not a failure worth showing an error for.
      setDossier(null)
    } finally {
      setLoading(false)
    }
  }, [ticker])

  useEffect(() => {
    void load()
  }, [load])

  const build = useCallback(async () => {
    setBuilding(true)
    setError(null)
    try {
      const { data } = await researchApi.build(ticker)
      setDossier(data)
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Research failed. Check the server logs.')
    } finally {
      setBuilding(false)
    }
  }, [ticker])

  if (loading) {
    return (
      <p className="text-[11.5px] text-[var(--color-fg-muted)]">Loading research…</p>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        {dossier ? <DossierHeader dossier={dossier} /> : (
          <p className="text-[11.5px] text-[var(--color-fg-muted)]">
            No dossier yet for {ticker}.
          </p>
        )}
        <button
          onClick={build}
          disabled={building}
          className="ml-auto flex items-center gap-1.5 rounded border border-[var(--color-border)] px-2.5 py-1 text-[11px] font-medium text-[var(--color-fg)] transition-colors hover:bg-[var(--color-hover)] disabled:opacity-60"
        >
          {building
            ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
            : <RefreshCw className="h-3 w-3" aria-hidden="true" />}
          {building ? 'Researching…' : dossier ? 'Re-run research' : 'Run deep research'}
        </button>
      </div>

      {building && (
        <p className="text-[11px] text-[var(--color-fg-muted)]">
          Four analysts are working this name in parallel, then a fifth merges them.
          This takes a minute or two.
        </p>
      )}

      {error && (
        <p className="flex items-start gap-2 text-[11px] leading-relaxed text-[var(--accent-sell)]">
          <AlertCircle className="mt-0.5 h-3 w-3 flex-shrink-0" aria-hidden="true" />
          <span>{error}</span>
        </p>
      )}

      {dossier && <DossierBody dossier={dossier} />}
    </div>
  )
}

function DossierHeader({ dossier }: { dossier: ResearchDossier }) {
  const assessment = dossier.report?.assessment
  const tone = ASSESSMENT_TONE[assessment ?? 'NEUTRAL'] ?? ASSESSMENT_TONE.NEUTRAL
  return (
    <>
      {assessment && (
        <span
          className="rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
          style={{ background: tone.bg, color: tone.fg }}
        >
          {assessment}
        </span>
      )}
      {dossier.conviction != null && (
        <span className="text-[12px] font-medium text-[var(--color-fg)]">
          Conviction {Math.round(dossier.conviction)}/100
        </span>
      )}
      <span className="text-[11px] text-[var(--color-fg-muted)]">
        {formatAge(dossier)}
      </span>
      {dossier.stale && (
        <span
          className="rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide"
          style={{ background: 'var(--tint-hold)', color: 'var(--accent-hold)' }}
        >
          Stale
        </span>
      )}
    </>
  )
}

function DossierBody({ dossier }: { dossier: ResearchDossier }) {
  const report = dossier.report
  return (
    <div className="flex flex-col gap-4">
      <Dimensions scores={dossier.dimensions} />

      {dossier.agents_failed.length > 0 && (
        <Callout>
          {dossier.agents_failed.join(', ')} did not report — the call failed.
          This dossier is missing that perspective, so read it as incomplete
          rather than as a verdict that considered everything.
        </Callout>
      )}

      {/* Deliberately a different message from a failure. Nothing broke here:
          there was no data in that area to assess, which is a fact about the
          collection rather than a fault — and it means those questions are
          unanswered, not answered neutrally. */}
      {dossier.agents_skipped.length > 0 && (
        <Callout>
          No {dossier.agents_skipped.join(', ')} analysis was run — nothing has
          been collected in {dossier.agents_skipped.length > 1 ? 'those areas' : 'that area'} for
          this ticker yet. Treat the questions it would have answered as open,
          not as neutral.
        </Callout>
      )}

      {!report && (
        <Callout>
          {dossier.synthesis_error
            ? <>The scored dimensions and evidence below were computed, but the
                merge step failed ({dossier.synthesis_error}). The numbers
                still stand on their own.</>
            : <>The scored dimensions and evidence below were computed, but no
                specialist produced anything to merge. The numbers still stand
                on their own.</>}
        </Callout>
      )}

      {report && (
        <>
          <Prose label="Thesis" text={report.thesis} emphasis />
          <div className="grid gap-4 sm:grid-cols-2">
            <Prose label="Bull case" text={report.bull_case} tone="buy" />
            <Prose label="Bear case" text={report.bear_case} tone="sell" />
          </div>
          <Prose
            label="What the market may be missing"
            text={report.what_the_market_is_missing}
          />

          <div className="grid gap-4 sm:grid-cols-2">
            <Bullets label="Key catalysts" items={report.key_catalysts} />
            <Bullets label="Key risks" items={report.key_risks} tone="sell" />
          </div>

          <Bullets
            label="What would change this view"
            items={report.what_would_change_my_opinion}
            hint="Each of these is meant to be checkable — a figure crossing a level, a dated report."
          />

          {report.risks_addressed.length > 0 && (
            <Bullets
              label="Risks raised and answered"
              items={report.risks_addressed}
              hint="The risk analyst raised these; the synthesis judged the evidence answers them. Shown so a dismissed risk is visible as a decision rather than a gap."
            />
          )}

          {report.conclusion && (
            <div>
              <div className="label-micro">Conclusion</div>
              <p className="mt-1 text-[12.5px] leading-relaxed text-[var(--color-fg)]">
                {report.conclusion}
              </p>
            </div>
          )}

          <ConvictionNote dossier={dossier} />
        </>
      )}

      {dossier.data_gaps.length > 0 && (
        <Bullets
          label="What could not be assessed"
          items={dossier.data_gaps}
          hint="Named by the analysts themselves. A question this dossier does not answer is not a question with a neutral answer."
        />
      )}

      <Evidence items={dossier.evidence} />
    </div>
  )
}

/**
 * The six dimension bars.
 *
 * Higher is better on every one, risk included — a panel where one bar ran
 * backwards would be misread eventually, so the direction is stated in the
 * caption rather than left to the reader to infer.
 */
function Dimensions({ scores }: { scores: DimensionScore[] }) {
  if (scores.length === 0) return null
  return (
    <div>
      <div className="label-micro">Scored dimensions</div>
      <p className="mt-1 text-[10.5px] text-[var(--color-fg-muted)]">
        0–100, higher is better on all six — including risk, where higher means safer.
      </p>
      <div className="mt-2.5 flex flex-col gap-2">
        {scores.map((score) => (
          <DimensionRow key={score.key} score={score} />
        ))}
      </div>
    </div>
  )
}

function DimensionRow({ score }: { score: DimensionScore }) {
  const value = score.score
  return (
    <div className="flex items-center gap-2.5">
      <span className="w-[110px] flex-shrink-0 text-[11.5px] text-[var(--color-fg)]">
        {score.label}
      </span>
      <div
        className="h-1.5 flex-1 overflow-hidden rounded-full"
        style={{ background: 'var(--color-hover)' }}
        role="img"
        aria-label={
          value == null
            ? `${score.label}: not scorable from available data`
            : `${score.label}: ${Math.round(value)} out of 100`
        }
      >
        {value != null && (
          <div
            className="h-full rounded-full"
            style={{ width: `${value}%`, background: barColor(value) }}
          />
        )}
      </div>
      <span className="w-[92px] flex-shrink-0 text-right text-[11px] tabular-nums text-[var(--color-fg-muted)]">
        {value == null ? 'no data' : Math.round(value)}
        {score.thin && value != null && (
          <span title="Few inputs — treat with caution"> · thin</span>
        )}
        {score.model_judged && value != null && (
          <span title="Judged by the model, not computed"> · judged</span>
        )}
      </span>
    </div>
  )
}

function barColor(value: number): string {
  if (value >= 60) return 'var(--accent-buy)'
  if (value >= 40) return 'var(--accent-hold)'
  return 'var(--accent-sell)'
}

function ConvictionNote({ dossier }: { dossier: ResearchDossier }) {
  const { conviction, derived_conviction: derived, report } = dossier
  if (conviction == null || derived == null) return null
  const gap = Math.abs(conviction - derived)
  return (
    <p className="text-[10.5px] leading-relaxed text-[var(--color-fg-muted)]">
      Conviction {Math.round(conviction)} against an arithmetic anchor of{' '}
      {Math.round(derived)} computed from the scored dimensions.
      {gap >= 10 && ' The two differ materially — the numbers and the narrative are not saying the same thing.'}
      {report?.conviction_rationale ? ` ${report.conviction_rationale}` : ''}
    </p>
  )
}

function Prose({
  label,
  text,
  tone,
  emphasis,
}: {
  label: string
  text?: string | null
  tone?: 'buy' | 'sell'
  emphasis?: boolean
}) {
  // Absent rather than empty. A heading over nothing reads as a bug; a section
  // that simply is not there reads as "nothing supportable was said".
  if (!text) return null
  const color =
    tone === 'buy' ? 'var(--accent-buy)' : tone === 'sell' ? 'var(--accent-sell)' : undefined
  return (
    <div>
      <div className="label-micro" style={color ? { color } : undefined}>{label}</div>
      <p
        className={`mt-1 leading-relaxed text-[var(--color-fg)] ${
          emphasis ? 'text-[13px]' : 'text-[12.5px]'
        }`}
      >
        {text}
      </p>
    </div>
  )
}

function Bullets({
  label,
  items,
  tone,
  hint,
}: {
  label: string
  items: string[]
  tone?: 'sell'
  hint?: string
}) {
  if (!items || items.length === 0) return null
  const color = tone === 'sell' ? 'var(--accent-sell)' : undefined
  return (
    <div>
      <div className="label-micro" style={color ? { color } : undefined}>{label}</div>
      {hint && (
        <p className="mt-1 text-[10.5px] leading-snug text-[var(--color-fg-muted)]">{hint}</p>
      )}
      <ul className="mt-1.5 flex flex-col gap-1">
        {items.map((item, index) => (
          <li
            key={`${label}-${index}`}
            className="flex gap-1.5 text-[12px] leading-relaxed text-[var(--color-fg)]"
          >
            <span aria-hidden="true" className="text-[var(--color-fg-muted)]">·</span>
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * The evidence ledger.
 *
 * Collapsed by default because it is long, but present in full: this is what
 * the citations in the prose above point at, and a report whose sources cannot
 * be opened is a report you have to take on trust.
 */
function Evidence({ items }: { items: EvidenceItem[] }) {
  const [open, setOpen] = useState(false)
  if (!items || items.length === 0) return null
  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls="research-evidence"
        className="flex w-full items-center gap-2 text-left"
      >
        <span className="label-micro">Evidence ({items.length} sourced facts)</span>
        <span className="ml-auto text-[11px] text-brand-500">{open ? 'Hide' : 'Show'}</span>
      </button>
      {open && (
        <ul id="research-evidence" className="mt-2 flex flex-col gap-1.5">
          {items.map((item) => (
            <li key={item.id} className="text-[11px] leading-snug">
              <span className="font-mono text-[10px] text-[var(--color-fg-muted)]">
                [{item.id}]
              </span>{' '}
              <span className="text-[var(--color-fg)]">{item.claim}:</span>{' '}
              <span className="text-[var(--color-fg)]">{item.value}</span>
              <span className="text-[var(--color-fg-muted)]">
                {' — '}{item.source}
                {item.as_of ? `, ${item.as_of}` : ''}
              </span>
              {item.url && (
                <a
                  href={item.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="ml-1 inline-flex items-center text-brand-500"
                  aria-label={`Open source for ${item.claim}`}
                >
                  <ExternalLink className="h-2.5 w-2.5" aria-hidden="true" />
                </a>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Callout({ children }: { children: React.ReactNode }) {
  return (
    <p
      className="flex items-start gap-2 rounded px-2.5 py-2 text-[11px] leading-relaxed"
      style={{ background: 'var(--tint-hold)', color: 'var(--accent-hold)' }}
    >
      <AlertCircle className="mt-0.5 h-3 w-3 flex-shrink-0" aria-hidden="true" />
      <span>{children}</span>
    </p>
  )
}

function formatAge(dossier: ResearchDossier): string {
  const hours = dossier.age_hours
  if (hours == null) return 'undated'
  if (hours < 1) return 'just now'
  if (hours < 24) return `${Math.round(hours)}h ago`
  return `${Math.round(hours / 24)}d ago`
}
