import { AlertTriangle, CheckCircle2, CircleSlash, Info, MinusCircle, XCircle } from 'lucide-react'
import { useSystemStatus } from '../lib/system-status'
import type { CapabilityStatus, CapabilityTier, SourceState, SystemStatus } from '../types'
import Layout from '../components/Layout'
import LoadingSpinner from '../components/LoadingSpinner'
import { formatDateTime } from '../lib/format'

/**
 * What is working, what is not, and what each answer costs a decision.
 *
 * This page exists because of one property of the engine: every external source
 * degrades to a neutral 0.50 rather than failing the cycle. That is the right
 * trade — a verdict on four factors beats no verdict — but it means a score
 * assembled from three fallbacks published exactly like one assembled from live
 * data, and until now nothing said which you were looking at.
 *
 * Two rules it inherits from the service behind it:
 *
 *   - **Nothing here is probed.** Every row is what the source actually did on
 *     the last pipeline cycle. A probe would spend the Alpha Vantage budget it
 *     was reporting on, and would answer "can we reach FRED now" when the
 *     question is "did FRED build the macro factor behind that BUY".
 *   - **A source with no key is not broken.** It is a configuration choice, and
 *     rendering it as a fault is how a status page becomes something nobody
 *     opens twice.
 *
 * The verdict sentence at the top is composed on the server, so this page and
 * the mobile one cannot end up wording "degraded" differently.
 */

const STATE_STYLE: Record<SourceState, { label: string; fg: string; bg: string; Icon: typeof CheckCircle2 }> = {
  ok: { label: 'Working', fg: 'var(--accent-buy)', bg: 'var(--tint-buy)', Icon: CheckCircle2 },
  stale: { label: 'Stale', fg: 'var(--accent-hold)', bg: 'var(--tint-hold)', Icon: Info },
  degraded: { label: 'Degraded', fg: 'var(--accent-hold)', bg: 'var(--tint-hold)', Icon: AlertTriangle },
  failed: { label: 'Failing', fg: 'var(--accent-sell)', bg: 'var(--tint-sell)', Icon: XCircle },
  // Muted, never red. An absent key is a decision, not an incident.
  not_configured: { label: 'Off', fg: 'var(--color-fg-muted)', bg: 'var(--color-hover)', Icon: MinusCircle },
  never_run: { label: 'No reading', fg: 'var(--color-fg-muted)', bg: 'var(--color-hover)', Icon: CircleSlash },
}

const TIER_TITLE: Record<CapabilityTier, string> = {
  stops: 'Stops trading',
  behaviour: 'Changes what the agent does',
  quiet: 'Degrades a score quietly',
}

const TIER_BLURB: Record<CapabilityTier, string> = {
  stops: 'Without these the cycle does not complete and no order is evaluated. Trading pauses rather than running on stale data.',
  behaviour: 'These do not stop anything. They change which decision path runs, so the same market produces a different action.',
  quiet: 'These fail silently by design: the factor they feed goes to a neutral 0.50 and the verdict still publishes. This is the group worth checking before you trust a score.',
}

const TIER_ORDER: CapabilityTier[] = ['stops', 'behaviour', 'quiet']

const OVERALL_STYLE = {
  ok: { fg: 'var(--accent-buy)', bg: 'var(--tint-buy)', Icon: CheckCircle2 },
  degraded: { fg: 'var(--accent-hold)', bg: 'var(--tint-hold)', Icon: AlertTriangle },
  halted: { fg: 'var(--accent-sell)', bg: 'var(--tint-sell)', Icon: XCircle },
} as const

function StatePill({ state }: { state: SourceState }) {
  const style = STATE_STYLE[state]
  return (
    <span
      className="inline-flex flex-shrink-0 items-center gap-1 rounded px-1.5 py-0.5
                 text-[10px] font-semibold uppercase tracking-wide"
      style={{ background: style.bg, color: style.fg }}
    >
      <style.Icon className="h-3 w-3" aria-hidden="true" />
      {style.label}
    </span>
  )
}

function CapabilityRow({ row }: { row: CapabilityStatus }) {
  return (
    <div className="border-b border-[var(--color-border)] px-4 py-3 last:border-b-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[13px] font-semibold text-[var(--color-fg)]">{row.label}</span>
        <StatePill state={row.state} />
        {row.last_success_at && (
          <span className="ml-auto text-[10.5px] text-[var(--color-fg-muted)]">
            Last answered {formatDateTime(row.last_success_at)}
          </span>
        )}
      </div>

      <p className="mt-1 text-[11.5px] leading-snug text-[var(--color-fg)]">{row.detail}</p>

      {/* The reason the row is worth reading. "FRED: failing" is not
          actionable; "the macro factor is pinned to 0.50" tells you how much
          to discount the number you are looking at. */}
      <p className="mt-1 text-[11.5px] leading-relaxed text-[var(--color-fg-muted)]">
        <span className="font-medium text-[var(--color-fg)]">Without it: </span>
        {row.impact}
      </p>

      {row.feeds && (
        <p className="mt-0.5 text-[10.5px] text-[var(--color-fg-muted)]">Feeds {row.feeds}</p>
      )}

      {row.last_error && row.state === 'failed' && (
        <p className="mt-1 font-mono text-[10.5px] leading-snug text-[var(--accent-sell)]">
          {row.last_error}
        </p>
      )}
    </div>
  )
}

function CycleCard({ status }: { status: SystemStatus }) {
  const { cycle, market_open: marketOpen } = status
  const ok = !cycle.stale
  return (
    <section
      className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4"
      aria-labelledby="cycle-heading"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="cycle-heading" className="text-[13px] font-semibold text-[var(--color-fg)]">
          Analysis cycle
        </h2>
        <StatePill state={ok ? 'ok' : 'degraded'} />
        <span className="ml-auto text-[10.5px] text-[var(--color-fg-muted)]">
          Market {marketOpen ? 'open' : 'closed'}
        </span>
      </div>

      <p className="mt-1.5 text-[11.5px] leading-relaxed text-[var(--color-fg-muted)]">
        {/* Stated first because every row below describes the last cycle. If
            that cycle is hours old, none of them means what it appears to. */}
        Everything below describes the most recent run. Scores refresh every five
        minutes while the market is open, and not at all outside it — a quiet
        overnight is the design, not an outage.
      </p>

      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
        <div>
          <dt className="text-[10px] uppercase tracking-[0.1em] text-[var(--color-fg-muted)]">Last run</dt>
          <dd className="text-[12px] text-[var(--color-fg)]">
            {cycle.last_run_at ? formatDateTime(cycle.last_run_at) : 'Never'}
            {cycle.age_minutes != null && (
              <span className="ml-1 text-[var(--color-fg-muted)]">({cycle.age_minutes}m ago)</span>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-[10px] uppercase tracking-[0.1em] text-[var(--color-fg-muted)]">Tickers</dt>
          <dd className="num text-[12px] text-[var(--color-fg)]">
            {cycle.tickers_total ? `${cycle.tickers_ok ?? 0} of ${cycle.tickers_total}` : '—'}
          </dd>
        </div>
        {cycle.failed_tickers.length > 0 && (
          <div className="col-span-2 sm:col-span-1">
            <dt className="text-[10px] uppercase tracking-[0.1em] text-[var(--color-fg-muted)]">Failed</dt>
            <dd className="num text-[12px] text-[var(--accent-sell)]">
              {cycle.failed_tickers.join(', ')}
            </dd>
          </div>
        )}
      </dl>

      {cycle.last_error && (
        <p className="mt-2 font-mono text-[10.5px] leading-snug text-[var(--accent-sell)]">
          {cycle.last_error}
        </p>
      )}
    </section>
  )
}

export default function StatusPage() {
  // The shared reading, not a second poll of the same endpoint — the chrome
  // indicator shows a summary of this exact object, and two independent fetches
  // would let the strip and the page disagree for up to a minute.
  const { status, loading, error } = useSystemStatus()
  const overall = status ? OVERALL_STYLE[status.overall] : null

  return (
    <Layout>
      <div className="mx-auto flex max-w-3xl flex-col gap-4 px-4 py-6">
        <header>
          <h1
            className="text-[19px] font-semibold text-[var(--color-fg)]"
            style={{ fontFamily: 'Archivo, system-ui, sans-serif' }}
          >
            System status
          </h1>
          <p className="mt-1 text-[12px] leading-relaxed text-[var(--color-fg-muted)]">
            Which inputs the engine actually has, and what each missing one costs
            the score. Nothing here is a live probe — every row is what the source
            did on the last analysis cycle, which is the same data your signals
            were built from.
          </p>
        </header>

        {loading && <LoadingSpinner />}

        {error && !loading && (
          <p className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]
                        px-4 py-6 text-center text-sm text-[var(--color-fg-muted)]">
            Could not read system status.
          </p>
        )}

        {status && overall && (
          <>
            {/* Composed on the server. Both clients render it verbatim so they
                cannot disagree about what "degraded" means. */}
            <div
              className="flex items-start gap-2.5 rounded-lg px-4 py-3"
              style={{ background: overall.bg }}
              role="status"
            >
              <overall.Icon
                className="mt-0.5 h-4 w-4 flex-shrink-0"
                style={{ color: overall.fg }}
                aria-hidden="true"
              />
              <p className="text-[12.5px] leading-relaxed" style={{ color: overall.fg }}>
                {status.summary}
              </p>
            </div>

            <CycleCard status={status} />

            {TIER_ORDER.map((tier) => {
              const rows = status.capabilities.filter((c) => c.tier === tier)
              if (rows.length === 0) return null
              return (
                <section key={tier} aria-labelledby={`tier-${tier}`}>
                  <h2
                    id={`tier-${tier}`}
                    className="text-[13px] font-semibold text-[var(--color-fg)]"
                    style={{ fontFamily: 'Archivo, system-ui, sans-serif' }}
                  >
                    {TIER_TITLE[tier]}
                  </h2>
                  <p className="mb-2 mt-0.5 text-[11.5px] leading-relaxed text-[var(--color-fg-muted)]">
                    {TIER_BLURB[tier]}
                  </p>
                  <div className="overflow-hidden rounded-lg border border-[var(--color-border)]
                                  bg-[var(--color-surface)]">
                    {rows.map((row) => <CapabilityRow key={row.id} row={row} />)}
                  </div>
                </section>
              )
            })}

            <p className="text-[10.5px] leading-relaxed text-[var(--color-fg-muted)]">
              Checked {formatDateTime(status.checked_at)}. A source shown as{' '}
              <strong className="text-[var(--color-fg)]">Off</strong> has no API key on
              this server — that is a configuration choice, not a fault, and the factor
              it feeds sits at a neutral 0.50 rather than scoring badly. How each of
              these reaches a trading decision is set out in{' '}
              <em>docs/12-how-a-trade-is-judged.md</em>.
            </p>
          </>
        )}
      </div>
    </Layout>
  )
}
