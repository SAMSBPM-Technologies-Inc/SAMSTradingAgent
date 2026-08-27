/*
 * The identity, in one place.
 *
 * Both marks used to live inside Layout.tsx, which was fine while the app
 * chrome was the only thing that had a logo. The public landing page is a
 * second consumer, and a second consumer means a second chance to draw the
 * brand slightly differently — which is exactly what happened the first time
 * the landing page was built. Import these; do not re-draw them.
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
 * Stacked wordmark: SAMSBPM in ink over a rule over TRADING AGENT in orange.
 *
 * The handoff specifies #281F13 for the wordmark. That is the light-mode ink
 * colour written as a literal, and on the dark surface (#141109) it would be
 * very nearly invisible — the exact failure the token rule in CLAUDE.md exists
 * to prevent. `--color-fg` is that colour in light mode and its counterpart in
 * dark, so the design's intent survives in both themes.
 *
 * `compact` drops the wordmark and keeps the mark alone.
 */
export function LogoLockup({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex flex-shrink-0 select-none items-center gap-2.5">
      <IconMark size={compact ? 28 : 30} />
      {!compact && (
        // Hidden below sm: at 390px the full lockup is 129px of a 390px bar,
        // and the room it takes is the room the header controls need to be
        // finger-sized. The mark alone still identifies the app.
        <span className="hidden flex-col items-center gap-[3px] sm:flex">
          <span
            className="leading-none text-[var(--color-fg)]"
            style={{ fontFamily: 'Fraunces, Georgia, serif', fontWeight: 600, fontSize: '15px', letterSpacing: '0.005em' }}
          >
            SAMSBPM
          </span>
          <span className="h-px w-full bg-[var(--color-border)]" />
          <span className="text-[8.5px] uppercase leading-none tracking-[0.185em] text-brand-500">
            Trading Agent
          </span>
        </span>
      )}
    </div>
  )
}

export default LogoLockup
