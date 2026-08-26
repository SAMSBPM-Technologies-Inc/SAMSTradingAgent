import React, { useState } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import {
  BarChart2,
  BookOpen,
  Briefcase,
  LineChart,
  LogOut,
  MoreHorizontal,
  Search,
  Settings as SettingsIcon,
  Target,
} from 'lucide-react'
import { useAuth } from '../lib/auth-context'
import { useTheme } from '../lib/theme-context'
import { useToast } from '../lib/toast-context'
import { useTradingSettings } from '../lib/trading-context'
import AccountBar from './AccountBar'
import CommandPalette from './CommandPalette'
import Menu, { MenuItem } from './Menu'
import type { TradingMode } from '../types'

/*
 * Application chrome for the 1.7 redesign.
 *
 * The header collapses ten nav entries into the three the design calls
 * destinations — Trade, Positions, Settings — and moves the rest behind an
 * overflow menu. Nothing was retired: Performance, Calibration, Guide and
 * Search keep their routes, their place in the overflow menu, and their
 * entries in the ⌘K palette. Fewer front doors, same building.
 */

const IconMark = ({ size = 30 }: { size?: number }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 34 34" aria-hidden="true">
    <rect width="34" height="34" rx="8" fill="#f2600c" />
    <path d="M9 23L15 17L19 20L25 11" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    <path d="M25 11H19M25 11V17" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
  </svg>
)

/**
 * Stacked wordmark: SAMSBPM in ink over a rule over TRADING AGENT in orange.
 *
 * The handoff specifies #281F13 for the wordmark. That is the light-mode ink
 * colour written as a literal, and on the dark surface (#141109) it would be
 * very nearly invisible — the exact failure the token rule in CLAUDE.md exists
 * to prevent. `--color-fg` is that colour in light mode and its counterpart in
 * dark, so the design's intent survives in both themes.
 */
function LogoLockup({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex flex-shrink-0 select-none items-center gap-2.5">
      <IconMark size={compact ? 28 : 30} />
      {!compact && (
        <span className="flex flex-col items-center gap-[3px]">
          <span
            className="leading-none text-[var(--color-fg)]"
            style={{ fontFamily: 'Fraunces, Georgia, serif', fontWeight: 600, fontSize: '15px', letterSpacing: '0.005em' }}
          >
            SAMSBPM
          </span>
          <span className="h-px w-full bg-[var(--color-border)]" />
          <span className="text-[8.5px] uppercase leading-none tracking-[0.185em] text-brand-500">
            Trading Agent
          </span>
        </span>
      )}
    </div>
  )
}

/** The three destinations. */
const primaryNav = [
  { to: '/', label: 'Trade', icon: LineChart, exact: true },
  { to: '/positions', label: 'Positions', icon: Briefcase, exact: false },
  { to: '/settings', label: 'Settings', icon: SettingsIcon, exact: false },
]

/** Kept, not retired — reachable here and from ⌘K. */
const overflowNav = [
  { to: '/performance', label: 'Performance', icon: BarChart2 },
  { to: '/calibration', label: 'Calibration', icon: Target },
  { to: '/search', label: 'Search tickers', icon: Search },
  { to: '/guide', label: 'IB Gateway guide', icon: BookOpen },
]

const MODE_LABEL: Record<TradingMode, string> = {
  MANUAL: 'Manual',
  SEMI_AUTO: 'Semi-auto',
  AUTO: 'Auto',
}

const MODE_DESC: Record<TradingMode, string> = {
  MANUAL: 'Agent proposes, you place every order.',
  SEMI_AUTO: 'Agent acts alone only at high conviction.',
  AUTO: 'Agent places orders unattended.',
}

/**
 * Autonomy control.
 *
 * The handoff has this pill cycle Manual→Semi-auto→Auto on click. It is
 * rendered here as an explicit menu instead, because one of those three
 * transitions hands an unattended process permission to spend money and a
 * blind cycle makes it reachable by a mis-click on the pill next to the theme
 * toggle. The pill still shows the mode and still changes it from the header —
 * it just makes you name the rung you're climbing to. Stepping *up* to AUTO
 * additionally asks for confirmation; stepping down never does, the same
 * asymmetry the engine applies to exits.
 */
function AutonomyPill() {
  const { settings, save } = useTradingSettings()
  const { toast } = useToast()
  const [busy, setBusy] = useState(false)

  if (!settings) return null

  const mode = settings.mode

  const choose = async (next: TradingMode, close: () => void) => {
    close()
    if (next === mode || busy) return
    if (next === 'AUTO') {
      const ok = window.confirm(
        'Switch to AUTO?\n\nThe agent will place orders unattended, without asking you first. '
        + 'It still obeys every server-side guard: position cap, daily loss limit, cash '
        + 'reserve and the risk gate on BUY.',
      )
      if (!ok) return
    }
    setBusy(true)
    try {
      await save({ mode: next })
      toast(`Autonomy set to ${MODE_LABEL[next]}.`, 'success')
    } catch {
      toast('Could not change autonomy mode.', 'error')
    } finally {
      setBusy(false)
    }
  }

  const tone =
    mode === 'AUTO'
      ? { bg: 'var(--tint-buy)', fg: 'var(--accent-buy)' }
      : mode === 'SEMI_AUTO'
        ? { bg: 'var(--tint-hold)', fg: 'var(--accent-hold)' }
        : { bg: 'var(--color-hover)', fg: 'var(--color-fg-muted)' }

  return (
    <Menu
      label={`Autonomy mode: ${MODE_LABEL[mode]}. Change`}
      triggerClassName="num h-[26px] rounded-[6px] px-2.5 text-[11px] font-semibold uppercase tracking-[0.06em] disabled:opacity-50"
      triggerStyle={{ background: tone.bg, color: tone.fg }}
      trigger={MODE_LABEL[mode]}
    >
      {(close) => (
        <>
          <p className="label-micro border-b border-[var(--color-border)] px-3 py-2">Autonomy</p>
          {(['MANUAL', 'SEMI_AUTO', 'AUTO'] as TradingMode[]).map((m) => (
            <MenuItem key={m} onClick={() => choose(m, close)} selected={m === mode}>
              <span className="block font-medium">{MODE_LABEL[m]}</span>
              <span className="block text-[10.5px] leading-snug text-[var(--color-fg-muted)]">
                {MODE_DESC[m]}
              </span>
            </MenuItem>
          ))}
        </>
      )}
    </Menu>
  )
}

/**
 * Paper/live routing indicator. Deliberately read-only here — switching an
 * account from paper to live money is a Settings decision, not a header one.
 */
function EnvPill() {
  const { settings } = useTradingSettings()
  if (!settings) return null
  const live = !settings.paper_trading
  return (
    <span
      title={live ? 'Orders route to your live-money account' : 'Orders route to the paper account'}
      className="num hidden h-[26px] items-center rounded-[6px] px-2.5 text-[11px] font-semibold uppercase tracking-[0.06em] sm:inline-flex"
      style={
        live
          ? { background: 'var(--tint-sell)', color: 'var(--accent-sell)' }
          : { background: 'var(--color-hover)', color: 'var(--color-fg-muted)' }
      }
    >
      {live ? 'Live' : 'Paper'}
    </span>
  )
}

function DesktopHeader({ onOpenPalette }: { onOpenPalette: () => void }) {
  const { user, logout } = useAuth()
  const { theme, toggleTheme } = useTheme()
  const navigate = useNavigate()
  const location = useLocation()

  const overflowActive = overflowNav.some((n) => location.pathname.startsWith(n.to))

  const tabClass = (isActive: boolean) =>
    `flex h-[30px] items-center gap-1.5 rounded-[6px] px-2.5 text-[12.5px] font-medium transition-colors
     ${isActive
      ? 'bg-[var(--color-hover)] text-[var(--color-fg)]'
      : 'text-[var(--color-fg-muted)] hover:text-[var(--color-fg)]'}`

  return (
    <header
      className="sticky top-0 z-30 flex h-12 flex-shrink-0 items-center gap-3 border-b
                 border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 md:gap-5"
    >
      <button onClick={() => navigate('/')} aria-label="SAMSBPM Trading Agent — go to Trade">
        <LogoLockup />
      </button>

      <nav aria-label="Primary" className="hidden items-center gap-0.5 md:flex">
        {primaryNav.map(({ to, label, exact }) => (
          <NavLink key={to} to={to} end={exact} className={({ isActive }) => tabClass(isActive)}>
            {label}
          </NavLink>
        ))}

        <Menu
          label="More screens"
          align="left"
          triggerClassName={tabClass(overflowActive)}
          trigger={
            <>
              <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
              More
            </>
          }
        >
          {(close) => (
            <>
              {overflowNav.map(({ to, label, icon: Icon }) => (
                <MenuItem
                  key={to}
                  onClick={() => { close(); navigate(to) }}
                  selected={location.pathname.startsWith(to)}
                >
                  <span className="flex items-center gap-2.5">
                    <Icon className="h-4 w-4 text-[var(--color-fg-muted)]" aria-hidden="true" />
                    {label}
                  </span>
                </MenuItem>
              ))}
            </>
          )}
        </Menu>
      </nav>

      <button
        onClick={onOpenPalette}
        className="ml-auto hidden h-7 items-center gap-2 rounded-[6px] border border-[var(--color-border)]
                   bg-[var(--color-bg)] pl-2.5 pr-2 text-[12px] text-[var(--color-fg-muted)]
                   transition-colors hover:border-brand-500 hover:text-[var(--color-fg)] lg:flex"
      >
        Jump to ticker or action
        <span className="num rounded border border-[var(--color-border)] px-1.5 py-px text-[10px]">⌘K</span>
      </button>

      <div className="ml-auto flex flex-shrink-0 items-center gap-2 lg:ml-0">
        <button
          onClick={onOpenPalette}
          aria-label="Search"
          className="grid h-7 w-7 place-items-center rounded-[6px] border border-[var(--color-border)]
                     text-[var(--color-fg-muted)] hover:bg-[var(--color-hover)] hover:text-[var(--color-fg)] lg:hidden"
        >
          <Search className="h-3.5 w-3.5" aria-hidden="true" />
        </button>

        <AutonomyPill />
        <EnvPill />

        <button
          onClick={toggleTheme}
          aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          className="grid h-7 w-7 place-items-center rounded-[6px] border border-[var(--color-border)]
                     text-[12px] text-[var(--color-fg-muted)] hover:bg-[var(--color-hover)] hover:text-[var(--color-fg)]"
        >
          <span aria-hidden="true">{theme === 'dark' ? '☀' : '☾'}</span>
        </button>

        <Menu
          label={`Account: ${user?.display_name ?? user?.email ?? 'signed in'}`}
          trigger={
            <span
              aria-hidden="true"
              className="num grid h-[26px] w-[26px] place-items-center rounded-full bg-brand-500
                         text-[11px] font-semibold text-white"
            >
              {(user?.display_name ?? user?.email ?? 'U')[0].toUpperCase()}
            </span>
          }
        >
          {(close) => (
            <>
              <p className="border-b border-[var(--color-border)] px-3 py-2 text-[11.5px] text-[var(--color-fg-muted)]">
                {user?.display_name ?? user?.email ?? 'Account'}
              </p>
              <MenuItem onClick={() => { close(); navigate('/settings') }}>Settings</MenuItem>
              {/* Below md the header has no "More" menu and the bottom bar
                  carries only the three destinations, so the secondary screens
                  would otherwise have no tap target at all. */}
              <div className="md:hidden">
                {overflowNav.map(({ to, label, icon: Icon }) => (
                  <MenuItem key={to} onClick={() => { close(); navigate(to) }}>
                    <span className="flex items-center gap-2.5">
                      <Icon className="h-4 w-4 text-[var(--color-fg-muted)]" aria-hidden="true" />
                      {label}
                    </span>
                  </MenuItem>
                ))}
              </div>
              <MenuItem danger onClick={() => { close(); logout() }}>
                <span className="flex items-center gap-2.5">
                  <LogOut className="h-4 w-4" aria-hidden="true" />
                  Log out
                </span>
              </MenuItem>
            </>
          )}
        </Menu>
      </div>
    </header>
  )
}

/** Mobile bottom bar — the same three destinations the header shows. */
function MobileBottomBar() {
  return (
    <nav
      aria-label="Primary"
      className="pb-safe fixed inset-x-0 bottom-0 z-30 border-t border-[var(--color-border)]
                 bg-[var(--color-surface)] md:hidden"
    >
      <div className="flex h-16 items-center justify-around px-2">
        {primaryNav.map(({ to, label, icon: Icon, exact }) => (
          <NavLink
            key={to}
            to={to}
            end={exact}
            className={({ isActive }) =>
              `flex min-h-[2.75rem] flex-1 flex-col items-center gap-0.5 rounded-xl px-3 py-2
               transition-colors ${isActive ? 'text-brand-500' : 'text-[var(--color-fg-muted)]'}`
            }
          >
            <Icon className="h-5 w-5" aria-hidden="true" />
            <span className="text-[0.65rem] font-medium leading-none">{label}</span>
          </NavLink>
        ))}
      </div>
    </nav>
  )
}

/**
 * Regulatory notice, on every screen at every breakpoint.
 *
 * It belongs where the recommendations are read, not one navigation away from
 * them. Exported so the Trade screen — which manages its own scroll and so
 * cannot inherit the padded page wrapper — can place it itself.
 */
export function Disclaimer({ compact = false }: { compact?: boolean }) {
  if (compact) {
    return (
      <p className="border-t border-[var(--color-border)] px-[18px] py-3.5 text-[10.5px] leading-relaxed text-[var(--color-fg-muted)]">
        <strong className="text-[var(--color-fg)]">Not financial advice.</strong>{' '}
        Automated analysis for informational purposes only. Signals are model output, not
        research; past accuracy does not predict future results. Trading risks total loss of capital.
      </p>
    )
  }
  return (
    <p className="mt-10 border-t border-[var(--color-border)] pt-4 text-[0.65rem] leading-relaxed text-[var(--color-fg-muted)]">
      <strong className="text-[var(--color-fg)]">Not financial advice.</strong>{' '}
      SAMSBPM Trading Agent is an automated analysis tool provided for informational
      purposes only. It is not a registered investment adviser, broker-dealer, or
      portfolio manager, and nothing here is a recommendation to buy or sell any
      security. Signals are model output, not research; past signal accuracy does
      not predict future results. Trading involves risk of loss, including total
      loss of capital. You are solely responsible for your investment decisions.
    </p>
  )
}

interface LayoutProps {
  children: React.ReactNode
  /**
   * `page` — padded, width-capped, document-scrolled, with the disclaimer and
   * footer appended. Every screen but one.
   *
   * `app` — the Trade screen: three columns that each scroll independently
   * inside a viewport-height grid, so it must own its padding, its scroll and
   * its own copy of the disclaimer.
   */
  variant?: 'page' | 'app'
}

export default function Layout({ children, variant = 'page' }: LayoutProps) {
  const [paletteOpen, setPaletteOpen] = useState(false)

  return (
    <div className="flex min-h-dvh flex-col bg-[var(--color-bg)]">
      {/* Visible only on focus. Without it a keyboard user tabs the whole nav
          on every page before reaching content. */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-[70]
                   focus:rounded-lg focus:bg-brand-500 focus:px-3 focus:py-2 focus:text-sm
                   focus:font-medium focus:text-white"
      >
        Skip to content
      </a>

      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
      <DesktopHeader onOpenPalette={() => setPaletteOpen(true)} />
      <AccountBar />

      {variant === 'app' ? (
        <main id="main-content" tabIndex={-1} className="min-h-0 flex-1 focus:outline-none">
          {children}
        </main>
      ) : (
        <>
          <main
            id="main-content"
            tabIndex={-1}
            className="mb-bottom-bar mx-auto w-full max-w-6xl flex-1 px-4 py-6 focus:outline-none md:mb-0 md:px-6 md:py-7"
          >
            {children}
            <Disclaimer />
          </main>

          <footer className="hidden border-t border-[var(--color-border)] bg-[var(--color-surface)] md:flex">
            <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-6 py-4">
              <div className="flex items-center gap-2">
                <IconMark size={20} />
                <p className="text-xs text-[var(--color-fg-muted)]">
                  © {new Date().getFullYear()} SAMSBPM Technologies Inc. All rights reserved.
                </p>
              </div>
              <a
                href="https://samsbpm.com"
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-[var(--color-fg-muted)] transition-colors hover:text-brand-500"
              >
                Built by SAMSBPM Technologies Inc
              </a>
            </div>
          </footer>
        </>
      )}

      <MobileBottomBar />
    </div>
  )
}
