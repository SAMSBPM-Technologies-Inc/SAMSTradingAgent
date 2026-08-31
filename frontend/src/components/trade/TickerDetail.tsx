import { Suspense, lazy, useState } from 'react'
import { AlertCircle, ChevronDown, ChevronUp } from 'lucide-react'
import type {
  AnalyzeResponse,
  Holding,
  Quote,
  SignalInputs,
  TradeRecord,
  WatchlistItem,
} from '../../types'
import { formatDateTime, relativeTime } from '../../lib/format'
import { useNow } from '../../lib/use-poll'
import { SOURCE_DESCRIPTION, tradeSource } from '../../lib/trade-source'
import { Disclaimer } from '../Layout'
import ConvictionBadge from '../ConvictionBadge'
import FactorBreakdown from '../FactorBreakdown'
import LoadingSpinner from '../LoadingSpinner'
import RiskPanel from '../RiskPanel'
import SignalBadge from '../SignalBadge'
import AltDataPanel from './AltDataPanel'
import { ResearchPanel } from './ResearchPanel'

// Split out: the charting library is ~200 kB and this is the only screen that
// draws one. Bundled eagerly it loaded on screens that have no chart.
const PriceChart = lazy(() => import('../PriceChart'))

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

/** Mirrors `_CACHE_TTL_MINUTES` in backend/app/routes/analysis.py. */
const ANALYSIS_TTL_MS = 30 * 60 * 1000

// ── Why ───────────────────────────────────────────────────────────────────────

/**
 * The plain-English line above the numbers.
 *
 * Prefers the model's own words. Where there are none it derives a sentence
 * from the gate the engine actually applied — never invents a rationale, which
 * on a screen that routes orders would be the worst possible place to do it.
 *
 * One case comes before the model's words rather than after: when the gate
 * overrode the analyst, `thesis` argues for a verdict that was *not published*.
 * Printing a bullish case unlabelled beneath a HOLD is the same contradiction
 * the gate rows used to carry, moved one band up the page. The refusal leads,
 * and the model's case follows it, attributed.
 */
function whyText(data: AnalyzeResponse): string {
  const own = data.thesis?.trim() || data.explanation?.trim()
  const score = Math.round(data.score * 100)
  const override = data.gate?.analyst?.override

  if (data.gate && override) {
    const sell = Math.round(data.gate.sell_threshold * 100)
    const lead = override === 'buy_refused'
      ? `Scored ${score}/100. The AI analyst read this as a buy; the gate refused it, so the verdict is HOLD.`
      : `Scored ${score}/100, below the ${sell} that triggers a sell. The AI analyst wanted to hold on, and an exit is never held back.`
    return own ? `${lead} The analyst's case, for what it is worth: ${own}` : lead
  }

  if (own) return own

  if (!data.gate) return `${data.signal} at ${score}/100. No further rationale was recorded.`

  const buy = Math.round(data.gate.buy_threshold * 100)
  const sell = Math.round(data.gate.sell_threshold * 100)
  const held = Math.round(data.gate.effective_buy_threshold * 100)

  if (data.signal === 'BUY') {
    // A BUY under the entry threshold is one the hysteresis band is holding
    // open, not one that cleared the bar. Saying it "cleared the 70" would be
    // false on exactly the readings a sceptical reader checks.
    return held < buy && score < buy
      ? `Scored ${score}/100. That is under the ${buy} needed to open a buy, but an established one holds until ${held}, and risk stayed under the veto.`
      : `Scored ${score}/100, clearing the ${buy} needed to buy, and risk stayed under the veto.`
  }
  if (data.signal === 'SELL') {
    return `Scored ${score}/100, below the ${sell} that triggers a sell. Exits are not risk-gated.`
  }
  if (data.gate.score_passes_buy && !data.gate.risk_passes_buy) {
    return `Scored ${score}/100 — enough to buy — but the risk gate vetoed it, so the verdict is HOLD.`
  }
  return `Scored ${score}/100: under the ${buy} needed to buy and over the ${sell} that would trigger a sell.`
}

function whyTone(signal: AnalyzeResponse['signal']) {
  if (signal === 'BUY') return { bg: 'var(--tint-buy)', fg: 'var(--accent-buy)' }
  if (signal === 'SELL') return { bg: 'var(--tint-sell)', fg: 'var(--accent-sell)' }
  return { bg: 'var(--tint-hold)', fg: 'var(--accent-hold)' }
}

// ── Composite score bar ───────────────────────────────────────────────────────

function ScoreBar({ data }: { data: AnalyzeResponse }) {
  const pct = Math.max(0, Math.min(100, Math.round(data.score * 100)))
  const buy = (data.gate?.buy_threshold ?? 0.7) * 100
  const sell = (data.gate?.sell_threshold ?? 0.3) * 100
  const color = pct >= buy ? 'var(--accent-buy)' : pct <= sell ? 'var(--accent-sell)' : 'var(--accent-hold)'

  return (
    <div className="ml-auto min-w-[230px] max-w-[320px] flex-1">
      <div className="flex items-baseline justify-between">
        <span className="label-micro">Composite score</span>
        <span className="num text-[13px] font-bold text-[var(--color-fg)]">
          {pct}<span className="font-normal text-[var(--color-fg-muted)]">/100</span>
        </span>
      </div>
      <div className="relative mt-1.5 h-[7px] overflow-hidden rounded bg-[var(--color-border)]">
        <div className="absolute inset-y-0 left-0 rounded" style={{ width: `${pct}%`, background: color }} />
      </div>
      {/* Thresholds are positioned from the gate the API returned, not from
          constants restated here — the two must not be able to drift. */}
      <div className="relative h-3 text-[9.5px] text-[var(--color-fg-muted)]">
        <span className="absolute -translate-x-1/2" style={{ left: `${sell}%` }}>sell {Math.round(sell)}</span>
        <span className="absolute -translate-x-1/2" style={{ left: `${buy}%` }}>buy {Math.round(buy)}</span>
      </div>
    </div>
  )
}

// ── Your position ─────────────────────────────────────────────────────────────

function PositionBlock({ holding, position }: { holding: Holding; position: TradeRecord | null }) {
  const source = tradeSource(position?.signal_type)
  const pnl = holding.unrealized_pnl

  const legs = [
    position?.stop_loss != null ? `stop ${usd.format(position.stop_loss)}` : null,
    position?.take_profit != null ? `target ${usd.format(position.take_profit)}` : null,
  ].filter(Boolean).join(' · ')

  const fields: { label: string; value: string; color?: string }[] = [
    { label: 'Shares', value: String(holding.qty) },
    { label: 'Avg cost', value: usd.format(holding.avg_cost) },
    { label: 'Value', value: holding.market_value != null ? usd.format(holding.market_value) : '—' },
    {
      label: 'Unrealised',
      value: pnl != null ? (pnl < 0 ? `(${usd.format(Math.abs(pnl))})` : usd.format(pnl)) : '—',
      color: pnl == null ? undefined
        : pnl < -0.005 ? 'var(--accent-sell)'
          : pnl > 0.005 ? 'var(--accent-buy)' : undefined,
    },
  ]

  return (
    <div className="flex flex-col gap-1 border-l-2 border-brand-500 pl-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="label-micro text-brand-500">Your position</span>
        <span className="text-[10.5px] text-[var(--color-fg-muted)]">
          {SOURCE_DESCRIPTION[source]}{legs ? ` · ${legs}` : ''}
        </span>
      </div>
      <div className="flex flex-wrap items-baseline gap-4">
        {fields.map((f) => (
          <div key={f.label} className="flex flex-col gap-px">
            <span className="text-[9.5px] uppercase tracking-[0.09em] text-[var(--color-fg-muted)]">
              {f.label}
            </span>
            <span className="num text-[13.5px] font-semibold" style={{ color: f.color ?? 'var(--color-fg)' }}>
              {f.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Timing tiles ──────────────────────────────────────────────────────────────

function TimingTiles({ item }: { item: WatchlistItem }) {
  const [showCriteria, setShowCriteria] = useState(false)

  const tiles: { label: string; value: string; color?: string }[] = [
    {
      label: 'RSI-14',
      value: item.rsi_14 != null ? item.rsi_14.toFixed(1) : '—',
      color: item.rsi_14 == null ? undefined
        : item.rsi_14 >= 70 ? 'var(--accent-sell)'
          : item.rsi_14 <= 45 ? 'var(--accent-buy)' : undefined,
    },
    {
      label: 'Stoch RSI',
      value: item.stoch_rsi != null ? `${(item.stoch_rsi * 100).toFixed(0)}%` : '—',
      color: item.stoch_rsi == null ? undefined
        : item.stoch_rsi <= 0.2 ? 'var(--accent-buy)' : undefined,
    },
    {
      label: 'BB position',
      value: item.bb_pct != null ? `${(item.bb_pct * 100).toFixed(0)}%` : '—',
      color: item.bb_pct == null ? undefined
        : item.bb_pct >= 0.9 ? 'var(--accent-sell)'
          : item.bb_pct <= 0.35 ? 'var(--accent-buy)' : undefined,
    },
    {
      label: 'Volume vs avg',
      value: item.volume_anomaly != null ? `${item.volume_anomaly.toFixed(2)}x` : '—',
      color: item.volume_anomaly != null && item.volume_anomaly >= 1.2 ? 'var(--accent-buy)' : undefined,
    },
    {
      label: '% vs MA-20',
      value: item.pct_from_ma20 != null
        ? `${item.pct_from_ma20 > 0 ? '+' : ''}${item.pct_from_ma20.toFixed(1)}%`
        : '—',
      color: item.pct_from_ma20 == null ? undefined
        : item.pct_from_ma20 >= 0 ? 'var(--accent-hold)' : 'var(--accent-buy)',
    },
  ]

  return (
    <>
      <div
        className="mt-3 grid gap-px overflow-hidden rounded-[7px] border border-[var(--color-border)]
                   bg-[var(--color-border)] sm:grid-cols-3 lg:grid-cols-5"
      >
        {tiles.map((t) => (
          <div key={t.label} className="bg-[var(--color-surface)] px-2.5 py-2">
            <div className="text-[9.5px] uppercase tracking-[0.09em] text-[var(--color-fg-muted)]">
              {t.label}
            </div>
            <div className="num mt-0.5 text-[14px] font-semibold" style={{ color: t.color ?? 'var(--color-fg)' }}>
              {t.value}
            </div>
          </div>
        ))}
      </div>

      <button
        onClick={() => setShowCriteria((v) => !v)}
        aria-expanded={showCriteria}
        aria-controls="setup-criteria"
        className="mt-2 flex items-center gap-1.5 text-[10.5px] text-[var(--color-fg-muted)]
                   transition-colors hover:text-[var(--color-fg)]"
      >
        <span aria-hidden="true">
          {showCriteria ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        </span>
        How setups are detected
      </button>

      {showCriteria && (
        <div
          id="setup-criteria"
          className="mt-2 grid gap-4 rounded-[7px] border border-[var(--color-border)] p-3
                     text-[11px] text-[var(--color-fg-muted)] sm:grid-cols-2"
        >
          <div>
            <div className="mb-1.5 font-semibold text-[var(--accent-buy)]">Entry setup (all must hold)</div>
            <ul className="flex flex-col gap-0.5">
              <li>RSI-14 ≤ 45 — not yet overbought</li>
              <li>Stochastic RSI ≤ 20% — oversold</li>
              <li>Bollinger position ≤ 35% — near the lower band</li>
            </ul>
          </div>
          <div>
            <div className="mb-1.5 font-semibold text-[var(--accent-sell)]">Exit alert (either fires)</div>
            <ul className="flex flex-col gap-0.5">
              <li>RSI-14 ≥ 70 — overbought territory</li>
              <li>Bollinger position ≥ 90% — near the upper band</li>
            </ul>
          </div>
        </div>
      )}
    </>
  )
}

// ── Collapsible section ───────────────────────────────────────────────────────

function Collapsible({
  title,
  defaultOpen = false,
  children,
}: {
  title: string
  defaultOpen?: boolean
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  const id = `sect-${title.toLowerCase().replace(/[^a-z]+/g, '-')}`
  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={id}
        className="flex w-full items-center gap-2 text-left"
      >
        <span className="label-micro">{title}</span>
        <span className="ml-auto text-[11px] text-brand-500">{open ? 'Hide' : 'Show'}</span>
      </button>
      {open && <div id={id} className="mt-2.5">{children}</div>}
    </div>
  )
}

// ── The two cases ─────────────────────────────────────────────────────────────

/** At most this many bullets a side. Past three it stops being a glance. */
const MAX_CASE_POINTS = 3

/**
 * One side of the argument, bullets first.
 *
 * `points` is written by the analyst, not derived here. Splitting a paragraph
 * on its full stops is a guess at which clause carried the argument, made by
 * the layer least equipped to know — so an analysis stored before the analyst
 * was asked for bullets shows its paragraph, clamped, with the full text a
 * click away. It never gets chopped into fake bullets.
 *
 * The prose, catalysts and risks are not dropped, only folded: this section is
 * at the top of the page now, and the whole reason it could move up is that it
 * stopped being four paragraphs tall.
 */
function CasePanel({
  label,
  colour,
  points,
  prose,
  extraLabel,
  extra,
}: {
  label: string
  colour: string
  points: string[]
  prose?: string | null
  extraLabel: string
  extra: string[]
}) {
  const [open, setOpen] = useState(false)
  const bullets = points.slice(0, MAX_CASE_POINTS)
  const id = `case-${label.toLowerCase().replace(/[^a-z]+/g, '-')}`
  const hasMore = !!prose || extra.length > 0

  return (
    <section className="min-w-0 bg-[var(--color-bg)] px-[18px] py-3.5">
      <div className="label-micro" style={{ color: colour }}>{label}</div>

      {bullets.length > 0 ? (
        <ul className="mt-2 flex flex-col gap-1.5">
          {bullets.map((p, i) => (
            <li key={i} className="flex gap-2 text-[13px] leading-snug text-[var(--color-fg)]">
              <span aria-hidden="true" className="mt-[7px] h-1 w-1 flex-shrink-0 rounded-full"
                    style={{ background: colour }} />
              <span className="min-w-0">{p}</span>
            </li>
          ))}
        </ul>
      ) : prose ? (
        // No bullets on this record. Show the analyst's own words, clamped —
        // the honest fallback, and the one that disappears as names are
        // re-analysed.
        <p className={`mt-2 text-[12.5px] leading-relaxed ${open ? '' : 'line-clamp-3'}`}>
          {prose}
        </p>
      ) : (
        <p className="mt-2 text-[11.5px] text-[var(--color-fg-muted)]">
          Not recorded for this analysis.
        </p>
      )}

      {hasMore && (
        <>
          <button
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-controls={id}
            className="mt-2 flex items-center gap-1.5 text-[10.5px] text-[var(--color-fg-muted)]
                       transition-colors hover:text-[var(--color-fg)]"
          >
            <span aria-hidden="true">
              {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
            </span>
            {open ? 'Less' : 'Full case'}
          </button>

          {open && (
            <div id={id} className="mt-2">
              {/* Suppressed when the clamped paragraph above is already this
                  text — an unclamped duplicate directly beneath it reads as a
                  rendering bug. */}
              {prose && bullets.length > 0 && (
                <p className="text-[12.5px] leading-relaxed text-[var(--color-fg-muted)]">{prose}</p>
              )}
              {extra.length > 0 && (
                <>
                  <div className="label-micro mt-3">{extraLabel}</div>
                  <ul className="mt-1.5 flex list-disc flex-col gap-1 pl-4 text-[12px]">
                    {extra.map((e, i) => <li key={i}>{e}</li>)}
                  </ul>
                </>
              )}
            </div>
          )}
        </>
      )}
    </section>
  )
}

// ── Detail ────────────────────────────────────────────────────────────────────

interface TickerDetailProps {
  data: AnalyzeResponse
  item: WatchlistItem | null
}

/**
 * The header does not require an analysis.
 *
 * That is the whole of the two-step change: a name with a live price and no
 * stored verdict is still a page worth painting, and the header is what paints
 * it. `data` is therefore nullable here and nowhere else.
 */
interface TickerHeaderProps {
  /** Known before either request returns — the header can render from this alone. */
  symbol: string
  data: AnalyzeResponse | null
  quote: Quote | null
  holding: Holding | null
  position: TradeRecord | null
}

/**
 * Identity and verdict: the ticker, the signal, the price, your position, the
 * score, and the one-line "why".
 *
 * Nothing here is a control. Watch, Remove, Export and Run full analysis used
 * to sit in a row at the bottom of this block, between the verdict and the
 * reasoning for it; they live in `TickerActions` now, beside the order ticket.
 * The reader's first screen is what the engine concluded and why — reading and
 * acting are separate questions and they are no longer interleaved.
 *
 * Split from the analysis below it so the two can be ordered independently.
 * On mobile the order ticket sits between them — you read what the name is and
 * what the engine concluded, then you can act, and the evidence follows. The
 * ticket first would invite an order before the verdict had been read; the
 * whole analysis first buried the ticket three screens down.
 */
export function TickerHeader({
  symbol,
  data,
  quote,
  holding,
  position,
}: TickerHeaderProps) {
  // Ticks so the age below stays true while the tab sits open. The threshold
  // is the server's own `_CACHE_TTL_MINUTES`: past it, `/analyze` would rebuild
  // rather than serve this, which makes it exactly the point where what is on
  // screen stops being what the engine would say.
  const now = useNow()
  const generatedMs = data ? Date.parse(data.generated_at) : NaN
  const stale = Number.isFinite(generatedMs) && now - generatedMs > ANALYSIS_TTL_MS

  /**
   * The price is the quote's, never the analysis's.
   *
   * `data.current_price` is whatever the price was when the pipeline last ran,
   * which on a stored read is by definition not now — and the whole point of
   * separating the two steps was that a stale verdict should not drag a stale
   * price along with it. The analysis is the fallback only when there is no
   * quote at all.
   */
  const price = quote?.price ?? data?.current_price ?? null
  const chg = quote?.price != null ? quote.day_change_pct : data?.day_change_pct
  const tone = data ? whyTone(data.signal) : null

  return (
    <>
      {/* ── Header ────────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-start gap-5 border-b border-[var(--color-border)] px-[18px] py-3.5">
        <div className="min-w-[190px]">
          <div className="flex flex-wrap items-baseline gap-2.5">
            <h1
              className="m-0 text-[26px] font-bold tracking-[-0.02em]"
              style={{ fontFamily: 'Archivo, system-ui, sans-serif' }}
            >
              {symbol}
            </h1>
            {data && <SignalBadge signal={data.signal} size="lg" />}
            {data?.conviction && <ConvictionBadge conviction={data.conviction} />}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-1 text-[11.5px]
                          text-[var(--color-fg-muted)]">
            {data?.time_horizon && <span>{data.time_horizon} horizon ·</span>}
            {/* Named, dated and stated outright rather than tucked into a
                relative aside. This is now the one line that tells a reader
                whether what they are looking at is a judgement from ten minutes
                ago or from Tuesday, because nothing on this page re-runs on its
                own any more. */}
            <span>
              Last in-depth analysis:{' '}
              <span className="text-[var(--color-fg)]">
                {data ? formatDateTime(data.generated_at) : 'never'}
              </span>
              {data ? ` · ${relativeTime(data.generated_at)}` : ''}
            </span>
            {/* Past the server's own cache window this analysis is older than
                anything the engine would still serve, so say so rather than
                letting a quiet "scored 47m ago" pass for current. `useNow`
                keeps it ticking; it used to render once and then stand still
                for as long as the tab stayed open. */}
            {stale && (
              <span
                className="inline-flex items-center gap-1 rounded px-1.5 py-px text-[10.5px] font-semibold"
                style={{ background: 'var(--tint-hold)', color: 'var(--accent-hold)' }}
              >
                <AlertCircle className="h-3 w-3" aria-hidden="true" />
                Stale — re-analyse
              </span>
            )}
            {data?.confidence != null && (
              <span>· {Math.round(data.confidence * 100)}% confidence</span>
            )}
          </div>
        </div>

        <div className="flex flex-col">
          <div className="flex items-baseline gap-2.5">
            <span className="num text-[26px] font-semibold">
              {price != null ? usd.format(price) : '—'}
            </span>
            {chg != null && (
              <span
                className="num text-[14px]"
                style={{ color: chg >= 0 ? 'var(--accent-buy)' : 'var(--accent-sell)' }}
              >
                {chg >= 0 ? '+' : ''}{chg.toFixed(2)}%
              </span>
            )}
          </div>
          {/* A price that is not live must say so. A stored figure shown with
              no label is the one number on this page a reader would act on
              without checking. */}
          <span className="text-[10.5px] text-[var(--color-fg-muted)]">
            {quote?.source === 'live'
              ? 'Live'
              : quote?.source === 'stored'
                ? `Last recorded ${relativeTime(quote.as_of)} — ${quote.note ?? 'no live quote'}`
                : quote?.source === 'unavailable'
                  ? quote.note ?? 'No price available'
                  : 'Fetching price…'}
          </span>
        </div>

        {holding && <PositionBlock holding={holding} position={position} />}

        {data && <ScoreBar data={data} />}
      </div>

      {/* ── Why ───────────────────────────────────────────────────────────── */}
      {data && tone && (
        <div
          className="flex items-start gap-3 border-b border-[var(--color-border)] px-[18px] py-3"
          style={{ background: tone.bg }}
        >
          <span className="label-micro flex-shrink-0 pt-0.5" style={{ color: tone.fg }}>Why</span>
          <p className="m-0 max-w-[66ch] text-[14px] leading-relaxed text-[var(--color-fg)]">
            {whyText(data)}
          </p>
        </div>
      )}
    </>
  )
}

/**
 * Everything behind the verdict, most-read first.
 *
 * The order is the change: the two cases used to sit below the chart, the
 * factor attribution and the risk gate — around five screens down on a laptop,
 * behind two open panels of numbers. They are the first thing here now, and
 * everything that is evidence *for* them is collapsed.
 *
 * The chart is the one detail left open. It is scanned rather than read, so it
 * costs a reader nothing to have it there, and it is the only thing on the page
 * that answers "what has this actually been doing" without being parsed.
 */
export function TickerAnalysis({
  data,
  item,
}: Pick<TickerDetailProps, 'data' | 'item'>) {
  return (
    <>
      {/* ── Bull / bear ───────────────────────────────────────────────────── */}
      {(data.bull_case || data.bear_case
        || data.bull_points?.length || data.bear_points?.length
        || data.catalysts?.length || data.key_risks?.length) && (
        <div className="grid gap-px border-b border-[var(--color-border)] bg-[var(--color-border)] lg:grid-cols-2">
          <CasePanel
            label="Bull case"
            colour="var(--accent-buy)"
            points={data.bull_points ?? []}
            prose={data.bull_case}
            extraLabel="Catalysts"
            extra={data.catalysts ?? []}
          />
          <CasePanel
            label="Bear case"
            colour="var(--accent-sell)"
            points={data.bear_points ?? []}
            prose={data.bear_case}
            extraLabel="Key risks"
            extra={data.key_risks ?? []}
          />
        </div>
      )}

      {/* ── Chart ─────────────────────────────────────────────────────────── */}
      <div className="border-b border-[var(--color-border)] px-[18px] py-3.5">
        <Suspense
          fallback={
            <div className="flex h-[260px] items-center justify-center">
              <LoadingSpinner size="md" />
            </div>
          }
        >
          <PriceChart
            ticker={data.ticker}
            stopLoss={data.stop_loss}
            priceTarget={data.price_target}
            height={260}
          />
        </Suspense>
      </div>

      {/* ── Timing ────────────────────────────────────────────────────────── */}
      <div className="border-b border-[var(--color-border)] px-[18px] py-3.5">
        <Collapsible title="Timing indicators">
          {item ? (
            <TimingTiles item={item} />
          ) : (
            <p className="rounded-[7px] border border-[var(--color-border)] px-3 py-2 text-[11px]
                          text-[var(--color-fg-muted)]">
              Timing indicators are computed for watched tickers only. Add {data.ticker} to your
              watchlist to see RSI, Stochastic RSI, Bollinger position and volume anomaly here.
            </p>
          )}
        </Collapsible>
      </div>

      {/* ── Score attribution + risk gate ─────────────────────────────────
          Both closed now. They are the workings behind the score in the header
          and the gate chip beside it — the answer is already above the fold,
          and this is where a reader goes when they want to argue with it. */}
      <div className="grid gap-px border-b border-[var(--color-border)] bg-[var(--color-border)] lg:grid-cols-2">
        <section className="min-w-0 bg-[var(--color-bg)] px-[18px] py-3.5">
          {data.breakdown ? (
            <Collapsible title="How the score was built">
              <FactorBreakdown breakdown={data.breakdown} inputs={data.inputs} />
            </Collapsible>
          ) : (
            <>
              <div className="label-micro">How the score was built</div>
              <p className="mt-2 text-[11.5px] text-[var(--color-fg-muted)]">
                No attribution was returned for this analysis.
              </p>
            </>
          )}
        </section>

        <section className="min-w-0 bg-[var(--color-bg)] px-[18px] py-3.5">
          {data.risk ? (
            <Collapsible title="Risk and the buy gate">
              <RiskPanel risk={data.risk} gate={data.gate} signal={data.signal} score={data.score} />
            </Collapsible>
          ) : (
            <>
              <div className="label-micro">Risk and the buy gate</div>
              <p className="mt-2 text-[11.5px] text-[var(--color-fg-muted)]">
                No risk assessment was returned for this analysis.
              </p>
            </>
          )}
        </section>
      </div>

      {/* ── Deep research ──────────────────────────────────────────────────
          A second, slower opinion than the 5-minute signal above, and a
          different kind of claim: everything in it is sourced to a dated fact
          in the evidence ledger, because anything that was not got deleted
          before it was stored. Collapsed by default — it is long, and it is
          not what a reader glancing at the ticker came for. */}
      <div className="border-b border-[var(--color-border)] px-[18px] py-3.5">
        <Collapsible title="Deep research">
          <ResearchPanel ticker={data.ticker} />
        </Collapsible>
      </div>

      {/* ── Everything the three-column layout has no room for ─────────────
          Collapsed rather than dropped. The redesign trims the default view;
          it does not remove analysis the engine paid to produce. */}
      <div className="flex flex-col gap-4 border-b border-[var(--color-border)] px-[18px] py-3.5">
        {data.analyst_note && (
          <Collapsible title="Analyst note">
            <p className="whitespace-pre-wrap text-[12.5px] leading-relaxed text-[var(--color-fg-muted)]">
              {data.analyst_note}
            </p>
          </Collapsible>
        )}

        {(data.entry_suggestion || data.exit_suggestion) && (
          <Collapsible title="Entry and exit">
            <div className="flex flex-col gap-2.5">
              {data.entry_suggestion && (
                <div>
                  <span className="text-[10px] font-semibold uppercase tracking-wide text-[var(--accent-buy)]">
                    Entry
                  </span>
                  <p className="mt-0.5 text-[12.5px] leading-relaxed">{data.entry_suggestion}</p>
                </div>
              )}
              {data.exit_suggestion && (
                <div>
                  <span className="text-[10px] font-semibold uppercase tracking-wide text-[var(--accent-sell)]">
                    Exit
                  </span>
                  <p className="mt-0.5 text-[12.5px] leading-relaxed">{data.exit_suggestion}</p>
                </div>
              )}
            </div>
          </Collapsible>
        )}

        {data.alternative_data && (
          <Collapsible title="Alternative data">
            <AltDataPanel data={data.alternative_data} />
          </Collapsible>
        )}

        {data.explanation && data.explanation !== whyText(data) && (
          <Collapsible title="Full explanation">
            <p className="whitespace-pre-wrap text-[12.5px] leading-relaxed text-[var(--color-fg-muted)]">
              {data.explanation}
            </p>
          </Collapsible>
        )}

        <Collapsible title="Where the inputs come from">
          <SourcesPanel data={data} />
        </Collapsible>
      </div>

      <Disclaimer compact />
    </>
  )
}


// ── Analysis sources ──────────────────────────────────────────────────────────
//
// Three states, not two. "Dev data" exists because yfinance is licensed for
// personal and development use only — badging it Live claimed a production
// data pipeline this deployment does not have, which is a licensing question
// rather than a cosmetic one.

type SourceStatus = 'live' | 'dev' | 'thin' | 'off' | 'planned'

const STATUS_LABEL: Record<SourceStatus, string> = {
  live: 'Live', dev: 'Dev data', thin: 'Thin', off: 'Off', planned: 'Soon',
}

const STATUS_TONE: Record<SourceStatus, { bg: string; fg: string }> = {
  live: { bg: 'var(--tint-buy)', fg: 'var(--accent-buy)' },
  dev: { bg: 'var(--tint-hold)', fg: 'var(--accent-hold)' },
  // A source that answered with less than it should. Warning-toned, because it
  // is a real fact about the number above it.
  thin: { bg: 'var(--tint-hold)', fg: 'var(--accent-hold)' },
  // Not configured. Deliberately NOT the sell tone: an absent key is a choice,
  // not a fault, and painting it red is how a panel like this stops being read.
  off: { bg: 'var(--color-hover)', fg: 'var(--color-fg-muted)' },
  planned: { bg: 'var(--color-hover)', fg: 'var(--color-fg-muted)' },
}

/**
 * How a factor's measured share reads as a badge.
 *
 * `dev` survives as its own state and is not derived from health at all: it is
 * a *licensing* statement about yfinance, not an availability one, and a source
 * can be simultaneously working perfectly and unlicensed for production.
 */
function stateBadge(
  inputs: SignalInputs | null | undefined,
  key: string,
  whenMeasured: SourceStatus = 'live',
): SourceStatus {
  const factor = inputs?.factors?.find((f) => f.key === key)
  if (!factor) return whenMeasured
  if (factor.state === 'fallback') return 'off'
  if (factor.state === 'partial') return 'thin'
  return whenMeasured
}

/** The note a factor's own coverage earns, appended to the editorial prose. */
function stateNote(inputs: SignalInputs | null | undefined, key: string): string {
  const factor = inputs?.factors?.find((f) => f.key === key)
  if (!factor) return ''
  if (factor.state === 'fallback') {
    return ' Not available for this report — the factor sits at a neutral 0.50 and says nothing about this company.'
  }
  if (factor.state === 'partial') {
    return ` Partial for this report (${Math.round(factor.coverage * 100)}% of its inputs); the rest is blended toward neutral.`
  }
  return ''
}

function analystSource(data: AnalyzeResponse): { label: string; value: string; status: SourceStatus } {
  // Read from the response rather than hardcoded here — a previous literal
  // said "Claude Sonnet 4.6" while the server was calling something else.
  if (!data.analyst_model) {
    return {
      label: 'AI Analyst',
      value: 'Disabled on this server — signals come from the rule-based scoring path.',
      status: 'planned',
    }
  }
  return {
    label: 'AI Analyst',
    value: `${data.analyst_model} (Anthropic) — synthesises all the above into signal, thesis, price target, and research note.`
      + (data.analyst_used ? '' : ' Not used for this report: the rule-based path produced it.'),
    status: data.analyst_used ? 'live' : 'planned',
  }
}

/**
 * Where the inputs came from — reported, not asserted.
 *
 * Every row here used to be a literal, so the panel claimed Finnhub and FRED
 * were "Live" on a server that might hold neither key, and would have gone on
 * calling the price feed "Dev data" after a switch to a licensed provider. It
 * was an active falsehood sitting directly beneath the score it described.
 *
 * The editorial prose stays hardcoded — it is a description of what a provider
 * supplies and no server field should own it. What the *server* now decides is
 * the badge and the per-report note, read from `data.inputs`.
 *
 * Deliberately driven by the per-signal payload rather than `/system/status`:
 * this panel sits under "where the inputs came from" for *this report*, and a
 * cached analyst verdict from an hour ago was built on the data of an hour ago.
 * A source that failed at 09:35 and recovered at 10:00 must still read as
 * absent on the 09:35 report, which is exactly what a global status view would
 * get wrong.
 *
 * `planned` rows stay literal: they describe things that do not exist, and no
 * server field can say anything about them.
 */
function SourcesPanel({ data }: { data: AnalyzeResponse }) {
  const inputs = data.inputs
  const priceLive: SourceStatus =
    data.data_sources?.price === 'polygon' ? 'live' : 'dev'

  const sources: { label: string; value: string; status: SourceStatus }[] = [
    {
      label: 'Price & market data',
      value: (priceLive === 'dev'
        ? 'Yahoo Finance — 90 days OHLCV, current price, day change'
        : 'Polygon (via Massive) — 90 days OHLCV, current price, day change')
        + '. The one input that can stop a cycle: without bars there is no score and no order.',
      status: priceLive,
    },
    { label: 'Financial statements', value: 'Massive (Polygon.io) — up to 12 annual and 12 quarterly filings per ticker, accumulated over time so margin trends and CAGRs are computable' + stateNote(inputs, 'fundamental'), status: stateBadge(inputs, 'fundamental') },
    { label: 'Company profile & ratios', value: 'Alpha Vantage OVERVIEW — business description, sector, forward P/E, EV/EBITDA, margins, ROE/ROA, beta, 52-week range, analyst consensus', status: stateBadge(inputs, 'fundamental') },
    { label: 'Earnings record', value: 'Alpha Vantage EARNINGS — reported vs estimated EPS by quarter, surprise history, and the next scheduled report date', status: stateBadge(inputs, 'catalyst') },
    { label: 'News & sentiment', value: 'Finnhub — last 7 days of headlines with publisher, date and link, scored locally with VADER NLP. Headline text only; article bodies are not retrieved' + stateNote(inputs, 'sentiment'), status: stateBadge(inputs, 'sentiment') },
    { label: 'Macro environment', value: 'FRED — Fed funds rate, 10Y/2Y Treasuries, CPI, unemployment, VIX' + stateNote(inputs, 'macro'), status: stateBadge(inputs, 'macro') },
    { label: 'Options flow', value: 'Yahoo Finance — nearest-expiry put/call volume ratio only, not open interest' + stateNote(inputs, 'alternative_data'), status: stateBadge(inputs, 'alternative_data', 'dev') },
    { label: 'Short interest', value: 'Yahoo Finance — % of float shorted and days-to-cover. Usually unavailable from this host', status: 'dev' },
    { label: 'Insider activity', value: 'Yahoo Finance (Form 4) — buy/sell counts over the most recent filed transactions. Not a date-bounded window and not dollar-weighted', status: stateBadge(inputs, 'alternative_data', 'dev') },
    analystSource(data),
    { label: 'Deep research agents', value: 'Four scoped analysts over one sourced evidence ledger, merged by a fifth. Every claim it makes cites a dated fact; uncited claims are deleted before storage', status: 'live' },
    { label: 'Institutional ownership', value: '13F holdings and ownership changes — not carried by any configured provider', status: 'planned' },
    { label: 'Earnings transcripts', value: 'Management guidance and earnings-call commentary — no configured provider supplies these, so the earnings analysis stops at estimates versus actuals', status: 'planned' },
    { label: 'SEC filings', value: 'EDGAR — 10-K/10-Q risk factors and Form 4 detail, which would also make citations document-level rather than provider-level', status: 'planned' },
    { label: 'Peer screening', value: 'A real comparable universe. Peers shown in research are drawn from your own watchlist plus a small static map — a convenience, not a screen', status: 'planned' },
    { label: 'Intraday & options', value: 'Polygon.io — intraday price data and live options flow', status: 'planned' },
    { label: 'ML scoring model', value: 'XGBoost — trained on signal history with real fundamental + sentiment features', status: 'planned' },
  ]

  return (
    <div className="flex flex-col gap-2.5">
      {sources.map(({ label, value, status }) => (
        <div key={label} className="flex items-start gap-2.5">
          <span
            className="mt-px flex-shrink-0 rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide"
            style={{ background: STATUS_TONE[status].bg, color: STATUS_TONE[status].fg }}
          >
            {STATUS_LABEL[status]}
          </span>
          <div className="min-w-0">
            <span className="text-[11.5px] font-medium text-[var(--color-fg)]">{label}</span>
            <p className="mt-px text-[11px] leading-snug text-[var(--color-fg-muted)]">{value}</p>
          </div>
        </div>
      ))}

      <p className="flex items-start gap-2 text-[10.5px] leading-relaxed text-[var(--accent-hold)]">
        <AlertCircle className="mt-0.5 h-3 w-3 flex-shrink-0" aria-hidden="true" />
        <span>
          <strong>Evaluation data.</strong> Rows marked <em>Dev data</em> come from yfinance,
          which is licensed for personal and development use only. Production deployment
          requires a commercial market-data provider.
        </span>
      </p>
    </div>
  )
}
