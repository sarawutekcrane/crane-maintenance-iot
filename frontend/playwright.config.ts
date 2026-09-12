import { defineConfig } from '@playwright/test'

// This environment pre-installs Chromium and disables the Playwright
// browser download step; point directly at that binary instead of
// letting Playwright try to fetch a matching revision.
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_PATH ?? '/opt/pw-browsers/chromium'

const FRONTEND_PORT = 4310
const BACKEND_PORT = 4311

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${FRONTEND_PORT}`,
    // This environment runs as root, where Chromium's sandbox cannot
    // initialize; --no-sandbox is required purely for that reason (not a
    // production concern — no untrusted content is loaded).
    launchOptions: { executablePath, args: ['--no-sandbox'] },
  },
  // Only Chromium is pre-installed in this environment (no WebKit/Firefox),
  // so mobile/tablet viewports are emulated on Chromium directly rather
  // than via the WebKit-only `devices['iPhone SE']` / `devices['iPad Mini']`
  // presets. This still exercises the same CSS breakpoints and touch/mobile
  // input handling (isMobile/hasTouch), which is what these tests check.
  projects: [
    {
      name: 'smartphone-portrait',
      use: {
        viewport: { width: 375, height: 667 },
        isMobile: true,
        hasTouch: true,
        deviceScaleFactor: 2,
        userAgent:
          'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36',
      },
    },
    {
      name: 'tablet-portrait',
      use: {
        viewport: { width: 768, height: 1024 },
        isMobile: true,
        hasTouch: true,
        deviceScaleFactor: 2,
      },
    },
    {
      name: 'desktop',
      use: { viewport: { width: 1280, height: 800 } },
    },
  ],
  webServer: [
    {
      command: `bash -c "cd ../backend && python3 -m venv .venv >/dev/null 2>&1; source .venv/bin/activate && pip install --quiet -r requirements.txt && DATA_REPOSITORY=mock DEV_AUTH_MODE=true APP_ENV=development uvicorn app.main:app --host 127.0.0.1 --port ${BACKEND_PORT}"`,
      url: `http://127.0.0.1:${BACKEND_PORT}/api/v1/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${FRONTEND_PORT}`,
      url: `http://127.0.0.1:${FRONTEND_PORT}/`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: {
        BACKEND_PORT: String(BACKEND_PORT),
        FRONTEND_PORT: String(FRONTEND_PORT),
      },
    },
  ],
})
