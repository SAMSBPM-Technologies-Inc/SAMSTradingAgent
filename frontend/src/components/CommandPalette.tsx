import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search } from 'lucide-react'
import { analyzeApi } from '../lib/api'
import LoadingSpinner from './LoadingSpinner'

/**
 * ⌘K ticker lookup, available on every page.
 *
 * Ticker search previously existed only inside the watchlist's add-form, so the
 * only way to research a name was to commit to watching it first. This is the
 * shortcut every comparable finance tool has.
 */

interface Suggestion {
  symbol: string
  name: string
}

export default function CommandPalette() {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Suggestion[]>([])
  const [loading, setLoading] = useState(false)
  const [active, setActive] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Global shortcut. Escape closes from anywhere, including the input.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen((v) => !v)
      } else if (e.key === 'Escape') {
        setOpen(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

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
        setResults(res.data.slice(0, 8))
        setActive(0)
      } catch {
        setResults([])
      } finally {
        setLoading(false)
      }
    }, 250)
  }, [])

  const go = (symbol: string) => {
    setOpen(false)
    navigate(`/ticker/${symbol.toUpperCase()}`)
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center pt-[15vh] px-4">
      {/* Backdrop as a real button: it is a dismiss control, so it should be
          focusable and announce itself rather than being a div that happens to
          respond to clicks. Escape closes too, handled globally above. */}
      <button
        type="button"
        aria-label="Close search"
        className="absolute inset-0 bg-black/40 backdrop-blur-sm cursor-default"
        onClick={() => setOpen(false)}
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
        aria-label="Search tickers"
        className="relative w-full max-w-lg rounded-xl border border-[var(--color-border)]
                   bg-[var(--color-surface)] overflow-hidden"
        style={{ boxShadow: '0 12px 40px rgba(0,0,0,0.25)' }}
        onKeyDown={onTrapKeyDown}
      >
        <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--color-border)]">
          {loading
            ? <LoadingSpinner size="sm" />
            : <Search className="w-4 h-4 text-[var(--color-fg-muted)]" />}
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => { setQuery(e.target.value); search(e.target.value) }}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') {
                e.preventDefault()
                setActive((i) => Math.min(i + 1, results.length - 1))
              } else if (e.key === 'ArrowUp') {
                e.preventDefault()
                setActive((i) => Math.max(i - 1, 0))
              } else if (e.key === 'Enter') {
                e.preventDefault()
                if (results[active]) go(results[active].symbol)
                else if (query.trim()) go(query.trim())
              }
            }}
            placeholder="Search ticker or company…"
            aria-label="Search ticker or company"
            className="flex-1 bg-transparent outline-none text-sm text-[var(--color-fg)]
                       placeholder:text-[var(--color-fg-muted)]"
            autoComplete="off"
          />
          <kbd className="text-[0.6rem] px-1.5 py-0.5 rounded border border-[var(--color-border)]
                          text-[var(--color-fg-muted)]">
            ESC
          </kbd>
        </div>

        <div className="max-h-80 overflow-y-auto" aria-live="polite">
          {results.map((r, i) => (
            <button
              key={r.symbol}
              onClick={() => go(r.symbol)}
              onMouseEnter={() => setActive(i)}
              className={`flex items-center gap-3 w-full px-4 py-2.5 text-left transition-colors
                          ${i === active ? 'bg-[var(--color-bg)]' : ''}`}
            >
              <span
                className="font-semibold text-sm w-16 flex-shrink-0 text-brand-500"
                style={{ fontFamily: 'Archivo, system-ui, sans-serif' }}
              >
                {r.symbol}
              </span>
              <span className="text-sm text-[var(--color-fg-muted)] truncate">{r.name}</span>
            </button>
          ))}

          {query.trim() && results.length === 0 && !loading && (
            <button
              onClick={() => go(query.trim())}
              className="w-full px-4 py-3 text-left text-sm text-[var(--color-fg-muted)]
                         hover:bg-[var(--color-bg)]"
            >
              Analyze <span className="text-[var(--color-fg)] font-medium">
                {query.trim().toUpperCase()}
              </span> anyway
            </button>
          )}

          {!query.trim() && (
            <p className="px-4 py-6 text-center text-xs text-[var(--color-fg-muted)]">
              Type a ticker or company name. You don&rsquo;t have to watch it first.
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
