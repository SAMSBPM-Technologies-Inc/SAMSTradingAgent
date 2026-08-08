import type { Signal } from '../types'

interface SignalBadgeProps {
  signal: Signal
  size?: 'sm' | 'lg'
}

const styles: Record<Signal, string> = {
  BUY:  'bg-[#eaf6ee] text-[#15803d]',
  SELL: 'bg-[#fbebeb] text-[#b91c1c]',
  HOLD: 'bg-[#fbf1e2] text-[#b45309]',
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
