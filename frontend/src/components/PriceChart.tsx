import { useEffect, useRef, useState } from 'react'
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  type IChartApi,
  type UTCTimestamp,
} from 'lightweight-charts'
import { AlertCircle, LineChart } from 'lucide-react'
import { chartApi } from '../lib/api'
import { useTheme } from '../lib/theme-context'
import type { ChartSeries } from '../types'
import LoadingSpinner from './LoadingSpinner'

/**
 * Interactive candlestick chart with SMA-20/50 and a volume panel.
 *
 * The backend can render this as a PNG (`GET /chart/{ticker}`) and that stays
 * the right answer for PDF export, but not for the page: a static image cannot
 * be zoomed or scrubbed, costs a matplotlib process per view, and is baked in
 * one theme. This reads `/chart/{ticker}/series` and draws client-side.
 *
 * The moving averages come from the server rather than being recomputed here,
 * so this and the exported PNG cannot disagree at the edges.
 */

const RANGES = [
  { label: '1M', days: 30 },
  { label: '3M', days: 90 },
  { label: '6M', days: 180 },
  { label: '1Y', days: 365 },
  { label: '2Y', days: 730 },
] as const

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

/** lightweight-charts wants epoch seconds; the API sends YYYY-MM-DD. */
function toTime(date: string): UTCTimestamp {
  return (Date.parse(`${date}T00:00:00Z`) / 1000) as UTCTimestamp
}

function palette(theme: 'light' | 'dark') {
  return theme === 'dark'
    ? {
        bg: '#141109', fg: '#f0ece4', muted: '#9a8f82', grid: '#2a2420',
        up: '#4ade80', down: '#f87171', sma20: '#f2600c', sma50: '#9a8f82',
      }
    : {
        bg: '#ffffff', fg: '#14110c', muted: '#83786a', grid: '#e7e2d8',
        up: '#15803d', down: '#b91c1c', sma20: '#f2600c', sma50: '#83786a',
      }
}

export default function PriceChart({
  ticker,
  stopLoss,
  priceTarget,
  height = 320,
}: {
  ticker: string
  /** Drawn as a dashed guide. The price scale is left alone — see below. */
  stopLoss?: number | null
  priceTarget?: number | null
  height?: number
}) {
  const { theme } = useTheme()
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const [days, setDays] = useState<number>(180)
  const [data, setData] = useState<ChartSeries | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Fetch whenever the range changes.
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    chartApi.series(ticker, days)
      .then((res) => { if (!cancelled) setData(res.data) })
      .catch((err: unknown) => {
        if (cancelled) return
        const detail = (err as { response?: { data?: { detail?: string } } })
          ?.response?.data?.detail
        setError(detail ?? 'Could not load price history.')
        setData(null)
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [ticker, days])

  // Build the chart. Re-runs on theme change — the library takes colours at
  // construction for some options, and recreating is cheaper than reconciling.
  useEffect(() => {
    const el = containerRef.current
    if (!el || !data || data.bars.length === 0) return

    const c = palette(theme)
    const chart = createChart(el, {
      layout: {
        background: { type: ColorType.Solid, color: c.bg },
        textColor: c.muted,
        fontFamily: 'Work Sans, system-ui, sans-serif',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: c.grid },
        horzLines: { color: c.grid },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: c.grid },
      timeScale: { borderColor: c.grid, timeVisible: false },
      height,
      autoSize: true,
    })
    chartRef.current = chart

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: c.up,
      downColor: c.down,
      borderUpColor: c.up,
      borderDownColor: c.down,
      wickUpColor: c.up,
      wickDownColor: c.down,
    })
    candles.setData(data.bars.map((b) => ({
      time: toTime(b.date),
      open: b.open, high: b.high, low: b.low, close: b.close,
    })))

    const sma20 = chart.addSeries(LineSeries, {
      color: c.sma20, lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
    })
    sma20.setData(data.sma_20.map((p) => ({ time: toTime(p.date), value: p.value })))

    const sma50 = chart.addSeries(LineSeries, {
      color: c.sma50, lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
    })
    sma50.setData(data.sma_50.map((p) => ({ time: toTime(p.date), value: p.value })))

    // Volume in its own pane at the foot, scaled independently of price.
    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    })
    volume.setData(data.bars.map((b) => ({
      time: toTime(b.date),
      value: b.volume,
      color: b.close >= b.open ? `${c.up}55` : `${c.down}55`,
    })))
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.82, bottom: 0 },
    })

    // Stop and target as dashed guides on the candle series.
    //
    // These are price *lines*, not data points, which matters: a stop far below
    // the visible range would rescale the whole chart if it were plotted as a
    // series, flattening the price action into a band at the top. A price line
    // is clamped to the pane and leaves the scale alone.
    if (stopLoss != null && stopLoss > 0) {
      candles.createPriceLine({
        price: stopLoss,
        color: c.down,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'stop',
      })
    }
    if (priceTarget != null && priceTarget > 0) {
      candles.createPriceLine({
        price: priceTarget,
        color: c.up,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'target',
      })
    }

    chart.timeScale().fitContent()

    return () => {
      chart.remove()
      chartRef.current = null
    }
  }, [data, theme, height, stopLoss, priceTarget])

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1.5" role="group" aria-label="Chart range">
          {RANGES.map((r) => (
            <button
              key={r.label}
              onClick={() => setDays(r.days)}
              aria-pressed={days === r.days}
              className="chip num"
            >
              {r.label}
            </button>
          ))}
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-3 text-[10.5px] text-[var(--color-fg-muted)]">
          <span className="flex items-center gap-1.5">
            <span aria-hidden="true" className="h-0.5 w-3 rounded-full bg-brand-500" /> SMA 20
          </span>
          <span className="flex items-center gap-1.5">
            <span aria-hidden="true" className="h-0.5 w-3 rounded-full bg-[var(--color-fg-muted)]" /> SMA 50
          </span>
          {stopLoss != null && stopLoss > 0 && (
            <span className="text-[var(--accent-sell)]">- - stop {usd.format(stopLoss)}</span>
          )}
          {priceTarget != null && priceTarget > 0 && (
            <span className="text-[var(--accent-buy)]">- - target {usd.format(priceTarget)}</span>
          )}
        </div>
      </div>

      <div className="relative" style={{ minHeight: height }}>
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-[var(--color-surface)]/70">
            <LoadingSpinner size="md" />
          </div>
        )}

        {error ? (
          <div
            className="flex flex-col items-center justify-center gap-2 text-center text-[var(--color-fg-muted)]"
            style={{ height }}
          >
            <AlertCircle className="h-6 w-6" aria-hidden="true" />
            <p className="max-w-xs text-xs">{error}</p>
          </div>
        ) : !loading && (!data || data.bars.length === 0) ? (
          <div
            className="flex flex-col items-center justify-center gap-2 text-center text-[var(--color-fg-muted)]"
            style={{ height }}
          >
            <LineChart className="h-6 w-6" aria-hidden="true" />
            <p className="text-xs">No price history yet.</p>
          </div>
        ) : (
          <div ref={containerRef} className="w-full" style={{ height }} />
        )}
      </div>
    </div>
  )
}
