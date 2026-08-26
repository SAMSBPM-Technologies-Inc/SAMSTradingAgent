import { useEffect, useId, useRef, useState } from 'react'

/**
 * Small dropdown menu used by the header (overflow nav, autonomy mode, account).
 *
 * Exists because the redesign moves several controls into the 48px header that
 * cannot all be visible at once. Menus are the part of a header people reach
 * for with the keyboard, so this implements the parts that make that work:
 * Escape closes and returns focus to the trigger, a click anywhere outside
 * dismisses, and the trigger carries aria-expanded/aria-haspopup so a screen
 * reader announces the state rather than reading a bare button.
 */

interface MenuProps {
  /** Rendered inside the trigger button. */
  trigger: React.ReactNode
  triggerClassName?: string
  triggerStyle?: React.CSSProperties
  /** Accessible name for the trigger. */
  label: string
  align?: 'left' | 'right'
  /** Receives a `close` callback so an item can dismiss the menu when chosen. */
  children: (close: () => void) => React.ReactNode
}

export default function Menu({
  trigger,
  triggerClassName = '',
  triggerStyle,
  label,
  align = 'right',
  children,
}: MenuProps) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuId = useId()

  useEffect(() => {
    if (!open) return

    const onPointerDown = (e: PointerEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false)
        // Without this the focus ring is left on a node that no longer exists
        // and the next Tab starts from the top of the document.
        triggerRef.current?.focus()
      }
    }

    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div ref={wrapRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((v) => !v)}
        className={triggerClassName}
        style={triggerStyle}
      >
        {trigger}
      </button>

      {open && (
        <div
          id={menuId}
          role="menu"
          aria-label={label}
          className={`absolute top-[calc(100%+6px)] z-50 min-w-[190px] overflow-hidden
                      rounded-lg border border-[var(--color-border)] bg-[var(--color-elev)]
                      ${align === 'right' ? 'right-0' : 'left-0'}`}
          style={{ boxShadow: '0 12px 34px rgba(0,0,0,0.28)' }}
        >
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  )
}

/** A single row inside a Menu. */
export function MenuItem({
  onClick,
  children,
  selected = false,
  danger = false,
}: {
  onClick: () => void
  children: React.ReactNode
  selected?: boolean
  danger?: boolean
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className={`flex w-full items-center gap-2.5 px-3 py-2 text-left text-[12.5px]
                  border-b border-[var(--color-border)] last:border-b-0
                  hover:bg-[var(--color-hover)] focus:outline-none focus:bg-[var(--color-hover)]
                  ${danger ? 'text-[var(--accent-sell)]' : 'text-[var(--color-fg)]'}`}
    >
      <span className="flex-1">{children}</span>
      {selected && <span aria-hidden="true" className="text-brand-500">✓</span>}
    </button>
  )
}
