import { expect, test, type Page } from '@playwright/test'

// R8 Whole-Phase (Owner source approval 2026-11-18) — dashboard drill-through (R8-01),
// URL-backed filtered list and back navigation (R8-02), vehicle summary from the guarded
// owner reads (R8-03 / R8-04), "not live" location (R8-05), the S5 open-alert filter and
// the part-lifetime-due report (R8-09). Runs against the legacy development-role mock
// backend (synthetic data only); every viewport project runs it (read-only).

const AM_E2E = process.env.ACCESS_MANAGEMENT_E2E === '1'
test.skip(AM_E2E, 'runs against the legacy development-role backend')

const STATUS_LABELS: [string, string][] = [
  ['WORKING', 'ใช้งานอยู่'],
  ['READY', 'พร้อมใช้งาน'],
  ['MAINTENANCE', 'ซ่อมบำรุง'],
  ['OUT_OF_SERVICE', 'หยุดใช้งาน'],
  ['LONG_TERM_PARKING', 'จอดระยะยาว'],
]

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(1)
}

function trackApi(page: Page) {
  const paths: string[] = []
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (url.pathname.startsWith('/api/')) paths.push(`${request.method()} ${url.pathname}${url.search}`)
  })
  return paths
}

test('@r8 a dashboard card opens its filtered list, a vehicle, and back to the same list', async ({ page }) => {
  await page.goto('/dashboard')
  await expect(page.locator('.fleet-status__card--total')).toBeVisible()
  // Pick a status whose card shows at least one vehicle (other specs may change statuses).
  let chosen: [string, string] | null = null
  for (const [code, label] of STATUS_LABELS) {
    const card = page.locator('.fleet-status__card').filter({ has: page.getByText(label, { exact: true }) })
    const count = Number((await card.locator('.fleet-status__count').innerText()).replace(' คัน', ''))
    if (count > 0) {
      chosen = [code, label]
      await card.getByRole('link').click()
      break
    }
  }
  expect(chosen).not.toBeNull()
  const [code] = chosen!
  await expect(page).toHaveURL(new RegExp(`/vehicles\\?status=${code}$`))
  await expect(page.locator('#vehicle-search-status')).toHaveValue(code)
  await expectNoHorizontalOverflow(page)

  const requests = trackApi(page)
  const firstVehicle = page.locator('table a[href^="/vehicle/"], .responsive-table a[href^="/vehicle/"]').first()
  const vehicleId = (await firstVehicle.innerText()).trim()
  await firstVehicle.click()
  await expect(page).toHaveURL(new RegExp(`/vehicle/${vehicleId}$`))
  await expect(page.getByRole('heading', { name: 'สรุปข้อมูลรถ' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'ทีมงานประจำเครน (Crew)' })).toBeVisible()
  await expect(page.getByText(/รอเชื่อมต่ออุปกรณ์ \(Phase 8\)/)).toBeVisible()
  await expect(
    page.getByText(/ตำแหน่งที่บันทึกล่าสุด ไม่ใช่ตำแหน่งสด|ยังไม่มีข้อมูลตำแหน่ง GPS/).first(),
  ).toBeVisible()
  await expectNoHorizontalOverflow(page)
  // The summary never calls the write-on-read certificate list or the ungated machine-state route.
  await expect.poll(() => requests.some((r) => r.includes('/machine-state'))).toBe(true)
  expect(requests.some((r) => r.includes(`/vehicles/${vehicleId}/certificates`))).toBe(false)
  expect(requests.some((r) => r.includes('/machine-state/current'))).toBe(false)

  await page.getByRole('link', { name: 'กลับไปรายการที่กรองไว้' }).click()
  await expect(page).toHaveURL(new RegExp(`/vehicles\\?status=${code}$`))
  await expect(page.locator('#vehicle-search-status')).toHaveValue(code)
})

test('@r8 the open-alert filter is sent and kept in the URL (S5)', async ({ page }) => {
  const requests = trackApi(page)
  await page.goto('/vehicles')
  const box = page.getByLabel(/เฉพาะรถที่มีการแจ้งเตือนที่ยังเปิดอยู่/)
  await box.check()
  await expect(page).toHaveURL(/has_open_alert=true/)
  await expect.poll(() => requests.some((r) => r.startsWith('GET /api/v1/vehicles?') && r.includes('has_open_alert=true'))).toBe(true)
  await expect(page.getByText(/มีการแจ้งเตือนที่ยังเปิดอยู่/).first()).toBeVisible()
  await expectNoHorizontalOverflow(page)
})

test('@r8 the part-lifetime-due report discloses out-of-scope vehicles and loads read-only', async ({ page }) => {
  const requests = trackApi(page)
  await page.goto('/reports/part-lifetime-due')
  await expect(page.getByRole('heading', { name: 'อายุอะไหล่ถึงกำหนด (ทั้งกองรถ)' })).toBeVisible()
  await expect(page.getByText(/ไม่ได้ประเมิน \d+ คัน/)).toBeVisible()
  await expectNoHorizontalOverflow(page)
  expect(requests.every((r) => r.startsWith('GET '))).toBe(true)
})
