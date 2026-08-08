import type { Conviction } from '../types'

interface ConvictionBadgeProps {
  conviction: Conviction
  size?: 'sm' | 'lg'
}

const label: Record<Conviction, string> = {
  HIGH:   'Strong signal',
  MEDIUM: 'Moderate',
  LOW:    'Weak signal',
}

const color: Record<Conviction, string> = {
  HIGH:   'text-[#f2600c]',
  MEDIUM: 'text-[#83786a]',
  LOW:    'text-[#83786a]',
}

export default function ConvictionBadge({ conviction, size = 'sm' }: ConvictionBadgeProps) {
  return (
    <span
      style={{ fontFamily: 'Work Sans, system-ui, sans-serif' }}
      className={`font-medium ${color[conviction]} ${size === 'lg' ? 'text-sm' : 'text-xs'}`}
    >
      {label[conviction]}
    </span>
  )
}
