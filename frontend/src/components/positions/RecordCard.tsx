import type { ReactNode } from 'react'

/**
 * One record, as a card, for screens too narrow to carry a table.
 *
 * The tables these replace are 46–52rem wide. In a 356px content column that
 * left 52–57% of every row off-screen to the right, with no fade, shadow or
 * hint that anything was there — so on a phone the Close button, unrealised
 * P&L, stop, target, net P&L and exit reason were all simply invisible. A
 * horizontal scroller you cannot see is not a disclosure, it is a hiding place.
 *
 * A card says the same fields in the same order, top to bottom. Nothing is
 * dropped: if a column is worth a table cell it is worth a line here.
 */

export interface CardField {
  label: string
  value: ReactNode
  /** Give a field the full row where its value is long (a reason, a note). */
  wide?: boolean
}

export function RecordCard({
  title,
  onTitleClick,
  badges,
  fields,
  note,
  action,
}: {
  title: ReactNode
  onTitleClick?: () => void
  /** Small pills beside the title — source, status, paper/live. */
  badges?: ReactNode
  fields: CardField[]
  /** Free text under the grid: an exit reason, a skip reason. */
  note?: ReactNode
  /** The row's action, full width so it is reachable with a thumb. */
  action?: ReactNode
}) {
  return (
    <div className="border-b border-[var(--color-border)] px-3.5 py-3 last:border-b-0">
      <div className="flex flex-wrap items-center gap-2">
        {onTitleClick ? (
          <button
            onClick={onTitleClick}
            className="num text-[15px] font-semibold text-[var(--color-fg)] hover:text-brand-500"
          >
            {title}
          </button>
        ) : (
          <span className="num text-[15px] font-semibold text-[var(--color-fg)]">{title}</span>
        )}
        {badges}
      </div>

      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-2">
        {fields.map((f) => (
          <div key={f.label} className={f.wide ? 'col-span-2' : undefined}>
            <dt className="text-[10px] uppercase tracking-[0.1em] text-[var(--color-fg-muted)]">
              {f.label}
            </dt>
            <dd className="num mt-px text-[13px] text-[var(--color-fg)]">{f.value}</dd>
          </div>
        ))}
      </dl>

      {note && (
        <p className="mt-2 text-[11px] leading-snug text-[var(--color-fg-muted)]">{note}</p>
      )}

      {action && <div className="mt-2.5">{action}</div>}
    </div>
  )
}

/** Shell around a list of cards, matching the table's bordered panel. */
export function CardList({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-hidden rounded-lg border border-[var(--color-border)]
                    bg-[var(--color-surface)]">
      {children}
    </div>
  )
}
