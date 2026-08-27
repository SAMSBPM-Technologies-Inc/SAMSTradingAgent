import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { AlertCircle, PanelLeft, X } from 'lucide-react'
import { analyzeApi, tradingApi, watchlistApi } from '../lib/api'
import { useToast } from '../lib/toast-context'
import { usePoll } from '../lib/use-poll'
import type {
  AnalyzeResponse,
  Holding,
  Proposal,
  TradeRecord,
  WatchlistItem,
  WatchlistSetupCounts,
} from '../types'
import Layout from '../components/Layout'
import LoadingSpinner from '../components/LoadingSpinner'
import WatchlistRail from '../components/trade/WatchlistRail'
import { TickerAnalysis, TickerHeader } from '../components/trade/TickerDetail'
import { ActivityPanel, ApprovalsPanel, OrderPanel } from '../components/trade/TradeSidebar'

/**
 * Trade — the screen the 1.7 redesign is built around.
 *
 * It fuses what used to be four routes: the Dashboard watchlist, the Ticker
 * deep-dive, the Search lookup, and the buy half of Orders. The argument for
 * fusing them is that they were always one question asked in three places —
 * what should I do about this name, and why — and answering it used to cost two
 * navigations and lose the list you were working through.
 *
 * `/` and `/ticker/:symbol` both render this. `/` selects the first watched
 * ticker; picking a row navigates, so every selection is deep-linkable, the
 * browser Back button walks the names you looked at, and a link to a ticker you
 * do not watch still works.
 */

const EMPTY_SETUPS: WatchlistSetupCounts = { entry: 0, exit_alert: 0, neutral: 0, pending: 0 }

/** Broker positions are the truth about what is held; `trades` is our record of why. */
function useHeld() {
  const [holdings, setHoldings] = useState<Holding[]>([])
  const [positions, setPositions] = useState<TradeRecord[]>([])

  const load = useCallback(async () => {
    const [h, p] = await Promise.all([
      tradingApi.getHoldings().catch(() => null),
      tradingApi.getPositions().catch(() => null),
    ])
    setHoldings(h?.data.connected ? h.data.holdings : [])
    setPositions(p?.data ?? [])
  }, [])

  useEffect(() => { load() }, [load])

  return { holdings, positions, reloadHeld: load }
}

export default function TradePage() {
  const { symbol } = useParams<{ symbol: string }>()
  const navigate = useNavigate()
  const { toast, toastWithUndo } = useToast()

  const [items, setItems] = useState<WatchlistItem[]>([])
  const [setups, setSetups] = useState<WatchlistSetupCounts>(EMPTY_SETUPS)
  const [listLoading, setListLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState<string | null>(null)

  const [data, setData] = useState<AnalyzeResponse | null>(null)
  // Starts true: on a deep link the fetch is already in flight by first paint,
  // and rendering "Nothing selected" for one frame before it lands reads as a
  // broken screen.
  const [analysisLoading, setAnalysisLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [proposals, setProposals] = useState<Proposal[]>([])
  const [orders, setOrders] = useState<TradeRecord[]>([])

  // Below lg the three columns cannot coexist; the rail becomes a drawer.
  const [railOpen, setRailOpen] = useState(false)

  const { holdings, positions, reloadHeld } = useHeld()

  // ── Watchlist ─────────────────────────────────────────────────────────────
  const loadWatchlist = useCallback(async (background = false) => {
    // A background refresh must not raise the loading flag: the rail would
    // flash its skeleton over rows already on screen, once a minute, forever.
    if (!background) setListLoading(true)
    try {
      const { data: res } = await watchlistApi.get()
      setItems(res.items ?? [])
      setSetups(res.setups ?? EMPTY_SETUPS)
      setLastUpdated(new Date().toISOString())
    } catch {
      setItems([])
    } finally {
      setListLoading(false)
    }
  }, [])

  useEffect(() => { loadWatchlist() }, [loadWatchlist])

  // Prices, verdicts and setup triggers go stale the moment they land — the
  // pipeline rewrites them every five minutes. Reading the watchlist is a
  // Mongo lookup per ticker, cheap enough to repeat; `/analyze` is not, and is
  // deliberately excluded (see usePoll).
  usePoll(() => loadWatchlist(true), 60_000)

  // ── Proposals + order history ─────────────────────────────────────────────
  const loadAgent = useCallback(async () => {
    const [p, o] = await Promise.all([
      tradingApi.getProposals().catch(() => null),
      tradingApi.getOrders().catch(() => null),
    ])
    setProposals(p?.data ?? [])
    setOrders(o?.data ?? [])
  }, [])

  useEffect(() => { loadAgent() }, [loadAgent])

  // A proposal that appears while the tab is open should not need a reload to
  // be seen — it is the one thing on this screen that is waiting on the user.
  usePoll(loadAgent, 60_000)

  // ── Selection ─────────────────────────────────────────────────────────────
  //
  // A route symbol always wins. With no route symbol, fall back to the first
  // watched ticker — but only to *display*, without rewriting the URL, so that
  // "/" stays a stable address rather than bouncing to whatever sorted first.
  const selected = symbol?.toUpperCase() ?? items[0]?.ticker ?? null

  const loadAnalysis = useCallback(async (ticker: string, force: boolean) => {
    if (force) setRefreshing(true)
    else setAnalysisLoading(true)
    setError(null)
    try {
      const res = await analyzeApi.get(ticker, force)
      setData(res.data)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Failed to load analysis.')
      setData(null)
    } finally {
      setAnalysisLoading(false)
      setRefreshing(false)
    }
  }, [])

  // Keyed on the ticker alone. It must NOT depend on watchlist loading state:
  // every add, remove or refresh would then re-fetch the analysis and flash a
  // spinner over a pane whose contents had not changed.
  useEffect(() => {
    if (!selected) return
    loadAnalysis(selected, false)
  }, [selected, loadAnalysis])

  // Nothing to select and the list has finished loading — an empty account,
  // not a pending one. Resolved separately so it cannot retrigger the fetch.
  useEffect(() => {
    if (!selected && !listLoading) {
      setData(null)
      setAnalysisLoading(false)
    }
  }, [selected, listLoading])

  // ── Derived ───────────────────────────────────────────────────────────────
  const heldTickers = useMemo(
    () => new Set(holdings.filter((h) => h.qty !== 0).map((h) => h.ticker)),
    [holdings],
  )

  const selectedItem = useMemo(
    () => items.find((i) => i.ticker === selected) ?? null,
    [items, selected],
  )
  const selectedHolding = useMemo(
    () => holdings.find((h) => h.ticker === selected && h.qty !== 0) ?? null,
    [holdings, selected],
  )
  const selectedPosition = useMemo(
    () => positions.find((p) => p.ticker === selected && p.closed_at == null) ?? null,
    [positions, selected],
  )

  const watched = selected != null && items.some((i) => i.ticker === selected)

  // ── Actions ───────────────────────────────────────────────────────────────
  const select = (ticker: string) => {
    setRailOpen(false)
    navigate(`/ticker/${ticker}`)
  }

  const addToWatchlist = async (ticker: string) => {
    await loadWatchlist()
    toast(`${ticker} added to your watchlist.`, 'success')
    // The row exists now but has no score until the pipeline runs. Kick a
    // forced analysis so the detail pane fills in rather than sitting empty.
    analyzeApi.get(ticker, true).then(() => loadWatchlist()).catch(() => {})
    if (ticker !== selected) navigate(`/ticker/${ticker}`)
  }

  /**
   * Remove optimistically, but hold the DELETE for the length of the undo
   * window. Previously the request fired on click with no confirmation and no
   * way back — a mis-tap silently destroyed a watchlist entry.
   */
  const removeFromWatchlist = (ticker: string) => {
    const snapshot = items
    setItems((prev) => prev.filter((i) => i.ticker !== ticker))

    toastWithUndo(
      `Removed ${ticker}`,
      async () => {
        try {
          await watchlistApi.remove(ticker)
        } catch {
          toast(`Could not remove ${ticker}.`, 'error')
          setItems(snapshot)
        }
      },
      () => setItems(snapshot),
    )
  }

  const watchSelected = () => {
    if (!selected) return
    watchlistApi.add(selected)
      .then(() => addToWatchlist(selected))
      .catch(() => toast(`Could not add ${selected} to your watchlist.`, 'error'))
  }

  // The verdict and the evidence behind it are separate slots so the layout can
  // put the order ticket between them on mobile. Neither is rendered twice.
  const header = data && (
    <TickerHeader
      data={data}
      holding={selectedHolding}
      position={selectedPosition}
      watched={watched}
      refreshing={refreshing}
      onRefresh={() => selected && loadAnalysis(selected, true)}
      onWatch={watchSelected}
      onUnwatch={() => selected && removeFromWatchlist(selected)}
    />
  )

  const pending = analysisLoading ? (
    <div className="flex items-center justify-center py-24">
      <LoadingSpinner size="lg" />
    </div>
  ) : error ? (
    <ErrorState message={error} onRetry={() => selected && loadAnalysis(selected, false)} />
  ) : !data ? <EmptyState /> : null

  const rail = (
    <WatchlistRail
      items={items}
      setups={setups}
      loading={listLoading}
      selected={selected}
      heldTickers={heldTickers}
      lastUpdated={lastUpdated}
      onSelect={select}
      onRefresh={loadWatchlist}
      onAdded={addToWatchlist}
    />
  )

  const onAgentChanged = () => { loadAgent(); reloadHeld() }

  /**
   * One tree, two layouts.
   *
   * This used to be two sibling containers — `hidden lg:grid` and `lg:hidden` —
   * each rendering `body` and `sidebar`. React mounts both: every component on
   * this screen existed twice, and the invisible copy still ran its effects.
   * Measured on desktop that meant 14 canvases (two full charts), two live
   * OrderTickets each fetching `/trading/account`, and a duplicate fetch of the
   * chart series — for a copy nobody could see.
   *
   * Now each child is mounted exactly once and CSS decides where it goes: a
   * flex column below lg, a three-column grid at lg. The rail is a drawer below
   * lg by being `fixed` (out of flow) and a grid column at lg by being static.
   */
  return (
    <Layout variant="app">
      <div
        // 268px, not 246: at the old width the symbol column could not hold a
        // five-letter ticker beside its signal badge, so GOOGL rendered "GO…".
        // 22px of rail buys back the one field in the row that identifies it.
        className="flex flex-col lg:grid lg:h-[calc(100dvh-82px)]
                   lg:grid-cols-[268px_minmax(0,1fr)_296px]"
      >
        {/* ── Mobile control bar ─────────────────────────────────────────── */}
        <div
          className="sticky top-[82px] z-10 flex items-center gap-2 border-b
                     border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 lg:hidden"
        >
          <button onClick={() => setRailOpen(true)} className="chip touch-target">
            <PanelLeft className="h-3.5 w-3.5" aria-hidden="true" />
            Watchlist
            <span className="num ml-1 opacity-60">{items.length}</span>
          </button>

          {/* Was a <span>: it announced work waiting and offered no way to
              reach it, on the one layout where the queue is furthest away. */}
          {proposals.length > 0 && (
            <button
              onClick={() => {
                document.getElementById('approvals')
                  ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
              }}
              className="chip touch-target border-[var(--accent-hold)]"
              style={{ background: 'var(--tint-hold)', color: 'var(--accent-hold)' }}
            >
              {proposals.length} waiting on you
            </button>
          )}
        </div>

        {/* ── Watchlist: drawer below lg, first column at lg ──────────────── */}
        <aside
          id="watchlist-rail"
          aria-label="Watchlist"
          aria-hidden={railOpen ? undefined : true}
          className={`fixed inset-y-0 left-0 z-40 flex w-[280px] max-w-[85vw] flex-col
                      bg-[var(--color-surface)] transition-transform duration-200
                      ${railOpen ? 'translate-x-0' : '-translate-x-full'}
                      lg:static lg:z-auto lg:w-auto lg:max-w-none lg:translate-x-0
                      lg:transition-none`}
        >
          <div className="flex items-center justify-between border-b border-[var(--color-border)]
                          px-3 py-2 lg:hidden">
            <span className="label-micro">Watchlist</span>
            <button
              onClick={() => setRailOpen(false)}
              aria-label="Close watchlist"
              className="grid h-11 w-11 place-items-center text-[var(--color-fg-muted)]
                         hover:text-[var(--color-fg)]"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
          {rail}
        </aside>

        {/* Backdrop. Separate from the rail so the rail can stay in the grid. */}
        {railOpen && (
          <button
            type="button"
            aria-label="Close watchlist"
            className="fixed inset-0 z-30 cursor-default bg-black/50 lg:hidden"
            onClick={() => setRailOpen(false)}
          />
        )}

        {/* ── Verdict, then evidence ───────────────────────────────────────
            `contents` below lg dissolves this wrapper so the two halves become
            flex items of the column and `order` can put the ticket between
            them. At lg it is the centre grid column, scrolling as one. */}
        <div className="contents lg:block lg:min-h-0 lg:overflow-y-auto">
          <div className="order-2 lg:order-none">{pending ?? header}</div>
          {data && (
            <div className="order-4 lg:order-none">
              <TickerAnalysis data={data} item={selectedItem} />
            </div>
          )}
        </div>

        {/* ── Ticket, approvals, activity ────────────────────────────────────
            Same trick: dissolved below lg so the ticket and the approvals queue
            land directly under the verdict (order-3) and the activity log falls
            to the bottom (order-5), while at lg all three stack in the right
            column. Every panel is mounted exactly once either way. */}
        <div
          className="contents lg:block lg:min-h-0 lg:overflow-y-auto lg:border-l
                     lg:border-[var(--color-border)] lg:bg-[var(--color-surface)]"
        >
          <div className="order-3 border-b border-[var(--color-border)]
                          bg-[var(--color-surface)] lg:order-none lg:border-b-0">
            <OrderPanel data={data} onOrderPlaced={onAgentChanged} />
            <ApprovalsPanel proposals={proposals} onProposalsChanged={onAgentChanged} />
          </div>

          <div className="mb-bottom-bar order-5 border-t border-[var(--color-border)]
                          bg-[var(--color-surface)] lg:order-none lg:mb-0 lg:border-t-0">
            <ActivityPanel orders={orders} />
          </div>
        </div>
      </div>
    </Layout>
  )
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center gap-4 px-6 py-20 text-center">
      <AlertCircle className="h-9 w-9 text-[var(--accent-sell)]" aria-hidden="true" />
      <p className="text-sm text-[var(--color-fg-muted)]">{message}</p>
      <button onClick={onRetry} className="btn-secondary">Try again</button>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-24 text-center">
      <h2
        className="text-lg text-[var(--color-fg)]"
        style={{ fontFamily: 'Fraunces, Georgia, serif' }}
      >
        Nothing selected
      </h2>
      <p className="max-w-xs text-sm text-[var(--color-fg-muted)]">
        Add a ticker to your watchlist, or press <kbd className="num">⌘K</kbd> to look one up —
        you don&rsquo;t have to watch it first.
      </p>
    </div>
  )
}
