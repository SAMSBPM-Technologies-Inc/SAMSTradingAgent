import { useEffect, useState } from 'react'
import { tradingApi } from './api'
import type { AccountSummaryResponse } from '../types'

/**
 * Broker balances, shared by the header badge and the Trade strip.
 *
 * Both sit on the same screen and want the same `/trading/account`, so a plain
 * per-component fetch would issue the request twice on every mount. The
 * in-flight promise is cached and the result is held briefly, which collapses
 * that to one call without pulling a provider through the tree for two readers.
 *
 * The window is deliberately short: these are balances, and a stale one is
 * worse than a late one.
 */

const TTL_MS = 20_000

let cached: { data: AccountSummaryResponse | null; at: number } | null = null
let inFlight: Promise<AccountSummaryResponse | null> | null = null

function load(): Promise<AccountSummaryResponse | null> {
  if (cached && Date.now() - cached.at < TTL_MS) return Promise.resolve(cached.data)
  if (inFlight) return inFlight

  inFlight = tradingApi.getAccount()
    .then(({ data }) => data)
    // A broker that is down must not take the screen down with it.
    .catch(() => null)
    .then((data) => {
      cached = { data, at: Date.now() }
      inFlight = null
      return data
    })

  return inFlight
}

export function useAccount(): { account: AccountSummaryResponse | null; loading: boolean } {
  const [account, setAccount] = useState<AccountSummaryResponse | null>(cached?.data ?? null)
  const [loading, setLoading] = useState(cached == null)

  useEffect(() => {
    let alive = true
    load().then((data) => {
      if (!alive) return
      setAccount(data)
      setLoading(false)
    })
    return () => { alive = false }
  }, [])

  return { account, loading }
}
