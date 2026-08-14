import React from 'react'
import { View, Text } from 'react-native'
import type { Signal } from '../types'

const config: Record<Signal, { bg: string; text: string; label: string }> = {
  BUY:  { bg: '#eaf6ee', text: '#15803d', label: 'BUY' },
  SELL: { bg: '#fbebeb', text: '#b91c1c', label: 'SELL' },
  HOLD: { bg: '#fbf1e2', text: '#b45309', label: 'HOLD' },
}

interface Props {
  signal: Signal
  size?: 'sm' | 'lg'
}

export default function SignalBadge({ signal, size = 'sm' }: Props) {
  const { bg, text, label } = config[signal] ?? config.HOLD
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
