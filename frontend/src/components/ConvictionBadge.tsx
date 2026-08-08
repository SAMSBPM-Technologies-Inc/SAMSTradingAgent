import type { Conviction } from '../types'

interface ConvictionBadgeProps {
  conviction: Conviction
  size?: 'sm' | 'lg'
}

const styles: Record<Conviction, string> = {
  HIGH:   'bg-brand-500/15 text-brand-500 border border-brand-500/25',
  MEDIUM: 'bg-brand-500/8 text-brand-600 border border-brand-500/15',
  LOW:    'bg-brand-500/5 text-brand-700 dark:text-brand-400 border border-brand-500/10',
}

export default function ConvictionBadge({ conviction, size = 'sm' }: ConvictionBadgeProps) {
  const isLg = size === 'lg'

  return (
    <span
      className={`
        inline-flex items-center font-medium rounded-full
        transition-colors duration-200
        ${styles[conviction]}
        ${isLg ? 'px-3.5 py-1 text-sm' : 'px-2 py-0.5 text-xs'}
      `}
    >
      {{ HIGH: 'Strong Signal', MEDIUM: 'Moderate', LOW: 'Weak Signal' }[conviction]}
    </span>
  )
}
