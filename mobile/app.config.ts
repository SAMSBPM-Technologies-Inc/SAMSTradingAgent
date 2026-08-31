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
    // The web client's origin, which is where password recovery lives. The
    // reset link in the email points at the web app, so sending someone there
    // to start the flow keeps one implementation rather than two — and the one
    // that exists is the one the email will land on.
    webBaseUrl: process.env.EXPO_PUBLIC_WEB_BASE_URL ?? 'https://sta.samsbpm.com',
    eas: { projectId: '' },
  },
})
