import type { AnalyzeResponse, FactorContribution } from '../types'

/**
 * Report export — plain text, email, and PDF.
 *
 * Two rules govern what goes in here.
 *
 * **The export is the whole analysis, not the prose half of it.** It used to
 * carry only the AI narrative — thesis, bull, bear, catalysts — and none of the
 * numbers the verdict was actually computed from, so the exported "report"
 * omitted the score breakdown, the risk assessment and the gate thresholds
 * entirely. Someone reading the file could not check the conclusion against
 * anything. The quantitative sections below are the same values the Trade
 * screen renders, from the same response.
 *
 * **A decomposition that the engine disowns is never printed.** `breakdown`
 * carries `attributable: false` on the XGBoost path, where the weights did not
 * produce the score; printing a factor table there would be fabrication dressed
 * as arithmetic. The report says so instead. This mirrors `explain_score` on
 * the backend, which refuses the same decomposition for the same reason.
 */

const pct = (v: number) => `${Math.round(v * 100)}%`
const usd = (v: number) => `$${v.toFixed(2)}`

/** Right-pad for the fixed-width factor table in the .txt export. */
const pad = (s: string, n: number) => s.length >= n ? s.slice(0, n) : s + ' '.repeat(n - s.length)
const padL = (s: string, n: number) => s.length >= n ? s : ' '.repeat(n - s.length) + s

function factorRows(factors: FactorContribution[]): string[] {
  return factors.map((f) =>
    `  ${pad(f.label, 22)}${padL(pct(f.score), 6)}${padL(pct(f.weight), 9)}${padL(f.contribution.toFixed(3), 11)}`,
  )
}

export function buildExportText(data: AnalyzeResponse): string {
  const lines: string[] = [
    `${data.ticker} — Analysis Report`,
    `Generated: ${new Date(data.generated_at).toLocaleString()}`,
    '',
  ]

  // ── Verdict ────────────────────────────────────────────────────────────────
  lines.push(
    'VERDICT',
    `  Signal: ${data.signal}   Score: ${Math.round(data.score * 100)}/100   Confidence: ${pct(data.confidence)}`,
  )
  if (data.conviction) lines.push(`  Conviction: ${data.conviction}`)
  if (data.current_price != null) {
    const chg = data.day_change_pct != null
      ? `  (${data.day_change_pct >= 0 ? '+' : ''}${data.day_change_pct.toFixed(2)}% today)`
      : ''
    lines.push(`  Price: ${usd(data.current_price)}${chg}`)
  }
  if (data.price_target != null) lines.push(`  Price target: ${usd(data.price_target)}`)
  if (data.stop_loss != null) lines.push(`  Stop loss: ${usd(data.stop_loss)}`)
  if (data.time_horizon) lines.push(`  Time horizon: ${data.time_horizon}`)
  lines.push('')

  // ── Risk ───────────────────────────────────────────────────────────────────
  if (data.risk) {
    lines.push(
      'RISK',
      `  ${data.risk.risk_level} — ${data.risk.risk_score.toFixed(1)}/10`,
      ...(data.risk.explanation ? [`  ${data.risk.explanation}`] : []),
      '',
    )
  }

  // ── Gate ───────────────────────────────────────────────────────────────────
  // The thresholds come from the engine, not from constants restated here, so
  // the exported document cannot disagree with the screen it was exported from.
  if (data.gate) {
    const g = data.gate
    lines.push(
      'SIGNAL GATE',
      `  BUY needs score > ${pct(g.buy_threshold)} and risk < ${g.risk_max_for_buy}`,
      `  SELL below score ${pct(g.sell_threshold)}`,
      `  Score test: ${g.score_passes_buy ? 'PASS' : 'FAIL'}   Risk test: ${g.risk_passes_buy ? 'PASS' : 'FAIL'}`,
      '',
    )
  }

  // ── Score breakdown ────────────────────────────────────────────────────────
  if (data.breakdown) {
    const b = data.breakdown
    lines.push('SCORE BREAKDOWN')
    if (!b.attributable) {
      lines.push(
        `  Method: ${b.method}. This score was not produced by weighting the`,
        '  factors below, so no per-factor decomposition is reported — one',
        '  would be a reconstruction rather than the reason for the score.',
      )
    } else {
      lines.push(
        `  Method: ${b.method}${b.personalized ? ' (your weights)' : ''}`,
        `  ${pad('Factor', 22)}${padL('Score', 6)}${padL('Weight', 9)}${padL('Points', 11)}`,
        ...factorRows(b.factors),
      )
      if (b.alternative_data) {
        lines.push('', ...factorRows([b.alternative_data]))
      }
      lines.push(
        `  ${pad('Base total', 22)}${padL('', 6)}${padL('', 9)}${padL(b.base_total.toFixed(3), 11)}`,
        `  ${pad('Composite', 22)}${padL('', 6)}${padL('', 9)}${padL(b.composite.toFixed(3), 11)}`,
      )
    }
    lines.push('')
  }

  // ── Narrative ──────────────────────────────────────────────────────────────
  const section = (label: string, text?: string | null) => {
    if (text) lines.push(label, text, '')
  }
  const bullets = (label: string, items?: string[] | null) => {
    if (items?.length) lines.push(label, ...items.map((s) => `  • ${s}`), '')
  }

  section('INVESTMENT THESIS', data.thesis)
  section('ANALYST NOTE', data.analyst_note)
  section('BULL CASE', data.bull_case)
  section('BEAR CASE', data.bear_case)
  bullets('CATALYSTS', data.catalysts)
  bullets('KEY RISKS', data.key_risks)
  section('ENTRY', data.entry_suggestion)
  section('EXIT', data.exit_suggestion)
  section('EXPLANATION', data.explanation)

  // ── Provenance ─────────────────────────────────────────────────────────────
  // Whether a model wrote the narrative above, or the rule-based path did, is
  // not a detail: it changes how much weight the prose deserves.
  lines.push(
    '---',
    data.analyst_used
      ? `Narrative generated by ${data.analyst_model ?? 'the configured analyst model'}.`
      : 'Narrative produced by the rule-based path; the AI analyst did not run.',
    'Disclaimer: This report is generated by SAMSTradingAgent for informational purposes only and does not constitute financial advice.',
  )

  return lines.join('\n')
}

/**
 * Save a Blob under a filename.
 *
 * The anchor is appended to the document before it is clicked and the object
 * URL is revoked on a later task, not on the next line. Firefox ignores a click
 * on a detached anchor, and revoking synchronously can invalidate the URL
 * before the download has read from it — together that is why "Download .txt"
 * did nothing at all in some browsers and produced an empty file in others.
 */
function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

const stamp = () => new Date().toISOString().slice(0, 10)

export function downloadTxt(data: AnalyzeResponse) {
  saveBlob(
    new Blob([buildExportText(data)], { type: 'text/plain;charset=utf-8' }),
    `${data.ticker}-analysis-${stamp()}.txt`,
  )
}

/**
 * Email the report.
 *
 * The body is capped: a `mailto:` URL longer than roughly 2,000 characters is
 * silently dropped by Windows and by several mail clients, so a full report —
 * which now carries the breakdown as well as the prose — would open an empty
 * compose window rather than a truncated one. The reader is told where the cut
 * is and pointed at the attachment-quality export.
 */
export function emailReport(data: AnalyzeResponse) {
  const LIMIT = 1800
  const full = buildExportText(data)
  const body = full.length > LIMIT
    ? `${full.slice(0, LIMIT)}\n\n[Truncated for email — use Download PDF for the full report.]`
    : full

  const subject = `${data.ticker} Analysis — ${data.signal} (${Math.round(data.score * 100)}/100)`
  window.location.href =
    `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`
}

export async function downloadPdf(data: AnalyzeResponse) {
  const { jsPDF } = await import('jspdf')
  const doc = new jsPDF({ unit: 'pt', format: 'letter' })
  const margin = 48
  const pageW = doc.internal.pageSize.getWidth()
  const pageH = doc.internal.pageSize.getHeight()
  const contentW = pageW - margin * 2
  let y = margin

  const brand: [number, number, number] = [242, 96, 12]  // #f2600c

  const checkY = (needed = 20) => {
    if (y + needed > pageH - margin) {
      doc.addPage()
      y = margin
    }
  }

  const heading = (text: string, size = 10) => {
    checkY(24)
    doc.setFontSize(size)
    doc.setTextColor(brand[0], brand[1], brand[2])
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

  /** A row of the factor table: label, sub-score, weight, points. */
  const row = (cells: [string, string, string, string], bold = false) => {
    checkY(14)
    doc.setFontSize(8)
    doc.setFont('helvetica', bold ? 'bold' : 'normal')
    doc.setTextColor(bold ? 30 : 70, bold ? 30 : 70, bold ? 30 : 70)
    doc.text(cells[0], margin, y)
    doc.text(cells[1], margin + contentW * 0.52, y, { align: 'right' })
    doc.text(cells[2], margin + contentW * 0.74, y, { align: 'right' })
    doc.text(cells[3], margin + contentW, y, { align: 'right' })
    y += 13
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
  doc.setTextColor(brand[0], brand[1], brand[2])
  doc.text(data.ticker, margin, y)

  if (data.current_price != null) {
    doc.setFontSize(14)
    doc.setTextColor(30, 30, 30)
    const chg = data.day_change_pct != null
      ? `  ${data.day_change_pct >= 0 ? '+' : ''}${data.day_change_pct.toFixed(2)}%`
      : ''
    doc.text(`${usd(data.current_price)}${chg}`, margin, y + 22)
  }

  const signalColor: Record<string, [number, number, number]> = {
    BUY: [34, 197, 94], SELL: [239, 68, 68], HOLD: [234, 179, 8],
  }
  const sc = signalColor[data.signal] ?? [100, 100, 100]
  doc.setFillColor(sc[0], sc[1], sc[2])
  doc.roundedRect(pageW - margin - 56, y - 16, 56, 22, 4, 4, 'F')
  doc.setFontSize(11)
  doc.setFont('helvetica', 'bold')
  doc.setTextColor(255, 255, 255)
  doc.text(data.signal, pageW - margin - 28, y - 1, { align: 'center' })

  y += 40
  divider()

  // ── Key metrics ───────────────────────────────────────────────────────────
  const metrics = [
    ['Score', `${Math.round(data.score * 100)}/100`],
    ['Confidence', pct(data.confidence)],
    data.conviction ? ['Conviction', data.conviction] : null,
    data.risk ? ['Risk', `${data.risk.risk_level} ${data.risk.risk_score.toFixed(1)}/10`] : null,
    data.price_target != null ? ['Price Target', usd(data.price_target)] : null,
    data.stop_loss != null ? ['Stop Loss', usd(data.stop_loss)] : null,
    data.time_horizon ? ['Time Horizon', data.time_horizon] : null,
  ].filter(Boolean) as [string, string][]

  const colW = contentW / 3
  metrics.forEach(([label, value], i) => {
    const cx = margin + (i % 3) * colW
    const cy = y + Math.floor(i / 3) * 36
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

  // ── Gate ──────────────────────────────────────────────────────────────────
  if (data.gate) {
    const g = data.gate
    heading('Signal Gate')
    body(`BUY needs score above ${pct(g.buy_threshold)} and risk below ${g.risk_max_for_buy}. `
       + `SELL below score ${pct(g.sell_threshold)}. `
       + `Score test: ${g.score_passes_buy ? 'PASS' : 'FAIL'}. `
       + `Risk test: ${g.risk_passes_buy ? 'PASS' : 'FAIL'}.`)
    gap(10)
  }

  // ── Score breakdown ───────────────────────────────────────────────────────
  if (data.breakdown) {
    const b = data.breakdown
    heading('Score Breakdown')
    if (!b.attributable) {
      body(`Method: ${b.method}. This score was not produced by weighting the factors, `
         + `so no per-factor decomposition is reported — one would be a reconstruction `
         + `rather than the reason for the score.`)
    } else {
      body(`Method: ${b.method}${b.personalized ? ' (your weights)' : ''}`)
      gap(4)
      row(['Factor', 'Score', 'Weight', 'Points'], true)
      b.factors.forEach((f) =>
        row([f.label, pct(f.score), pct(f.weight), f.contribution.toFixed(3)]))
      if (b.alternative_data) {
        const a = b.alternative_data
        row([a.label, pct(a.score), pct(a.weight), a.contribution.toFixed(3)])
      }
      row(['Composite', '', '', b.composite.toFixed(3)], true)
    }
    gap(10)
  }

  // ── Risk ──────────────────────────────────────────────────────────────────
  if (data.risk?.explanation) {
    heading('Risk Assessment')
    body(`${data.risk.risk_level} — ${data.risk.risk_score.toFixed(1)}/10. ${data.risk.explanation}`)
    gap(10)
  }

  // ── Narrative ─────────────────────────────────────────────────────────────
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
  const provenance = data.analyst_used
    ? `Narrative by ${data.analyst_model ?? 'the configured analyst model'}`
    : 'Rule-based narrative; AI analyst did not run'
  body(
    `Generated ${new Date(data.generated_at).toLocaleString()}  ·  SAMSTradingAgent  ·  `
    + `${provenance}  ·  For informational purposes only, not financial advice.`,
    7,
  )

  // `doc.save()` builds the blob and drives the same anchor dance as saveBlob,
  // but through jsPDF's own helper, which has the detached-anchor problem this
  // module fixed for the .txt path. Going through saveBlob keeps one code path.
  saveBlob(doc.output('blob'), `${data.ticker}-analysis-${stamp()}.pdf`)
}
