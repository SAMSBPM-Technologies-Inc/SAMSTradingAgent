import { useCallback, useEffect, useMemo, useState } from 'react'
import { useMatch, useNavigate, useParams } from 'react-router-dom'
import { PanelLeft, X } from 'lucide-react'
import { analyzeApi, watchlistApi } from '../lib/api'
import { useToast } from '../lib/toast-context'
import { useAuth } from '../lib/auth-context'
import { entitlementsOf, tierRefusal } from '../lib/entitlements'
import { usePoll } from '../lib/use-poll'
import { PortfolioProvider, usePortfolio } from '../lib/portfolio-context'
import type {
  AnalyzeResponse,
  Quote,
  WatchlistItem,
  WatchlistSetupCounts,
} from '../types'
import Layout from '../components/Layout'
import WatchlistRail from '../components/trade/WatchlistRail'
import TickerPanel from '../components/trade/TickerPanel'
import TransactionDetail from '../components/positions/TransactionDetail'
import BrokerPanel from '../components/BrokerPanel'
import PositionsDashboard from '../components/PositionsDashboard'
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

/**
 * The provider is mounted here, not at the app root: it fetches four broker and
 * trade endpoints, and every screen that is not this one needs none of them.
 * Scoping it to Trade is what makes a single copy cheaper than two, rather than
 * just moving the waste somewhere less visible.
 */
export default function TradePage() {
  return (
    <PortfolioProvider>
      <TradeScreen />
    </PortfolioProvider>
  )
}

function TradeScreen() {
  const { symbol } = useParams<{ symbol: string }>()
  const navigate = useNavigate()
  const { toast, toastWithUndo } = useToast()
  const { user } = useAuth()
  const ent = entitlementsOf(user)

  const [items, setItems] = useState<WatchlistItem[]>([])
  const [setups, setSetups] = useState<WatchlistSetupCounts>(EMPTY_SETUPS)
  const [listLoading, setListLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState<string | null>(null)

  const [data, setData] = useState<AnalyzeResponse | null>(null)
  const [quote, setQuote] = useState<Quote | null>(null)
  // True only when a deep link means the fetch is already in flight at first
  // paint. On `/` there is nothing to load, and starting true would put a
  // spinner inside a panel that is not even shown.
  const [analysisLoading, setAnalysisLoading] = useState(!!symbol)
  // Separate from `analysisLoading` on purpose. Reading the stored analysis is
  // a Mongo lookup; running one is the whole pipeline plus an analyst call.
  // Only the second earns the staged progress display, and only the second is
  // something the user asked for.
  const [analysing, setAnalysing] = useState(false)
  // Nothing has ever been analysed for this ticker. A 404 from the stored read,
  // which is an empty state with a Run button — not a failure.
  const [neverAnalysed, setNeverAnalysed] = useState(false)
  const [error, setError] = useState<string | null>(null)


  // Below lg the three columns cannot coexist; the rail becomes a drawer.
  const [railOpen, setRailOpen] = useState(false)

  // Holdings, positions, orders and proposals come from the one provider the
  // dashboard body also reads, so the rail's held-badges and the tables below
  // can never be drawn from two different reads of the same account.
  const { holdings, positions, orders, proposals, reload } = usePortfolio()

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


  // ── Selection ─────────────────────────────────────────────────────────────
  //
  // The route, and nothing else. `/` used to fall back to `items[0].ticker`,
  // which made the landing page's slowest request depend on its fastest one:
  // `/analyze` could not start until `/watchlist` had returned a name, and on a
  // cache miss `/analyze` runs the whole pipeline — yfinance, Finnhub, FRED,
  // fundamentals — before it answers. Two sequential round-trips, the second
  // unbounded, to analyse a ticker nobody asked for.
  //
  // Now `/` renders the dashboard, whose panels are all cheap lookups that
  // start in parallel at first paint, and no analysis runs until a name is
  // actually selected.
  const selected = symbol?.toUpperCase() ?? null
  // `/transaction/:id` renders this same screen with a different centre column.
  const transactionId = useMatch('/transaction/:id')?.params.id ?? null

  /**
   * Read what is stored. Never runs the pipeline.
   *
   * This is what a ticker click does now. It used to call plain `/analyze`,
   * which rebuilds anything older than thirty minutes — yfinance, Finnhub,
   * FRED, fundamentals and a Claude call — so glancing at a name cost tens of
   * seconds of work nobody asked for.
   *
   * A 404 is the expected answer for a name never analysed. It sets the empty
   * state, not the error one: there is nothing wrong, there is just nothing
   * there yet.
   */
  const loadStored = useCallback(async (ticker: string) => {
    setAnalysisLoading(true)
    setError(null)
    setNeverAnalysed(false)
    try {
      const res = await analyzeApi.get(ticker)
      setData(res.data)
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      setData(null)
      if (status === 404) {
        setNeverAnalysed(true)
      } else {
        const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        setError(msg ?? 'Failed to load the stored analysis.')
      }
    } finally {
      setAnalysisLoading(false)
    }
  }, [])

  /** The live price, independently of the analysis. Cheap, and always current. */
  const loadQuote = useCallback(async (ticker: string) => {
    try {
      const res = await analyzeApi.quote(ticker)
      setQuote(res.data)
    } catch {
      // The endpoint falls back to a stored price server-side and does not
      // raise, so reaching here means the request itself failed. The header
      // shows the analysis's price and says nothing is live.
      setQuote(null)
    }
  }, [])

  /** The explicit run — the only path on this client that starts a pipeline. */
  const runAnalysis = useCallback(async (ticker: string) => {
    setAnalysing(true)
    setError(null)
    try {
      const res = await analyzeApi.run(ticker)
      setData(res.data)
      setNeverAnalysed(false)
      // A fresh run just repriced the name; take the new price with it rather
      // than leaving a quote from before the run on screen.
      void loadQuote(ticker)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'The analysis could not be completed.')
    } finally {
      setAnalysing(false)
    }
  }, [loadQuote])

  // Keyed on the ticker alone. It must NOT depend on watchlist loading state:
  // every add, remove or refresh would then re-fetch and flash a spinner over a
  // pane whose contents had not changed.
  //
  // Both requests start together. Neither can run the pipeline, so the pair is
  // bounded by the slower of one Mongo lookup and one quote call, and the
  // header paints from whichever lands first.
  useEffect(() => {
    if (!selected) return
    void loadStored(selected)
    void loadQuote(selected)
  }, [selected, loadStored, loadQuote])

  // No selection is the resting state of `/` now, not an edge case: clear the
  // previous name's analysis so reopening cannot flash stale data for the
  // ticker you looked at before.
  useEffect(() => {
    if (!selected) {
      setData(null)
      setQuote(null)
      setError(null)
      setNeverAnalysed(false)
      setAnalysisLoading(false)
    }
  }, [selected])

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
    //
    // This is the one implicit run left, and it is not a contradiction of the
    // two-step change: adding a name to the watchlist *is* asking the engine to
    // cover it. Without this the row sits blank until the five-minute cycle
    // reaches it, which reads as a broken add.
    analyzeApi.run(ticker).then(() => loadWatchlist()).catch(() => {})
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
      // The server's own message, not a generic one. This used to discard the
      // response body entirely, which is fine for "the network failed" and
      // useless for "your plan covers 15 tickers, remove one" — the only
      // refusal here that the user can actually do something about.
      .catch((err) =>
        toast(
          tierRefusal(err)?.message ?? `Could not add ${selected} to your watchlist.`,
          'error',
        ))
  }

  const onAgentChanged = () => { void reload() }

  // ── Centre column ─────────────────────────────────────────────────────────
  //
  // One region, three states, all of them routed. The analysis used to be a
  // modal over the dashboard; it is not one any more, for the same reason the
  // transaction detail never became one — the context a reader wants beside a
  // record is exactly what a backdrop hides.
  const centre = selected ? (
    <TickerPanel
      symbol={selected}
      data={data}
      quote={quote}
      item={selectedItem}
      holding={selectedHolding}
      position={selectedPosition}
      watched={watched}
      loading={analysisLoading}
      analysing={analysing}
      neverAnalysed={neverAnalysed}
      error={error}
      onRunAnalysis={() => runAnalysis(selected)}
      onWatch={watchSelected}
      onUnwatch={() => removeFromWatchlist(selected)}
      onRetry={() => loadStored(selected)}
      // Back rather than a push, so opening and closing five names does not
      // bury the dashboard under five history entries.
      onClose={() => navigate('/')}
      footer={ent.may_trade
        ? <OrderPanel data={data} onOrderPlaced={onAgentChanged} />
        : undefined}
    />
  ) : transactionId ? (
    <TransactionDetail />
  ) : ent.may_trade ? (
    <PositionsDashboard />
  ) : (
    // The dashboard is holdings and order history, which an account without
    // trading has none of. A substitute rather than a blank: the watchlist is
    // beside this column already, so the useful thing to say is which name to
    // open, not that a table is empty.
    <div className="flex min-h-[50vh] flex-col items-center justify-center px-6 text-center">
      <p className="text-[13.5px] font-medium text-[var(--color-fg)]">
        Pick a ticker to read its analysis
      </p>
      <p className="mt-1.5 max-w-sm text-[12px] leading-relaxed text-[var(--color-fg-muted)]">
        {items.length === 0
          ? 'Your watchlist is empty. Add a ticker and the engine will start covering it.'
          : 'Every verdict comes with the six factors behind it, the thresholds it was judged against, and which inputs were actually available.'}
      </p>
    </div>
  )

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

        {/* ── Centre column ──────────────────────────────────────────────
            The dashboard, one name's analysis, or one order's record — chosen
            by the route above. `PositionsDashboard` is the component itself
            rather than a second rendering of the same tables: two copies would
            have drifted, and the close-position undo window is not worth
            maintaining twice. */}
        <div className="order-2 min-w-0 px-3 py-3 lg:order-none lg:min-h-0 lg:overflow-y-auto lg:px-4">
          {centre}
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
          {/* The whole right column is the brokerage account: a session
              status, a queue of proposed orders and a log of placed ones. An
              account whose plan has no trading has none of those things, so
              this is removed rather than shown empty — and the server refuses
              every request behind it regardless. */}
          {ent.may_trade && (
          <div className="order-3 border-b border-[var(--color-border)]
                          bg-[var(--color-surface)] lg:order-none lg:border-b-0">
            {/* Broker session first: when it is down every action on this
                screen is refused, so it is the first thing worth knowing. It
                sits here rather than across the top of the dashboard because
                it is a standing status, not a result — a small box you glance
                at, not a banner competing with the positions. */}
            <div className="border-b border-[var(--color-border)] px-3 py-2.5">
              <BrokerPanel compact />
            </div>
            {/* The order ticket moved into the analysis overlay: it is about
                the name being read, and a ticket in this rail would sit behind
                the sheet that is covering the screen. */}
            <ApprovalsPanel proposals={proposals} onProposalsChanged={onAgentChanged} />
          </div>
          )}

          {ent.may_trade && (
          <div className="mb-bottom-bar order-5 border-t border-[var(--color-border)]
                          bg-[var(--color-surface)] lg:order-none lg:mb-0 lg:border-t-0">
            {/* Scoped to the name being read, when there is one: what was
                bought, sold, proposed or refused on *this* ticker is the
                context that turns a verdict into a decision. */}
            <ActivityPanel orders={orders} ticker={selected ?? undefined} />
          </div>
          )}
        </div>
      </div>
    </Layout>
  )
}
