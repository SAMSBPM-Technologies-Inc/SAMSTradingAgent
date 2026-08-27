import { useEffect, useState } from 'react'

/**
 * Subscribe to a CSS media query from JS.
 *
 * Used where a layout has to *switch structure*, not just restyle — a nine
 * column table and a stack of cards are different DOM, and no amount of CSS
 * turns one into the other without lying to a screen reader about what is a
 * row and what is a cell.
 *
 * Where CSS alone can do the job it should: this hook renders one branch or the
 * other, so anything gated on it is absent from the DOM at the other size. That
 * is the point — it is what stops a 52rem table existing at all on a phone —
 * but it also means the two branches must never both be mounted.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window !== 'undefined' && window.matchMedia
      ? window.matchMedia(query).matches
      : false,
  )

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return
    const mql = window.matchMedia(query)
    const onChange = () => setMatches(mql.matches)
    onChange()
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [query])

  return matches
}

/** Tailwind's `md` breakpoint — where the wide record tables become readable. */
export const useIsCompact = () => !useMediaQuery('(min-width: 768px)')
