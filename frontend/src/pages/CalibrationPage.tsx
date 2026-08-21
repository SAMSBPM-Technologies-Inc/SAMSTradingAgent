import { useCallback, useEffect, useState } from 'react'
import { AlertCircle, CheckCircle2, HelpCircle, Minus, XCircle } from 'lucide-react'
import { performanceApi } from '../lib/api'
import type {
  CalibrationBucket,
  CalibrationReport,
  ConfidenceBucket,
  ScoreBucket,
  ThresholdRow,
} from '../types'
import Layout from '../components/Layout'
import LoadingSpinner from '../components/LoadingSpinner'

/**
 * Threshold calibration — does the score actually rank outcomes?
 *
 * The engine has always written signal history and settled it with a realised
 * 20-day return, and until now nothing read it back. This is the page that
 * answers "how do you know the signals work?" with evidence rather than a
 * win-rate headline.
 *
 * Two rules borrowed from the service and enforced here:
 *   - Every number carries its sample size, and anything under
 *     `min_samples_for_signal` is marked as anecdote rather than shown as a
 *     confident percentage.
 *   - The page reports; it does not tune. Auto-fitting a threshold to its own
 *     history is how a system talks itself into whatever the last few months
 *     rewarded.
 */

function pct(v: number | null | undefined, digits = 0): string {
  if (v == null) return '—'
  return `${(v * 100).toFixed(digits)}%`
}

function signedPct(v: number | null | undefined, digits = 2): string {
  if (v == null) return '—'
  const s = (v * 100).toFixed(digits)
  return v >= 0 ? `+${s}%` : `${s}%`
}

function returnTone(v: number | null | undefined): string {
  if (v == null) return 'text-[var(--color-fg-muted)]'
  return v >= 0 ? 'text-[var(--accent-buy)]' : 'text-[var(--accent-sell)]'
}

/**
 * Sample-size marker. Deliberately loud: an unflagged 80% win rate on four
 * records is the single most misleading thing this page could render.
 */
function SampleCell({ row }: { row: CalibrationBucket }) {
  if (row.n === 0) {
    return <span className="text-[var(--color-fg-muted)] tabular-nums">0</span>
  }
  return (
    <span className="inline-flex items-center gap-1.5 tabular-nums">
      <span className={row.significant ? 'text-[var(--color-fg)]' : 'text-[var(--color-fg-muted)]'}>
        {row.n}
      </span>
      {!row.significant && (
        <span
          className="text-[0.6rem] uppercase tracking-wide px-1 py-0.5 rounded
                     bg-amber-500/10 text-amber-600 dark:text-amber-400"
          title="Below the minimum sample size — treat as anecdote, not evidence"
        >
          thin
        </span>
      )}
    </span>
  )
}

/** Horizontal bar centred on zero, so losses read as losses. */
function ReturnBar({ value, max }: { value: number | null; max: number }) {
  if (value == null || max === 0) return null
  const width = Math.min(50, (Math.abs(value) / max) * 50)
  const positive = value >= 0
  return (
    <div className="relative h-1.5 w-full rounded-full bg-[var(--color-border)]/50 overflow-hidden">
      <div className="absolute left-1/2 top-0 bottom-0 w-px bg-[var(--color-border)]" />
      <div
        className="absolute top-0 bottom-0 rounded-full transition-all duration-500"
        style={{
          width: `${width}%`,
          left: positive ? '50%' : `${50 - width}%`,
          background: positive ? 'var(--accent-buy)' : 'var(--accent-sell)',
        }}
      />
    </div>
  )
}

// ── Verdict banner ────────────────────────────────────────────────────────────

function RanksVerdict({ report }: { report: CalibrationReport }) {
  const ranks = report.score_ranks_outcomes

  const config = ranks === true
    ? {
        Icon: CheckCircle2,
        tone: 'bg-green-500/10 border-green-500/20 text-[var(--accent-buy)]',
        title: 'The score ranks outcomes.',
        body: `Average return rises across the ${report.usable_buckets} score bands that have `
             + 'enough settled records to say. The composite is separating winners from '
             + 'losers, so where the BUY threshold sits is a real question.',
      }
    : ranks === false
      ? {
          Icon: XCircle,
          tone: 'bg-red-500/10 border-red-500/20 text-[var(--accent-sell)]',
          title: 'The score does not rank outcomes.',
          body: 'Average return does not rise with the score across the bands with enough '
               + 'data. No threshold is the right threshold on a flat curve — the answer is '
               + 'to fix the score, not to move the line.',
        }
      : {
          Icon: HelpCircle,
          tone: 'bg-[var(--color-border)]/40 border-[var(--color-border)] text-[var(--color-fg-muted)]',
          title: 'Not enough evidence yet.',
          body: `Fewer than two score bands have reached ${report.min_samples_for_signal} settled `
               + 'records, so whether the score ranks outcomes cannot be answered either way. '
               + 'This is the honest state of a young track record, not a failure.',
        }

  const { Icon, tone, title, body } = config
  return (
    <div className={`flex items-start gap-3 px-4 py-3 rounded-xl border ${tone}`}>
      <Icon className="w-5 h-5 flex-shrink-0 mt-0.5" />
      <div>
        <p className="text-sm font-semibold">{title}</p>
        <p className="text-xs mt-1 leading-relaxed text-[var(--color-fg-muted)]">{body}</p>
      </div>
    </div>
  )
}

// ── Tables ────────────────────────────────────────────────────────────────────

function TableShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="card overflow-hidden p-0">
      <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[38rem]">{children}</table>
      </div>
    </div>
  )
}

const TH = 'px-4 py-2.5 text-[10.5px] font-semibold uppercase tracking-widest text-[var(--color-fg-muted)]'
const TD = 'px-4 py-3'

function ScoreBucketsTable({ rows }: { rows: ScoreBucket[] }) {
  const max = Math.max(...rows.map((r) => Math.abs(r.avg_return ?? 0)), 0.0001)
  return (
    <TableShell>
      <thead>
        <tr className="border-b border-[var(--color-border)]">
          <th scope="col" className={`${TH} text-left`}>Score band</th>
          <th scope="col" className={`${TH} text-right`}>Signals</th>
          <th scope="col" className={`${TH} text-right`}>Win rate</th>
          <th scope="col" className={`${TH} text-right`}>Avg 20d</th>
          <th scope="col" className={`${TH} text-right`}>Median</th>
          <th scope="col" className={`${TH} text-left w-32`}>&nbsp;</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={`${r.lo}-${r.hi}`} className="border-b border-[var(--color-border)]/50 last:border-0">
            <td className={`${TD} tabular-nums text-[var(--color-fg)]`}>
              {r.lo.toFixed(2)} – {r.hi.toFixed(2)}
            </td>
            <td className={`${TD} text-right`}><SampleCell row={r} /></td>
            <td className={`${TD} text-right tabular-nums text-[var(--color-fg)]`}>{pct(r.win_rate, 1)}</td>
            <td className={`${TD} text-right tabular-nums ${returnTone(r.avg_return)}`}>
              {signedPct(r.avg_return)}
            </td>
            <td className={`${TD} text-right tabular-nums text-[var(--color-fg-muted)]`}>
              {signedPct(r.median_return)}
            </td>
            <td className={TD}><ReturnBar value={r.avg_return} max={max} /></td>
          </tr>
        ))}
      </tbody>
    </TableShell>
  )
}

function ThresholdSweepTable({ rows, incumbent }: { rows: ThresholdRow[]; incumbent: number }) {
  const coverage = rows[0]?.risk_coverage ?? 0
  const filtered = rows[0]?.risk_filtered ?? false
  return (
    <div className="flex flex-col gap-2">
      <TableShell>
        <thead>
          <tr className="border-b border-[var(--color-border)]">
            <th scope="col" className={`${TH} text-left`}>BUY above</th>
            <th scope="col" className={`${TH} text-right`}>Signals</th>
            <th scope="col" className={`${TH} text-right`}>Win rate</th>
            <th scope="col" className={`${TH} text-right`}>Avg 20d</th>
            <th scope="col" className={`${TH} text-right`}>Median</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const isIncumbent = Math.abs(r.threshold - incumbent) < 1e-9
            return (
              <tr
                key={r.threshold}
                className={`border-b border-[var(--color-border)]/50 last:border-0 ${
                  isIncumbent ? 'bg-brand-500/5' : ''
                }`}
              >
                <td className={`${TD} tabular-nums text-[var(--color-fg)]`}>
                  {r.threshold.toFixed(2)}
                  {isIncumbent && (
                    <span className="ml-2 text-[0.6rem] uppercase tracking-wide px-1.5 py-0.5
                                     rounded bg-brand-500/10 text-brand-500">
                      current
                    </span>
                  )}
                </td>
                <td className={`${TD} text-right`}><SampleCell row={r} /></td>
                <td className={`${TD} text-right tabular-nums text-[var(--color-fg)]`}>{pct(r.win_rate, 1)}</td>
                <td className={`${TD} text-right tabular-nums ${returnTone(r.avg_return)}`}>
                  {signedPct(r.avg_return)}
                </td>
                <td className={`${TD} text-right tabular-nums text-[var(--color-fg-muted)]`}>
                  {signedPct(r.median_return)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </TableShell>

      {/* Reading a low-coverage sweep as if it modelled the real gate would
          overstate it, so the coverage is stated rather than assumed. */}
      {filtered && coverage < 1 && (
        <p className="text-[0.65rem] text-amber-600 dark:text-amber-400 leading-relaxed">
          The risk veto could only be applied to {pct(coverage, 0)} of these records — signal
          history did not carry a risk score until recently. The remainder are score-only,
          so this sweep is not a full model of the live gate.
        </p>
      )}
    </div>
  )
}

function ConfidenceTable({ rows }: { rows: ConfidenceBucket[] }) {
  return (
    <TableShell>
      <thead>
        <tr className="border-b border-[var(--color-border)]">
          <th scope="col" className={`${TH} text-left`}>Stated confidence</th>
          <th scope="col" className={`${TH} text-right`}>Signals</th>
          <th scope="col" className={`${TH} text-right`}>Win rate</th>
          <th scope="col" className={`${TH} text-right`}>Avg 20d</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={`${r.lo}-${r.hi}`} className="border-b border-[var(--color-border)]/50 last:border-0">
            <td className={`${TD} tabular-nums text-[var(--color-fg)]`}>
              {pct(r.lo)} – {pct(r.hi)}
            </td>
            <td className={`${TD} text-right`}><SampleCell row={r} /></td>
            <td className={`${TD} text-right tabular-nums text-[var(--color-fg)]`}>{pct(r.win_rate, 1)}</td>
            <td className={`${TD} text-right tabular-nums ${returnTone(r.avg_return)}`}>
              {signedPct(r.avg_return)}
            </td>
          </tr>
        ))}
      </tbody>
    </TableShell>
  )
}

// ── Section wrapper ───────────────────────────────────────────────────────────

function Block({ title, blurb, children }: {
  title: string
  blurb: string
  children: React.ReactNode
}) {
  return (
    <section className="flex flex-col gap-3">
      <div>
        <h2 className="text-[11px] font-semibold uppercase tracking-widest text-[var(--color-fg-muted)]">
          {title}
        </h2>
        <p className="text-xs text-[var(--color-fg-muted)] mt-1 leading-relaxed max-w-2xl">
          {blurb}
        </p>
      </div>
      {children}
    </section>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function CalibrationPage() {
  const [report, setReport] = useState<CalibrationReport | null>(null)
  const [applyRiskGate, setApplyRiskGate] = useState(true)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (riskGate: boolean) => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await performanceApi.calibration(undefined, riskGate)
      setReport(res.data)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setError(detail ?? 'Failed to load calibration data.')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => { load(applyRiskGate) }, [load, applyRiskGate])

  const incumbentThreshold = 0.70

  return (
    <Layout>
      <div className="mb-6">
        <h1
          className="text-2xl font-light text-[var(--color-fg)]"
          style={{ fontFamily: 'Fraunces, Georgia, serif' }}
        >
          Calibration
        </h1>
        <p className="text-sm text-[var(--color-fg-muted)] mt-0.5 max-w-2xl">
          Were the signal thresholds in the right place? Measured against realised
          20-day returns on settled signals.
        </p>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <LoadingSpinner size="lg" />
        </div>
      ) : error ? (
        <div className="flex items-center gap-3 px-4 py-3 rounded-xl
                        bg-red-500/10 border border-red-500/20 text-red-500 text-sm">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          {error}
        </div>
      ) : !report || report.settled_records === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <div className="w-16 h-16 rounded-2xl bg-brand-500/10 flex items-center justify-center mb-4">
            <Minus className="w-8 h-8 text-brand-500" />
          </div>
          <h3 className="text-lg font-medium text-[var(--color-fg)] mb-2"
              style={{ fontFamily: 'Fraunces, Georgia, serif' }}>
            Nothing has settled yet
          </h3>
          <p className="text-sm text-[var(--color-fg-muted)] max-w-sm">
            Calibration needs signals that are at least 20 trading days old, so their
            realised return is known. Until then there is nothing to calibrate against —
            and no honest way to claim the thresholds are right.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-8">
          <RanksVerdict report={report} />

          {/* Base rate — every bucket below should be read against this. */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="card flex flex-col gap-1">
              <span className="text-[11px] font-semibold uppercase tracking-widest text-[var(--color-fg-muted)]">
                Settled
              </span>
              <span className="text-[22px] font-bold tabular-nums text-[var(--color-fg)]"
                    style={{ fontFamily: 'Archivo, system-ui, sans-serif' }}>
                {report.settled_records}
              </span>
              <span className="text-[11px] text-[var(--color-fg-muted)]">signals with a 20d outcome</span>
            </div>
            <div className="card flex flex-col gap-1">
              <span className="text-[11px] font-semibold uppercase tracking-widest text-[var(--color-fg-muted)]">
                Base win rate
              </span>
              <span className="text-[22px] font-bold tabular-nums text-[var(--color-fg)]"
                    style={{ fontFamily: 'Archivo, system-ui, sans-serif' }}>
                {pct(report.base_rate.win_rate, 1)}
              </span>
              <span className="text-[11px] text-[var(--color-fg-muted)]">all signals, ungated</span>
            </div>
            <div className="card flex flex-col gap-1">
              <span className="text-[11px] font-semibold uppercase tracking-widest text-[var(--color-fg-muted)]">
                Base avg 20d
              </span>
              <span className={`text-[22px] font-bold tabular-nums ${returnTone(report.base_rate.avg_return)}`}
                    style={{ fontFamily: 'Archivo, system-ui, sans-serif' }}>
                {signedPct(report.base_rate.avg_return)}
              </span>
              <span className="text-[11px] text-[var(--color-fg-muted)]">the bar to beat</span>
            </div>
            <div className="card flex flex-col gap-1">
              <span className="text-[11px] font-semibold uppercase tracking-widest text-[var(--color-fg-muted)]">
                Usable bands
              </span>
              <span className="text-[22px] font-bold tabular-nums text-[var(--color-fg)]"
                    style={{ fontFamily: 'Archivo, system-ui, sans-serif' }}>
                {report.usable_buckets}
              </span>
              <span className="text-[11px] text-[var(--color-fg-muted)]">
                ≥{report.min_samples_for_signal} records
              </span>
            </div>
          </div>

          <Block
            title="Does a higher score earn a higher return?"
            blurb="Read this first. A composite that ranks well produces returns that rise with
                   the band. A flat or jagged curve means the score is not separating winners
                   from losers, and moving the BUY threshold would only pick a different
                   arbitrary point on a flat line."
          >
            <ScoreBucketsTable rows={report.score_buckets} />
          </Block>

          <Block
            title="What would each BUY cutoff have returned?"
            blurb="The incumbent threshold is 0.70, placed by guess before there was any
                   history to place it with. This is what the alternatives would have done —
                   evidence for a human decision, not a setting to auto-fit."
          >
            <div className="flex items-center gap-2 mb-1">
              <button
                onClick={() => setApplyRiskGate((v) => !v)}
                role="switch"
                aria-checked={applyRiskGate}
                className={`relative w-9 h-5 rounded-full transition-colors flex-shrink-0
                  ${applyRiskGate ? 'bg-brand-500' : 'bg-[var(--color-border)]'}`}
              >
                <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow
                                  transition-transform ${applyRiskGate ? 'translate-x-4' : ''}`} />
              </button>
              <span className="text-xs text-[var(--color-fg)]">Also apply the risk veto</span>
            </div>
            <ThresholdSweepTable rows={report.threshold_sweep} incumbent={incumbentThreshold} />
          </Block>

          <Block
            title="Does stated confidence track being right?"
            blurb="Confidence is computed as distance from the decision boundary — which is not
                   a hit rate, and had never been compared to one. If the win rate does not
                   rise across these bands, the number is presentation rather than information."
          >
            <ConfidenceTable rows={report.confidence_buckets} />
          </Block>

          <p className="text-[0.65rem] text-[var(--color-fg-muted)] leading-relaxed max-w-2xl">
            This page reports; it does not tune. Fitting a threshold to its own history is how
            a system talks itself into whatever the last few months happened to reward, and at
            these sample sizes the noise is larger than the signal. Rows marked{' '}
            <span className="text-amber-600 dark:text-amber-400">thin</span> have fewer than{' '}
            {report.min_samples_for_signal} settled records and are anecdote, not evidence.
          </p>
        </div>
      )}
    </Layout>
  )
}
