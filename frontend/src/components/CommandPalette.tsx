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

  useEffect(() => {
    if (open) {
      setQuery('')
      setResults([])
      setActive(0)
      // Focus after paint, or the input is not in the DOM yet.
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [open])

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
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center pt-[15vh] px-4
                 bg-black/40 backdrop-blur-sm"
      onClick={() => setOpen(false)}
      role="dialog"
      aria-modal="true"
      aria-label="Search tickers"
    >
      <div
        className="w-full max-w-lg rounded-xl border border-[var(--color-border)]
                   bg-[var(--color-surface)] overflow-hidden"
        style={{ boxShadow: '0 12px 40px rgba(0,0,0,0.25)' }}
        onClick={(e) => e.stopPropagation()}
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
