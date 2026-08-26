import React from 'react'
import { Text } from 'react-native'
import type { Conviction } from '../types'
import { usePalette, type Palette } from '../lib/palette'

function config(C: Palette): Record<Conviction, { label: string; color: string }> {
  return {
    HIGH:   { label: 'Strong signal', color: C.brand },
    MEDIUM: { label: 'Moderate',      color: C.fgMuted },
    LOW:    { label: 'Weak signal',   color: C.fgMuted },
  }
}

interface Props {
  conviction: Conviction
  size?: 'sm' | 'lg'
}

export default function ConvictionBadge({ conviction, size = 'sm' }: Props) {
  const cfg = config(usePalette())
  const { label, color } = cfg[conviction] ?? cfg.LOW
  const fontSize = size === 'lg' ? 13 : 11

  return (
    <Text style={{ color, fontSize, fontWeight: '600' }}>
      {label}
    </Text>
  )
}
