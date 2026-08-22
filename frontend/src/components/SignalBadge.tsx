import type { Signal } from '../types'

interface SignalBadgeProps {
  /** PENDING covers a watched ticker the pipeline has not scored yet. */
  signal: Signal | 'PENDING'
  size?: 'sm' | 'lg'
}

const styles: Record<Signal | 'PENDING', string> = {
  BUY:  'bg-[var(--tint-buy)] text-[var(--accent-buy)]',
  SELL: 'bg-[var(--tint-sell)] text-[var(--accent-sell)]',
  HOLD: 'bg-[var(--tint-hold)] text-[var(--accent-hold)]',
  PENDING: 'bg-[var(--color-border)]/60 text-[var(--color-fg-muted)]',
}

export default function SignalBadge({ signal, size = 'sm' }: SignalBadgeProps) {
  return (
    <span
      style={{ borderRadius: '6px', fontFamily: 'Work Sans, system-ui, sans-serif', letterSpacing: '0.02em' }}
      className={`
        inline-flex items-center font-bold
        ${styles[signal]}
        ${size === 'lg' ? 'px-3.5 py-1.5 text-sm' : 'px-2.5 py-1 text-[11px]'}
      `}
    >
      {signal}
    </span>
  )
}
