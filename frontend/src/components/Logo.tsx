/*
 * The identity, in one place.
 *
 * Both marks used to live inside Layout.tsx, which was fine while the app
 * chrome was the only thing that had a logo. The public landing page is a
 * second consumer, and a second consumer means a second chance to draw the
 * brand slightly differently — which is exactly what happened the first time
 * the landing page was built. Import these; do not re-draw them.
 *
 * The wordmark follows samsbpm.ca's logo system exactly: Plus Jakarta Sans
 * at weight 800, a lowercase wordmark with an orange full stop, and an
 * italic subline underneath — so the mark reads as one SAMSBPM family
 * across properties rather than a second brand drawn from scratch. The icon
 * glyph itself stays the trend-arrow (trading-specific), just recoloured to
 * the same gradient the reference site uses for its mark.
 */

import { useId } from 'react'

/** The app icon: white trend arrow on the brand gradient square. */
export const IconMark = ({ size = 30 }: { size?: number }) => {
  const gradientId = useId()
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 34 34"
      aria-hidden="true"
      style={{ filter: 'drop-shadow(0 6px 12px rgba(234,88,12,0.45))' }}
    >
      <defs>
        <linearGradient id={gradientId} gradientTransform="rotate(152 17 17)">
          <stop offset="0%" stopColor="#FFB068" />
          <stop offset="50%" stopColor="#F97316" />
          <stop offset="100%" stopColor="#B45309" />
        </linearGradient>
      </defs>
      <rect width="34" height="34" rx="10" fill={`url(#${gradientId})`} />
      <path d="M9 23L15 17L19 20L25 11" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      <path d="M25 11H19M25 11V17" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </svg>
  )
}

/**
 * Lockup: gradient mark beside a lowercase "samsbpm." wordmark, with an
 * italic "trading agent" subline — same font, layout, colour and case as
 * samsbpm.ca's logo.
 *
 * `compact` drops the wordmark and keeps the mark alone.
 */
export function LogoLockup({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex flex-shrink-0 select-none items-center gap-2.5">
      <IconMark size={compact ? 28 : 32} />
      {!compact && (
        // Hidden below sm: at 390px the full lockup is 129px of a 390px bar,
        // and the room it takes is the room the header controls need to be
        // finger-sized. The mark alone still identifies the app.
        <span className="hidden flex-col leading-none sm:flex">
          <span className="font-jakarta text-[17px] font-extrabold leading-none tracking-[-0.025em] text-[var(--color-fg)]">
            samsbpm<span className="text-brand-500">.</span>
          </span>
          <span className="font-jakarta mt-1 text-[9px] font-medium italic leading-none tracking-[0.04em] text-[var(--color-fg-muted)]">
            trading agent
          </span>
        </span>
      )}
    </div>
  )
}

export default LogoLockup
