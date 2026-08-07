import { Moon, Sun } from 'lucide-react'
import { useTheme } from '../lib/theme-context'

interface ThemeToggleProps {
  className?: string
}

export default function ThemeToggle({ className = '' }: ThemeToggleProps) {
  const { theme, toggleTheme } = useTheme()

  return (
    <button
      onClick={toggleTheme}
      aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
      className={`
        btn-ghost w-11 h-11 rounded-xl
        text-[var(--color-fg-muted)] hover:text-[var(--color-fg)]
        ${className}
      `}
    >
      {theme === 'dark' ? (
        <Sun className="w-5 h-5" />
      ) : (
        <Moon className="w-5 h-5" />
      )}
    </button>
  )
}
