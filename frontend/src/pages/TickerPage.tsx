import { jsPDF } from 'jspdf'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Activity,
  AlertCircle,
  ArrowLeft,
  Calendar,
  ChevronDown,
  ChevronUp,
  Download,
  Mail,
  RefreshCw,
  Shield,
  Target,
  TrendingDown,
  TrendingUp,
  Users,
  Zap,
} from 'lucide-react'
import { analyzeApi } from '../lib/api'
import type { AnalyzeResponse, AlternativeData } from '../types'
import Layout from '../components/Layout'
import SignalBadge from '../components/SignalBadge'
import ConvictionBadge from '../components/ConvictionBadge'
import LoadingSpinner from '../components/LoadingSpinner'

// ── Score gauge ───────────────────────────────────────────────────────────────

function ScoreGauge({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  // Clamp rotation: 0 = -90deg, 100 = 90deg
  const rotation = -90 + (pct / 100) * 180

  const color =
    pct >= 70 ? '#22c55e' :
    pct >= 40 ? '#f97316' :
    '#ef4444'

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative w-32 h-16 overflow-hidden">
        {/* Background arc */}
        <svg viewBox="0 0 128 64" className="w-full h-full" aria-hidden="true">
          <path
            d="M 8 64 A 56 56 0 0 1 120 64"
            fill="none"
            stroke="var(--color-border)"
            strokeWidth="10"
            strokeLinecap="round"
          />
          {/* Colored arc — approximate using stroke-dasharray */}
          <path
            d="M 8 64 A 56 56 0 0 1 120 64"
            fill="none"
            stroke={color}
            strokeWidth="10"
            strokeLinecap="round"
            strokeDasharray={`${(pct / 100) * 176} 176`}
            style={{ transition: 'stroke-dasharray 0.6s ease' }}
          />
        </svg>
        {/* Needle */}
        <div
          className="absolute bottom-0 left-1/2 origin-bottom"
          style={{
            width: '2px',
            height: '3rem',
            marginLeft: '-1px',
            backgroundColor: color,
            borderRadius: '1px',
            transform: `rotate(${rotation}deg)`,
            transition: 'transform 0.6s ease',
          }}
        />
        <div
          className="absolute bottom-0 left-1/2 -translate-x-1/2 w-3 h-3 rounded-full"
          style={{ backgroundColor: color, marginBottom: '-6px' }}
        />
      </div>
      <div className="flex flex-col items-center">
        <span
          className="text-3xl font-light text-[var(--color-fg)]"
          style={{ fontFamily: 'Fraunces, Georgia, serif' }}
        >
          {pct}
        </span>
        <span className="text-xs text-[var(--color-fg-muted)]">/ 100 score</span>
      </div>
    </div>
  )
}

// ── Stat cell ─────────────────────────────────────────────────────────────────

function StatCell({
  label,
  value,
  icon: Icon,
  color = 'text-[var(--color-fg)]',
}: {
  label: string
  value: string
  icon?: React.FC<{ className?: string }>
  color?: string
}) {
  return (
    <div className="flex flex-col gap-1 p-3 rounded-xl bg-[var(--color-bg)] border border-[var(--color-border)]">
      <div className="flex items-center gap-1.5">
        {Icon && <Icon className="w-3.5 h-3.5 text-[var(--color-fg-muted)]" />}
        <span className="text-xs text-[var(--color-fg-muted)]">{label}</span>
      </div>
      <span className={`text-base font-semibold ${color}`}>{value}</span>
    </div>
  )
}

// ── Section block ─────────────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="card p-5">
      <h3
        className="text-base font-medium text-[var(--color-fg)] mb-3"
        style={{ fontFamily: 'Fraunces, Georgia, serif' }}
      >
        {title}
      </h3>
      {children}
    </div>
  )
}

// ── List block ────────────────────────────────────────────────────────────────

function BulletList({ items, color }: { items: string[]; color?: string }) {
  return (
    <ul className="flex flex-col gap-2">
      {items.map((item, i) => (
        <li key={i} className="flex items-start gap-2 text-sm text-[var(--color-fg)]">
          <span className={`mt-1.5 w-1.5 h-1.5 rounded-full flex-shrink-0 ${color ?? 'bg-brand-500'}`} />
          {item}
        </li>
      ))}
    </ul>
  )
}

// ── Collapsible ───────────────────────────────────────────────────────────────

function Collapsible({ title, children }: { title: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(true)
  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center justify-between w-full py-1 text-sm font-medium
                   text-[var(--color-fg-muted)] hover:text-[var(--color-fg)] transition-colors"
      >
        {title}
        {open ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
      </button>
      {open && <div className="mt-3">{children}</div>}
    </div>
  )
}

// ── Alternative Data section ──────────────────────────────────────────────────

function SentimentPill({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null
  const bullish = ['BULLISH', 'MILDLY_BULLISH', 'LOW'].includes(value)
  const bearish  = ['BEARISH', 'MILDLY_BEARISH', 'HIGH'].includes(value)
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium
      ${bullish ? 'bg-green-500/10 text-green-500' :
        bearish ? 'bg-red-500/10 text-red-500' :
        'bg-[var(--color-border)]/60 text-[var(--color-fg-muted)]'}`}>
      {label}: {value.replace('_', ' ')}
    </span>
  )
}

function AltDataRow({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="flex items-start justify-between gap-2 py-1.5 border-b border-[var(--color-border)] last:border-0">
      <span className="text-xs text-[var(--color-fg-muted)] flex-shrink-0">{label}</span>
      <div className="text-right">
        <span className="text-xs font-medium text-[var(--color-fg)]">{value}</span>
        {sub && <div className="text-[0.65rem] text-[var(--color-fg-muted)]">{sub}</div>}
      </div>
    </div>
  )
}

function AlternativeDataSection({ data }: { data: AlternativeData }) {
  const si  = data.short_interest
  const opt = data.options_flow
  const ins = data.insider_trades

  const hasAny = si?.short_percent_of_float != null || opt?.put_call_ratio != null || (ins?.buy_count_90d != null || ins?.sell_count_90d != null)
  if (!hasAny) return null

  return (
    <Section title="Alternative Data">
      <div className="flex flex-col gap-4">

        {/* Options Flow */}
        {opt?.put_call_ratio != null && (
          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <Activity className="w-3.5 h-3.5 text-[var(--color-fg-muted)]" />
              <span className="text-xs font-medium text-[var(--color-fg-muted)] uppercase tracking-wide">Options Flow</span>
              <SentimentPill label="signal" value={opt.sentiment} />
            </div>
            <AltDataRow
              label="Put/Call Ratio"
              value={opt.put_call_ratio.toFixed(2)}
              sub={`${(opt.put_volume ?? 0).toLocaleString()} puts  /  ${(opt.call_volume ?? 0).toLocaleString()} calls  ·  exp ${opt.expiry ?? ''}`}
            />
            <p className="text-[0.65rem] text-[var(--color-fg-muted)] mt-1">
              {'<0.7 = calls dominating (bullish)  ·  >1.5 = puts dominating (bearish hedging)'}
            </p>
          </div>
        )}

        {/* Short Interest */}
        {si?.short_percent_of_float != null && (
          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <TrendingDown className="w-3.5 h-3.5 text-[var(--color-fg-muted)]" />
              <span className="text-xs font-medium text-[var(--color-fg-muted)] uppercase tracking-wide">Short Interest</span>
              {si.squeeze_risk && (
                <SentimentPill label="squeeze risk" value={si.squeeze_risk} />
              )}
            </div>
            <AltDataRow
              label="% of Float Shorted"
              value={`${((si.short_percent_of_float ?? 0) * 100).toFixed(1)}%`}
            />
            {si.short_ratio != null && (
              <AltDataRow
                label="Days to Cover"
                value={`${si.short_ratio.toFixed(1)}d`}
                sub="avg days for shorts to buy back at current volume"
              />
            )}
            <p className="text-[0.65rem] text-[var(--color-fg-muted)] mt-1">
              High short float + rising price = potential short squeeze
            </p>
          </div>
        )}

        {/* Insider Activity */}
        {(ins?.buy_count_90d != null || ins?.sell_count_90d != null) && (
          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <Users className="w-3.5 h-3.5 text-[var(--color-fg-muted)]" />
              <span className="text-xs font-medium text-[var(--color-fg-muted)] uppercase tracking-wide">Insider Activity (90d)</span>
              <SentimentPill label="signal" value={ins.net_sentiment} />
            </div>
            <AltDataRow
              label="Transactions"
              value={`${ins.buy_count_90d ?? 0} buys  /  ${ins.sell_count_90d ?? 0} sells`}
            />
            {ins.recent && ins.recent.length > 0 && (
              <div className="mt-2 flex flex-col gap-1">
                {ins.recent.slice(0, 3).map((t, i) => (
                  <div key={i} className="flex items-start justify-between text-[0.65rem] text-[var(--color-fg-muted)]">
                    <span className="truncate mr-2">{t.insider ?? 'Unknown'}</span>
                    <span className="flex-shrink-0 tabular-nums">
                      {t.transaction ?? ''}{t.shares ? ` · ${t.shares.toLocaleString()} sh` : ''} · {t.date ?? ''}
                    </span>
                  </div>
                ))}
              </div>
            )}
            <p className="text-[0.65rem] text-[var(--color-fg-muted)] mt-1">
              Insider buying = management confidence. Selling = diversification (less signal).
            </p>
          </div>
        )}
      </div>
    </Section>
  )
}

// ── Analyst note bullet summariser ────────────────────────────────────────────

function toSentences(text: string): string[] {
  // Split on sentence boundaries, filter noise
  return text
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 20)
}

function AnalystNoteSummary({ note }: { note: string }) {
  const sentences = toSentences(note)
  return (
    <ul className="flex flex-col gap-2">
      {sentences.map((s, i) => (
        <li key={i} className="flex items-start gap-2 text-sm text-[var(--color-fg-muted)]">
          <span className="mt-1.5 w-1.5 h-1.5 rounded-full flex-shrink-0 bg-brand-500" />
          {s}
        </li>
      ))}
    </ul>
  )
}

// ── Export helpers ─────────────────────────────────────────────────────────────

function buildExportText(data: AnalyzeResponse): string {
  const lines: string[] = [
    `${data.ticker} — Analysis Report`,
    `Generated: ${new Date(data.generated_at).toLocaleString()}`,
    '',
    `Signal: ${data.signal}  |  Score: ${Math.round(data.score * 100)}/100  |  Confidence: ${Math.round(data.confidence * 100)}%`,
    data.conviction ? `Conviction: ${data.conviction}` : '',
    data.price_target ? `Price Target: $${data.price_target.toFixed(2)}` : '',
    data.stop_loss ? `Stop Loss: $${data.stop_loss.toFixed(2)}` : '',
    data.time_horizon ? `Time Horizon: ${data.time_horizon}` : '',
    '',
  ]

  if (data.thesis) lines.push('INVESTMENT THESIS', data.thesis, '')
  if (data.analyst_note) lines.push('ANALYST NOTE', data.analyst_note, '')
  if (data.bull_case) lines.push('BULL CASE', data.bull_case, '')
  if (data.bear_case) lines.push('BEAR CASE', data.bear_case, '')
  if (data.entry_suggestion) lines.push('ENTRY', data.entry_suggestion, '')
  if (data.exit_suggestion) lines.push('EXIT', data.exit_suggestion, '')
  if (data.catalysts?.length) lines.push('CATALYSTS', ...data.catalysts.map((c) => `• ${c}`), '')
  if (data.key_risks?.length) lines.push('KEY RISKS', ...data.key_risks.map((r) => `• ${r}`), '')
  if (data.explanation) lines.push('EXPLANATION', data.explanation, '')

  lines.push('---', 'Disclaimer: This report is generated by SAMSTradingAgent for informational purposes only and does not constitute financial advice.')
  return lines.filter((l) => l !== undefined).join('\n')
}

function downloadTxt(data: AnalyzeResponse) {
  const text = buildExportText(data)
  const blob = new Blob([text], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${data.ticker}-analysis-${new Date().toISOString().slice(0, 10)}.txt`
  a.click()
  URL.revokeObjectURL(url)
}

function emailReport(data: AnalyzeResponse) {
  const subject = encodeURIComponent(`${data.ticker} Analysis — ${data.signal} (${Math.round(data.score * 100)}/100)`)
  const body = encodeURIComponent(buildExportText(data))
  window.location.href = `mailto:?subject=${subject}&body=${body}`
}

function downloadPdf(data: AnalyzeResponse) {
  const doc = new jsPDF({ unit: 'pt', format: 'letter' })
  const margin = 48
  const pageW = doc.internal.pageSize.getWidth()
  const contentW = pageW - margin * 2
  let y = margin

  const brand = [242, 96, 12] as const  // #f2600c

  const addPage = () => {
    doc.addPage()
    y = margin
  }

  const checkY = (needed = 20) => {
    if (y + needed > doc.internal.pageSize.getHeight() - margin) addPage()
  }

  const heading = (text: string, size = 10) => {
    checkY(20)
    doc.setFontSize(size)
    doc.setTextColor(...brand)
    doc.setFont('helvetica', 'bold')
    doc.text(text.toUpperCase(), margin, y)
    y += size + 4
    doc.setTextColor(30, 30, 30)
  }

  const body = (text: string, size = 9) => {
    doc.setFontSize(size)
    doc.setFont('helvetica', 'normal')
    doc.setTextColor(60, 60, 60)
    const lines = doc.splitTextToSize(text, contentW) as string[]
    lines.forEach((line: string) => {
      checkY(size + 3)
      doc.text(line, margin, y)
      y += size + 3
    })
  }

  const divider = () => {
    checkY(12)
    doc.setDrawColor(220, 220, 220)
    doc.line(margin, y, pageW - margin, y)
    y += 10
  }

  const gap = (n = 12) => { y += n }

  // ── Header ────────────────────────────────────────────────────────────────
  doc.setFontSize(28)
  doc.setFont('helvetica', 'bold')
  doc.setTextColor(...brand)
  doc.text(data.ticker, margin, y)

  if (data.current_price != null) {
    doc.setFontSize(14)
    doc.setTextColor(30, 30, 30)
    const priceStr = `$${data.current_price.toFixed(2)}${data.day_change_pct != null ? `  ${data.day_change_pct >= 0 ? '+' : ''}${data.day_change_pct.toFixed(2)}%` : ''}`
    doc.text(priceStr, margin, y + 22)
  }

  // Signal pill (right-aligned)
  const signalColor: Record<string, [number, number, number]> = {
    BUY: [34, 197, 94], SELL: [239, 68, 68], HOLD: [234, 179, 8],
  }
  const sc = signalColor[data.signal] ?? ([100, 100, 100] as [number, number, number])
  doc.setFillColor(...sc)
  doc.roundedRect(pageW - margin - 56, y - 16, 56, 22, 4, 4, 'F')
  doc.setFontSize(11)
  doc.setFont('helvetica', 'bold')
  doc.setTextColor(255, 255, 255)
  doc.text(data.signal, pageW - margin - 28, y - 1, { align: 'center' })

  y += 40
  divider()

  // ── Key metrics ───────────────────────────────────────────────────────────
  const score = Math.round(data.score * 100)
  const conf  = Math.round(data.confidence * 100)
  const metrics = [
    ['Score', `${score}/100`],
    ['Confidence', `${conf}%`],
    data.conviction ? ['Conviction', data.conviction] : null,
    data.price_target ? ['Price Target', `$${data.price_target.toFixed(2)}`] : null,
    data.stop_loss    ? ['Stop Loss',    `$${data.stop_loss.toFixed(2)}`]    : null,
    data.time_horizon ? ['Time Horizon', data.time_horizon]                  : null,
  ].filter(Boolean) as [string, string][]

  const colW = contentW / 3
  metrics.forEach(([label, value], i) => {
    const col = i % 3
    const row = Math.floor(i / 3)
    const cx = margin + col * colW
    const cy = y + row * 36
    doc.setFontSize(7)
    doc.setFont('helvetica', 'normal')
    doc.setTextColor(120, 120, 120)
    doc.text(label.toUpperCase(), cx, cy)
    doc.setFontSize(11)
    doc.setFont('helvetica', 'bold')
    doc.setTextColor(30, 30, 30)
    doc.text(value, cx, cy + 13)
  })

  y += Math.ceil(metrics.length / 3) * 36 + 4
  divider()

  // ── Sections ──────────────────────────────────────────────────────────────
  const section = (label: string, text?: string | null, items?: string[] | null) => {
    if (!text && !items?.length) return
    heading(label)
    if (text) body(text)
    if (items?.length) items.forEach((s) => body(`• ${s}`))
    gap(10)
  }

  section('Investment Thesis', data.thesis)
  section('Analyst Note', data.analyst_note)
  section('Bull Case', data.bull_case)
  section('Bear Case', data.bear_case)
  section('Catalysts', null, data.catalysts)
  section('Key Risks', null, data.key_risks)
  section('Entry', data.entry_suggestion)
  section('Exit', data.exit_suggestion)
  section('Explanation', data.explanation)

  // ── Footer ────────────────────────────────────────────────────────────────
  divider()
  doc.setFontSize(7)
  doc.setFont('helvetica', 'italic')
  doc.setTextColor(160, 160, 160)
  doc.text(
    `Generated ${new Date(data.generated_at).toLocaleString()}  ·  SAMSTradingAgent  ·  For informational purposes only, not financial advice.`,
    margin, y,
  )

  doc.save(`${data.ticker}-analysis-${new Date().toISOString().slice(0, 10)}.pdf`)
}

function ExportMenu({ data }: { data: AnalyzeResponse }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="btn-secondary text-sm px-3 py-1.5 h-auto min-h-0 flex items-center gap-1.5"
      >
        <Download className="w-3.5 h-3.5" />
        Export
        <ChevronDown className="w-3 h-3" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 z-20 w-40 border border-[var(--color-border)] bg-[var(--color-surface)] overflow-hidden" style={{ borderRadius: '8px', boxShadow: '0 4px 12px rgba(0,0,0,0.08)' }}>
            <button
              onClick={() => { downloadPdf(data); setOpen(false) }}
              className="flex items-center gap-2 w-full px-4 py-2.5 text-sm text-[var(--color-fg)] hover:bg-[var(--color-bg)] transition-colors"
            >
              <Download className="w-3.5 h-3.5 text-[var(--color-fg-muted)]" />
              Download PDF
            </button>
            <button
              onClick={() => { downloadTxt(data); setOpen(false) }}
              className="flex items-center gap-2 w-full px-4 py-2.5 text-sm text-[var(--color-fg)] hover:bg-[var(--color-bg)] transition-colors"
            >
              <Download className="w-3.5 h-3.5 text-[var(--color-fg-muted)]" />
              Download .txt
            </button>
            <button
              onClick={() => { emailReport(data); setOpen(false) }}
              className="flex items-center gap-2 w-full px-4 py-2.5 text-sm text-[var(--color-fg)] hover:bg-[var(--color-bg)] transition-colors"
            >
              <Mail className="w-3.5 h-3.5 text-[var(--color-fg-muted)]" />
              Email report
            </button>
          </div>
        </>
      )}
    </div>
  )
}

// ── Ticker Page ───────────────────────────────────────────────────────────────

export default function TickerPage() {
  const { symbol } = useParams<{ symbol: string }>()
  const navigate = useNavigate()
  const [data, setData] = useState<AnalyzeResponse | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async (force = false) => {
    if (!symbol) return
    if (force) setIsRefreshing(true)
    else setIsLoading(true)
    setError(null)
    try {
      const res = await analyzeApi.get(symbol.toUpperCase(), force)
      setData(res.data)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setError(msg ?? 'Failed to load analysis.')
    } finally {
      setIsLoading(false)
      setIsRefreshing(false)
    }
  }, [symbol])

  useEffect(() => {
    fetchData(false)
  }, [fetchData])

  return (
    <Layout>
      {/* Back button */}
      <button
        onClick={() => navigate(-1)}
        className="btn-ghost mb-4 -ml-2 text-sm text-[var(--color-fg-muted)]"
      >
        <ArrowLeft className="w-4 h-4" />
        Back
      </button>

      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <LoadingSpinner size="lg" />
        </div>
      ) : error ? (
        <div className="flex flex-col items-center gap-4 py-16 text-center">
          <AlertCircle className="w-10 h-10 text-red-500" />
          <p className="text-[var(--color-fg-muted)]">{error}</p>
          <button onClick={() => fetchData(false)} className="btn-secondary">
            Try again
          </button>
        </div>
      ) : data ? (
        <div className="flex flex-col gap-4">
          {/* Header */}
          <div className="card p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h1
                  className="text-4xl font-light text-[var(--color-fg)] mb-1"
                  style={{ fontFamily: 'Fraunces, Georgia, serif' }}
                >
                  {data.ticker}
                </h1>
                {data.current_price != null && (
                  <div className="flex items-baseline gap-2 mb-2">
                    <span className="text-2xl font-semibold tabular-nums text-[var(--color-fg)]">
                      ${data.current_price.toFixed(2)}
                    </span>
                    {data.day_change_pct != null && (
                      <span className={`text-sm tabular-nums font-medium ${data.day_change_pct >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                        {data.day_change_pct >= 0 ? '+' : ''}{data.day_change_pct.toFixed(2)}%
                      </span>
                    )}
                  </div>
                )}
                <div className="flex items-center gap-2 flex-wrap">
                  <SignalBadge signal={data.signal} size="lg" />
                  {data.conviction && <ConvictionBadge conviction={data.conviction} size="lg" />}
                </div>
              </div>

              {/* Score gauge */}
              <div className="flex-shrink-0">
                <ScoreGauge score={data.score} />
              </div>
            </div>

            {/* Refresh + Export */}
            <div className="mt-4 pt-4 border-t border-[var(--color-border)] flex items-center justify-between gap-2">
              <div className="flex items-center gap-1.5 text-xs text-[var(--color-fg-muted)]">
                <Calendar className="w-3.5 h-3.5" />
                Generated {new Date(data.generated_at).toLocaleString()}
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => fetchData(true)}
                  disabled={isRefreshing}
                  className="btn-secondary text-sm px-3 py-1.5 h-auto min-h-0"
                >
                  {isRefreshing
                    ? <LoadingSpinner size="sm" />
                    : <RefreshCw className="w-3.5 h-3.5" />}
                  {isRefreshing ? 'Refreshing…' : 'Refresh'}
                </button>
                <ExportMenu data={data} />
              </div>
            </div>
          </div>

          {/* Stats grid */}
          <div className="flex flex-col gap-2 sm:grid sm:grid-cols-3">
            {data.price_target && (
              <StatCell
                label="Price Target"
                value={`$${data.price_target.toFixed(2)}`}
                icon={Target}
                color="text-brand-500"
              />
            )}
            {data.stop_loss && (
              <StatCell
                label="Stop Loss"
                value={`$${data.stop_loss.toFixed(2)}`}
                icon={Shield}
                color="text-red-500"
              />
            )}
            {data.time_horizon && (
              <StatCell
                label="Time Horizon"
                value={data.time_horizon}
                icon={Calendar}
              />
            )}
            <StatCell
              label="Confidence"
              value={`${Math.round(data.confidence * 100)}%`}
              icon={Zap}
              color={
                data.confidence >= 0.7 ? 'text-green-500' :
                data.confidence >= 0.4 ? 'text-yellow-500' :
                'text-red-500'
              }
            />
          </div>

          {/* Thesis */}
          {data.thesis && (
            <Section title="Investment Thesis">
              <p className="text-sm text-[var(--color-fg)] leading-relaxed">{data.thesis}</p>
            </Section>
          )}

          {/* Analyst note — split into bullet points */}
          {data.analyst_note && (
            <Section title="Analyst Note">
              <AnalystNoteSummary note={data.analyst_note} />
            </Section>
          )}

          {/* Bull / Bear */}
          {(data.bull_case || data.bear_case) && (
            <Section title="Bull & Bear Case">
              <div className="flex flex-col gap-4">
                {data.bull_case && (
                  <Collapsible title="Bull Case">
                    <div className="flex items-start gap-2">
                      <TrendingUp className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
                      <p className="text-sm text-[var(--color-fg)] leading-relaxed">{data.bull_case}</p>
                    </div>
                  </Collapsible>
                )}
                {data.bear_case && (
                  <Collapsible title="Bear Case">
                    <div className="flex items-start gap-2">
                      <TrendingDown className="w-4 h-4 text-red-500 mt-0.5 flex-shrink-0" />
                      <p className="text-sm text-[var(--color-fg)] leading-relaxed">{data.bear_case}</p>
                    </div>
                  </Collapsible>
                )}
              </div>
            </Section>
          )}

          {/* Entry / Exit */}
          {(data.entry_suggestion || data.exit_suggestion) && (
            <Section title="Entry & Exit">
              <div className="flex flex-col gap-3">
                {data.entry_suggestion && (
                  <div>
                    <span className="text-xs font-medium text-green-500 uppercase tracking-wide">Entry</span>
                    <p className="text-sm text-[var(--color-fg)] mt-1 leading-relaxed">
                      {data.entry_suggestion}
                    </p>
                  </div>
                )}
                {data.exit_suggestion && (
                  <div>
                    <span className="text-xs font-medium text-red-500 uppercase tracking-wide">Exit</span>
                    <p className="text-sm text-[var(--color-fg)] mt-1 leading-relaxed">
                      {data.exit_suggestion}
                    </p>
                  </div>
                )}
              </div>
            </Section>
          )}

          {/* Catalysts */}
          {data.catalysts && data.catalysts.length > 0 && (
            <Section title="Catalysts">
              <BulletList items={data.catalysts} color="bg-green-500" />
            </Section>
          )}

          {/* Key risks */}
          {data.key_risks && data.key_risks.length > 0 && (
            <Section title="Key Risks">
              <BulletList items={data.key_risks} color="bg-red-500" />
            </Section>
          )}

          {/* Alternative Data */}
          {data.alternative_data && (
            <AlternativeDataSection data={data.alternative_data} />
          )}

          {/* Explanation */}
          {data.explanation && (
            <Section title="Explanation">
              <p className="text-sm text-[var(--color-fg-muted)] leading-relaxed whitespace-pre-wrap">
                {data.explanation}
              </p>
            </Section>
          )}

          {/* Analysis Sources */}
          <div className="card p-5">
            <h3
              className="text-base font-medium text-[var(--color-fg)] mb-3"
              style={{ fontFamily: 'Fraunces, Georgia, serif' }}
            >
              Analysis Sources
            </h3>
            <div className="flex flex-col gap-3">
              {[
                {
                  label: 'Price & Market Data',
                  value: 'Yahoo Finance — 90 days OHLCV, current price, day change',
                  status: 'live',
                },
                {
                  label: 'Fundamentals',
                  value: 'Yahoo Finance (yfinance) — P/E, revenue growth, FCF, debt/equity, analyst consensus',
                  status: 'live',
                },
                {
                  label: 'News & Sentiment',
                  value: 'Finnhub API — last 7 days of headlines, scored locally with VADER NLP',
                  status: 'live',
                },
                {
                  label: 'Macro Environment',
                  value: 'FRED (Federal Reserve) — Fed funds rate, 10Y/2Y Treasuries, CPI, unemployment, VIX',
                  status: 'live',
                },
                {
                  label: 'Options Flow',
                  value: 'Yahoo Finance — nearest-expiry put/call ratio across the full chain',
                  status: 'live',
                },
                {
                  label: 'Short Interest',
                  value: 'Yahoo Finance — % of float shorted, days-to-cover, squeeze risk',
                  status: 'live',
                },
                {
                  label: 'Insider Activity',
                  value: 'Yahoo Finance (Form 4) — buy/sell counts over 90 days',
                  status: 'live',
                },
                {
                  label: 'AI Analyst',
                  value: 'Claude Sonnet 4.6 (Anthropic) — synthesises all the above into signal, thesis, price target, and research note',
                  status: 'live',
                },
                {
                  label: 'Real-time News NLP',
                  value: 'NewsAPI + Reddit sentiment — broader news search and retail sentiment',
                  status: 'planned',
                },
                {
                  label: 'SEC Filings',
                  value: 'EDGAR — 10-K/10-Q filings and earnings call transcripts',
                  status: 'planned',
                },
                {
                  label: 'Intraday & Options',
                  value: 'Polygon.io — intraday price data and live options flow',
                  status: 'planned',
                },
                {
                  label: 'ML Scoring Model',
                  value: 'XGBoost — trained on signal history with real fundamental + sentiment features',
                  status: 'planned',
                },
              ].map(({ label, value, status }) => (
                <div key={label} className="flex items-start gap-3">
                  <span className={`mt-0.5 flex-shrink-0 text-[0.6rem] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded ${
                    status === 'live'
                      ? 'bg-green-500/10 text-green-500'
                      : 'bg-[var(--color-border)]/60 text-[var(--color-fg-muted)]'
                  }`}>
                    {status === 'live' ? 'Live' : 'Soon'}
                  </span>
                  <div className="min-w-0">
                    <span className="text-xs font-medium text-[var(--color-fg)]">{label}</span>
                    <p className="text-xs text-[var(--color-fg-muted)] mt-0.5">{value}</p>
                  </div>
                </div>
              ))}
            </div>
            <p className="text-[0.65rem] text-[var(--color-fg-muted)] mt-4 pt-3 border-t border-[var(--color-border)]">
              Scoring is a weighted composite of technical, fundamental, sentiment, macro, volatility, and alternative data sub-scores. When the AI analyst is enabled, Claude synthesises all inputs and may override the rule-based signal. See <code className="font-mono">docs/09-analysis-sources.md</code> for full methodology.
            </p>
          </div>
        </div>
      ) : null}
    </Layout>
  )
}
