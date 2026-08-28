import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { AlertCircle } from 'lucide-react'
import { analyzeApi } from '../lib/api'
import type { AnalyzeResponse } from '../types'
import Layout from '../components/Layout'
import AnalysisProgress from '../components/trade/AnalysisProgress'
import { TickerAnalysis, TickerHeader } from '../components/trade/TickerDetail'

/**
 * One name, nothing else — the target of the overlay's "New window" control.
 *
 * Deliberately thin. It renders the analysis and no watchlist, no order
 * ticket, no approvals queue, because its whole purpose is to be opened twice
 * and put side by side. It also makes no watchlist request, so a second window
 * costs one call rather than five.
 *
 * Watch and unwatch are absent for the same reason: mutating a list this window
 * does not display would leave the dashboard in the other window stale with
 * nothing to tell it. Those actions live where the list is.
 */
export default function AnalysisPage() {
  const { symbol } = useParams<{ symbol: string }>()
  const ticker = symbol?.toUpperCase() ?? null

  const [data, setData] = useState<AnalyzeResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (force: boolean) => {
    if (!ticker) return
    if (force) setRefreshing(true)
    else setLoading(true)
    setError(null)
    try {
      const res = await analyzeApi.get(ticker, force)
      setData(res.data)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Failed to load analysis.')
      setData(null)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [ticker])

  useEffect(() => { load(false) }, [load])

  useEffect(() => {
    if (ticker) document.title = `${ticker} — Analysis`
  }, [ticker])

  return (
    <Layout variant="app">
      <div className="mx-auto w-full max-w-[980px]">
        {loading ? (
          <AnalysisProgress ticker={ticker ?? ''} />
        ) : error ? (
          <div
            role="alert"
            className="m-4 flex items-center gap-3 rounded-lg border px-4 py-3 text-sm"
            style={{
              background: 'var(--tint-sell)',
              borderColor: 'var(--accent-sell)',
              color: 'var(--accent-sell)',
            }}
          >
            <AlertCircle className="h-4 w-4 flex-shrink-0" aria-hidden="true" />
            {error}
          </div>
        ) : data ? (
          <>
            <TickerHeader
              data={data}
              holding={null}
              position={null}
              watched={false}
              refreshing={refreshing}
              onRefresh={() => load(true)}
              onWatch={() => {}}
              onUnwatch={() => {}}
            />
            <TickerAnalysis data={data} item={null} />
          </>
        ) : null}
      </div>
    </Layout>
  )
}
