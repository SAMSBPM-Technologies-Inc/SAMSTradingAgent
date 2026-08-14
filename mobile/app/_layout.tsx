import '../global.css'
import React, { useEffect } from 'react'
import { Stack, Redirect } from 'expo-router'
import { View, ActivityIndicator } from 'react-native'
import { SafeAreaProvider } from 'react-native-safe-area-context'
import { StatusBar } from 'expo-status-bar'
import { AuthProvider, useAuth } from '../src/lib/auth-context'
import { ThemeProvider } from '../src/lib/theme-context'

function RootNavigator() {
  const { token, isLoading } = useAuth()

  if (isLoading) {
    return (
      <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#f5f2ed' }}>
        <ActivityIndicator size="large" color="#f2600c" />
      </View>
    )
  }

  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="(auth)" redirect={!!token} />
      <Stack.Screen name="(app)" redirect={!token} />
      <Stack.Screen
        name="ticker/[symbol]"
        options={{
          headerShown: true,
          headerTitle: '',
          headerBackTitle: 'Back',
          headerTintColor: '#f2600c',
          headerStyle: { backgroundColor: '#f5f2ed' },
          headerShadowVisible: false,
        }}
      />
    </Stack>
  )
}

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <ThemeProvider>
        <AuthProvider>
          <StatusBar style="dark" />
          <RootNavigator />
        </AuthProvider>
      </ThemeProvider>
    </SafeAreaProvider>
  )
}
