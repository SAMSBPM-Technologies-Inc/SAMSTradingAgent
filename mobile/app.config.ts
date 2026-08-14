import type { ExpoConfig, ConfigContext } from 'expo/config'

export default ({ config }: ConfigContext): ExpoConfig => ({
  ...config,
  name: 'SAMSBPM Trading',
  slug: 'samsbpm-trading',
  scheme: 'samsbpm',
  version: '1.0.0',
  orientation: 'portrait',
  icon: './assets/icon.png',
  userInterfaceStyle: 'automatic',
  splash: {
    image: './assets/splash.png',
    resizeMode: 'contain',
    backgroundColor: '#f5f2ed',
  },
  ios: {
    supportsTablet: false,
    bundleIdentifier: 'com.samsbpm.trading',
  },
  android: {
    adaptiveIcon: {
      foregroundImage: './assets/adaptive-icon.png',
      backgroundColor: '#f2600c',
    },
    package: 'com.samsbpm.trading',
  },
  plugins: [
    'expo-router',
    'expo-secure-store',
    ['expo-system-ui', { userInterfaceStyle: 'automatic' }],
  ],
  experiments: {
    typedRoutes: true,
  },
  extra: {
    // Set EXPO_PUBLIC_API_BASE_URL in your .env file
    apiBaseUrl: process.env.EXPO_PUBLIC_API_BASE_URL ?? 'http://localhost:8000',
    eas: { projectId: '' },
  },
})
