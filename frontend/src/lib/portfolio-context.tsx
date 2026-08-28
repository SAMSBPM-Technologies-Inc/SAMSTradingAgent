import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
} from 'react'
import type { ReactNode } from 'react'
import { performanceApi, tradingApi } from './api'
import { usePoll } from './use-poll'
import { useTradingSettings } from './trading-context'
import type {
  Holding, Proposal, TradePerformanceResponse, TradeRecord,
} from '../types'

/**
 * One copy of the portfolio, for one screen.
 *
 * The Trade dashboard has two consumers of the same four endpoints: the
 * dashboard body draws the positions and order tables, while the watchlist rail
 * needs `holdings` for its held-badges and the analysis overlay needs the
 * holding and trade record for the name being read. Each used to fetch its own,
 * so `/trading/holdings`, `/trading/positions` and `/trading/orders` were all
 * requested twice on every load — parallel and cheap, but duplicated work on
 * the screen whose whole complaint was that it took too long.
 *
 * Scoped to the Trade screen rather than mounted app-wide on purpose. Hoisted
 * to the root it would fetch four broker endpoints behind Settings, Guide and
 * Calibration, which need none of them — trading the duplicate for a wider
 * waste. Balances are the exception and already live in `trading-context`,
 * because the account strip in the header does need them everywhere.
 */

interface PortfolioValue {
  holdings: Holding[]
  positions: TradeRecord[]
  orders: TradeRecord[]
  proposals: Proposal[]
  perf: TradePerformanceResponse | null
  /** First load only. A background refresh must never raise this. */
  loading: boolean
  refreshing: boolean
  error: string | null
  /** `spinner` distinguishes the Refresh button from the poll. */
  reload: (spinner?: boolean) => Promise<void>
}

const PortfolioContext = createContext<PortfolioValue | null>(null)

export function PortfolioProvider({ children }: { children: ReactNode }) {
  const { refreshAccount } = useTradingSettings()

  const [holdings, setHoldings] = useState<Holding[]>([])
  const [positions, setPositions] = useState<TradeRecord[]>([])
  const [orders, setOrders] = useState<TradeRecord[]>([])
  const [proposals, setProposals] = useState<Proposal[]>([])
  const [perf, setPerf] = useState<TradePerformanceResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async (spinner = false) => {
    if (spinner) setRefreshing(true)
    setError(null)
    // Every one of these is independently optional: a broker that is down must
    // not blank the order history, and a failed performance call must not hide
    // the positions. Each catches its own so one failure cannot reject the lot.
    const [hold, pos, ord, prop, tp] = await Promise.all([
      tradingApi.getHoldings().catch(() => null),
      tradingApi.getPositions().catch(() => null),
      tradingApi.getOrders().catch(() => null),
      tradingApi.getProposals().catch(() => null),
      performanceApi.trades().catch(() => null),
      refreshAccount().catch(() => null),
    ])
    setHoldings(hold?.data.connected ? hold.data.holdings : [])
    setPositions(pos?.data ?? [])
    setOrders(ord?.data ?? [])
    setProposals(prop?.data ?? [])
    setPerf(tp?.data ?? null)
    if (!ord) setError('Could not load your orders.')
    setLoading(false)
    setRefreshing(false)
  }, [refreshAccount])

  useEffect(() => { void reload() }, [reload])

  /**
   * The poll is narrower than the load, deliberately.
   *
   * A proposal appearing while the tab is open is the one thing on this screen
   * waiting on the user, so proposals and the order log are re-read every
   * minute. Holdings, the trade records and realised performance are not: they
   * change when *you* act, and every path that acts already calls `reload`.
   * Polling all five would have quietly tripled the standing request rate of
   * the screen this work exists to make lighter.
   */
  const pollAgent = useCallback(async () => {
    const [prop, ord] = await Promise.all([
      tradingApi.getProposals().catch(() => null),
      tradingApi.getOrders().catch(() => null),
    ])
    if (prop) setProposals(prop.data)
    if (ord) setOrders(ord.data)
  }, [])

  usePoll(() => { void pollAgent() }, 60_000)

  const value = useMemo<PortfolioValue>(
    () => ({ holdings, positions, orders, proposals, perf, loading, refreshing, error, reload }),
    [holdings, positions, orders, proposals, perf, loading, refreshing, error, reload],
  )

  return <PortfolioContext.Provider value={value}>{children}</PortfolioContext.Provider>
}

export function usePortfolio(): PortfolioValue {
  const ctx = useContext(PortfolioContext)
  if (!ctx) {
    // Loud rather than a silent empty portfolio: a screen rendering "no
    // positions" because its provider is missing is indistinguishable from an
    // account that genuinely holds nothing, which is the worst way to fail here.
    throw new Error('usePortfolio must be used inside a PortfolioProvider')
  }
  return ctx
}
