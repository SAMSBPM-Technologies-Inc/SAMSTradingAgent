import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search } from 'lucide-react'
import { analyzeApi } from '../lib/api'
import { useTheme } from '../lib/theme-context'
import LoadingSpinner from './LoadingSpinner'

/**
 * ⌘K palette — tickers, screens and actions.
 *
 * Ticker search previously existed only inside the watchlist's add-form, so the
 * only way to research a name was to commit to watching it first.
 *
 * The redesign gives it a second job. With ten nav entries reduced to three,
 * this is the flat index of everything the app can do — which is what keeps
 * Performance, Calibration and the Gateway guide one keystroke away rather
 * than buried a menu deep.
 */

interface Suggestion {
  symbol: string
  name: string
}

interface Item {
  key: string
  kind: string
  label: string
  hint: string
  run: () => void
}

interface CommandPaletteProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export default function CommandPalette({ open, onOpenChange }: CommandPaletteProps) {
  const navigate = useNavigate()
  const { theme, toggleTheme } = useTheme()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Suggestion[]>([])
  const [loading, setLoading] = useState(false)
  const [active, setActive] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null)

  const close = useCallback(() => onOpenChange(false), [onOpenChange])

  // Global shortcut. Escape closes from anywhere, including the input.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        onOpenChange(!open)
      } else if (e.key === 'Escape') {
        onOpenChange(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onOpenChange])

  // Where focus was before the dialog opened, so it can be handed back. A
  // modal that drops focus to the top of the document on close loses a
  // keyboard user their place entirely.
  const restoreFocusTo = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (open) {
      restoreFocusTo.current = document.activeElement as HTMLElement | null
      setQuery('')
      setResults([])
      setActive(0)
      // Focus after paint, or the input is not in the DOM yet.
      requestAnimationFrame(() => inputRef.current?.focus())
      // The page behind a modal must not scroll under it.
      const prevOverflow = document.body.style.overflow
      document.body.style.overflow = 'hidden'
      return () => { document.body.style.overflow = prevOverflow }
    }
    restoreFocusTo.current?.focus?.()
  }, [open])

  // Trap Tab inside the dialog. Without this, tabbing walks into the page
  // behind it while the overlay still covers everything.
  const onTrapKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== 'Tab') return
    const focusable = e.currentTarget.querySelectorAll<HTMLElement>(
      'input, button, [href], [tabindex]:not([tabindex="-1"])',
    )
    if (focusable.length === 0) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    }
  }

  const search = useCallback((q: string) => {
    if (debounce.current) clearTimeout(debounce.current)
    if (!q.trim()) {
      setResults([])
      return
    }
    debounce.current = setTimeout(async () => {
      setLoading(true)
      try {
        const res = await analyzeApi.search(q)
        setResults(res.data.slice(0, 6))
      } catch {
        setResults([])
      } finally {
        setLoading(false)
      }
    }, 250)
  }, [])

  const destinations = useMemo(
    () => [
      { kind: 'Screen', label: 'Trade', hint: 'Watchlist, analysis and the order ticket', to: '/' },
      { kind: 'Screen', label: 'Positions', hint: 'Holdings, working orders, closed trades', to: '/positions' },
      { kind: 'Screen', label: 'Settings', hint: 'Autonomy, risk limits, weights, alerts', to: '/settings' },
      { kind: 'Screen', label: 'Performance', hint: 'Signal accuracy and win rate', to: '/performance' },
      { kind: 'Screen', label: 'Calibration', hint: 'Do the thresholds hold up?', to: '/calibration' },
      { kind: 'Screen', label: 'Search tickers', hint: 'Analyse without watching first', to: '/search' },
      { kind: 'Screen', label: 'IB Gateway guide', hint: 'Broker connection setup', to: '/guide' },
    ],
    [],
  )

  const items: Item[] = useMemo(() => {
    const q = query.trim().toLowerCase()

    const screens: Item[] = destinations
      .filter((d) => !q || d.label.toLowerCase().includes(q) || d.hint.toLowerCase().includes(q))
      .map((d) => ({
        key: `screen:${d.to}`,
        kind: d.kind,
        label: d.label,
        hint: d.hint,
        run: () => { close(); navigate(d.to) },
      }))

    const tickers: Item[] = results.map((r) => ({
      key: `ticker:${r.symbol}`,
      kind: 'Ticker',
      label: r.symbol,
      hint: r.name,
      run: () => { close(); navigate(`/ticker/${r.symbol.toUpperCase()}`) },
    }))

    const actionLabel = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'
    const actions: Item[] = (!q || actionLabel.toLowerCase().includes(q) || 'theme'.includes(q))
      ? [{
        key: 'action:theme',
        kind: 'Action',
        label: actionLabel,
        hint: 'Theme',
        run: () => { close(); toggleTheme() },
      }]
      : []

    // Tickers first once the user has typed — a ticker is what they came for.
    return q ? [...tickers, ...screens, ...actions] : [...screens, ...actions]
  }, [query, results, destinations, theme, navigate, close, toggleTheme])

  // A shrinking result list must not leave the highlight past its end.
  useEffect(() => { setActive(0) }, [query, results])

  if (!open) return null

  const typed = query.trim()

  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center px-4 pt-[12vh]">
      {/* Backdrop as a real button: it is a dismiss control, so it should be
          focusable and announce itself rather than being a div that happens to
          respond to clicks. Escape closes too, handled globally above. */}
      <button
        type="button"
        aria-label="Close search"
        className="absolute inset-0 cursor-default bg-black/50 backdrop-blur-sm"
        onClick={close}
      />
      {/*
        A modal dialog has to intercept Tab to keep focus inside it — that is the
        WAI-ARIA authoring practice, not an interaction bolted onto inert markup.
        The rule classes `dialog` as non-interactive and cannot express the
        exception.
      */}
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Jump to ticker, screen or action"
        className="relative w-full max-w-[520px] overflow-hidden rounded-[10px]
                   border border-[var(--color-border)] bg-[var(--color-surface)]"
        style={{ boxShadow: '0 18px 50px rgba(0,0,0,.45)' }}
        onKeyDown={onTrapKeyDown}
      >
        <div className="flex items-center gap-3 border-b border-[var(--color-border)] px-3.5 py-3">
          {loading
            ? <LoadingSpinner size="sm" />
            : <Search className="h-4 w-4 text-[var(--color-fg-muted)]" aria-hidden="true" />}
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => { setQuery(e.target.value); search(e.target.value) }}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') {
                e.preventDefault()
                setActive((i) => Math.min(i + 1, items.length - 1))
              } else if (e.key === 'ArrowUp') {
                e.preventDefault()
                setActive((i) => Math.max(i - 1, 0))
              } else if (e.key === 'Enter') {
                e.preventDefault()
                if (items[active]) items[active].run()
                else if (typed) { close(); navigate(`/ticker/${typed.toUpperCase()}`) }
              }
            }}
            placeholder="Ticker, screen, or action…"
            aria-label="Ticker, screen, or action"
            className="flex-1 bg-transparent text-sm text-[var(--color-fg)] outline-none
                       placeholder:text-[var(--color-fg-muted)]"
            autoComplete="off"
          />
          <kbd className="rounded border border-[var(--color-border)] px-1.5 py-0.5 text-[0.6rem]
                          text-[var(--color-fg-muted)]">
            ESC
          </kbd>
        </div>

        <div className="max-h-[340px] overflow-y-auto" aria-live="polite">
          {items.map((item, i) => (
            <button
              key={item.key}
              onClick={item.run}
              onMouseEnter={() => setActive(i)}
              className={`flex w-full items-center gap-2.5 border-b border-[var(--color-border)]
                          px-3.5 py-2.5 text-left text-[12.5px] text-[var(--color-fg)] last:border-b-0
                          ${i === active ? 'bg-[var(--color-hover)]' : ''}`}
            >
              <span className="label-micro w-[52px] flex-shrink-0">{item.kind}</span>
              <span className={`flex-1 truncate ${item.kind === 'Ticker' ? 'num font-semibold text-brand-500' : ''}`}>
                {item.label}
              </span>
              <span className="max-w-[46%] truncate text-[11px] text-[var(--color-fg-muted)]">{item.hint}</span>
            </button>
          ))}

          {typed && !loading && (
            <button
              onClick={() => { close(); navigate(`/ticker/${typed.toUpperCase()}`) }}
              className="w-full px-3.5 py-3 text-left text-sm text-[var(--color-fg-muted)] hover:bg-[var(--color-hover)]"
            >
              Analyze <span className="num font-medium text-[var(--color-fg)]">{typed.toUpperCase()}</span> anyway
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
