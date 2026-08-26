import React, { useEffect, useMemo, useState } from 'react'
import { ActivityIndicator, LayoutChangeEvent, Pressable, Text, View } from 'react-native'
import Svg, { Line, Path, Rect } from 'react-native-svg'
import { chartApi } from '../lib/api'
import type { ChartSeries } from '../types'
import { usePalette } from '../lib/palette'

/**
 * Candlestick chart with SMA-20/50 and a volume strip.
 *
 * `lightweight-charts` powers the web chart but is DOM-only, so this draws with
 * react-native-svg against the same `/chart/{ticker}/series` endpoint. The
 * moving averages come from the server, so all three renderers — this, the web
 * chart, and the export PNG — plot the same line.
 *
 * Deliberately not interactive. A crosshair worth having on a phone needs
 * gesture handling and a value readout; a half-built one that swallows scroll
 * gestures inside a ScrollView is worse than a clean static chart.
 */


const RANGES = [
  { label: '3M', days: 90 },
  { label: '6M', days: 180 },
  { label: '1Y', days: 365 },
] as const

const CHART_H = 180
const VOLUME_H = 34
const PAD = 4

const usd = new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', maximumFractionDigits: 2,
})

export default function PriceChart({ ticker }: { ticker: string }) {
  const C = usePalette()
  const [days, setDays] = useState<number>(180)
  const [data, setData] = useState<ChartSeries | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [width, setWidth] = useState(0)

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

  const geometry = useMemo(() => {
    if (!data || data.bars.length === 0 || width <= 0) return null

    const bars = data.bars
    const lows = bars.map((b) => b.low)
    const highs = bars.map((b) => b.high)
    const min = Math.min(...lows)
    const max = Math.max(...highs)
    // A flat series would divide by zero; give it a nominal band instead.
    const span = max - min || Math.max(max * 0.02, 0.01)

    const innerW = width - PAD * 2
    const step = innerW / bars.length
    // Candles leave a gap between them, and never collapse to invisible.
    const candleW = Math.max(1, Math.min(step * 0.7, 8))

    const y = (price: number) => PAD + (1 - (price - min) / span) * (CHART_H - PAD * 2)
    const x = (i: number) => PAD + i * step + step / 2

    const maxVol = Math.max(...bars.map((b) => b.volume), 1)

    // SMA lines are keyed by date because the server omits the warm-up period —
    // index alignment would silently shift the line left.
    const dateIndex = new Map(bars.map((b, i) => [b.date, i]))
    const linePath = (points: { date: string; value: number }[]): string => {
      let d = ''
      let started = false
      for (const p of points) {
        const i = dateIndex.get(p.date)
        if (i === undefined) continue
        d += `${started ? 'L' : 'M'}${x(i).toFixed(2)},${y(p.value).toFixed(2)}`
        started = true
      }
      return d
    }

    return {
      bars, x, y, step, candleW, maxVol,
      sma20: linePath(data.sma_20),
      sma50: linePath(data.sma_50),
      min, max,
    }
  }, [data, width])

  const last = data?.bars[data.bars.length - 1]

  return (
    <View style={{ gap: 10 }}>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 5 }}>
            <View style={{ width: 12, height: 2, backgroundColor: C.brand }} />
            <Text style={{ fontSize: 9, color: C.fgMuted }}>SMA 20</Text>
          </View>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 5 }}>
            <View style={{ width: 12, height: 2, backgroundColor: C.fgMuted }} />
            <Text style={{ fontSize: 9, color: C.fgMuted }}>SMA 50</Text>
          </View>
        </View>

        <View style={{ flexDirection: 'row', gap: 4 }}>
          {RANGES.map((r) => {
            const active = days === r.days
            return (
              <Pressable
                key={r.label}
                onPress={() => setDays(r.days)}
                accessibilityRole="button"
                accessibilityState={{ selected: active }}
                style={{
                  paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6,
                  backgroundColor: active ? C.brand : 'transparent',
                }}
              >
                <Text style={{
                  fontSize: 11, fontWeight: '600',
                  color: active ? '#fff' : C.fgMuted,
                }}>
                  {r.label}
                </Text>
              </Pressable>
            )
          })}
        </View>
      </View>

      <View
        onLayout={(e: LayoutChangeEvent) => setWidth(e.nativeEvent.layout.width)}
        style={{ height: CHART_H + VOLUME_H, justifyContent: 'center' }}
      >
        {loading ? (
          <ActivityIndicator size="small" color={C.brand} />
        ) : error ? (
          <Text style={{ fontSize: 11, color: C.fgMuted, textAlign: 'center' }}>{error}</Text>
        ) : !geometry ? (
          <Text style={{ fontSize: 11, color: C.fgMuted, textAlign: 'center' }}>
            No price history yet.
          </Text>
        ) : (
          <Svg width={width} height={CHART_H + VOLUME_H}>
            {/* Horizontal guides at the extremes of the visible range. */}
            <Line x1={0} y1={PAD} x2={width} y2={PAD} stroke={C.border} strokeWidth={1} />
            <Line
              x1={0} y1={CHART_H - PAD} x2={width} y2={CHART_H - PAD}
              stroke={C.border} strokeWidth={1}
            />

            {geometry.bars.map((b, i) => {
              const up = b.close >= b.open
              const colour = up ? C.up : C.down
              const cx = geometry.x(i)
              const yHigh = geometry.y(b.high)
              const yLow = geometry.y(b.low)
              const yOpen = geometry.y(b.open)
              const yClose = geometry.y(b.close)
              const bodyTop = Math.min(yOpen, yClose)
              // A doji would otherwise render as nothing at all.
              const bodyH = Math.max(1, Math.abs(yClose - yOpen))
              const volH = (b.volume / geometry.maxVol) * (VOLUME_H - 4)

              return (
                <React.Fragment key={b.date}>
                  <Line
                    x1={cx} y1={yHigh} x2={cx} y2={yLow}
                    stroke={colour} strokeWidth={1}
                  />
                  <Rect
                    x={cx - geometry.candleW / 2}
                    y={bodyTop}
                    width={geometry.candleW}
                    height={bodyH}
                    fill={colour}
                  />
                  <Rect
                    x={cx - geometry.candleW / 2}
                    y={CHART_H + (VOLUME_H - 4) - volH}
                    width={geometry.candleW}
                    height={volH}
                    fill={colour}
                    opacity={0.35}
                  />
                </React.Fragment>
              )
            })}

            <Path d={geometry.sma20} stroke={C.brand} strokeWidth={1.4} fill="none" />
            <Path d={geometry.sma50} stroke={C.fgMuted} strokeWidth={1.4} fill="none" />
          </Svg>
        )}
      </View>

      {geometry && last && (
        <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
          <Text style={{ fontSize: 9, color: C.fgMuted }}>
            {geometry.bars[0].date}
          </Text>
          <Text style={{ fontSize: 9, color: C.fgMuted, fontVariant: ['tabular-nums'] }}>
            low {usd.format(geometry.min)} · high {usd.format(geometry.max)}
          </Text>
          <Text style={{ fontSize: 9, color: C.fgMuted }}>{last.date}</Text>
        </View>
      )}
    </View>
  )
}
