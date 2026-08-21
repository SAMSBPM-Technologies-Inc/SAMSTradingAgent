import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, Search } from 'lucide-react'
import { analyzeApi } from '../lib/api'
import Layout from '../components/Layout'
import LoadingSpinner from '../components/LoadingSpinner'

/**
 * Ticker lookup, reachable from the mobile "Analyze" tab.
 *
 * The watchlist's add-form can also search, but it only ever *adds* — there was
 * no way to look up a symbol you don't already track. This route goes straight
 * to the analysis instead, so researching a name and committing to watching it
 * stay separate decisions.
 */
export default function SearchPage() {
  const navigate = useNavigate()
  const [value, setValue] = useState('')
  const [results, setResults] = useState<{ symbol: string; name: string }[]>([])
  const [isSearching, setIsSearching] = useState(false)
  const [searched, setSearched] = useState(false)
  const [activeIdx, setActiveIdx] = useState(-1)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => { inputRef.current?.focus() }, [])

  const search = useCallback((q: string) => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (!q.trim()) {
      setResults([])
      setSearched(false)
      return
    }
    debounceRef.current = setTimeout(async () => {
      setIsSearching(true)
      try {
        const res = await analyzeApi.search(q)
        setResults(res.data)
        setActiveIdx(-1)
      } catch {
        setResults([])
      } finally {
        setIsSearching(false)
        setSearched(true)
      }
    }, 300)
  }, [])

  const open = (symbol: string) => navigate(`/ticker/${symbol.toUpperCase()}`)

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIdx((i) => Math.min(i + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx((i) => Math.max(i - 1, -1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (activeIdx >= 0) open(results[activeIdx].symbol)
      else if (value.trim()) open(value.trim())
    }
  }

  return (
    <Layout>
      <div className="mb-6">
        <h1
          className="text-2xl font-light text-[var(--color-fg)]"
          style={{ fontFamily: 'Fraunces, Georgia, serif' }}
        >
          Analyze a Ticker
        </h1>
        <p className="text-sm text-[var(--color-fg-muted)] mt-0.5">
          Look up any symbol — you don&rsquo;t have to watch it first.
        </p>
      </div>

      <div className="relative mb-4">
        <div className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-fg-muted)]">
          {isSearching ? <LoadingSpinner size="sm" /> : <Search className="w-4 h-4" />}
        </div>
        <input
          ref={inputRef}
          id="ticker-search"
          type="text"
          value={value}
          onChange={(e) => {
            setValue(e.target.value)
            search(e.target.value)
          }}
          onKeyDown={handleKeyDown}
          placeholder="Search ticker or company name…"
          aria-label="Search ticker or company name"
          className="input pl-9"
          maxLength={20}
          autoComplete="off"
        />
      </div>

      <div aria-live="polite">
        {results.length > 0 ? (
          <div className="card overflow-hidden p-0">
            {results.map((r, i) => (
              <button
                key={r.symbol}
                onClick={() => open(r.symbol)}
                onMouseEnter={() => setActiveIdx(i)}
                className={`flex items-center gap-3 w-full px-4 py-3 text-left
                            border-b border-[var(--color-border)] last:border-b-0
                            transition-colors group
                            ${i === activeIdx ? 'bg-[var(--color-bg)]' : ''}`}
              >
                <span
                  className="font-semibold text-sm w-16 flex-shrink-0 text-brand-500"
                  style={{ fontFamily: 'Archivo, system-ui, sans-serif' }}
                >
                  {r.symbol}
                </span>
                <span className="text-sm text-[var(--color-fg-muted)] truncate flex-1">
                  {r.name}
                </span>
                <ArrowRight className="w-4 h-4 flex-shrink-0 text-[var(--color-fg-muted)]
                                       opacity-0 group-hover:opacity-100 transition-opacity" />
              </button>
            ))}
          </div>
        ) : searched && !isSearching ? (
          <p className="text-sm text-[var(--color-fg-muted)] px-1">
            No matches for &ldquo;{value}&rdquo;. Press Enter to analyze it as a symbol anyway.
          </p>
        ) : null}
      </div>
    </Layout>
  )
}
