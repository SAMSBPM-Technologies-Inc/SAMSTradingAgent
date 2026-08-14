/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/**/*.{js,jsx,ts,tsx}',
    './src/**/*.{js,jsx,ts,tsx}',
  ],
  presets: [require('nativewind/preset')],
  darkMode: 'media',
  theme: {
    extend: {
      colors: {
        brand: {
          400: '#f5803b',
          500: '#f2600c',
          700: '#c24d08',
        },
        // Light semantic tokens
        fg: '#14110c',
        'fg-muted': '#83786a',
        surface: '#ffffff',
        bg: '#f5f2ed',
        border: '#e7e2d8',
      },
    },
  },
  plugins: [],
}
