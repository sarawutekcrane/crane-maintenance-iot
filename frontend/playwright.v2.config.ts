import { defineConfig } from '@playwright/test'

/**
 * R2 Batch R2f-h4 B4 — the DEDICATED Technician V2 mock E2E (C1 Amendment
 * A1-§31, owner decision O4). Separate from the unchanged baseline suite
 * (`playwright.config.ts`, ports 4310/4311, cutover OFF).
 *
 * Two isolated pairs of processes, each started by this config and stopped by
 * Playwright at the end of the run (never reused, so a stray server with a
 * different setting cannot be picked up):
 *
 * - ON : backend 4321 (mock repository, DEV auth, development env,
 *        TECHNICIAN_ASSIGNMENT_V2_ENABLED=true — this process only) +
 *        frontend 4320 proxying /api to it;
 * - OFF: backend 4331 (same, the V2 setting left at its default OFF) +
 *        frontend 4330.
 *
 * The real frontend talks to the running mock backend; route stubs are used
 * only for error injection (A1-§31). No live Google Sheets access: the backend
 * runs with DATA_REPOSITORY=mock and the synthetic TEST fixtures.
 *
 * Run: npx playwright test -c playwright.v2.config.ts
 */
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_PATH ?? '/opt/pw-browsers/chromium'

export const ON_FRONTEND_PORT = 4320
export const ON_BACKEND_PORT = 4321
export const OFF_FRONTEND_PORT = 4330
export const OFF_BACKEND_PORT = 4331

const MOCK_ENV = 'DATA_REPOSITORY=mock DEV_AUTH_MODE=true APP_ENV=development'

function backend(port: number, extraEnv: string) {
  return {
    command: `bash -c "cd ../backend && source .venv/bin/activate && env -u TECHNICIAN_ASSIGNMENT_V2_ENABLED ${MOCK_ENV} ${extraEnv} uvicorn app.main:app --host 127.0.0.1 --port ${port}"`,
    url: `http://127.0.0.1:${port}/api/v1/health`,
    reuseExistingServer: false,
    timeout: 120_000,
  }
}

function frontend(port: number, backendPort: number) {
  return {
    command: `npm run dev -- --host 127.0.0.1 --port ${port} --strictPort`,
    url: `http://127.0.0.1:${port}/`,
    reuseExistingServer: false,
    timeout: 60_000,
    env: { BACKEND_PORT: String(backendPort), FRONTEND_PORT: String(port) },
  }
}

const launchOptions = { executablePath, args: ['--no-sandbox'] }
const mobile = {
  isMobile: true,
  hasTouch: true,
  deviceScaleFactor: 2,
}

export default defineConfig({
  testDir: './e2e-v2',
  fullyParallel: true,
  retries: 0,
  reporter: [['list']],
  use: { launchOptions },
  projects: [
    {
      name: 'v2-on-desktop',
      testMatch: /v2-on\.spec\.ts/,
      use: { baseURL: `http://127.0.0.1:${ON_FRONTEND_PORT}`, viewport: { width: 1280, height: 800 } },
    },
    {
      name: 'v2-on-tablet',
      testMatch: /v2-on\.spec\.ts/,
      use: { baseURL: `http://127.0.0.1:${ON_FRONTEND_PORT}`, viewport: { width: 768, height: 1024 }, ...mobile },
    },
    {
      name: 'v2-on-mobile',
      testMatch: /v2-on\.spec\.ts/,
      use: {
        baseURL: `http://127.0.0.1:${ON_FRONTEND_PORT}`,
        viewport: { width: 375, height: 667 },
        ...mobile,
        userAgent:
          'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36',
      },
    },
    {
      name: 'v2-off-desktop',
      testMatch: /v2-off\.spec\.ts/,
      use: { baseURL: `http://127.0.0.1:${OFF_FRONTEND_PORT}`, viewport: { width: 1280, height: 800 } },
    },
    {
      name: 'v2-off-mobile',
      testMatch: /v2-off\.spec\.ts/,
      use: { baseURL: `http://127.0.0.1:${OFF_FRONTEND_PORT}`, viewport: { width: 375, height: 667 }, ...mobile },
    },
  ],
  webServer: [
    backend(ON_BACKEND_PORT, 'TECHNICIAN_ASSIGNMENT_V2_ENABLED=true'),
    frontend(ON_FRONTEND_PORT, ON_BACKEND_PORT),
    backend(OFF_BACKEND_PORT, ''),
    frontend(OFF_FRONTEND_PORT, OFF_BACKEND_PORT),
  ],
})
