import { type ChildProcess, spawn } from 'node:child_process'
import { createServer } from 'node:net'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'

// Phase 7 Batch 7O2d R1 — I-OC-01, literally (Outcome Classification
// Addendum): "a mocked 500 after a real mock-repository write shows the
// uncertainty banner, and the next history read settles it" — as ONE browser
// flow.
//
// Isolation: each test run starts its OWN application backend (the real
// FastAPI app with the real MockRepository, DATA_REPOSITORY=mock) as a separate
// process on a free port, so its in-memory repository is fresh and private.
// The browser's `/api/v1/**` calls are routed to that isolated backend with
// `route.fetch()`; the shared mock backend used by every other spec (and the
// other 4 viewport projects) is never written. No production code has a test
// hook: only the browser boundary is intercepted.
//
// The one mutation (PATCH registration) goes to the isolated backend for real
// (W1 history append + W2 master cells in its MockRepository). Only AFTER that
// real response arrives is it replaced, at the browser boundary, by a
// correlated 500 INTERNAL_ERROR. The next registration-history read (the
// client's own re-read after an uncertain outcome) is held at the browser
// boundary until the test has inspected the kept intent, then forwarded to the
// isolated backend; its real response is delivered unmodified.

const VID = 'VEH-1047' // synthetic: กข-1234 / TH-99, no registration history in a fresh repository
const UNKNOWN = 'ยังไม่ทราบผลการบันทึก — ระบบจะตรวจสอบจากประวัติ'
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
const BACKEND_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../backend')

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = createServer()
    server.once('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const address = server.address()
      const port = typeof address === 'object' && address ? address.port : 0
      server.close(() => resolve(port))
    })
  })
}

async function startIsolatedBackend(): Promise<{ base: string; process: ChildProcess }> {
  const port = await freePort()
  const child = spawn(
    path.join(BACKEND_DIR, '.venv/bin/python'),
    ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(port)],
    {
      cwd: BACKEND_DIR,
      env: { ...process.env, DATA_REPOSITORY: 'mock', DEV_AUTH_MODE: 'true', APP_ENV: 'development' },
      stdio: 'ignore',
    },
  )
  const base = `http://127.0.0.1:${port}`
  const deadline = Date.now() + 30_000
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${base}/api/v1/health`)
      if (response.ok) return { base, process: child }
    } catch {
      // not listening yet
    }
    await new Promise((resolve) => setTimeout(resolve, 200))
  }
  child.kill()
  throw new Error('isolated backend did not start')
}

test('I-OC-01: a mocked 500 after a real mock-repository write shows the uncertainty banner; the next real history read settles it', async ({
  page,
  request,
}) => {
  test.setTimeout(90_000)
  const isolated = await startIsolatedBackend()
  try {
    const me = await (await request.get(`${isolated.base}/api/v1/me`)).json()
    const storeKey = `crane.registryPending.v1:${me.user_id}:${VID}`
    const patches: { id: string; backendStatus: number; backendBody: Record<string, unknown> }[] = []
    const historyReads: { status: number; body: { consistency: string; items: { request_id: string }[] } }[] = []
    let releaseHistory!: () => void
    const historyGate = new Promise<void>((resolve) => {
      releaseHistory = resolve
    })
    let heldReads = 0
    // Every API call goes to the isolated backend.
    await page.route('**/api/v1/**', async (route) => {
      const url = new URL(route.request().url())
      const target = `${isolated.base}${url.pathname}${url.search}`
      const method = route.request().method()
      const isHistory = method === 'GET' && url.pathname === `/api/v1/vehicles/${VID}/registration-history`
      if (isHistory && patches.length > 0) {
        heldReads += 1
        await historyGate // the read after the 500 waits until the test has inspected the intent
      }
      const response = await route.fetch({ url: target })
      if (method === 'PATCH' && url.pathname === `/api/v1/vehicles/${VID}/registration`) {
        // the real write has completed in the isolated MockRepository; only now is the
        // browser shown a correlated 500 instead of the real response
        const id = route.request().headers()['x-request-id']
        patches.push({ id, backendStatus: response.status(), backendBody: await response.json() })
        await route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ error: { code: 'INTERNAL_ERROR', message: 'x', details: null, request_id: id } }),
        })
        return
      }
      if (isHistory) {
        historyReads.push({ status: response.status(), body: await response.json() })
      }
      await route.fulfill({ response }) // unmodified real response
    })

    await page.goto(`/vehicle/${VID}`)
    await expect(page.getByRole('heading', { name: 'TC-13' })).toBeVisible()
    const panel = page.getByTestId('registration-history-panel')
    await expect(panel.getByText('ยังไม่มีประวัติ', { exact: true })).toBeVisible() // fresh isolated repository
    await page.getByRole('button', { name: 'เปลี่ยนทะเบียน' }).click()
    const input = page.getByLabel('ทะเบียนรถ', { exact: true })
    await expect(input).toHaveValue('กข-1234')
    await input.fill('กข 7O2D')
    await page.getByLabel('จังหวัดที่จดทะเบียน').selectOption('')
    await page.getByRole('button', { name: 'บันทึกทะเบียน' }).click()

    // the browser saw a 500; the isolated backend really wrote
    const banner = page.getByTestId('registration-intent-banner')
    await expect(banner.getByText(UNKNOWN)).toBeVisible()
    expect(patches).toHaveLength(1)
    const sent = patches[0].id
    expect(sent).toMatch(UUID)
    expect(patches[0].backendStatus).toBe(200)
    expect(patches[0].backendBody).toMatchObject({ request_id: sent, changed: true, master_write: 'WRITTEN' })
    const history = await request.get(`${isolated.base}/api/v1/vehicles/${VID}/registration-history`)
    const recorded = await history.json()
    expect(recorded.items.map((i: { request_id: string }) => i.request_id)).toEqual([sent])
    expect(recorded.consistency).toBe('CONSISTENT')
    const vehicle = await (await request.get(`${isolated.base}/api/v1/vehicles/${VID}`)).json()
    expect(vehicle.vehicle.registry.registration_no).toEqual({ state: 'RECORDED', value: 'กข 7O2D' }) // master = history
    expect(vehicle.vehicle.registry.registration_province).toEqual({ state: 'NOT_RECORDED', value: null })
    expect(recorded.items[0]).toMatchObject({ new_registration_no: 'กข 7O2D', new_registration_province_code: null })

    // the intent is kept (UNKNOWN) and listed with its request id while the next read is pending
    await expect.poll(() => heldReads).toBeGreaterThan(0) // the client's own re-read after the 500
    await expect(banner).toContainText(sent)
    const stored = await page.evaluate((key) => window.localStorage.getItem(key), storeKey)
    expect(stored).toContain(sent)
    expect(JSON.parse(stored ?? '[]')).toMatchObject([{ request_id: sent, operation: 'registration', state: 'UNKNOWN' }])
    await expect(page.getByTestId('registration-settlement-notice')).toHaveCount(0)
    expect(patches).toHaveLength(1)

    // release the next history read: the isolated repository's real state, unmodified
    const readsBefore = historyReads.length
    releaseHistory()
    await expect(page.getByTestId('registration-intent-banner')).toHaveCount(0)
    const notice = page.getByTestId('registration-settlement-notice')
    await expect(notice).toContainText('ตรวจสอบจากประวัติแล้ว')
    await expect(notice).toContainText(sent)
    expect(historyReads.length).toBeGreaterThan(readsBefore)
    const settlingRead = historyReads[historyReads.length - 1]
    expect(settlingRead.status).toBe(200)
    expect(settlingRead.body.consistency).toBe('CONSISTENT')
    expect(settlingRead.body.items.map((i) => i.request_id)).toEqual([sent])
    const after = await page.evaluate((key) => window.localStorage.getItem(key), storeKey)
    expect(after === null || !after.includes(sent)).toBe(true)
    expect(patches).toHaveLength(1) // never resent automatically
    // the shared mock backend (through the app's own proxy) never saw this write
    const shared = await (await request.get(`/api/v1/vehicles/${VID}/registration-history`)).json()
    expect(shared.items.map((i: { request_id: string }) => i.request_id)).not.toContain(sent)
  } finally {
    isolated.process.kill()
  }
})
