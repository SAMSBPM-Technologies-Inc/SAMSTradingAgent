import React, { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { tradingApi } from './api'
import { useAuth } from './auth-context'
import type { AutoTradeSettings, AutoTradeSettingsResponse } from '../types'

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
 */

interface TradingContextValue {
  settings: AutoTradeSettingsResponse | null
  loading: boolean
  /** Re-read from the server. */
  refresh: () => Promise<void>
  /** Merge a patch over the current settings and persist the whole document. */
  save: (patch: Partial<AutoTradeSettings>) => Promise<AutoTradeSettingsResponse>
}

const TradingContext = createContext<TradingContextValue | null>(null)

export function TradingSettingsProvider({ children }: { children: React.ReactNode }) {
  const { token } = useAuth()
  const [settings, setSettings] = useState<AutoTradeSettingsResponse | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    if (!token) {
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
  }, [token])

  useEffect(() => {
    setLoading(true)
    refresh()
  }, [refresh])

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
    <TradingContext.Provider value={{ settings, loading, refresh, save }}>
      {children}
    </TradingContext.Provider>
  )
}

export function useTradingSettings(): TradingContextValue {
  const ctx = useContext(TradingContext)
  if (!ctx) throw new Error('useTradingSettings must be used within TradingSettingsProvider')
  return ctx
}
