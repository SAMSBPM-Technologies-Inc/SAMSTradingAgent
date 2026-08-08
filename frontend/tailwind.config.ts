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
      },
      fontFamily: {
        archivo: ['Archivo', 'system-ui', 'sans-serif'],
        'work-sans': ['Work Sans', 'system-ui', 'sans-serif'],
        fraunces: ['Fraunces', 'Georgia', 'serif'],
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
