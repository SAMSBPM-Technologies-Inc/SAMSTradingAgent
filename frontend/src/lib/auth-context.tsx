import React, { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { authApi, TOKEN_STORAGE_KEY } from './api'
import type { User } from '../types'

interface AuthContextValue {
  user: User | null
  token: string | null
  isLoading: boolean
  login: (token: string) => Promise<void>
  logout: () => void
  fetchUser: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

// Read once, synchronously, so the first render already knows whether there is
// a session to restore. This is what keeps the public landing page from
// flashing a spinner at a visitor who has no token at all: with the old
// unconditional `useState(true)`, every anonymous page load painted the
// loading state for a frame before deciding there was nothing to load.
function storedToken(): string | null {
  if (typeof window === 'undefined') return null
  return localStorage.getItem(TOKEN_STORAGE_KEY)
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(storedToken)
  // Loading means "a stored session is being verified" — never true when there
  // is nothing stored.
  const [isLoading, setIsLoading] = useState(() => storedToken() !== null)

  const fetchUser = useCallback(async () => {
    try {
      const res = await authApi.me()
      setUser(res.data)
    } catch {
      // Token is invalid — clear it
      localStorage.removeItem(TOKEN_STORAGE_KEY)
      setToken(null)
      setUser(null)
    }
  }, [])

  // Hydrate from localStorage on mount. The token is already in state by now;
  // this verifies it and loads the user behind it.
  useEffect(() => {
    if (!storedToken()) return
    let cancelled = false
    fetchUser().finally(() => {
      if (!cancelled) setIsLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [fetchUser])

  const login = useCallback(async (newToken: string) => {
    localStorage.setItem(TOKEN_STORAGE_KEY, newToken)
    setToken(newToken)
    await fetchUser()
  }, [fetchUser])

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_STORAGE_KEY)
    setToken(null)
    setUser(null)
    // Navigate to auth — use location to avoid window dependency in tests
    if (typeof window !== 'undefined') {
      window.location.href = '/auth'
    }
  }, [])

  return (
    <AuthContext.Provider value={{ user, token, isLoading, login, logout, fetchUser }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
