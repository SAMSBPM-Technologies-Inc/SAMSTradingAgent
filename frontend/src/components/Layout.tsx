import React from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import {
  BarChart2,
  BookOpen,
  Home,
  LogOut,
  Search,
  User,
} from 'lucide-react'
import { useAuth } from '../lib/auth-context'
import ThemeToggle from './ThemeToggle'

// SAMSBPM Logo — text-based lockup for desktop
function LogoLockup() {
  return (
    <div className="flex items-center gap-2 select-none">
      {/* Icon mark */}
      <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 flex-shrink-0">
        <span className="text-white font-bold text-sm" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>S</span>
      </div>
      {/* Text lockup */}
      <div className="leading-tight">
        <div
          className="text-brand-500 font-bold text-base tracking-tight"
          style={{ fontFamily: 'Fraunces, Georgia, serif' }}
        >
          SAMSBPM
        </div>
        <div className="text-[var(--color-fg-muted)] text-[0.6rem] tracking-widest uppercase">
          Trading
        </div>
      </div>
    </div>
  )
}

// Mobile mark only
function LogoMark() {
  return (
    <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 flex-shrink-0">
      <span className="text-white font-bold text-sm" style={{ fontFamily: 'Fraunces, Georgia, serif' }}>S</span>
    </div>
  )
}

const navLinks = [
  { to: '/', label: 'Dashboard', icon: Home, exact: true },
  { to: '/performance', label: 'Performance', icon: BarChart2, exact: false },
  { to: '/guide', label: 'Guide', icon: BookOpen, exact: false },
]

function DesktopNav() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  return (
    <header className="hidden md:flex fixed top-0 inset-x-0 z-30 h-16 items-center px-6 gap-6
                       bg-[var(--color-surface)]/90 backdrop-blur-md
                       border-b border-[var(--color-border)]
                       transition-colors duration-200">
      {/* Logo */}
      <button onClick={() => navigate('/')} className="flex-shrink-0">
        <LogoLockup />
      </button>

      {/* Nav links */}
      <nav className="flex items-center gap-1 flex-1">
        {navLinks.map(({ to, label, icon: Icon, exact }) => (
          <NavLink
            key={to}
            to={to}
            end={exact}
            className={({ isActive }) =>
              `flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium transition-colors duration-200
               ${isActive
                 ? 'bg-brand-500/10 text-brand-500'
                 : 'text-[var(--color-fg-muted)] hover:text-[var(--color-fg)] hover:bg-[var(--color-border)]/40'
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
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl
                          bg-[var(--color-border)]/30">
            <div className="w-6 h-6 rounded-full bg-brand-500/20 flex items-center justify-center flex-shrink-0">
              <User className="w-3.5 h-3.5 text-brand-500" />
            </div>
            <span className="text-sm text-[var(--color-fg-muted)] max-w-[10rem] truncate">
              {user?.display_name ?? user?.email ?? 'Account'}
            </span>
          </div>
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
  { to: '/ticker/search', label: 'Analyze', icon: Search, exact: false },
  { to: '/performance', label: 'Performance', icon: BarChart2, exact: false },
  { to: '/guide', label: 'Guide', icon: BookOpen, exact: false },
  { to: '/profile', label: 'Profile', icon: User, exact: false },
]

function MobileBottomBar() {
  return (
    <nav className="md:hidden fixed bottom-0 inset-x-0 z-30
                    bg-[var(--color-surface)]/95 backdrop-blur-lg
                    border-t border-[var(--color-border)]
                    pb-safe
                    transition-colors duration-200">
      <div className="flex items-center justify-around px-2 h-16">
        {bottomTabs.map(({ to, label, icon: Icon, exact }) => (
          <NavLink
            key={to}
            to={to}
            end={exact}
            className={({ isActive }) =>
              `flex flex-col items-center gap-0.5 px-3 py-2 rounded-xl flex-1 min-h-[2.75rem]
               transition-colors duration-200
               ${isActive
                 ? 'text-brand-500'
                 : 'text-[var(--color-fg-muted)]'
               }`
            }
          >
            {({ isActive }) => (
              <>
                <div className={`p-1.5 rounded-xl transition-colors duration-200
                                ${isActive ? 'bg-brand-500/10' : ''}`}>
                  <Icon className="w-5 h-5" />
                </div>
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
                          bg-[var(--color-surface)]/90 backdrop-blur-md
                          border-b border-[var(--color-border)]
                          transition-colors duration-200 sticky top-0 z-30">
        <LogoMark />
        <ThemeToggle />
      </header>

      {/* Main content */}
      <main className="flex-1 md:pt-16 mb-bottom-bar md:mb-0 px-4 py-6 md:px-6 md:py-8
                       max-w-5xl mx-auto w-full">
        {children}
      </main>

      <MobileBottomBar />
    </div>
  )
}
