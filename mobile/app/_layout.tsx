import '../global.css'
import React, { useEffect } from 'react'
import { Stack, Redirect } from 'expo-router'
import { View, ActivityIndicator } from 'react-native'
import { SafeAreaProvider } from 'react-native-safe-area-context'
import { StatusBar } from 'expo-status-bar'
import { AuthProvider, useAuth } from '../src/lib/auth-context'
import { ThemeProvider, useTheme } from '../src/lib/theme-context'
import { usePalette } from '../src/lib/palette'
import { ToastProvider } from '../src/lib/toast-context'

function RootNavigator() {
  const { token, isLoading } = useAuth()
  const C = usePalette()

  if (isLoading) {
    return (
      <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: C.bg }}>
        <ActivityIndicator size="large" color={C.brand} />
      </View>
    )
  }

  return (
    <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: C.bg } }}>
      <Stack.Screen name="(auth)" redirect={!!token} />
      <Stack.Screen name="(app)" redirect={!token} />
      <Stack.Screen
        name="ticker/[symbol]"
        options={{
          headerShown: true,
          headerTitle: '',
          headerBackTitle: 'Back',
          headerTintColor: C.brand,
          headerStyle: { backgroundColor: C.bg },
          headerShadowVisible: false,
        }}
      />
    </Stack>
  )
}

/**
 * Status bar content colour is the inverse of the ground it sits on: dark
 * glyphs on the light theme, light glyphs on the dark one. Hardcoding `dark`
 * left the clock and battery invisible against a dark background.
 */
function ThemedStatusBar() {
  const { theme } = useTheme()
  return <StatusBar style={theme === 'dark' ? 'light' : 'dark'} />
}

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <ThemeProvider>
        <AuthProvider>
          {/* Inside SafeAreaProvider — the toast stack positions itself above
              the tab bar using the safe-area insets. */}
          <ToastProvider>
            <ThemedStatusBar />
            <RootNavigator />
          </ToastProvider>
        </AuthProvider>
      </ThemeProvider>
    </SafeAreaProvider>
  )
}
