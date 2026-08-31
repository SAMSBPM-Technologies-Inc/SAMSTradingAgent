import React from 'react'
import { Tabs } from 'expo-router'
import { Briefcase, LineChart, Settings as SettingsIcon } from 'lucide-react-native'
import { useAuth } from '../../src/lib/auth-context'
import { entitlementsOf } from '../../src/lib/entitlements'
import { usePalette } from '../../src/lib/palette'

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
  const C = usePalette()
  const { user } = useAuth()
  // Positions is holdings and order history on one shared brokerage account.
  // An account whose plan has no trading gets no tab for it — but the screen
  // stays *registered* so a deep link still resolves rather than throwing, and
  // guards itself. `href: null` hides a tab; it does not close a route.
  const mayTrade = entitlementsOf(user).may_trade

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: C.brand,
        tabBarInactiveTintColor: C.fgMuted,
        sceneStyle: { backgroundColor: C.bg },
        tabBarStyle: {
          backgroundColor: C.surface,
          borderTopColor: C.border,
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
        options={mayTrade
          ? {
            title: 'Positions',
            tabBarIcon: ({ color, size }) => <Briefcase size={size} color={color} />,
          }
          : { href: null }}
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
      <Tabs.Screen name="status" options={{ href: null }} />
      <Tabs.Screen name="guide" options={{ href: null }} />
    </Tabs>
  )
}
