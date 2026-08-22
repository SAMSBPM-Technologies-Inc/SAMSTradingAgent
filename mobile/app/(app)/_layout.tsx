import React from 'react'
import { Tabs } from 'expo-router'
import { Home, BarChart2, Briefcase, ClipboardList, User } from 'lucide-react-native'
import { useTheme } from '../../src/lib/theme-context'

const BRAND = '#f2600c'

/** Mirrors the web tokens in frontend/src/index.css — keep the two in step. */
const PALETTE = {
  light: { muted: '#83786a', surface: '#f5f2ed', border: '#e7e2d8' },
  dark:  { muted: '#9a8f82', surface: '#141109', border: '#2a2420' },
} as const

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
          title: 'Watchlist',
          tabBarIcon: ({ color, size }) => <Home size={size} color={color} />,
        }}
      />
      {/* Second tab deliberately: approving a proposal is the thing you want
          to do from wherever you are, where the watchlist is what you read at
          a desk. */}
      <Tabs.Screen
        name="orders"
        options={{
          title: 'Orders',
          tabBarIcon: ({ color, size }) => <ClipboardList size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="holdings"
        options={{
          title: 'Holdings',
          tabBarIcon: ({ color, size }) => <Briefcase size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="performance"
        options={{
          title: 'Performance',
          tabBarIcon: ({ color, size }) => <BarChart2 size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="profile"
        options={{
          title: 'Profile',
          tabBarIcon: ({ color, size }) => <User size={size} color={color} />,
        }}
      />
      {/* Hidden from the tab bar. Five tabs is the practical limit on a phone,
          so these are reached by link: guide from Profile, calibration from
          Performance — the same discovery path as the web app. */}
      <Tabs.Screen name="guide" options={{ href: null }} />
      <Tabs.Screen name="calibration" options={{ href: null }} />
    </Tabs>
  )
}
