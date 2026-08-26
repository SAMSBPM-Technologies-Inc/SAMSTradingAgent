import React, { useState } from 'react'
import {
  View,
  Text,
  TextInput,
  Pressable,
  ScrollView,
} from 'react-native'
import { router } from 'expo-router'
import { useForm, Controller } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Eye, EyeOff, LogIn } from 'lucide-react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { authApi } from '../../src/lib/api'
import { useAuth } from '../../src/lib/auth-context'
import LoadingSpinner from '../../src/components/LoadingSpinner'
import { usePalette } from '../../src/lib/palette'
import LogoLockup from '../../src/components/LogoLockup'

// ── Schema ────────────────────────────────────────────────────────────────────

const loginSchema = z.object({
  email: z.string().email('Enter a valid email'),
  password: z.string().min(6, 'Password must be at least 6 characters'),
})

type LoginFormData = z.infer<typeof loginSchema>

// ── Field components ──────────────────────────────────────────────────────────

function FieldLabel({ label }: { label: string }) {
  const C = usePalette()
  return <Text style={{ fontSize: 13, fontWeight: '500', color: C.fg, marginBottom: 6 }}>{label}</Text>
}

function FieldError({ message }: { message?: string }) {
  const C = usePalette()
  if (!message) return null
  return <Text style={{ fontSize: 11, color: C.red, marginTop: 4 }}>{message}</Text>
}

function PasswordField({
  control,
  name,
  label,
  placeholder,
  error,
}: {
  control: ReturnType<typeof useForm>['control']
  name: string
  label: string
  placeholder?: string
  error?: string
}) {
  const C = usePalette()
  const [show, setShow] = useState(false)
  return (
    <View style={{ marginBottom: 4 }}>
      <FieldLabel label={label} />
      <View style={{ flexDirection: 'row', alignItems: 'center', position: 'relative' }}>
        <Controller
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          control={control as any}
          name={name}
          render={({ field: { onChange, onBlur, value } }) => (
            <TextInput
              style={{
                flex: 1,
                borderWidth: 1,
                borderColor: C.border,
                borderRadius: 10,
                paddingHorizontal: 14,
                paddingVertical: 12,
                paddingRight: 44,
                fontSize: 14,
                color: C.fg,
                backgroundColor: C.surface,
              }}
              secureTextEntry={!show}
              onChangeText={onChange}
              onBlur={onBlur}
              value={value}
              placeholder={placeholder}
              placeholderTextColor={C.fgMuted}
              autoCapitalize="none"
            />
          )}
        />
        <Pressable
          onPress={() => setShow((v) => !v)}
          style={{ position: 'absolute', right: 12 }}
          hitSlop={8}
        >
          {show
            ? <EyeOff size={16} color={C.fgMuted} />
            : <Eye size={16} color={C.fgMuted} />}
        </Pressable>
      </View>
      <FieldError message={error} />
    </View>
  )
}

// ── Login Form ────────────────────────────────────────────────────────────────

function LoginForm({ onSuccess }: { onSuccess: () => void }) {
  const C = usePalette()
  const { login } = useAuth()
  const [serverError, setServerError] = useState<string | null>(null)

  const { control, handleSubmit, formState: { errors, isSubmitting } } =
    useForm<LoginFormData>({ resolver: zodResolver(loginSchema) })

  const onSubmit = async (data: LoginFormData) => {
    setServerError(null)
    try {
      const res = await authApi.loginJson(data.email, data.password)
      await login(res.data.access_token)
      onSuccess()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setServerError(msg ?? 'Login failed. Please check your credentials.')
    }
  }

  return (
    <View style={{ gap: 16 }}>
      <View>
        <FieldLabel label="Email" />
        <Controller
          control={control}
          name="email"
          render={({ field: { onChange, onBlur, value } }) => (
            <TextInput
              style={{
                borderWidth: 1, borderColor: C.border, borderRadius: 10,
                paddingHorizontal: 14, paddingVertical: 12, fontSize: 14,
                color: C.fg, backgroundColor: C.surface,
              }}
              onChangeText={onChange}
              onBlur={onBlur}
              value={value}
              placeholder="you@example.com"
              placeholderTextColor={C.fgMuted}
              keyboardType="email-address"
              autoCapitalize="none"
              autoComplete="email"
            />
          )}
        />
        <FieldError message={errors.email?.message} />
      </View>

      <PasswordField
        control={control}
        name="password"
        label="Password"
        placeholder="••••••••"
        error={errors.password?.message}
      />

      {serverError && (
        <View style={{
          paddingHorizontal: 14, paddingVertical: 12, borderRadius: 10,
          backgroundColor: `${C.red}1a`, borderWidth: 1, borderColor: `${C.red}33`,
        }}>
          <Text style={{ color: C.red, fontSize: 13 }}>{serverError}</Text>
        </View>
      )}

      <Pressable
        onPress={handleSubmit(onSubmit)}
        disabled={isSubmitting}
        style={{
          backgroundColor: C.brand,
          borderRadius: 10, paddingVertical: 16,
          flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8,
        }}
      >
        {isSubmitting ? <LoadingSpinner size="sm" color="#fff" /> : <LogIn size={16} color="#fff" />}
        <Text style={{ color: '#fff', fontSize: 15, fontWeight: '600' }}>
          {isSubmitting ? 'Signing in…' : 'Sign In'}
        </Text>
      </Pressable>
    </View>
  )
}

// ── Auth Screen ───────────────────────────────────────────────────────────────

export default function AuthScreen() {
  const C = usePalette()
  const onSuccess = () => router.replace('/(app)')

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.bg }}>
      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={{ paddingHorizontal: 20, paddingTop: 8, paddingBottom: 80 }}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
        bounces={true}
      >
        {/* Brand header */}
        <View style={{ marginBottom: 32 }}>
          <LogoLockup size={36} />
        </View>

        {/* Heading */}
        <View style={{ marginBottom: 24 }}>
          <Text style={{ fontSize: 28, fontWeight: '300', color: C.fg, marginBottom: 4 }}>
            Welcome back
          </Text>
          <Text style={{ fontSize: 14, color: C.fgMuted }}>
            Sign in to your trading dashboard
          </Text>
        </View>

        {/* Card */}
        <View style={{
          backgroundColor: C.surface, borderRadius: 16,
          borderWidth: 1, borderColor: C.border,
          padding: 20,
          shadowColor: '#000', shadowOffset: { width: 0, height: 1 },
          shadowOpacity: 0.05, shadowRadius: 4, elevation: 2,
        }}>
          <LoginForm onSuccess={onSuccess} />
        </View>
      </ScrollView>
    </SafeAreaView>
  )
}
