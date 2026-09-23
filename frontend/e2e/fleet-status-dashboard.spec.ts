import { expect, test, type Page, type Route } from '@playwright/test'

// Phase 7 Batch 7B2 — fleet status dashboard (/dashboard).
//
// The [mocked] tests intercept GET /api/v1/dashboard/fleet-status with
// page.route() and return synthetic responses, because data-quality,
// schema and read failures cannot be produced from the shared mock seed
// data without editing it. They exercise the real page/CSS in every
// configured viewport, not the backend. The [unmocked smoke] test runs
// against the real mock backend started by playwright.config.ts.

const SUMMARY = /\/api\/v1\/dashboard\/fleet-status(\?|$)/

function summary(counts: Record<string, number>) {
  return {
    population: 'VEHICLE_MASTER_VALIDATED_RECORDS',
    vehicle_total: Object.values(counts).reduce((a, b) => a + b, 0),
    status_counts: counts,
  }
}

const SYN_COUNTS = { WORKING: 12, READY: 5, MAINTENANCE: 3, OUT_OF_SERVICE: 2, LONG_TERM_PARKING: 1 }
const STATUS_LABELS: [string, string][] = [
  ['WORKING', 'ใช้งานอยู่'],
  ['READY', 'พร้อมใช้งาน'],
  ['MAINTENANCE', 'ซ่อมบำรุง'],
  ['OUT_OF_SERVICE', 'หยุดใช้งาน'],
  ['LONG_TERM_PARKING', 'จอดระยะยาว'],
]

function trackApi(page: Page) {
  const requests: { method: string; path: string }[] = []
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (url.pathname.startsWith('/api/')) requests.push({ method: request.method(), path: url.pathname })
  })
  return requests
}

const fulfill = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })

async function expectNoHorizontalOverflow(page: Page) {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1)
}

async function openMenuIfCollapsed(page: Page) {
  const toggle = page.getByRole('button', { name: 'เปิดเมนู' })
  if (await toggle.isVisible()) await toggle.click()
}

function statusCard(page: Page, label: string) {
  return page.locator('.fleet-status__card').filter({ has: page.getByText(label, { exact: true }) })
}

test('[mocked] menu reaches the dashboard, success renders Thai cards without overflow', async ({ page }) => {
  const requests = trackApi(page)
  await page.route(SUMMARY, (route) => fulfill(route, summary(SYN_COUNTS)))
  await page.goto('/')

  await openMenuIfCollapsed(page)
  await page.getByRole('link', { name: 'ภาพรวมกองรถ' }).click()
  await expect(page).toHaveURL(/\/dashboard$/)
  await expect(page.getByRole('heading', { name: 'ภาพรวมกองรถ' })).toBeVisible()

  const total = page.locator('.fleet-status__card--total')
  await expect(total.getByText('รถในทะเบียนทั้งหมด')).toBeVisible()
  await expect(total.getByText('23 คัน')).toBeVisible()
  for (const [code, label] of STATUS_LABELS) {
    await expect(statusCard(page, label).getByText(`${SYN_COUNTS[code as keyof typeof SYN_COUNTS]} คัน`)).toBeVisible()
  }
  await expect(page.getByText(/หน้านี้แสดงเฉพาะจำนวนรถตามสถานะที่บันทึกไว้ในทะเบียนรถ/)).toBeVisible()

  // Exactly one page link (the plain unfiltered list); status cards are not links.
  const pageLinks = page.locator('.page a')
  await expect(pageLinks).toHaveCount(1)
  await expect(pageLinks).toHaveText('ดูรายการรถทั้งหมด (ไม่กรองสถานะ)')
  await expect(pageLinks).toHaveAttribute('href', '/vehicles')

  // Responsive grid: 1 column on phones, 2 from 641px, 3 from 1024px.
  const width = page.viewportSize()?.width ?? 0
  const columns = await page
    .locator('.fleet-status__grid')
    .evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(' ').length)
  expect(columns).toBe(width >= 1024 ? 3 : width >= 641 ? 2 : 1)
  await expectNoHorizontalOverflow(page)

  const refresh = page.getByRole('button', { name: 'โหลดข้อมูลใหม่' })
  const box = await refresh.boundingBox()
  expect(box?.height).toBeGreaterThanOrEqual(44)

  expect(requests.every((r) => r.method === 'GET')).toBe(true)
  expect(requests.some((r) => /^\/api\/v1\/vehicles\//.test(r.path))).toBe(false)
})

test('[mocked] data-quality and read failures show Thai errors without numbers, retry recovers', async ({
  page,
}) => {
  // Phase-driven (not call-counted): the dev server runs React StrictMode,
  // so the mount effect may issue the initial GET twice.
  let phase: 'data' | 'read' | 'ok' = 'data'
  await page.route(SUMMARY, async (route) => {
    if (phase === 'data') {
      await fulfill(
        route,
        {
          error: {
            code: 'VEHICLE_MASTER_DATA_INVALID',
            message: 'synthetic',
            details: { issue_counts: { BLANK_STATUS: 1 }, sample_vehicle_ids: ['SYN-1'] },
            request_id: 'req-e2e-data',
          },
        },
        500,
      )
    } else if (phase === 'read') {
      await fulfill(route, { error: { code: 'VEHICLE_MASTER_READ_FAILED', message: 'synthetic', request_id: 'req-e2e-read' } }, 503)
    } else {
      await fulfill(route, summary(SYN_COUNTS))
    }
  })
  await page.goto('/dashboard')

  const alert = page.getByRole('alert')
  await expect(alert.getByText('ไม่แสดงตัวเลขสรุป')).toBeVisible()
  await expect(alert.getByText(/ข้อมูลทะเบียนรถบางรายการไม่ครบหรือไม่ถูกต้อง/)).toBeVisible()
  await expect(alert.getByText('รหัสอ้างอิง: req-e2e-data')).toBeVisible()
  await expect(page.getByText(/\d+ คัน$/)).toHaveCount(0)
  await expectNoHorizontalOverflow(page)

  phase = 'read'
  await page.getByRole('button', { name: 'ลองใหม่อีกครั้ง' }).click()
  await expect(alert.getByText('โหลดภาพรวมกองรถไม่สำเร็จ')).toBeVisible()
  await expect(alert.getByText(/ไม่สามารถอ่านข้อมูลทะเบียนรถได้ในขณะนี้/)).toBeVisible()
  await expect(alert.getByText('รหัสอ้างอิง: req-e2e-read')).toBeVisible()
  await expect(page.getByText(/\d+ คัน$/)).toHaveCount(0)

  phase = 'ok'
  await page.getByRole('button', { name: 'โหลดข้อมูลใหม่' }).click()
  await expect(page.locator('.fleet-status__card--total').getByText('23 คัน')).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('[mocked] schema failure and permission denied never show numbers', async ({ page }) => {
  let denied = false
  await page.route(SUMMARY, async (route) => {
    if (denied) {
      await fulfill(route, { error: { code: 'HTTP_ERROR', message: 'denied', request_id: 'req-403' } }, 403)
    } else {
      await fulfill(
        route,
        {
          error: {
            code: 'VEHICLE_MASTER_SCHEMA_INVALID',
            message: 'synthetic',
            details: { tab: 'vehicle_master', problem: 'MISSING_HEADERS', headers: ['operational_status'] },
            request_id: 'req-e2e-schema',
          },
        },
        500,
      )
    }
  })
  await page.goto('/dashboard')
  await expect(page.getByRole('alert').getByText(/โครงสร้างตารางทะเบียนรถไม่ตรงกับที่ระบบรองรับ/)).toBeVisible()
  await expect(page.getByText(/\d+ คัน$/)).toHaveCount(0)

  denied = true
  await page.getByRole('button', { name: 'โหลดข้อมูลใหม่' }).click()
  await expect(page.getByText('ไม่มีสิทธิ์เข้าถึง', { exact: true })).toBeVisible()
  await expect(page.getByText(/\d+ คัน$/)).toHaveCount(0)
  await expectNoHorizontalOverflow(page)
})

test('[mocked] a slow older response cannot replace a newer refresh', async ({ page }) => {
  // Every mount request (StrictMode may send two) is slow and carries
  // different numbers; the refresh pressed meanwhile is fast.
  let slow = true
  await page.route(SUMMARY, async (route) => {
    if (slow) {
      await new Promise((resolve) => setTimeout(resolve, 1500))
      await fulfill(route, summary({ ...SYN_COUNTS, WORKING: 90 }))
    } else {
      await fulfill(route, summary(SYN_COUNTS))
    }
  })
  await page.goto('/dashboard')
  await expect(page.getByText('กำลังโหลดภาพรวมกองรถ...')).toBeVisible()
  slow = false
  await page.getByRole('button', { name: 'โหลดข้อมูลใหม่' }).click()
  await expect(page.locator('.fleet-status__card--total').getByText('23 คัน')).toBeVisible()

  await page.waitForTimeout(1800)
  await expect(page.locator('.fleet-status__card--total').getByText('23 คัน')).toBeVisible()
  await expect(page.getByText('101 คัน')).toHaveCount(0)
})

test('[unmocked smoke] dashboard totals agree with the vehicle list against the mock backend', async ({
  page,
}) => {
  const requests = trackApi(page)
  await page.goto('/')
  await openMenuIfCollapsed(page)
  await page.getByRole('link', { name: 'ภาพรวมกองรถ' }).click()
  await expect(page).toHaveURL(/\/dashboard$/)
  await expect(page.locator('.fleet-status__card--total')).toBeVisible()
  await expectNoHorizontalOverflow(page)

  // Shell GET /me and the page's own summary GETs are reported separately;
  // the dev server's StrictMode may repeat the mount effect (<= 2 GETs).
  const meRequests = requests.filter((r) => r.path === '/api/v1/me').length
  const summaryRequests = requests.filter((r) => r.path === '/api/v1/dashboard/fleet-status').length
  test.info().annotations.push({ type: 'request-count', description: `GET /me=${meRequests}; GET /dashboard/fleet-status=${summaryRequests}` })
  expect(requests.every((r) => r.path === '/api/v1/me' || r.path === '/api/v1/dashboard/fleet-status')).toBe(true)
  expect(summaryRequests).toBeGreaterThanOrEqual(1)
  expect(summaryRequests).toBeLessThanOrEqual(2)

  // Other specs may change a seed vehicle's status concurrently on the
  // shared mock backend, so compare a fresh dashboard read with the list
  // and retry the whole comparison if the data moved in between.
  await expect(async () => {
    await page.goto('/dashboard')
    const readCount = async (locator: ReturnType<Page['locator']>) =>
      Number((await locator.locator('.fleet-status__count').innerText()).replace(' คัน', ''))
    const total = await readCount(page.locator('.fleet-status__card--total'))
    const byStatus: Record<string, number> = {}
    for (const [code, label] of STATUS_LABELS) byStatus[code] = await readCount(statusCard(page, label))
    expect(total).toBe(Object.values(byStatus).reduce((a, b) => a + b, 0))

    await page.getByRole('link', { name: 'ดูรายการรถทั้งหมด (ไม่กรองสถานะ)' }).click()
    await expect(page).toHaveURL(/\/vehicles$/)
    await expect(page.getByText(`แสดงรายการที่ 1–${Math.min(total, 50)} จาก ${total} คันที่ตรงกับเงื่อนไข`)).toBeVisible({ timeout: 5000 })
    for (const [code] of STATUS_LABELS) {
      await page.getByLabel('สถานะ').selectOption(code)
      if (byStatus[code] === 0) {
        await expect(page.getByText('ไม่พบยานพาหนะ')).toBeVisible({ timeout: 5000 })
      } else {
        await expect(
          page.getByText(`แสดงรายการที่ 1–${Math.min(byStatus[code], 50)} จาก ${byStatus[code]} คันที่ตรงกับเงื่อนไข`),
        ).toBeVisible({ timeout: 5000 })
      }
    }
  }).toPass({ timeout: 60_000 })

  expect(requests.every((r) => r.method === 'GET')).toBe(true)
})
