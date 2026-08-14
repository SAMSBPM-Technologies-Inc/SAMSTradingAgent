import React from 'react'
import { ActivityIndicator } from 'react-native'

const sizes = { sm: 16, md: 24, lg: 40 }

interface Props {
  size?: 'sm' | 'md' | 'lg'
  color?: string
}

export default function LoadingSpinner({ size = 'md', color = '#f2600c' }: Props) {
  return <ActivityIndicator size={sizes[size]} color={color} />
}
