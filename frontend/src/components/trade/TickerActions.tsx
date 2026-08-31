import { Check, Download, Mail, Plus, RefreshCw, Trash2 } from 'lucide-react'
import type { AnalyzeResponse } from '../../types'
import { downloadPdf, downloadTxt, emailReport } from '../../lib/report'
import { useToast } from '../../lib/toast-context'
import { useAuth } from '../../lib/auth-context'
import { entitlementsOf } from '../../lib/entitlements'
import Menu, { MenuItem } from '../Menu'

/**
 * Everything you can *do* to the name being read.
 *
 * These four controls used to sit in a row directly beneath the verdict, which
 * put the two irreversible ones — Remove, and a pipeline run that costs an
 * analyst call — in the path of a reader's eye on the way from the signal to
 * the reasoning. The centre column answers "what is this name and why"; the
 * right column is where acting on it lives, and the order ticket is already
 * there. Actions are now in one place rather than two.
 *
 * `layout` exists because `/analysis/:symbol` has no right column — it is
 * deliberately one name and nothing else, opened twice and put side by side —
 * so there the controls stay inline under the header. That window also has no
 * watchlist to mutate, which is why `onWatch`/`onUnwatch` are optional rather
 * than stubbed: a control that silently does nothing is worse than an absent
 * one.
 */

interface Props {
  symbol: string
  data: AnalyzeResponse | null
  watched: boolean
  /** The explicit full run is in flight. */
  analysing: boolean
  onRunAnalysis: () => void
  /** Omitted where there is no watchlist on screen to keep in step. */
  onWatch?: () => void
  onUnwatch?: () => void
  /** `rail` stacks full-width; `inline` is a single row. */
  layout?: 'rail' | 'inline'
}

export default function TickerActions({
  symbol,
  data,
  watched,
  analysing,
  onRunAnalysis,
  onWatch,
  onUnwatch,
  layout = 'rail',
}: Props) {
  const { toast } = useToast()
  const { user } = useAuth()
  const maySpend = entitlementsOf(user).may_spend_tokens

  /**
   * Run an export and report a failure.
   *
   * These used to be bare calls in the menu handler, so the promise floated:
   * if `import('jspdf')` never resolved — a stale chunk hash after a deploy is
   * the usual way — the click did nothing at all and left no trace. A silent
   * no-op on a button is indistinguishable from a broken app.
   */
  const runExport = async (fn: () => void | Promise<void>, what: string) => {
    try {
      await fn()
    } catch (err) {
      console.error(`${what} export failed`, err)
      toast(`Could not produce the ${what} export.`, 'error')
    }
  }

  const rail = layout === 'rail'
  const wrap = rail
    ? 'flex flex-col gap-1.5'
    : 'flex flex-wrap items-center gap-1.5'
  const wide = rail ? 'w-full justify-center' : ''

  const watchlistControls = watched
    ? (
      // One control, not two. The old row carried a "Watching ✓" toggle *and* a
      // trash button, both bound to the same unwatch handler — so the state
      // readout was itself a way to destroy the row it was reporting on. The
      // state is now a state, and removing is a button that says so.
      <>
        <span
          className={`chip pointer-events-none ${wide}`}
          style={{ background: 'var(--tint-buy)', color: 'var(--accent-buy)' }}
        >
          <Check className="h-3 w-3" aria-hidden="true" />
          On your watchlist
        </span>
        {onUnwatch && (
          <button
            onClick={onUnwatch}
            className={`chip touch-target hover:!text-[var(--accent-sell)] ${wide}`}
            aria-label={`Remove ${symbol} from watchlist`}
          >
            <Trash2 className="h-3 w-3" aria-hidden="true" />
            Remove from watchlist
          </button>
        )}
      </>
    )
    : onWatch && (
      <button
        onClick={onWatch}
        className={`chip touch-target ${wide}`}
        aria-label={`Add ${symbol} to watchlist`}
      >
        <Plus className="h-3 w-3" aria-hidden="true" />
        Add to watchlist
      </button>
    )

  return (
    <div className={rail ? 'border-b border-[var(--color-border)] px-3.5 py-3' : 'px-[18px] py-2.5'}>
      {rail && <span className="label-micro">Actions — {symbol}</span>}

      <div className={`${wrap} ${rail ? 'mt-2' : ''}`}>
        {/* The only control on the client that starts a pipeline run, and
            styled as the primary action because on a name with no stored
            analysis it is the only thing to do. Everything else on this page
            is a read — which is why a plan that cannot run one still gets the
            whole page, and a sentence here rather than a missing button. */}
        {maySpend ? (
          <button
            onClick={onRunAnalysis}
            disabled={analysing}
            className={`btn-primary disabled:opacity-40 ${wide}`}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${analysing ? 'animate-spin' : ''}`} aria-hidden="true" />
            {analysing ? 'Analysing…' : data ? 'Run full analysis again' : 'Run full analysis'}
          </button>
        ) : (
          <span className="text-[11.5px] text-[var(--color-fg-muted)]">
            Running a new analysis is part of the Pro plan.
          </span>
        )}

        {watchlistControls}

        {data && (
          <Menu
            label="Export report"
            align="left"
            triggerClassName={`chip touch-target ${wide}`}
            trigger={<><Download className="h-3 w-3" aria-hidden="true" /> Export report</>}
          >
            {(close) => (
              <>
                {/* Both are fallible — the PDF lazily imports jsPDF, so a
                    chunk that fails to load surfaces here rather than as a
                    click that silently does nothing. */}
                <MenuItem onClick={() => { close(); void runExport(() => downloadPdf(data), 'PDF') }}>
                  Download PDF
                </MenuItem>
                <MenuItem onClick={() => { close(); void runExport(() => downloadTxt(data), '.txt') }}>
                  Download .txt
                </MenuItem>
                <MenuItem onClick={() => { close(); emailReport(data) }}>
                  <span className="flex items-center gap-2.5">
                    <Mail className="h-3.5 w-3.5 text-[var(--color-fg-muted)]" aria-hidden="true" />
                    Email report
                  </span>
                </MenuItem>
              </>
            )}
          </Menu>
        )}
      </div>
    </div>
  )
}
