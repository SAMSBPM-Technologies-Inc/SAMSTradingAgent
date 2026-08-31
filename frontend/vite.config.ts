import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  // `loadEnv` rather than `process.env`: the dev target belongs in the same
  // gitignored `.env.local` as `VITE_API_BASE_URL`, and only the config reads
  // it — it is deliberately not `VITE_`-prefixed, so it can never be inlined
  // into a client bundle.
  //
  // The env dir is '.' and not `process.cwd()` on purpose. This file is part of
  // the `tsc -b` that gates `npm run build`, `@types/node` is not a dependency,
  // and a bare `process` there is a type error — so that spelling builds fine
  // under the dev server, which does not typecheck, and fails the deploy.
  const env = loadEnv(mode, '.', '')

  return {
    plugins: [react()],
    base: '/',
    build: {
      rollupOptions: {
        output: {
          manualChunks: {
            // React runtime — changes rarely, long cache lifetime
            'vendor-react': ['react', 'react-dom', 'react-router-dom'],
            // Icons — large but stable
            'vendor-icons': ['lucide-react'],
          },
        },
      },
    },
    server: {
      proxy: {
        /**
         * Dev only, and the default is unchanged: a local backend on :8000.
         *
         * `DEV_API_TARGET` points it at a deployed API instead — set it, set
         * `VITE_API_BASE_URL=/api`, and the browser talks only to the dev
         * server, so the deployed CORS allow-list never sees a localhost
         * origin and does not need to be widened to include one. That matters
         * here: `CORS_ORIGINS` in production is one entry, the real site, and
         * adding localhost to a live trading API to look at a layout would be
         * a bad trade.
         *
         * Note what this does *not* buy you: the app is fully live against
         * whatever it points at. Placing an order through it places a real
         * order.
         */
        '/api': {
          target: env.DEV_API_TARGET || 'http://localhost:8000',
          changeOrigin: true,
          secure: true,
          rewrite: (path) => path.replace(/^\/api/, ''),
        },
      },
    },
  }
})
