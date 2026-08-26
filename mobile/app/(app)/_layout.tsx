import React from 'react'
import { Tabs } from 'expo-router'
import { Briefcase, LineChart, Settings as SettingsIcon } from 'lucide-react-native'
import { useTheme } from '../../src/lib/theme-context'

const BRAND = '#f2600c'

/** Mirrors the web tokens in frontend/src/index.css — keep the two in step. */
const PALETTE = {
  light: { muted: '#83786a', surface: '#f5f2ed', border: '#e7e2d8' },
  dark:  { muted: '#9a8f82', surface: '#141109', border: '#2a2420' },
} as const

/**
 * Three destinations, matching the web app's 1.7 information architecture:
 * Trade, Positions, Settings.
 *
 * Nothing was retired to get here. Performance, Calibration and the Gateway
 * guide keep their routes and are reached by link from Settings — the same
 * arrangement the web header's "More" menu provides, and the same discovery
 * path Guide and Calibration already used before this change.
 */
export default function AppLayout() {
  const { theme } = useTheme()
  const c = PALETTE[theme]

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: BRAND,
        tabBarInactiveTintColor: c.muted,
        tabBarStyle: {
          backgroundColor: c.surface,
          borderTopColor: c.border,
          borderTopWidth: 1,
          height: 60,
          paddingBottom: 8,
        },
        tabBarLabelStyle: {
          fontSize: 10,
          fontWeight: '600',
        },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: 'Trade',
          tabBarIcon: ({ color, size }) => <LineChart size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="positions"
        options={{
          title: 'Positions',
          tabBarIcon: ({ color, size }) => <Briefcase size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="settings"
        options={{
          title: 'Settings',
          tabBarIcon: ({ color, size }) => <SettingsIcon size={size} color={color} />,
        }}
      />

      {/* Off the tab bar, still routed. Linked from Settings. */}
      <Tabs.Screen name="performance" options={{ href: null }} />
      <Tabs.Screen name="calibration" options={{ href: null }} />
      <Tabs.Screen name="guide" options={{ href: null }} />
    </Tabs>
  )
}
