import React from 'react'
import { Text } from 'react-native'
import type { Conviction } from '../types'

const config: Record<Conviction, { label: string; color: string }> = {
  HIGH:   { label: 'Strong signal', color: '#f2600c' },
  MEDIUM: { label: 'Moderate',      color: '#83786a' },
  LOW:    { label: 'Weak signal',   color: '#83786a' },
}

interface Props {
  conviction: Conviction
  size?: 'sm' | 'lg'
}

export default function ConvictionBadge({ conviction, size = 'sm' }: Props) {
  const { label, color } = config[conviction] ?? config.LOW
  const fontSize = size === 'lg' ? 13 : 11

  return (
    <Text style={{ color, fontSize, fontWeight: '600' }}>
      {label}
    </Text>
  )
}
