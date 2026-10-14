import { defineConfig } from '@playwright/test'

// This environment pre-installs Chromium and disables the Playwright
// browser download step; point directly at that binary instead of
// letting Playwright try to fetch a matching revision.
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_PATH ?? '/opt/pw-browsers/chromium'

const FRONTEND_PORT = 4310
const BACKEND_PORT = 4311
// R2 Batch R2f-h4 B5: the isolated cutover-OFF pair (technician-v2-off.spec.ts only).
const OFF_FRONTEND_PORT = 4330
const OFF_BACKEND_PORT = 4331
const MOCK_ENV = 'DATA_REPOSITORY=mock DEV_AUTH_MODE=true APP_ENV=development'
const OFF_SPEC = /technician-v2-off\.spec\.ts/
// R2 Batch R2f-h4 B5 responsive fix: the photo-field overflow matrix sets its own five
// viewports per test, so it runs once, in its own project.
const PHOTO_RESPONSIVE_SPEC = /photo-attachment-responsive\.spec\.ts/

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  retries: 0,
  reporter: [['list']],
  // The OFF spec runs only in its own projects, against the OFF pair.
  testIgnore: [OFF_SPEC, PHOTO_RESPONSIVE_SPEC],
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
      // Exercises the `min-width: 481px` "smartphone landscape" breakpoint
      // band documented in docs/architecture/RESPONSIVE_UI.md, which no
      // other project's width falls into (smartphone-portrait is 375px,
      // tablet-portrait jumps straight to 768px).
      name: 'smartphone-landscape',
      use: {
        viewport: { width: 568, height: 320 },
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
      // Exercises the `min-width: 1024px` "tablet landscape / small
      // desktop" breakpoint band, which no other project's width falls
      // into (tablet-portrait is 768px, desktop jumps to 1280px).
      name: 'tablet-landscape',
      use: {
        viewport: { width: 1024, height: 768 },
        isMobile: true,
        hasTouch: true,
        deviceScaleFactor: 2,
      },
    },
    {
      name: 'desktop',
      use: { viewport: { width: 1280, height: 800 } },
    },
    {
      name: 'responsive-photo',
      testIgnore: [],
      testMatch: PHOTO_RESPONSIVE_SPEC,
      use: { viewport: { width: 1280, height: 800 } },
    },
    {
      name: 'cutover-off-desktop',
      testIgnore: [],
      testMatch: OFF_SPEC,
      use: { baseURL: `http://127.0.0.1:${OFF_FRONTEND_PORT}`, viewport: { width: 1280, height: 800 } },
    },
    {
      name: 'cutover-off-smartphone',
      testIgnore: [],
      testMatch: OFF_SPEC,
      use: {
        baseURL: `http://127.0.0.1:${OFF_FRONTEND_PORT}`,
        viewport: { width: 375, height: 667 },
        isMobile: true,
        hasTouch: true,
        deviceScaleFactor: 2,
      },
    },
  ],
  webServer: [
    {
      // R2 Batch R2f-h4 B5 (A1-§26 O4 / §31): the main suite's DEDICATED mock TEST
      // backend runs with TECHNICIAN_ASSIGNMENT_V2_ENABLED=true — the supported
      // workflow after the navigation cutover. Mock repository + DEV auth only; this
      // process is the only place the setting is ON (never staging / production).
      command: `bash -c "cd ../backend && python3 -m venv .venv >/dev/null 2>&1; source .venv/bin/activate && pip install --quiet -r requirements.txt && env -u TECHNICIAN_ASSIGNMENT_V2_ENABLED ${MOCK_ENV} TECHNICIAN_ASSIGNMENT_V2_ENABLED=true uvicorn app.main:app --host 127.0.0.1 --port ${BACKEND_PORT}"`,
      url: `http://127.0.0.1:${BACKEND_PORT}/api/v1/health`,
      // Never reuse a server already listening: it could run with a different V2 setting.
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${FRONTEND_PORT} --strictPort`,
      url: `http://127.0.0.1:${FRONTEND_PORT}/`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        BACKEND_PORT: String(BACKEND_PORT),
        FRONTEND_PORT: String(FRONTEND_PORT),
      },
    },
    {
      // The isolated cutover-OFF pair (the V2 setting explicitly unset → its
      // default OFF), used only by technician-v2-off.spec.ts.
      command: `bash -c "cd ../backend && source .venv/bin/activate && env -u TECHNICIAN_ASSIGNMENT_V2_ENABLED ${MOCK_ENV} uvicorn app.main:app --host 127.0.0.1 --port ${OFF_BACKEND_PORT}"`,
      url: `http://127.0.0.1:${OFF_BACKEND_PORT}/api/v1/health`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${OFF_FRONTEND_PORT} --strictPort`,
      url: `http://127.0.0.1:${OFF_FRONTEND_PORT}/`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        BACKEND_PORT: String(OFF_BACKEND_PORT),
        FRONTEND_PORT: String(OFF_FRONTEND_PORT),
      },
    },
  ],
})
