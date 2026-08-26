import React from 'react'
import { ActivityIndicator } from 'react-native'
import { usePalette } from '../lib/palette'

const sizes = { sm: 16, md: 24, lg: 40 }

interface Props {
  size?: 'sm' | 'md' | 'lg'
  color?: string
}

export default function LoadingSpinner({ size = 'md', color }: Props) {
  const C = usePalette()
  return <ActivityIndicator size={sizes[size]} color={color ?? C.brand} />
}
