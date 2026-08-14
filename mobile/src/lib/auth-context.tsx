import React, { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { router } from 'expo-router'
import * as SecureStore from 'expo-secure-store'
import { authApi, TOKEN_STORAGE_KEY, syncTokenToApi, registerUnauthorizedHandler } from './api'
import type { User } from '../types'

interface AuthContextValue {
  user: User | null
  token: string | null
  isLoading: boolean
  login: (token: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  const doLogout = useCallback(() => {
    SecureStore.deleteItemAsync(TOKEN_STORAGE_KEY).catch(() => {})
    syncTokenToApi(null)
    setToken(null)
    setUser(null)
    router.replace('/(auth)')
  }, [])

  useEffect(() => {
    registerUnauthorizedHandler(doLogout)
  }, [doLogout])

  const fetchUser = useCallback(async () => {
    try {
      const res = await authApi.me()
      setUser(res.data as User)
    } catch {
      await SecureStore.deleteItemAsync(TOKEN_STORAGE_KEY).catch(() => {})
      syncTokenToApi(null)
      setToken(null)
      setUser(null)
    }
  }, [])

  // Hydrate from SecureStore on mount
  useEffect(() => {
    const hydrate = async () => {
      try {
        const storedToken = await SecureStore.getItemAsync(TOKEN_STORAGE_KEY)
        if (storedToken) {
          syncTokenToApi(storedToken)
          setToken(storedToken)
          await fetchUser()
        }
      } catch {
        // SecureStore unavailable
      } finally {
        setIsLoading(false)
      }
    }
    hydrate()
  }, [fetchUser])

  const login = useCallback(
    async (newToken: string) => {
      await SecureStore.setItemAsync(TOKEN_STORAGE_KEY, newToken)
      syncTokenToApi(newToken)
      setToken(newToken)
      await fetchUser()
    },
    [fetchUser],
  )

  const logout = useCallback(() => {
    doLogout()
  }, [doLogout])

  return (
    <AuthContext.Provider value={{ user, token, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
