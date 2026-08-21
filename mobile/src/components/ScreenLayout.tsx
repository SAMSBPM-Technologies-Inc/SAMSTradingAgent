import React from 'react'
import { ScrollView, KeyboardAvoidingView, Platform } from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import Disclaimer from './Disclaimer'

interface Props {
  children: React.ReactNode
  /** Pass true on screens that have autocomplete dropdowns or text inputs near the bottom */
  avoidKeyboard?: boolean
}

export default function ScreenLayout({ children, avoidKeyboard = false }: Props) {
  const inner = (
    <SafeAreaView className="flex-1 bg-bg" edges={['top']}>
      <ScrollView
        className="flex-1"
        contentContainerStyle={{ paddingHorizontal: 16, paddingTop: 20, paddingBottom: 100 }}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
      >
        {children}
        <Disclaimer />
      </ScrollView>
    </SafeAreaView>
  )

  if (avoidKeyboard) {
    return (
      <KeyboardAvoidingView
        className="flex-1"
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      >
        {inner}
      </KeyboardAvoidingView>
    )
  }

  return inner
}
