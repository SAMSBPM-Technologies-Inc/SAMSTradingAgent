import type { Signal } from '../types'

interface SignalBadgeProps {
  signal: Signal
  size?: 'sm' | 'lg'
}

const styles: Record<Signal, string> = {
  BUY:  'bg-green-500/10 text-green-500 border border-green-500/20',
  SELL: 'bg-red-500/10 text-red-500 border border-red-500/20',
  HOLD: 'bg-yellow-500/10 text-yellow-500 border border-yellow-500/20',
}

const dot: Record<Signal, string> = {
  BUY:  'bg-green-500',
  SELL: 'bg-red-500',
  HOLD: 'bg-yellow-500',
}

export default function SignalBadge({ signal, size = 'sm' }: SignalBadgeProps) {
  const isLg = size === 'lg'

  return (
    <span
      className={`
        inline-flex items-center gap-1.5 font-semibold rounded-full
        transition-colors duration-200
        ${styles[signal]}
        ${isLg ? 'px-4 py-1.5 text-base' : 'px-2.5 py-0.5 text-xs'}
      `}
    >
      <span className={`rounded-full flex-shrink-0 ${dot[signal]} ${isLg ? 'w-2.5 h-2.5' : 'w-1.5 h-1.5'}`} />
      {signal}
    </span>
  )
}
