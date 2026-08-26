import React from 'react'
import { View, Text } from 'react-native'
import type { Signal } from '../types'
import { usePalette, type Palette } from '../lib/palette'

/**
 * Tint and accent per verdict, taken from the palette so the badge follows the
 * theme. The pairs match the web `--tint-*` / `--accent-*` tokens: tint behind,
 * accent on top, both flipping together so contrast survives either ground.
 */
function config(C: Palette): Record<Signal | 'PENDING', { bg: string; text: string; label: string }> {
  return {
    BUY:  { bg: C.tintBuy,  text: C.green,   label: 'BUY' },
    SELL: { bg: C.tintSell, text: C.red,     label: 'SELL' },
    HOLD: { bg: C.tintHold, text: C.amber,   label: 'HOLD' },
    PENDING: { bg: C.hover, text: C.fgMuted, label: '—' },
  }
}

interface Props {
  /** PENDING covers a watched ticker the pipeline has not scored yet. */
  signal: Signal | 'PENDING'
  size?: 'sm' | 'lg'
}

export default function SignalBadge({ signal, size = 'sm' }: Props) {
  const C = usePalette()
  const cfg = config(C)
  const { bg, text, label } = cfg[signal] ?? cfg.HOLD
  const fontSize = size === 'lg' ? 13 : 11
  const px = size === 'lg' ? 10 : 8
  const py = size === 'lg' ? 4 : 2

  return (
    <View
      style={{
        backgroundColor: bg,
        paddingHorizontal: px,
        paddingVertical: py,
        borderRadius: 6,
        alignSelf: 'flex-start',
      }}
    >
      <Text style={{ color: text, fontSize, fontWeight: '700', letterSpacing: 0.5 }}>
        {label}
      </Text>
    </View>
  )
}
