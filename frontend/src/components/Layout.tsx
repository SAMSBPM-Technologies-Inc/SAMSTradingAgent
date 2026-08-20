import React from 'react'
import { Link, NavLink, useNavigate } from 'react-router-dom'
import {
  BarChart2,
  Briefcase,
  BookOpen,
  Crosshair,
  Home,
  LogOut,
  Search,
  User,
} from 'lucide-react'
import { useAuth } from '../lib/auth-context'
import AccountBar from './AccountBar'
import ThemeToggle from './ThemeToggle'

// Icon mark SVG (inlined so it renders at any size with no extra request)
const IconMark = ({ size = 32 }: { size?: number }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 34 34" aria-hidden="true">
    <rect width="34" height="34" rx="8" fill="#f2600c" />
    <path d="M9 23L15 17L19 20L25 11" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    <path d="M25 11H19M25 11V17" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
  </svg>
)

// Full horizontal lockup for desktop nav
function LogoLockup() {
  return (
    <div className="flex items-center gap-2.5 select-none">
      <IconMark size={32} />
      <div className="leading-tight">
        <div style={{ fontFamily: 'Fraunces, Georgia, serif', color: '#f2600c', fontWeight: 600, fontSize: '15px', letterSpacing: '-0.01em' }}>
          SAMSBPM
        </div>
        <div className="text-[var(--color-fg-muted)] text-[0.6rem] tracking-widest uppercase">
          Trading Agent
        </div>
      </div>
    </div>
  )
}

// Icon-only mark for mobile top bar
function LogoMark() {
  return <IconMark size={32} />
}

const navLinks = [
  { to: '/', label: 'Dashboard', icon: Home, exact: true },
  { to: '/radar', label: 'Alpha Radar', icon: Crosshair, exact: false },
  { to: '/holdings', label: 'Holdings', icon: Briefcase, exact: false },
  { to: '/performance', label: 'Performance', icon: BarChart2, exact: false },
  { to: '/guide', label: 'Guide', icon: BookOpen, exact: false },
]

function DesktopNav() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  return (
    <header className="hidden md:flex fixed top-0 inset-x-0 z-30 h-[60px] items-center px-6 gap-6
                       bg-[var(--color-surface)]
                       border-b border-[var(--color-border)]
                       transition-colors duration-200">
      {/* Logo */}
      <button onClick={() => navigate('/')} className="flex-shrink-0">
        <LogoLockup />
      </button>

      {/* Nav links */}
      <nav className="flex items-center flex-1">
        {navLinks.map(({ to, label, icon: Icon, exact }) => (
          <NavLink
            key={to}
            to={to}
            end={exact}
            className={({ isActive }) =>
              `flex items-center gap-2 text-[13.5px] font-medium transition-colors duration-150
               border-b-2 pb-0.5 px-0 py-1 mr-6
               ${isActive
                 ? 'text-[#14110c] border-[#f2600c]'
                 : 'text-[#83786a] border-transparent hover:text-[#14110c]'
               }`
            }
          >
            <Icon className="w-4 h-4" />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Right section */}
      <div className="flex items-center gap-2 flex-shrink-0">
        <ThemeToggle />

        {/* User info + logout */}
        <div className="flex items-center gap-2 pl-2 border-l border-[var(--color-border)]">
          <Link
            to="/profile"
            className="flex items-center gap-2 px-2"
          >
            <div style={{ width: 28, height: 28, borderRadius: '50%', background: '#f2600c', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
              <span style={{ color: '#fff', fontFamily: 'Archivo, system-ui, sans-serif', fontWeight: 600, fontSize: '12px' }}>
                {(user?.display_name ?? user?.email ?? 'U')[0].toUpperCase()}
              </span>
            </div>
            <div className="flex flex-col">
              <span className="text-sm text-[var(--color-fg-muted)] max-w-[10rem] truncate leading-tight">
                {user?.display_name ?? user?.email ?? 'Account'}
              </span>
            </div>
          </Link>
          <button
            onClick={logout}
            aria-label="Log out"
            className="btn-ghost w-9 h-9 rounded-xl text-[var(--color-fg-muted)] hover:text-red-500"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>
    </header>
  )
}

const bottomTabs = [
  { to: '/', label: 'Home', icon: Home, exact: true },
  { to: '/radar', label: 'Radar', icon: Crosshair, exact: false },
  { to: '/holdings', label: 'Holdings', icon: Briefcase, exact: false },
  { to: '/ticker/search', label: 'Analyze', icon: Search, exact: false },
  { to: '/performance', label: 'Perf', icon: BarChart2, exact: false },
  { to: '/profile', label: 'Profile', icon: User, exact: false },
]

function MobileBottomBar() {
  return (
    <nav className="md:hidden fixed bottom-0 inset-x-0 z-30
                    bg-[var(--color-surface)]
                    border-t border-[var(--color-border)]
                    pb-safe">
      <div className="flex items-center justify-around px-2 h-16">
        {bottomTabs.map(({ to, label, icon: Icon, exact }) => (
          <NavLink
            key={to}
            to={to}
            end={exact}
            className={({ isActive }) =>
              `flex flex-col items-center gap-0.5 px-3 py-2 rounded-xl flex-1 min-h-[2.75rem]
               transition-colors duration-150
               ${isActive
                 ? 'text-brand-500'
                 : 'text-[var(--color-fg-muted)]'
               }`
            }
          >
            {({ isActive: _isActive }) => (
              <>
                <Icon className="w-5 h-5" />
                <span className="text-[0.65rem] font-medium leading-none">{label}</span>
              </>
            )}
          </NavLink>
        ))}
      </div>
    </nav>
  )
}

interface LayoutProps {
  children: React.ReactNode
}

export default function Layout({ children }: LayoutProps) {
  return (
    <div className="min-h-dvh flex flex-col bg-[var(--color-bg)] transition-colors duration-200">
      <DesktopNav />

      {/* Mobile top bar */}
      <header className="md:hidden flex items-center justify-between px-4 h-14 flex-shrink-0
                          bg-[var(--color-surface)]
                          border-b border-[var(--color-border)]
                          sticky top-0 z-30">
        <LogoMark />
        <ThemeToggle />
      </header>

      {/* Account strip + main content.
          The desktop header is fixed, so the 60px offset lives on this wrapper
          rather than on <main> — that way AccountBar clears the header too and
          can stick directly beneath it. */}
      <div className="flex-1 flex flex-col md:pt-[60px] min-w-0">
        <AccountBar />

        <main className="flex-1 mb-bottom-bar md:mb-0 px-4 py-6 md:px-6 md:py-8
                         max-w-5xl mx-auto w-full">
          {children}
        </main>
      </div>

      {/* Footer */}
      <footer className="hidden md:flex border-t border-[var(--color-border)] bg-[var(--color-surface)] transition-colors duration-200">
        <div className="max-w-5xl mx-auto w-full px-6 py-4 flex items-center justify-between gap-4">
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
            className="text-xs text-[var(--color-fg-muted)] hover:text-brand-500 transition-colors"
          >
            Built by SAMSBPM Technologies Inc
          </a>
        </div>
      </footer>

      <MobileBottomBar />
    </div>
  )
}
