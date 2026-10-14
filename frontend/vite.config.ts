import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Local development: frontend dev server proxies /api to the local backend
// so the browser never needs to know the backend's host/port directly.
// Frozen in Phase 1 (see docs/architecture/API_CONVENTIONS.md).
const backendPort = Number(process.env.BACKEND_PORT ?? 8000)
const frontendPort = Number(process.env.FRONTEND_PORT ?? 5173)

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: frontendPort,
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${backendPort}`,
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
    // e2e/ holds Playwright specs (real-browser viewport tests), run via
    // `npm run test:e2e`, not Vitest. e2e-v2/ holds the dedicated Technician V2
    // mock E2E (R2 Batch R2f-h4 B4), run via `playwright.v2.config.ts`.
    exclude: ['e2e/**', 'e2e-v2/**', 'node_modules/**'],
  },
})
