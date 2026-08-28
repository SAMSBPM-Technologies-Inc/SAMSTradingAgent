import React, { useEffect, useRef } from 'react'
import { ExternalLink, X } from 'lucide-react'
import type { AnalyzeResponse, Holding, TradeRecord, WatchlistItem } from '../../types'
import LoadingSpinner from '../LoadingSpinner'
import { TickerAnalysis, TickerHeader } from './TickerDetail'

/**
 * The analysis, over the dashboard.
 *
 * Selecting a ticker used to replace the whole centre column, which meant the
 * dashboard — positions, the agent's entries, the approvals queue — was
 * destroyed to read about one name and rebuilt on the way back. An overlay
 * keeps the thing you were working through underneath, so closing costs
 * nothing and loses no scroll position.
 *
 * It is driven by the route (`/ticker/:symbol`), not by local state, so a
 * selection is still deep-linkable and Back still walks the names you looked
 * at. The ⧉ control opens `/analysis/:symbol` in a new window — the same
 * analysis with no dashboard around it, for reading two names side by side.
 */

interface Props {
  symbol: string
  data: AnalyzeResponse | null
  item: WatchlistItem | null
  holding: Holding | null
  position: TradeRecord | null
  watched: boolean
  loading: boolean
  refreshing: boolean
  error: string | null
  onRefresh: () => void
  onWatch: () => void
  onUnwatch: () => void
  onRetry: () => void
  onClose: () => void
  /**
   * The order ticket. It belongs inside the dialog rather than in the rail
   * behind it: the ticket is *about* the name being read, and with a full-height
   * sheet over the screen a ticket in the rail is both invisible and unusable.
   */
  footer?: React.ReactNode
}

export default function AnalysisOverlay({
  symbol, data, item, holding, position, watched,
  loading, refreshing, error,
  onRefresh, onWatch, onUnwatch, onRetry, onClose, footer,
}: Props) {
  const panelRef = useRef<HTMLDivElement>(null)

  // Escape closes from anywhere inside, including the order ticket's inputs.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // The page behind must not scroll while a full-height sheet is over it —
  // otherwise a trackpad flick moves the dashboard, not the report being read.
  useEffect(() => {
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = prev }
  }, [])

  // Move focus into the dialog on open so a keyboard user is not left on the
  // row they clicked, behind the backdrop.
  useEffect(() => { panelRef.current?.focus() }, [symbol])

  /**
   * Keep Tab inside the dialog — the WAI-ARIA authoring practice for a modal.
   * The a11y rule classes `dialog` as non-interactive and has no way to express
   * the exception, which is why the suppression below is written out.
   */
  const onTrapKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== 'Tab') return
    const focusable = panelRef.current?.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )
    if (!focusable?.length) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    }
  }

  return (
    <div className="fixed inset-0 z-[70] flex items-start justify-center px-0 py-0 sm:px-4 sm:py-[4vh]">
      <button
        type="button"
        aria-label={`Close ${symbol} analysis`}
        className="absolute inset-0 cursor-default bg-black/55 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={`${symbol} analysis`}
        tabIndex={-1}
        onKeyDown={onTrapKeyDown}
        className="relative flex h-full w-full max-w-[980px] flex-col overflow-hidden
                   border-[var(--color-border)] bg-[var(--color-bg)] outline-none
                   sm:h-auto sm:max-h-[92vh] sm:rounded-[12px] sm:border"
        style={{ boxShadow: '0 24px 70px rgba(0,0,0,.5)' }}
      >
        {/* Controls sit above the scrolling body so they stay reachable in a
            long report — the close button scrolling away is how a modal traps
            someone on a phone. */}
        <div className="flex items-center justify-end gap-1.5 border-b border-[var(--color-border)]
                        bg-[var(--color-surface)] px-2.5 py-1.5">
          <button
            onClick={() => window.open(`/analysis/${symbol}`, '_blank', 'noopener')}
            className="chip touch-target"
            title={`Open ${symbol} analysis in a new window`}
          >
            <ExternalLink className="h-3 w-3" aria-hidden="true" />
            New window
          </button>
          <button
            onClick={onClose}
            aria-label="Close analysis"
            className="grid h-9 w-9 place-items-center rounded text-[var(--color-fg-muted)]
                       hover:bg-[var(--color-hover)] hover:text-[var(--color-fg)]"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center py-24">
              <LoadingSpinner size="lg" />
            </div>
          ) : error ? (
            <div className="flex flex-col items-center gap-4 px-6 py-20 text-center">
              <p className="text-sm text-[var(--color-fg-muted)]">{error}</p>
              <button onClick={onRetry} className="btn-secondary">Try again</button>
            </div>
          ) : data ? (
            <>
              <TickerHeader
                data={data}
                holding={holding}
                position={position}
                watched={watched}
                refreshing={refreshing}
                onRefresh={onRefresh}
                onWatch={onWatch}
                onUnwatch={onUnwatch}
              />
              <TickerAnalysis data={data} item={item} />
              {footer}
            </>
          ) : null}
        </div>
      </div>
    </div>
  )
}
