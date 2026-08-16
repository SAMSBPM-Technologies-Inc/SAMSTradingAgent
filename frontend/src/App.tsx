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
import AlphaRadarPage from './pages/AlphaRadarPage'
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
        path="/profile"
        element={
          <ProtectedRoute>
            <ProfilePage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/guide"
        element={
          <ProtectedRoute>
            <GuidePage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/radar"
        element={
          <ProtectedRoute>
            <AlphaRadarPage />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to="/" replace /> />
    </Routes>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </ThemeProvider>
  )
}
