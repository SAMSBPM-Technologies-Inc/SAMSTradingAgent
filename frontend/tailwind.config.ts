import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        brand: {
          50:  '#fff4ee',
          100: '#ffe4d0',
          200: '#ffc4a0',
          300: '#ff9a6a',
          400: '#f87240',
          500: '#f2600c',
          600: '#d9530a',
          700: '#b34208',
          800: '#8c3307',
          900: '#6e2805',
          950: '#3d1402',
        },
        bg: 'var(--color-bg)',
        surface: 'var(--color-surface)',
        'surface-border': 'var(--color-border)',
        fg: 'var(--color-fg)',
        'fg-muted': 'var(--color-fg-muted)',
        // Verdict palette. Named here so a component writes `text-accent-buy`
        // instead of `text-[var(--accent-buy)]` — the token stays the single
        // definition either way, but the short form is what stops someone
        // reaching for a raw green hex when they're in a hurry.
        elev: 'var(--color-elev)',
        wash: 'var(--color-hover)',
        'tint-buy': 'var(--tint-buy)',
        'tint-sell': 'var(--tint-sell)',
        'tint-hold': 'var(--tint-hold)',
        'accent-buy': 'var(--accent-buy)',
        'accent-sell': 'var(--accent-sell)',
        'accent-hold': 'var(--accent-hold)',
      },
      fontFamily: {
        archivo: ['Archivo', 'system-ui', 'sans-serif'],
        'work-sans': ['Work Sans', 'system-ui', 'sans-serif'],
        fraunces: ['Fraunces', 'Georgia', 'serif'],
        jakarta: ['Plus Jakarta Sans', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      borderRadius: {
        card: '10px',
        chip: '6px',
      },
    },
  },
  plugins: [],
}

export default config
