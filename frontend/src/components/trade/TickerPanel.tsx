import React from 'react'
import { ArrowLeft, ExternalLink } from 'lucide-react'
import type { AnalyzeResponse, Holding, Quote, TradeRecord, WatchlistItem } from '../../types'
import AnalysisProgress from './AnalysisProgress'
import { TickerAnalysis, TickerHeader } from './TickerDetail'

/**
 * One name's analysis, in the centre column.
 *
 * This was a modal over the dashboard. It stopped being one for the same reason
 * the transaction detail never became one: the things a reader wants beside an
 * analysis — what is held, what has been traded on this name — are what a
 * backdrop covers up. The centre column is a routed region now, and this is one
 * of its three states.
 *
 * It is driven by the route (`/ticker/:symbol`), not by local state, so a
 * selection stays deep-linkable and Back walks the names you looked at. The ⧉
 * control opens `/analysis/:symbol` in a new window — the same analysis with no
 * dashboard around it, for reading two names side by side.
 *
 * The two loading states are separate on purpose. `loading` is the stored read,
 * which is a Mongo lookup and shows a spinner nobody notices. `analysing` is
 * the explicit full run, which is the whole pipeline plus an analyst call, and
 * is the only thing that earns the staged progress display.
 */

interface Props {
  symbol: string
  data: AnalyzeResponse | null
  quote: Quote | null
  item: WatchlistItem | null
  holding: Holding | null
  position: TradeRecord | null
  watched: boolean
  /** Reading the stored analysis. Fast; no pipeline involved. */
  loading: boolean
  /** The explicit full run is in flight. */
  analysing: boolean
  /** Nothing has ever been analysed for this ticker. Not an error. */
  neverAnalysed: boolean
  error: string | null
  onRunAnalysis: () => void
  onWatch: () => void
  onUnwatch: () => void
  onRetry: () => void
  onClose: () => void
  /**
   * The order ticket. It belongs under the analysis rather than in the rail:
   * the ticket is *about* the name being read, and the rail is where the
   * account-wide queues live.
   */
  footer?: React.ReactNode
}

export default function TickerPanel({
  symbol, data, quote, item, holding, position, watched,
  loading, analysing, neverAnalysed, error,
  onRunAnalysis, onWatch, onUnwatch, onRetry, onClose, footer,
}: Props) {
  return (
    <div className="overflow-hidden rounded-lg border border-[var(--color-border)]
                    bg-[var(--color-bg)]">
      <div className="flex items-center gap-1.5 border-b border-[var(--color-border)]
                      bg-[var(--color-surface)] px-2.5 py-1.5">
        <button onClick={onClose} className="chip touch-target">
          <ArrowLeft className="h-3 w-3" aria-hidden="true" />
          Dashboard
        </button>
        <button
          onClick={() => window.open(`/analysis/${symbol}`, '_blank', 'noopener')}
          className="chip touch-target ml-auto"
          title={`Open ${symbol} analysis in a new window`}
        >
          <ExternalLink className="h-3 w-3" aria-hidden="true" />
          New window
        </button>
      </div>

      {/* The header paints as soon as the quote lands, so a name with no stored
          analysis is still a page with a price on it rather than a spinner. */}
      <TickerHeader
        symbol={symbol}
        data={data}
        quote={quote}
        holding={holding}
        position={position}
        watched={watched}
        analysing={analysing}
        onRunAnalysis={onRunAnalysis}
        onWatch={onWatch}
        onUnwatch={onUnwatch}
      />

      {analysing ? (
        <AnalysisProgress ticker={symbol} />
      ) : loading ? (
        <p className="px-[18px] py-10 text-center text-sm text-[var(--color-fg-muted)]">
          Reading the last analysis…
        </p>
      ) : error ? (
        <div className="flex flex-col items-center gap-4 px-6 py-16 text-center">
          <p className="text-sm text-[var(--color-fg-muted)]">{error}</p>
          <button onClick={onRetry} className="btn-secondary">Try again</button>
        </div>
      ) : neverAnalysed ? (
        <div className="flex flex-col items-center gap-3 px-6 py-16 text-center">
          <p className="m-0 text-sm text-[var(--color-fg)]">
            No in-depth analysis has been run for {symbol}.
          </p>
          <p className="m-0 max-w-[46ch] text-[12px] leading-relaxed text-[var(--color-fg-muted)]">
            The price above is live. Scoring the name means fetching prices,
            news, fundamentals and macro data and putting an analyst over the
            result — tens of seconds of work, so it happens when you ask for it.
          </p>
          <button onClick={onRunAnalysis} className="btn-primary">Run full analysis</button>
        </div>
      ) : data ? (
        <>
          <TickerAnalysis data={data} item={item} />
          {footer}
        </>
      ) : null}
    </div>
  )
}
