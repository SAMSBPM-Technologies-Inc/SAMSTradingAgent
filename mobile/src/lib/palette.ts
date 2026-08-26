import { useTheme } from './theme-context'

/**
 * The mobile colour palette, in both themes.
 *
 * Mirrors the web tokens in `frontend/src/index.css` — `:root` is `light` here
 * and `.dark` is `dark`. The web file is the reference; when a token changes
 * there it changes here, and the two must not be allowed to drift.
 *
 * Every mobile screen used to declare its own light-only `const C` block. That
 * made dark mode impossible and, less obviously, let the screens disagree with
 * each other: the watchlist painted its verdict colours `#16a34a/#d97706/
 * #ef4444` while every other screen used the web accents `#15803d/#b45309/
 * #b91c1c`, so the same BUY was two different greens depending on where you
 * looked. Both are now the web accent.
 *
 * Colours live here and nowhere else. A raw hex in a component is a
 * light-mode-only colour — the same rule the web side already enforces, and for
 * the same reason: it renders as an unreadable block the first time someone
 * switches theme.
 */

export interface Palette {
  /** Page background. */
  bg: string
  /** Cards and rows sitting on `bg`. */
  surface: string
  /** One step above `surface`, for things that float: menus, sheets, toasts. */
  elev: string
  border: string
  /** Wash for pressed/hovered bordered controls. */
  hover: string
  fg: string
  fgMuted: string
  brand: string

  /** Verdict accents — bars and outcome text. Darken in light, lighten in dark
   *  so they stay legible against `surface` either way. */
  green: string
  amber: string
  red: string

  /** Verdict tints — the card wash behind BUY / HOLD / SELL. */
  tintBuy: string
  tintSell: string
  tintHold: string

  /** Candle bodies. Same values as green/red, named for the chart's benefit. */
  up: string
  down: string
}

export const light: Palette = {
  bg: '#fbfaf8',
  surface: '#ffffff',
  elev: '#f6f4ef',
  border: '#e7e2d8',
  hover: '#f1eee6',
  fg: '#14110c',
  fgMuted: '#83786a',
  brand: '#f2600c',

  green: '#15803d',
  amber: '#b45309',
  red: '#b91c1c',

  tintBuy: '#eaf6ee',
  tintSell: '#fbebeb',
  tintHold: '#fbf1e2',

  up: '#15803d',
  down: '#b91c1c',
}

export const dark: Palette = {
  bg: '#0e0c09',
  surface: '#141109',
  elev: '#1a1610',
  border: '#2a2420',
  hover: '#221d17',
  fg: '#f0ece4',
  fgMuted: '#9a8f82',
  // The brand orange is the one colour that does not flip: it is the identity,
  // and it clears contrast on both grounds.
  brand: '#f2600c',

  green: '#4ade80',
  amber: '#fbbf24',
  red: '#f87171',

  tintBuy: '#10231a',
  tintSell: '#2a1414',
  tintHold: '#2a2010',

  up: '#4ade80',
  down: '#f87171',
}

export const PALETTES = { light, dark } as const

/** The palette for the active theme. Re-renders when the theme changes. */
export function usePalette(): Palette {
  const { theme } = useTheme()
  return PALETTES[theme]
}
