import type { AlternativeData } from '../../types'

/**
 * Options flow, short interest and insider activity.
 *
 * Carried over from the old TickerPage unchanged in substance — the 1.7
 * redesign moves it behind a collapsible on the Trade screen rather than
 * dropping it, because it is a real input to the composite score and a reader
 * who wants to argue with the verdict needs to see it.
 */

function Pill({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null
  const bullish = ['BULLISH', 'MILDLY_BULLISH', 'LOW'].includes(value)
  const bearish = ['BEARISH', 'MILDLY_BEARISH', 'HIGH'].includes(value)
  const tone = bullish
    ? { bg: 'var(--tint-buy)', fg: 'var(--accent-buy)' }
    : bearish
      ? { bg: 'var(--tint-sell)', fg: 'var(--accent-sell)' }
      : { bg: 'var(--color-hover)', fg: 'var(--color-fg-muted)' }
  return (
    <span
      className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium"
      style={{ background: tone.bg, color: tone.fg }}
    >
      {label}: {value.replace('_', ' ')}
    </span>
  )
}

function Row({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="flex items-start justify-between gap-2 border-b border-[var(--color-border)] py-1.5 last:border-0">
      <span className="flex-shrink-0 text-[11px] text-[var(--color-fg-muted)]">{label}</span>
      <div className="text-right">
        <span className="num text-[11.5px] font-medium text-[var(--color-fg)]">{value}</span>
        {sub && <div className="text-[10px] text-[var(--color-fg-muted)]">{sub}</div>}
      </div>
    </div>
  )
}

function Group({ title, pill, children, note }: {
  title: string
  pill?: React.ReactNode
  children: React.ReactNode
  note: string
}) {
  return (
    <div>
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <span className="label-micro">{title}</span>
        {pill}
      </div>
      {children}
      <p className="mt-1 text-[10px] text-[var(--color-fg-muted)]">{note}</p>
    </div>
  )
}

export default function AltDataPanel({ data }: { data: AlternativeData }) {
  const si = data.short_interest
  const opt = data.options_flow
  const ins = data.insider_trades

  const hasAny =
    si?.short_percent_of_float != null
    || opt?.put_call_ratio != null
    || ins?.buy_count_90d != null
    || ins?.sell_count_90d != null

  if (!hasAny) {
    return (
      <p className="text-[11.5px] text-[var(--color-fg-muted)]">
        No alternative data was returned for this ticker.
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {opt?.put_call_ratio != null && (
        <Group
          title="Options flow"
          pill={<Pill label="signal" value={opt.sentiment} />}
          note="<0.7 = calls dominating (bullish) · >1.5 = puts dominating (bearish hedging)"
        >
          <Row
            label="Put/call ratio"
            value={opt.put_call_ratio.toFixed(2)}
            sub={`${(opt.put_volume ?? 0).toLocaleString()} puts / ${(opt.call_volume ?? 0).toLocaleString()} calls${opt.expiry ? ` · exp ${opt.expiry}` : ''}`}
          />
        </Group>
      )}

      {si?.short_percent_of_float != null && (
        <Group
          title="Short interest"
          pill={si.squeeze_risk ? <Pill label="squeeze risk" value={si.squeeze_risk} /> : undefined}
          note="High short float plus a rising price is the setup for a squeeze."
        >
          <Row
            label="% of float shorted"
            value={`${((si.short_percent_of_float ?? 0) * 100).toFixed(1)}%`}
          />
          {si.short_ratio != null && (
            <Row
              label="Days to cover"
              value={`${si.short_ratio.toFixed(1)}d`}
              sub="average days for shorts to buy back at current volume"
            />
          )}
        </Group>
      )}

      {(ins?.buy_count_90d != null || ins?.sell_count_90d != null) && (
        <Group
          title="Insider activity (90d)"
          pill={<Pill label="signal" value={ins?.net_sentiment} />}
          note="Insider buying signals management confidence. Selling is often diversification — much weaker signal."
        >
          <Row
            label="Transactions"
            value={`${ins?.buy_count_90d ?? 0} buys / ${ins?.sell_count_90d ?? 0} sells`}
          />
          {ins?.recent && ins.recent.length > 0 && (
            <div className="mt-1.5 flex flex-col gap-1">
              {ins.recent.slice(0, 3).map((t, i) => (
                <div key={i} className="flex items-start justify-between gap-2 text-[10px] text-[var(--color-fg-muted)]">
                  <span className="truncate">{t.insider ?? 'Unknown'}</span>
                  <span className="num flex-shrink-0">
                    {t.transaction ?? ''}{t.shares ? ` · ${t.shares.toLocaleString()} sh` : ''}
                    {t.date ? ` · ${t.date}` : ''}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Group>
      )}
    </div>
  )
}
