import React from 'react'
import { Tabs } from 'expo-router'
import { Home, BarChart2, User } from 'lucide-react-native'

const BRAND = '#f2600c'
const MUTED = '#83786a'
const BG = '#f5f2ed'

export default function AppLayout() {
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: BRAND,
        tabBarInactiveTintColor: MUTED,
        tabBarStyle: {
          backgroundColor: BG,
          borderTopColor: '#e7e2d8',
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
      {/* Hidden from tab bar — accessible via Profile link */}
      <Tabs.Screen
        name="guide"
        options={{ href: null }}
      />
    </Tabs>
  )
}
