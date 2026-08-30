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
 * glyph is unchanged from before that pass — a gradient recolour of it was
 * tried and rejected, so it stays the flat brand-orange square.
 */

/** The app icon: white trend arrow on the brand square. */
export const IconMark = ({ size = 30 }: { size?: number }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 34 34" aria-hidden="true">
    <rect width="34" height="34" rx="8" fill="#f2600c" />
    <path d="M9 23L15 17L19 20L25 11" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    <path d="M25 11H19M25 11V17" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
  </svg>
)

/**
 * Lockup: the brand-orange mark beside a lowercase "samsbpm." wordmark, with
 * an italic "trading agent" subline — same font, layout, colour and case as
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
