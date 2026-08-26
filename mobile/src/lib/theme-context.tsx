import React, { createContext, useContext, useEffect, useState } from 'react'
import { Appearance, useColorScheme } from 'react-native'
import AsyncStorage from '@react-native-async-storage/async-storage'

type Theme = 'dark' | 'light'

interface ThemeContextValue {
  theme: Theme
  toggleTheme: () => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)
const THEME_KEY = 'sams_theme'

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const systemScheme = useColorScheme()
  const [theme, setTheme] = useState<Theme>(systemScheme ?? 'light')
  // The stored choice arrives a tick after first paint. Rendering in the
  // meantime shows the system theme and then snaps to the saved one — a white
  // flash on every cold start for anyone who chose dark. Hold the first frame
  // instead; the read is a single AsyncStorage hit.
  const [hydrated, setHydrated] = useState(false)

  useEffect(() => {
    AsyncStorage.getItem(THEME_KEY)
      .then((stored) => {
        if (stored === 'dark' || stored === 'light') {
          setTheme(stored)
          Appearance.setColorScheme(stored)
        }
      })
      .catch(() => {})
      // Never leave the app blank because storage failed.
      .finally(() => setHydrated(true))
  }, [])

  const toggleTheme = () => {
    setTheme((t) => {
      const next = t === 'dark' ? 'light' : 'dark'
      Appearance.setColorScheme(next)
      AsyncStorage.setItem(THEME_KEY, next).catch(() => {})
      return next
    })
  }

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme }}>
      {hydrated ? children : null}
    </ThemeContext.Provider>
  )
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider')
  return ctx
}
