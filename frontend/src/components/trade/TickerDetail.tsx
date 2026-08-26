import { Suspense, lazy, useState } from 'react'
import {
  AlertCircle,
  Check,
  ChevronDown,
  ChevronUp,
  Download,
  Mail,
  Plus,
  RefreshCw,
  Trash2,
} from 'lucide-react'
import type {
  AnalyzeResponse,
  Holding,
  TradeRecord,
  WatchlistItem,
} from '../../types'
import { relativeTime } from '../../lib/format'
import { downloadPdf, downloadTxt, emailReport } from '../../lib/report'
import { SOURCE_DESCRIPTION, tradeSource } from '../../lib/trade-source'
import { Disclaimer } from '../Layout'
import ConvictionBadge from '../ConvictionBadge'
import FactorBreakdown from '../FactorBreakdown'
import LoadingSpinner from '../LoadingSpinner'
import Menu, { MenuItem } from '../Menu'
import RiskPanel from '../RiskPanel'
import SignalBadge from '../SignalBadge'
import AltDataPanel from './AltDataPanel'

// Split out: the charting library is ~200 kB and this is the only screen that
// draws one. Bundled eagerly it loaded on screens that have no chart.
const PriceChart = lazy(() => import('../PriceChart'))

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

// ── Why ───────────────────────────────────────────────────────────────────────

/**
 * The plain-English line above the numbers.
 *
 * Prefers the model's own words. Where there are none it derives a sentence
 * from the gate the engine actually applied — never invents a rationale, which
 * on a screen that routes orders would be the worst possible place to do it.
 */
function whyText(data: AnalyzeResponse): string {
  const own = data.thesis?.trim() || data.explanation?.trim()
  if (own) return own

  const score = Math.round(data.score * 100)
  if (!data.gate) return `${data.signal} at ${score}/100. No further rationale was recorded.`

  const buy = Math.round(data.gate.buy_threshold * 100)
  const sell = Math.round(data.gate.sell_threshold * 100)

  if (data.signal === 'BUY') {
    return `Scored ${score}/100, clearing the ${buy} needed to buy, and risk stayed under the veto.`
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

// ── Detail ────────────────────────────────────────────────────────────────────

interface TickerDetailProps {
  data: AnalyzeResponse
  item: WatchlistItem | null
  holding: Holding | null
  position: TradeRecord | null
  watched: boolean
  refreshing: boolean
  onRefresh: () => void
  onWatch: () => void
  onUnwatch: () => void
}

export default function TickerDetail({
  data,
  item,
  holding,
  position,
  watched,
  refreshing,
  onRefresh,
  onWatch,
  onUnwatch,
}: TickerDetailProps) {
  const chg = data.day_change_pct
  const tone = whyTone(data.signal)

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
              {data.ticker}
            </h1>
            <SignalBadge signal={data.signal} size="lg" />
            {data.conviction && <ConvictionBadge conviction={data.conviction} />}
          </div>
          <div className="mt-0.5 text-[11.5px] text-[var(--color-fg-muted)]">
            {data.time_horizon ? `${data.time_horizon} horizon · ` : ''}
            scored {relativeTime(data.generated_at)}
            {data.confidence != null ? ` · ${Math.round(data.confidence * 100)}% confidence` : ''}
          </div>
        </div>

        <div className="flex items-baseline gap-2.5">
          <span className="num text-[26px] font-semibold">
            {data.current_price != null ? usd.format(data.current_price) : '—'}
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

        {holding && <PositionBlock holding={holding} position={position} />}

        <ScoreBar data={data} />

        <div className="flex w-full items-center gap-1.5">
          <button
            onClick={watched ? onUnwatch : onWatch}
            className="chip"
            aria-label={watched ? `Remove ${data.ticker} from watchlist` : `Add ${data.ticker} to watchlist`}
          >
            {watched
              ? <><Check className="h-3 w-3" aria-hidden="true" /> Watching</>
              : <><Plus className="h-3 w-3" aria-hidden="true" /> Watch</>}
          </button>

          <button onClick={onRefresh} disabled={refreshing} className="chip disabled:opacity-40">
            <RefreshCw className={`h-3 w-3 ${refreshing ? 'animate-spin' : ''}`} aria-hidden="true" />
            {refreshing ? 'Refreshing…' : 'Re-analyse'}
          </button>

          <Menu
            label="Export report"
            align="left"
            triggerClassName="chip"
            trigger={<><Download className="h-3 w-3" aria-hidden="true" /> Export</>}
          >
            {(close) => (
              <>
                <MenuItem onClick={() => { close(); downloadPdf(data) }}>Download PDF</MenuItem>
                <MenuItem onClick={() => { close(); downloadTxt(data) }}>Download .txt</MenuItem>
                <MenuItem onClick={() => { close(); emailReport(data) }}>
                  <span className="flex items-center gap-2.5">
                    <Mail className="h-3.5 w-3.5 text-[var(--color-fg-muted)]" aria-hidden="true" />
                    Email report
                  </span>
                </MenuItem>
              </>
            )}
          </Menu>

          {watched && (
            <button
              onClick={onUnwatch}
              className="chip ml-auto hover:!text-[var(--accent-sell)]"
              aria-label={`Remove ${data.ticker} from watchlist`}
            >
              <Trash2 className="h-3 w-3" aria-hidden="true" />
              Remove
            </button>
          )}
        </div>
      </div>

      {/* ── Why ───────────────────────────────────────────────────────────── */}
      <div
        className="flex items-start gap-3 border-b border-[var(--color-border)] px-[18px] py-3"
        style={{ background: tone.bg }}
      >
        <span className="label-micro flex-shrink-0 pt-0.5" style={{ color: tone.fg }}>Why</span>
        <p className="m-0 max-w-[66ch] text-[14px] leading-relaxed text-[var(--color-fg)]">
          {whyText(data)}
        </p>
      </div>

      {/* ── Chart + timing ────────────────────────────────────────────────── */}
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

        {item ? (
          <TimingTiles item={item} />
        ) : (
          <p className="mt-3 rounded-[7px] border border-[var(--color-border)] px-3 py-2 text-[11px]
                        text-[var(--color-fg-muted)]">
            Timing indicators are computed for watched tickers only. Add {data.ticker} to your
            watchlist to see RSI, Stochastic RSI, Bollinger position and volume anomaly here.
          </p>
        )}
      </div>

      {/* ── Score attribution + risk gate ─────────────────────────────────── */}
      <div className="grid gap-px border-b border-[var(--color-border)] bg-[var(--color-border)] lg:grid-cols-2">
        <section className="min-w-0 bg-[var(--color-bg)] px-[18px] py-3.5">
          {data.breakdown ? (
            <Collapsible title="How the score was built" defaultOpen>
              <FactorBreakdown breakdown={data.breakdown} />
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
          <div className="label-micro mb-2.5">Risk and the buy gate</div>
          {data.risk ? (
            <RiskPanel risk={data.risk} gate={data.gate} signal={data.signal} score={data.score} />
          ) : (
            <p className="text-[11.5px] text-[var(--color-fg-muted)]">
              No risk assessment was returned for this analysis.
            </p>
          )}
        </section>
      </div>

      {/* ── Bull / bear ───────────────────────────────────────────────────── */}
      {(data.bull_case || data.bear_case || data.catalysts?.length || data.key_risks?.length) && (
        <div className="grid gap-px border-b border-[var(--color-border)] bg-[var(--color-border)] lg:grid-cols-2">
          <section className="bg-[var(--color-bg)] px-[18px] py-3.5">
            <div className="label-micro text-[var(--accent-buy)]">Bull case</div>
            {data.bull_case && (
              <p className="mt-2 text-[12.5px] leading-relaxed">{data.bull_case}</p>
            )}
            {data.catalysts && data.catalysts.length > 0 && (
              <>
                <div className="label-micro mt-3">Catalysts</div>
                <ul className="mt-1.5 flex list-disc flex-col gap-1 pl-4 text-[12px]">
                  {data.catalysts.map((c, i) => <li key={i}>{c}</li>)}
                </ul>
              </>
            )}
          </section>

          <section className="bg-[var(--color-bg)] px-[18px] py-3.5">
            <div className="label-micro text-[var(--accent-sell)]">Bear case</div>
            {data.bear_case && (
              <p className="mt-2 text-[12.5px] leading-relaxed">{data.bear_case}</p>
            )}
            {data.key_risks && data.key_risks.length > 0 && (
              <>
                <div className="label-micro mt-3">Key risks</div>
                <ul className="mt-1.5 flex list-disc flex-col gap-1 pl-4 text-[12px]">
                  {data.key_risks.map((r, i) => <li key={i}>{r}</li>)}
                </ul>
              </>
            )}
          </section>
        </div>
      )}

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

type SourceStatus = 'live' | 'dev' | 'planned'

const STATUS_LABEL: Record<SourceStatus, string> = { live: 'Live', dev: 'Dev data', planned: 'Soon' }

const STATUS_TONE: Record<SourceStatus, { bg: string; fg: string }> = {
  live: { bg: 'var(--tint-buy)', fg: 'var(--accent-buy)' },
  dev: { bg: 'var(--tint-hold)', fg: 'var(--accent-hold)' },
  planned: { bg: 'var(--color-hover)', fg: 'var(--color-fg-muted)' },
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

function SourcesPanel({ data }: { data: AnalyzeResponse }) {
  const sources: { label: string; value: string; status: SourceStatus }[] = [
    { label: 'Price & market data', value: 'Yahoo Finance — 90 days OHLCV, current price, day change', status: 'dev' },
    { label: 'Fundamentals', value: 'Yahoo Finance — P/E, revenue growth, FCF, debt/equity, analyst consensus', status: 'dev' },
    { label: 'News & sentiment', value: 'Finnhub — last 7 days of headlines, scored locally with VADER NLP', status: 'live' },
    { label: 'Macro environment', value: 'FRED — Fed funds rate, 10Y/2Y Treasuries, CPI, unemployment, VIX', status: 'live' },
    { label: 'Options flow', value: 'Yahoo Finance — nearest-expiry put/call ratio across the full chain', status: 'dev' },
    { label: 'Short interest', value: 'Yahoo Finance — % of float shorted, days-to-cover, squeeze risk', status: 'dev' },
    { label: 'Insider activity', value: 'Yahoo Finance (Form 4) — buy/sell counts over 90 days', status: 'dev' },
    analystSource(data),
    { label: 'Real-time news NLP', value: 'NewsAPI + Reddit sentiment — broader news search and retail sentiment', status: 'planned' },
    { label: 'SEC filings', value: 'EDGAR — 10-K/10-Q filings and earnings call transcripts', status: 'planned' },
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
