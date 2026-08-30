import React from 'react'
import { Tabs } from 'expo-router'
import { Briefcase, LineChart, Settings as SettingsIcon } from 'lucide-react-native'
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
      <Tabs.Screen name="status" options={{ href: null }} />
      <Tabs.Screen name="guide" options={{ href: null }} />
    </Tabs>
  )
}
