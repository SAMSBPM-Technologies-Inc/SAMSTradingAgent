import React, { useState } from 'react'
import {
  View,
  Text,
  TextInput,
  Pressable,
  ScrollView,
  KeyboardAvoidingView,
  Platform,
} from 'react-native'
import { router } from 'expo-router'
import { useForm, Controller } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Eye, EyeOff, LogIn, UserPlus } from 'lucide-react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { authApi } from '../../src/lib/api'
import { useAuth } from '../../src/lib/auth-context'
import LoadingSpinner from '../../src/components/LoadingSpinner'

// ── Schemas ───────────────────────────────────────────────────────────────────

const loginSchema = z.object({
  email: z.string().email('Enter a valid email'),
  password: z.string().min(6, 'Password must be at least 6 characters'),
})

const registerSchema = z
  .object({
    display_name: z.string().min(2, 'Name must be at least 2 characters'),
    email: z.string().email('Enter a valid email'),
    password: z.string().min(6, 'Password must be at least 6 characters'),
    confirm_password: z.string(),
  })
  .refine((d) => d.password === d.confirm_password, {
    message: "Passwords don't match",
    path: ['confirm_password'],
  })

type LoginFormData = z.infer<typeof loginSchema>
type RegisterFormData = z.infer<typeof registerSchema>

// ── Field components ──────────────────────────────────────────────────────────

function FieldLabel({ label }: { label: string }) {
  return <Text style={{ fontSize: 13, fontWeight: '500', color: '#14110c', marginBottom: 6 }}>{label}</Text>
}

function FieldError({ message }: { message?: string }) {
  if (!message) return null
  return <Text style={{ fontSize: 11, color: '#ef4444', marginTop: 4 }}>{message}</Text>
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
                borderColor: '#e7e2d8',
                borderRadius: 10,
                paddingHorizontal: 14,
                paddingVertical: 12,
                paddingRight: 44,
                fontSize: 14,
                color: '#14110c',
                backgroundColor: '#ffffff',
              }}
              secureTextEntry={!show}
              onChangeText={onChange}
              onBlur={onBlur}
              value={value}
              placeholder={placeholder}
              placeholderTextColor="#83786a"
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
            ? <EyeOff size={16} color="#83786a" />
            : <Eye size={16} color="#83786a" />}
        </Pressable>
      </View>
      <FieldError message={error} />
    </View>
  )
}

// ── Login Form ────────────────────────────────────────────────────────────────

function LoginForm({ onSuccess }: { onSuccess: () => void }) {
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
                borderWidth: 1, borderColor: '#e7e2d8', borderRadius: 10,
                paddingHorizontal: 14, paddingVertical: 12, fontSize: 14,
                color: '#14110c', backgroundColor: '#ffffff',
              }}
              onChangeText={onChange}
              onBlur={onBlur}
              value={value}
              placeholder="you@example.com"
              placeholderTextColor="#83786a"
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
          backgroundColor: 'rgba(239,68,68,0.1)', borderWidth: 1, borderColor: 'rgba(239,68,68,0.2)',
        }}>
          <Text style={{ color: '#ef4444', fontSize: 13 }}>{serverError}</Text>
        </View>
      )}

      <Pressable
        onPress={handleSubmit(onSubmit)}
        disabled={isSubmitting}
        style={({ pressed }) => ({
          backgroundColor: isSubmitting || pressed ? '#c24d08' : '#f2600c',
          borderRadius: 10, paddingVertical: 14,
          flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8,
          marginTop: 8,
        })}
      >
        {isSubmitting ? <LoadingSpinner size="sm" color="#fff" /> : <LogIn size={16} color="#fff" />}
        <Text style={{ color: '#fff', fontSize: 15, fontWeight: '600' }}>
          {isSubmitting ? 'Signing in…' : 'Sign In'}
        </Text>
      </Pressable>
    </View>
  )
}

// ── Register Form ─────────────────────────────────────────────────────────────

function RegisterForm({ onSuccess }: { onSuccess: () => void }) {
  const { login } = useAuth()
  const [serverError, setServerError] = useState<string | null>(null)

  const { control, handleSubmit, formState: { errors, isSubmitting } } =
    useForm<RegisterFormData>({ resolver: zodResolver(registerSchema) })

  const onSubmit = async (data: RegisterFormData) => {
    setServerError(null)
    try {
      const res = await authApi.register(data.email, data.password, data.display_name)
      await login(res.data.access_token)
      onSuccess()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setServerError(msg ?? 'Registration failed. Please try again.')
    }
  }

  return (
    <View style={{ gap: 16 }}>
      <View>
        <FieldLabel label="Display Name" />
        <Controller
          control={control}
          name="display_name"
          render={({ field: { onChange, onBlur, value } }) => (
            <TextInput
              style={{
                borderWidth: 1, borderColor: '#e7e2d8', borderRadius: 10,
                paddingHorizontal: 14, paddingVertical: 12, fontSize: 14,
                color: '#14110c', backgroundColor: '#ffffff',
              }}
              onChangeText={onChange}
              onBlur={onBlur}
              value={value}
              placeholder="Your name"
              placeholderTextColor="#83786a"
              autoComplete="name"
            />
          )}
        />
        <FieldError message={errors.display_name?.message} />
      </View>

      <View>
        <FieldLabel label="Email" />
        <Controller
          control={control}
          name="email"
          render={({ field: { onChange, onBlur, value } }) => (
            <TextInput
              style={{
                borderWidth: 1, borderColor: '#e7e2d8', borderRadius: 10,
                paddingHorizontal: 14, paddingVertical: 12, fontSize: 14,
                color: '#14110c', backgroundColor: '#ffffff',
              }}
              onChangeText={onChange}
              onBlur={onBlur}
              value={value}
              placeholder="you@example.com"
              placeholderTextColor="#83786a"
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

      <PasswordField
        control={control}
        name="confirm_password"
        label="Confirm Password"
        placeholder="••••••••"
        error={errors.confirm_password?.message}
      />

      {serverError && (
        <View style={{
          paddingHorizontal: 14, paddingVertical: 12, borderRadius: 10,
          backgroundColor: 'rgba(239,68,68,0.1)', borderWidth: 1, borderColor: 'rgba(239,68,68,0.2)',
        }}>
          <Text style={{ color: '#ef4444', fontSize: 13 }}>{serverError}</Text>
        </View>
      )}

      <Pressable
        onPress={handleSubmit(onSubmit)}
        disabled={isSubmitting}
        style={({ pressed }) => ({
          backgroundColor: isSubmitting || pressed ? '#c24d08' : '#f2600c',
          borderRadius: 10, paddingVertical: 14,
          flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8,
          marginTop: 8,
        })}
      >
        {isSubmitting ? <LoadingSpinner size="sm" color="#fff" /> : <UserPlus size={16} color="#fff" />}
        <Text style={{ color: '#fff', fontSize: 15, fontWeight: '600' }}>
          {isSubmitting ? 'Creating account…' : 'Create Account'}
        </Text>
      </Pressable>
    </View>
  )
}

// ── Auth Screen ───────────────────────────────────────────────────────────────

export default function AuthScreen() {
  const [tab, setTab] = useState<'login' | 'register'>('login')
  const onSuccess = () => router.replace('/(app)/')

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: '#f5f2ed' }}>
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      >
        <ScrollView
          contentContainerStyle={{ flexGrow: 1, paddingHorizontal: 20, paddingTop: 8, paddingBottom: 40 }}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          {/* Brand header */}
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 32 }}>
            <View style={{
              width: 36, height: 36, borderRadius: 9,
              backgroundColor: '#f2600c',
              alignItems: 'center', justifyContent: 'center',
            }}>
              <Text style={{ color: '#fff', fontWeight: '700', fontSize: 16 }}>S</Text>
            </View>
            <Text style={{ color: '#f2600c', fontWeight: '700', fontSize: 17, letterSpacing: -0.3 }}>
              SAMSBPM
            </Text>
          </View>

          {/* Heading */}
          <View style={{ marginBottom: 24 }}>
            <Text style={{ fontSize: 28, fontWeight: '300', color: '#14110c', marginBottom: 4 }}>
              {tab === 'login' ? 'Welcome back' : 'Get started'}
            </Text>
            <Text style={{ fontSize: 14, color: '#83786a' }}>
              {tab === 'login' ? 'Sign in to your trading dashboard' : 'Create your SAMSBPM account'}
            </Text>
          </View>

          {/* Card */}
          <View style={{
            backgroundColor: '#ffffff', borderRadius: 16,
            borderWidth: 1, borderColor: '#e7e2d8',
            padding: 20,
            shadowColor: '#000', shadowOffset: { width: 0, height: 1 },
            shadowOpacity: 0.05, shadowRadius: 4, elevation: 2,
          }}>
            {/* Tab switcher */}
            <View style={{
              flexDirection: 'row', backgroundColor: '#f5f2ed',
              borderRadius: 10, padding: 4, marginBottom: 24,
            }}>
              {(['login', 'register'] as const).map((t) => (
                <Pressable
                  key={t}
                  onPress={() => setTab(t)}
                  style={{
                    flex: 1, paddingVertical: 8, borderRadius: 8, alignItems: 'center',
                    backgroundColor: tab === t ? '#ffffff' : 'transparent',
                    shadowColor: tab === t ? '#000' : 'transparent',
                    shadowOffset: { width: 0, height: 1 },
                    shadowOpacity: tab === t ? 0.06 : 0,
                    shadowRadius: 2,
                    elevation: tab === t ? 1 : 0,
                  }}
                >
                  <Text style={{
                    fontSize: 13, fontWeight: '600',
                    color: tab === t ? '#14110c' : '#83786a',
                  }}>
                    {t === 'login' ? 'Sign In' : 'Register'}
                  </Text>
                </Pressable>
              ))}
            </View>

            {tab === 'login'
              ? <LoginForm onSuccess={onSuccess} />
              : <RegisterForm onSuccess={onSuccess} />}
          </View>

          {/* Switch link */}
          <View style={{ flexDirection: 'row', justifyContent: 'center', marginTop: 20 }}>
            <Text style={{ fontSize: 13, color: '#83786a' }}>
              {tab === 'login' ? "Don't have an account? " : 'Already have an account? '}
            </Text>
            <Pressable onPress={() => setTab(tab === 'login' ? 'register' : 'login')}>
              <Text style={{ fontSize: 13, color: '#f2600c', fontWeight: '600' }}>
                {tab === 'login' ? 'Register' : 'Sign in'}
              </Text>
            </Pressable>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  )
}
