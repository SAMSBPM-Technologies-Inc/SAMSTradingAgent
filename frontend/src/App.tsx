import React from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { ThemeProvider } from './lib/theme-context'
import { AuthProvider, useAuth } from './lib/auth-context'
import AuthPage from './pages/AuthPage'
import HomePage from './pages/HomePage'
import TradePage from './pages/TradePage'
import PerformancePage from './pages/PerformancePage'
import SettingsPage from './pages/SettingsPage'
import GuidePage from './pages/GuidePage'
import AnalysisPage from './pages/AnalysisPage'
import SearchPage from './pages/SearchPage'
import CalibrationPage from './pages/CalibrationPage'
import StatusPage from './pages/StatusPage'
import { SystemStatusProvider } from './lib/system-status'
import { ToastProvider } from './lib/toast-context'
import { TradingSettingsProvider } from './lib/trading-context'
import LoadingSpinner from './components/LoadingSpinner'

function AuthGate({ children }: { children: React.ReactNode }) {
  const { isLoading } = useAuth()

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-dvh">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  return <>{children}</>
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { token } = useAuth()

  if (!token) {
    return <Navigate to="/auth" replace />
  }

  return <AuthGate>{children}</AuthGate>
}

/* `/` is the one route with two faces. A signed-out visitor gets the public
   landing page — sta.samsbpm.com used to open on a password prompt, which
   tells someone who has never seen the product nothing about it — and a
   signed-in one goes straight to Trade, unchanged.
 *
 * The split is here rather than inside either page so that HomePage stays
 * free of auth entirely: when the landing page moves to its own public host,
 * this branch is what gets deleted, and nothing inside HomePage changes.
 */
function RootRoute() {
  const { token } = useAuth()
  return token ? <TradePage /> : <HomePage />
}

function AuthRoute() {
  const { token } = useAuth()
  return token ? <Navigate to="/" replace /> : <AuthPage />
}

function AppRoutes() {
  return (
    <Routes>
      {/* Signing in again when you already are lands on the dashboard rather
          than a form that would immediately redirect. */}
      <Route
        path="/auth"
        element={
          <AuthGate>
            <AuthRoute />
          </AuthGate>
        }
      />
      {/* Trade answers "what should I do about this name, and why". `/` shows
          the first watched ticker; `/ticker/:symbol` deep-links to any name,
          watched or not. Both render the same screen. */}
      <Route
        path="/"
        element={
          <AuthGate>
            <RootRoute />
          </AuthGate>
        }
      />
      {/* The landing page on its own path too, so it stays reachable while
          signed in — and so the future public host has a URL to mirror. */}
      <Route path="/home" element={<HomePage />} />
      {/* The three destinations of the 1.7 IA. `/holdings`, `/orders` and
          `/profile` still resolve — they redirect here, so bookmarks and the
          mobile app's older deep links keep working. */}
      {/* Positions merged into the Trade dashboard, which now renders the same
          component as its centre column. The old paths still resolve so
          bookmarks and the mobile app's deep links keep working — the same
          courtesy `/holdings` and `/orders` were already given. */}
      <Route path="/positions" element={<Navigate to="/" replace />} />
      <Route path="/holdings" element={<Navigate to="/" replace />} />
      {/* Declared before /ticker/:symbol so the mobile "Analyze" tab resolves
          to the lookup screen rather than being read as a symbol named
          "search" — which is exactly what it used to do. */}
      <Route
        path="/search"
        element={
          <ProtectedRoute>
            <SearchPage />
          </ProtectedRoute>
        }
      />
      {/* Three routes, one screen. The centre column is what changes: the
          dashboard on `/`, one name's analysis on `/ticker/:symbol`, one order's
          record on `/transaction/:id`. Each is a real URL, so a selection is
          deep-linkable and Back walks what you looked at.

          None of them is a modal. An audit trail read through a backdrop puts
          the reader's context behind the thing they opened to compare it with.

          `/analysis/:symbol` is the same report with no dashboard around it —
          what the "New window" control opens, and the only form worth having
          two of on screen at once. */}
      <Route
        path="/ticker/:symbol"
        element={
          <ProtectedRoute>
            <TradePage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/transaction/:id"
        element={
          <ProtectedRoute>
            <TradePage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/analysis/:symbol"
        element={
          <ProtectedRoute>
            <AnalysisPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/performance"
        element={
          <ProtectedRoute>
            <PerformancePage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/calibration"
        element={
          <ProtectedRoute>
            <CalibrationPage />
          </ProtectedRoute>
        }
      />
      {/* What the engine actually has to work with right now. Authenticated
          like everything else: it names environment variables and provider
          error text, which is not for a stranger. */}
      <Route
        path="/status"
        element={
          <ProtectedRoute>
            <StatusPage />
          </ProtectedRoute>
        }
      />
      <Route path="/orders" element={<Navigate to="/" replace />} />
      <Route
        path="/settings"
        element={
          <ProtectedRoute>
            <SettingsPage />
          </ProtectedRoute>
        }
      />
      <Route path="/profile" element={<Navigate to="/settings" replace />} />
      <Route
        path="/guide"
        element={
          <ProtectedRoute>
            <GuidePage />
          </ProtectedRoute>
        }
      />
      {/* Alpha Radar merged into the dashboard — its dip-buy setups are now a
          column and filter on the watchlist. Kept as a redirect for bookmarks. */}
      <Route path="/radar" element={<Navigate to="/" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <TradingSettingsProvider>
          <SystemStatusProvider>
            <ToastProvider>
              <AppRoutes />
            </ToastProvider>
          </SystemStatusProvider>
        </TradingSettingsProvider>
      </AuthProvider>
    </ThemeProvider>
  )
}
