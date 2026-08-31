import React, { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { tradingApi } from './api'
import { useAuth } from './auth-context'
import { entitlementsOf } from './entitlements'
import { usePoll } from './use-poll'
import type {
  AccountSummaryResponse,
  AutoTradeSettings,
  AutoTradeSettingsResponse,
} from '../types'

/**
 * One owner for the auto-trade settings document.
 *
 * Three surfaces read it and two of them write it: the header shows the
 * autonomy mode and the paper/live routing, the order ticket needs
 * `paper_trading` to decide whether an order requires typed confirmation, and
 * the Settings screen edits the whole thing. Before this, each fetched its own
 * copy — which meant flipping to live in Settings left a header still saying
 * PAPER, and an order ticket still willing to submit without confirmation.
 * A stale copy of *this* document is a safety bug, not a cosmetic one, so
 * there is exactly one.
 *
 * `save` takes a patch and PUTs the merged whole, because the API replaces the
 * document rather than patching it — sending a partial would silently reset
 * every field the caller didn't mention.
 *
 * The account summary lives here for the same reason. Four screens fetched it
 * independently with no shared cache — the account strip, the order ticket,
 * Settings and Positions — which cost three round-trips per Trade page load
 * and, worse, let two of them disagree: the strip refreshed every 30 seconds
 * while the ticket read equity once and never again, so the number sizing an
 * order could differ from the number displayed above it.
 *
 * **Nothing here fetches for an account whose plan has no trading.** This
 * provider sits at app level, so without that check every page load for such a
 * user fires two requests that come back 403 and a poll that repeats one of
 * them every thirty seconds. Both catch blocks fold an error into `null` — by
 * design, since a guessed mode is the one thing the header must not show —
 * which would make the whole loop completely invisible from the UI.
 */

interface TradingContextValue {
  settings: AutoTradeSettingsResponse | null
  loading: boolean
  /** Re-read from the server. */
  refresh: () => Promise<void>
  /** Merge a patch over the current settings and persist the whole document. */
  save: (patch: Partial<AutoTradeSettings>) => Promise<AutoTradeSettingsResponse>

  /** Broker balances. One copy, polled here, read everywhere. */
  account: AccountSummaryResponse | null
  accountLoading: boolean
  refreshAccount: () => Promise<void>
}

const TradingContext = createContext<TradingContextValue | null>(null)

export function TradingSettingsProvider({ children }: { children: React.ReactNode }) {
  const { token, user } = useAuth()
  // Not "is there a token" but "may this account trade at all". Both are
  // needed: the token gates an anonymous visitor, the plan gates a signed-in
  // reader.
  const mayTrade = !!token && entitlementsOf(user).may_trade
  const [settings, setSettings] = useState<AutoTradeSettingsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [account, setAccount] = useState<AccountSummaryResponse | null>(null)
  const [accountLoading, setAccountLoading] = useState(true)

  const refresh = useCallback(async () => {
    if (!mayTrade) {
      setSettings(null)
      setLoading(false)
      return
    }
    try {
      const { data } = await tradingApi.getSettings()
      setSettings(data)
    } catch {
      // Non-fatal. The header degrades to showing nothing rather than
      // guessing a mode — and a guessed mode is the one thing it must not do.
      setSettings(null)
    } finally {
      setLoading(false)
    }
  }, [mayTrade])

  useEffect(() => {
    setLoading(true)
    refresh()
  }, [refresh])

  const refreshAccount = useCallback(async () => {
    if (!mayTrade) {
      setAccount(null)
      setAccountLoading(false)
      return
    }
    try {
      const { data } = await tradingApi.getAccount()
      setAccount(data)
    } catch {
      // Non-fatal: the strip shows "disconnected" rather than stale balances,
      // and the order ticket falls back to asking for an explicit quantity.
      setAccount(null)
    } finally {
      setAccountLoading(false)
    }
  }, [mayTrade])

  useEffect(() => {
    setAccountLoading(true)
    refreshAccount()
  }, [refreshAccount])

  // Balances move intraday. Polled once, here, instead of once per consumer —
  // and paused while the tab is hidden rather than spending broker round-trips
  // on a screen nobody is looking at.
  usePoll(refreshAccount, 30_000, mayTrade)

  const save = useCallback(
    async (patch: Partial<AutoTradeSettings>) => {
      if (!settings) throw new Error('Trading settings are not loaded yet')
      const { connected: _connected, ...current } = settings
      const { data } = await tradingApi.updateSettings({ ...current, ...patch })
      setSettings(data)
      return data
    },
    [settings],
  )

  return (
    <TradingContext.Provider
      value={{ settings, loading, refresh, save, account, accountLoading, refreshAccount }}
    >
      {children}
    </TradingContext.Provider>
  )
}

export function useTradingSettings(): TradingContextValue {
  const ctx = useContext(TradingContext)
  if (!ctx) throw new Error('useTradingSettings must be used within TradingSettingsProvider')
  return ctx
}
