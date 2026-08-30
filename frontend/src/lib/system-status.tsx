import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { systemApi } from './api'
import { useAuth } from './auth-context'
import type { SystemStatus } from '../types'

/**
 * One shared reading of what is working, for everything that shows it.
 *
 * The chrome indicator and the status page ask the same question, and two
 * independent polls would let them answer it differently for up to a minute —
 * the same drift `AccountBar` avoids by reading equity from the trading context
 * rather than fetching its own.
 *
 * Polled once a minute. The pipeline moves every five, and the server does no
 * fetching to answer this (every row is a stored record of what the last cycle
 * actually did), so the request is nearly free and anything faster is noise.
 */

interface SystemStatusValue {
  status: SystemStatus | null
  loading: boolean
  error: boolean
  refresh: () => void
}

const SystemStatusContext = createContext<SystemStatusValue | null>(null)

const POLL_MS = 60_000

export function SystemStatusProvider({ children }: { children: ReactNode }) {
  const { token } = useAuth()
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)

  const load = useCallback(() => {
    if (!token) return
    systemApi.status()
      .then(({ data }) => { setStatus(data); setError(false) })
      .catch(() => setError(true))
      .finally(() => setLoading(false))
  }, [token])

  useEffect(() => {
    if (!token) {
      // Signed out: hold nothing. The endpoint names environment variables and
      // provider error text, and a stale copy surviving a sign-out would leak
      // one account's deployment shape into the next session on that browser.
      setStatus(null)
      setLoading(false)
      return
    }
    setLoading(true)
    load()
    const timer = setInterval(load, POLL_MS)
    return () => clearInterval(timer)
  }, [token, load])

  return (
    <SystemStatusContext.Provider value={{ status, loading, error, refresh: load }}>
      {children}
    </SystemStatusContext.Provider>
  )
}

export function useSystemStatus(): SystemStatusValue {
  const ctx = useContext(SystemStatusContext)
  if (!ctx) throw new Error('useSystemStatus must be used within SystemStatusProvider')
  return ctx
}
