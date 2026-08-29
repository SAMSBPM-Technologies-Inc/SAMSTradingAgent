import { useCallback, useEffect, useState } from 'react'
import { AlertCircle, ExternalLink, Loader2, RefreshCw, ShieldAlert } from 'lucide-react'

import { researchApi } from '../../lib/api'
import type {
  DimensionScore,
  EvidenceItem,
  ModelUsed,
  PriorRecordCoverage,
  ResearchDebate,
  ResearchDossier,
  ResearchOutcome,
  ResearchStances,
  ResearchVetoStatus,
  TradeStance,
} from '../../types'

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

      <VetoNote veto={dossier?.veto} />

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
      {dossier.research_conviction != null && (
        <span className="text-[12px] font-medium text-[var(--color-fg)]">
          {/* Labelled "Research conviction", never bare "Conviction". The
              analyst's own HIGH/MEDIUM/LOW conviction appears elsewhere on
              this same page and gates something else entirely. */}
          Research conviction {Math.round(dossier.research_conviction)}/100
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
      <VetoChip veto={dossier.veto} />
    </>
  )
}

/**
 * Whether this dossier is standing on the Buy button.
 *
 * Shown in the header rather than buried in the body because it is the one
 * thing here that changes what the system will do, as opposed to what it
 * thinks. Until now it could only be discovered by placing an order and
 * reading the refusal afterwards in the order history.
 *
 * Two states, deliberately worded differently. `blocking` is a fact about
 * right now. `would_block` with the veto switched off is a fact about a
 * setting the user has not turned on — presenting that as "blocked" would be
 * a lie, and hiding it would waste the only evidence they have for deciding
 * whether to turn it on.
 */
function VetoChip({ veto }: { veto?: ResearchVetoStatus | null }) {
  if (!veto?.would_block) return null
  const blocking = veto.blocking
  return (
    <span
      className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide"
      style={{
        background: blocking ? 'var(--tint-sell)' : 'var(--tint-hold)',
        color: blocking ? 'var(--accent-sell)' : 'var(--accent-hold)',
      }}
    >
      <ShieldAlert className="h-3 w-3" aria-hidden="true" />
      {blocking ? 'Blocks buying' : 'Would block'}
    </span>
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

          <Debate debate={dossier.debate} />
          <Stances stances={dossier.stances} />
          <ConvictionNote dossier={dossier} />
        </>
      )}

      <ModelsLine models={dossier.models_used} />
      <PriorRecordNote coverage={dossier.prior_record} />
      <OutcomeNote outcome={dossier.outcome} />

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
  const {
    research_conviction: conviction,
    derived_research_conviction: derived,
    report,
  } = dossier
  if (conviction == null || derived == null) return null
  const gap = Math.abs(conviction - derived)
  return (
    <p className="text-[10.5px] leading-relaxed text-[var(--color-fg-muted)]">
      Research conviction {Math.round(conviction)} against an arithmetic anchor of{' '}
      {Math.round(derived)} computed from the scored dimensions.
      {gap >= 10 && ' The two differ materially — the numbers and the narrative are not saying the same thing.'}
      {report?.conviction_rationale ? ` ${report.conviction_rationale}` : ''}
    </p>
  )
}

/**
 * What this dossier does to a BUY, stated in full.
 *
 * The chip in the header is the alert; this is the explanation, and it is the
 * part that has to survive a sceptical reading. It names the trigger, the
 * threshold, and — when nothing is blocking — how much room is left, because a
 * conviction of 38 against a floor of 35 is a different situation from 90
 * against 35 and the number alone does not say which.
 */
function VetoNote({ veto }: { veto?: ResearchVetoStatus | null }) {
  if (!veto) return null

  // Nothing to say about a dossier too old or too absent to matter. The
  // dossier's own "Stale" chip already covers the why; repeating it as a
  // veto sentence would imply the veto did something.
  if (!veto.considered) {
    if (veto.not_considered_reason === 'stale') {
      return (
        <Callout>
          This dossier is older than the {veto.max_age_hours}h the veto will
          trust, so it cannot block an entry. That is deliberate: a stale
          dossier means the refresh job has not run, and a research outage must
          not silently halt buying.
        </Callout>
      )
    }
    return null
  }

  if (veto.would_block) {
    const trigger = veto.trigger === 'bearish'
      ? 'the assessment is BEARISH'
      : `research conviction ${Math.round(veto.research_conviction ?? 0)} is below the ${Math.round(veto.min_conviction)} floor`
    return (
      <Callout tone={veto.blocking ? 'sell' : undefined}>
        {veto.blocking ? (
          <>
            <strong>Research is blocking new buying in {' '}
            this name</strong> — {trigger}. Both the agent and your own Buy
            button run the same guard, so an order placed here will be refused
            with this reason. Selling is unaffected: research may veto an
            entry, never an exit.
          </>
        ) : (
          <>
            Research would block a buy here — {trigger} — but the veto is
            switched off (<code>RESEARCH_VETO_ENABLED</code>), so nothing is
            being stopped. This is what turning it on would have caught.
          </>
        )}
      </Callout>
    )
  }

  const margin = veto.research_conviction != null
    ? Math.round(veto.research_conviction - veto.min_conviction)
    : null
  return (
    <p className="text-[10.5px] leading-relaxed text-[var(--color-fg-muted)]">
      Research does not block buying in this name
      {margin != null && ` — conviction clears the ${Math.round(veto.min_conviction)} floor by ${margin}`}
      {!veto.enabled && ', and the veto is switched off in any case'}.
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

/**
 * The panel's caveat block. `tone="sell"` is for the one case that is not a
 * caveat but a refusal — research actively blocking an entry — which should
 * not read in the same amber as "an agent didn't report".
 */
function Callout({ children, tone }: { children: React.ReactNode; tone?: 'sell' }) {
  const palette = tone === 'sell'
    ? { background: 'var(--tint-sell)', color: 'var(--accent-sell)' }
    : { background: 'var(--tint-hold)', color: 'var(--accent-hold)' }
  return (
    <p
      className="flex items-start gap-2 rounded px-2.5 py-2 text-[11px] leading-relaxed"
      style={palette}
    >
      <AlertCircle className="mt-0.5 h-3 w-3 flex-shrink-0" aria-hidden="true" />
      <span>{children}</span>
    </p>
  )
}

/**
 * The rebuttal exchange.
 *
 * Shown because the concession is the part worth the most. A bear case nobody
 * ever answered reaches the report at full strength whether or not the
 * evidence disposes of it, and a defence that answered every risk is the
 * clearest sign the step was not done honestly — both are visible here and
 * neither is visible in the merged report alone.
 */
function Debate({ debate }: { debate?: ResearchDebate | null }) {
  const [open, setOpen] = useState(false)
  if (!debate) return null

  const risk = debate.risk_rebuttal
  const defence = debate.defence_rebuttal
  const conceded = defence?.conceded ?? []
  const surviving = risk?.surviving ?? []

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between text-left"
        aria-expanded={open}
      >
        <span className="label-micro">The rebuttal</span>
        <span className="text-[10.5px] text-[var(--color-fg-muted)]">
          {open ? 'hide' : 'show'}
        </span>
      </button>
      <p className="mt-1 text-[10.5px] leading-snug text-[var(--color-fg-muted)]">
        One exchange, after both sides had already written independently — so
        neither inherited the other&rsquo;s framing. {surviving.length} risk
        {surviving.length === 1 ? '' : 's'} survived the evidence;{' '}
        {conceded.length} {conceded.length === 1 ? 'was' : 'were'} conceded as
        unanswerable from what was collected.
      </p>

      {open && (
        <div className="mt-2.5 flex flex-col gap-3">
          {!risk && (
            <Callout>
              The risk analyst&rsquo;s reply did not come back. Its original
              risks stand unanswered rather than disposed of.
            </Callout>
          )}
          {!defence && (
            <Callout>
              No defence was recorded. Do not read any risk as answered because
              this half is missing.
            </Callout>
          )}
          <Bullets
            label="Conceded — the evidence does not answer these"
            items={conceded}
            tone="sell"
            hint="Named by the side arguing for the company. A concession here is the strongest thing in this panel."
          />
          <Bullets
            label="Survived the evidence"
            items={surviving}
            tone="sell"
          />
          <Bullets
            label="Made worse by the evidence"
            items={risk?.sharpened ?? []}
            tone="sell"
          />
          <Bullets
            label="Answered"
            items={defence?.answered ?? []}
            hint="Risks the collected evidence disposes of, each citing what does it."
          />
          {risk?.residual_severity != null && (
            <p className="text-[11px] leading-relaxed text-[var(--color-fg-muted)]">
              The risk analyst put the bear case at {risk.residual_severity}/100
              after the exchange
              {risk.residual_rationale ? <> — {risk.residual_rationale}</> : null}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * The advisory stance panel.
 *
 * The wording here is load-bearing. These do not size anything: position
 * sizing is arithmetic on a frozen equity basis, no part of the trading guard
 * chain reads them, and three unanimous WAITs still leave the order the risk
 * model computed. A panel that implied otherwise would be claiming the system
 * behaves in a way it does not.
 */
function Stances({ stances }: { stances?: ResearchStances | null }) {
  if (!stances) return null
  const rows: Array<[string, TradeStance | null | undefined]> = [
    ['Aggressive', stances.aggressive],
    ['Neutral', stances.neutral],
    ['Conservative', stances.conservative],
  ]
  if (!rows.some(([, stance]) => stance)) return null

  return (
    <div>
      <div className="label-micro">How three readers would size this</div>
      <p className="mt-1 text-[10.5px] leading-snug text-[var(--color-fg-muted)]">
        Advice, not sizing. The order quantity comes from the risk model and
        your account — nothing here changes it. These readers are also not
        shown how much of your account is already in this name.
      </p>
      <div className="mt-2 flex flex-col gap-2">
        {rows.map(([label, stance]) =>
          stance ? (
            <div key={label} className="flex flex-col gap-0.5">
              <div className="flex items-baseline gap-2">
                <span className="text-[11px] font-medium text-[var(--color-fg)]">
                  {label}
                </span>
                <span
                  className="rounded px-1.5 py-0.5 text-[10px] font-medium"
                  style={stanceStyle(stance.stance)}
                >
                  {stanceLabel(stance.stance)}
                </span>
              </div>
              {stance.rationale ? (
                <p className="text-[11.5px] leading-relaxed text-[var(--color-fg)]">
                  {stance.rationale}
                </p>
              ) : (
                /* The stance is a closed enum and survives on its own; the
                   reasoning was stripped for citing nothing. Saying so beats
                   showing a recommendation with invisible support. */
                <p className="text-[11px] italic leading-relaxed text-[var(--color-fg-muted)]">
                  Its reasoning cited no evidence and was removed.
                </p>
              )}
            </div>
          ) : null,
        )}
      </div>
    </div>
  )
}

function stanceLabel(stance?: string | null): string {
  switch (stance) {
    case 'SIZE_UP': return 'lean in'
    case 'SIZE_DOWN': return 'take less'
    case 'HOLD_SIZE': return 'as sized'
    case 'WAIT': return 'wait'
    default: return 'no view'
  }
}

function stanceStyle(stance?: string | null): React.CSSProperties {
  switch (stance) {
    case 'SIZE_UP':
      return { background: 'var(--tint-buy)', color: 'var(--accent-buy)' }
    case 'SIZE_DOWN':
    case 'WAIT':
      return { background: 'var(--tint-sell)', color: 'var(--accent-sell)' }
    default:
      return { background: 'var(--tint-hold)', color: 'var(--accent-hold)' }
  }
}

/**
 * Whether the agents were given this desk's own track record.
 *
 * Worth stating rather than assuming. Zero is the honest answer for any name
 * being read for the first time and for every dossier written before outcome
 * settlement existed — and a reader who assumes the agents know their history
 * when they do not is drawing a conclusion the panel never supported.
 */
function PriorRecordNote({ coverage }: { coverage?: PriorRecordCoverage | null }) {
  if (!coverage) return null
  const { same_ticker: same, cross_ticker: cross } = coverage
  return (
    <p className="text-[10.5px] leading-relaxed text-[var(--color-fg-muted)]">
      {same === 0 && cross === 0 ? (
        <>
          The analysts had no settled record to work from on this name — every
          reading here comes from the current evidence alone.
        </>
      ) : (
        <>
          The analysts were shown {same} previous graded reading
          {same === 1 ? '' : 's'} of this name
          {cross > 0 ? <> and {cross} from other names</> : null}, each with what
          the position went on to do. Those entries are cited like any other
          evidence, and they can lower conviction but never raise it past the
          arithmetic anchor.
        </>
      )}
    </p>
  )
}

/**
 * How a past reading turned out.
 *
 * Absent on the dossier a ticker page normally shows, since that one was
 * written today. Present when looking at a graded reading, and the number that
 * matters is alpha rather than return: bullish on a name that rose 4% while
 * the market rose 9% was not right.
 */
function OutcomeNote({ outcome }: { outcome?: ResearchOutcome | null }) {
  if (!outcome || outcome.return == null) return null
  const alpha = outcome.alpha
  const correct = outcome.assessment_correct
  const tone =
    correct === true ? 'var(--accent-buy)'
      : correct === false ? 'var(--accent-sell)'
        : 'var(--color-fg-muted)'

  return (
    <div>
      <div className="label-micro">How this reading turned out</div>
      <p className="mt-1 text-[11.5px] leading-relaxed text-[var(--color-fg)]">
        Over the following {outcome.horizon_days} days the name returned{' '}
        {formatPct(outcome.return)}
        {alpha != null && outcome.benchmark_return != null ? (
          <>
            , against {formatPct(outcome.benchmark_return)} for{' '}
            {outcome.benchmark_ticker ?? 'the benchmark'} — {formatPct(alpha)} of
            alpha
          </>
        ) : (
          <> (the benchmark could not be read for this window, so there is no
            alpha to judge it on)</>
        )}
        .{' '}
        <span style={{ color: tone }}>
          {correct === true
            ? 'The call was right on alpha.'
            : correct === false
              ? 'The call was wrong on alpha.'
              : 'Not graded — the reading took no side, or the window could not be measured.'}
        </span>
      </p>
      {outcome.reflection?.lesson ? (
        <p className="mt-1.5 text-[11.5px] leading-relaxed text-[var(--color-fg)]">
          <span className="text-[var(--color-fg-muted)]">Lesson recorded: </span>
          {outcome.reflection.lesson}
        </p>
      ) : outcome.reflection?.uncited ? (
        <p className="mt-1.5 text-[10.5px] italic leading-relaxed text-[var(--color-fg-muted)]">
          A lesson was written but cited no evidence, so it was not kept. The
          figures above stand on their own.
        </p>
      ) : null}
    </div>
  )
}

/**
 * Which models wrote this reading.
 *
 * Only interesting once a trader can choose — but then it is essential: two
 * dossiers on the same company are not comparable without knowing which model
 * produced each, and "try a different agent" is not a workflow you can follow
 * if the answer is invisible. Absent on dossiers written before provenance was
 * recorded, which is the honest rendering of "we did not keep this".
 */
function ModelsLine({ models }: { models?: ModelUsed[] }) {
  if (!models || models.length === 0) return null
  return (
    <p className="text-[10.5px] leading-relaxed text-[var(--color-fg-muted)]">
      {models.length === 1 ? 'Written by ' : 'Written by '}
      {models.map((m, i) => (
        <span key={`${m.provider}-${m.model}`}>
          {i > 0 ? '; ' : ''}
          <span className="text-[var(--color-fg)]">{m.model}</span>
          {m.agents.length > 0 ? <> ({m.agents.join(', ')})</> : null}
        </span>
      ))}
      .
    </p>
  )
}

function formatPct(value: number): string {
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(1)}%`
}

function formatAge(dossier: ResearchDossier): string {
  const hours = dossier.age_hours
  if (hours == null) return 'undated'
  if (hours < 1) return 'just now'
  if (hours < 24) return `${Math.round(hours)}h ago`
  return `${Math.round(hours / 24)}d ago`
}
