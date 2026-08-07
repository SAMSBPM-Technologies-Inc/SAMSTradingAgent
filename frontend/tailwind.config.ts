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
          50:  '#fff7ed',
          100: '#ffedd5',
          200: '#fed7aa',
          300: '#fdba74',
          400: '#fb923c',
          500: '#f97316',
          600: '#ea580c',
          700: '#c2410c',
          800: '#9a3412',
          900: '#7c2d12',
          950: '#431407',
        },
        // Semantic tokens via CSS variables
        bg: 'var(--color-bg)',
        surface: 'var(--color-surface)',
        'surface-border': 'var(--color-border)',
        fg: 'var(--color-fg)',
        'fg-muted': 'var(--color-fg-muted)',
      },
      fontFamily: {
        lora: ['Lora', 'Georgia', 'serif'],
        fraunces: ['Fraunces', 'Georgia', 'serif'],
      },
      boxShadow: {
        'brand-sm': '0 1px 3px 0 rgba(249,115,22,0.15), 0 1px 2px -1px rgba(249,115,22,0.1)',
        'brand-md': '0 4px 12px 0 rgba(249,115,22,0.2), 0 2px 4px -2px rgba(249,115,22,0.15)',
        card: '0 1px 4px 0 rgba(0,0,0,0.12), 0 1px 2px -1px rgba(0,0,0,0.08)',
      },
      borderRadius: {
        '2xl': '1rem',
        '3xl': '1.5rem',
      },
    },
  },
  plugins: [],
}

export default config
