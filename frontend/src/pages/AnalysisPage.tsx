import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { AlertCircle } from 'lucide-react'
import { analyzeApi } from '../lib/api'
import type { AnalyzeResponse, Quote } from '../types'
import Layout from '../components/Layout'
import AnalysisProgress from '../components/trade/AnalysisProgress'
import { TickerAnalysis, TickerHeader } from '../components/trade/TickerDetail'
import TickerActions from '../components/trade/TickerActions'

/**
 * One name, nothing else — the target of the "New window" control.
 *
 * Deliberately thin. It renders the analysis and no watchlist, no order
 * ticket, no approvals queue, because its whole purpose is to be opened twice
 * and put side by side. It also makes no watchlist request, so a second window
 * costs two calls rather than five.
 *
 * Watch and unwatch are absent for the same reason: mutating a list this window
 * does not display would leave the dashboard in the other window stale with
 * nothing to tell it. Those actions live where the list is.
 *
 * The two-step split applies here too — opening a name reads the stored
 * analysis and a live price, and running a new one is a button. A window opened
 * to compare two names must not silently start two pipeline runs.
 */
export default function AnalysisPage() {
  const { symbol } = useParams<{ symbol: string }>()
  const ticker = symbol?.toUpperCase() ?? null

  const [data, setData] = useState<AnalyzeResponse | null>(null)
  const [quote, setQuote] = useState<Quote | null>(null)
  const [loading, setLoading] = useState(true)
  const [analysing, setAnalysing] = useState(false)
  const [neverAnalysed, setNeverAnalysed] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadStored = useCallback(async () => {
    if (!ticker) return
    setLoading(true)
    setError(null)
    setNeverAnalysed(false)
    try {
      const res = await analyzeApi.get(ticker)
      setData(res.data)
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      setData(null)
      if (status === 404) setNeverAnalysed(true)
      else {
        const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        setError(msg ?? 'Failed to load the stored analysis.')
      }
    } finally {
      setLoading(false)
    }
  }, [ticker])

  const loadQuote = useCallback(async () => {
    if (!ticker) return
    try {
      setQuote((await analyzeApi.quote(ticker)).data)
    } catch {
      setQuote(null)
    }
  }, [ticker])

  const runAnalysis = useCallback(async () => {
    if (!ticker) return
    setAnalysing(true)
    setError(null)
    try {
      const res = await analyzeApi.run(ticker)
      setData(res.data)
      setNeverAnalysed(false)
      void loadQuote()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'The analysis could not be completed.')
    } finally {
      setAnalysing(false)
    }
  }, [ticker, loadQuote])

  useEffect(() => { void loadStored(); void loadQuote() }, [loadStored, loadQuote])

  useEffect(() => {
    if (ticker) document.title = `${ticker} — Analysis`
  }, [ticker])

  return (
    <Layout variant="app">
      <div className="mx-auto w-full max-w-[980px]">
        <TickerHeader
          symbol={ticker ?? ''}
          data={data}
          quote={quote}
          holding={null}
          position={null}
        />
        {/* Inline, because this window has no right column to put them in —
            being one name and nothing else is the whole point of it. Watch and
            unwatch stay absent for the reason above: mutating a list this
            window does not display would leave the dashboard in the other
            window stale with nothing to tell it. */}
        <TickerActions
          symbol={ticker ?? ''}
          data={data}
          watched={false}
          analysing={analysing}
          onRunAnalysis={() => void runAnalysis()}
          layout="inline"
        />
        {analysing ? (
          <AnalysisProgress ticker={ticker ?? ''} />
        ) : loading ? (
          <p className="px-[18px] py-10 text-center text-sm text-[var(--color-fg-muted)]">
            Reading the last analysis…
          </p>
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
        ) : neverAnalysed ? (
          <p className="px-6 py-16 text-center text-sm text-[var(--color-fg-muted)]">
            No in-depth analysis has been run for {ticker}. The price above is live.
          </p>
        ) : data ? (
          <TickerAnalysis data={data} item={null} />
        ) : null}
      </div>
    </Layout>
  )
}
