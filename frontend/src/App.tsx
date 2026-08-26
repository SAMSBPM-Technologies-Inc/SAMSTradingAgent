import React from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { ThemeProvider } from './lib/theme-context'
import { AuthProvider, useAuth } from './lib/auth-context'
import AuthPage from './pages/AuthPage'
import DashboardPage from './pages/DashboardPage'
import TickerPage from './pages/TickerPage'
import PerformancePage from './pages/PerformancePage'
import ProfilePage from './pages/ProfilePage'
import GuidePage from './pages/GuidePage'
import HoldingsPage from './pages/HoldingsPage'
import SearchPage from './pages/SearchPage'
import CalibrationPage from './pages/CalibrationPage'
import OrdersPage from './pages/OrdersPage'
import { ToastProvider } from './lib/toast-context'
import { TradingSettingsProvider } from './lib/trading-context'
import LoadingSpinner from './components/LoadingSpinner'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { token, isLoading } = useAuth()

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-dvh">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  if (!token) {
    return <Navigate to="/auth" replace />
  }

  return <>{children}</>
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/auth" element={<AuthPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <DashboardPage />
          </ProtectedRoute>
        }
      />
      {/* The three destinations of the 1.7 IA. `/holdings`, `/orders` and
          `/profile` still resolve — they redirect here, so bookmarks and the
          mobile app's older deep links keep working. */}
      <Route
        path="/positions"
        element={
          <ProtectedRoute>
            <HoldingsPage />
          </ProtectedRoute>
        }
      />
      <Route path="/holdings" element={<Navigate to="/positions" replace />} />
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
      <Route
        path="/ticker/:symbol"
        element={
          <ProtectedRoute>
            <TickerPage />
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
      <Route
        path="/orders"
        element={
          <ProtectedRoute>
            <OrdersPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/settings"
        element={
          <ProtectedRoute>
            <ProfilePage />
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
          <ToastProvider>
            <AppRoutes />
          </ToastProvider>
        </TradingSettingsProvider>
      </AuthProvider>
    </ThemeProvider>
  )
}
