import { randomUUID } from 'node:crypto'
import { expect, test, type APIRequestContext, type Browser, type Page } from '@playwright/test'

// R8 early workstream (Owner source approval 2026-11-18) — Crew Assignment Extension and
// Resource Calendar. Synthetic Mock/TEST data only (TEST vehicle VEH-1048, TEST driver
// DRV-TEST-901, synthetic TEST personnel). Writes run once, on the desktop project, on dates
// far in the future so they cannot collide with other specs' E2 data. Not production or
// PostgreSQL evidence.

const AM_E2E = process.env.ACCESS_MANAGEMENT_E2E === '1'

function bangkokDate(offsetDays: number): string {
  const ms = Date.now() + 7 * 3_600_000 + offsetDays * 86_400_000
  return new Date(ms).toISOString().slice(0, 10)
}

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(1)
}

async function open(browser: Browser, baseURL: string | undefined, headers: Record<string, string>) {
  const context = await browser.newContext({ baseURL, extraHTTPHeaders: headers })
  return context.newPage()
}

test.describe('legacy development-role backend', () => {
  test.skip(AM_E2E, 'runs against the legacy development-role backend')

  test('@r8 the month calendar renders 42 day cells and a day opens its detail', async ({ page }) => {
    await page.goto(`/resource-calendar?date=${bangkokDate(0)}`)
    await expect(page.getByRole('heading', { name: 'ปฏิทินทรัพยากร' })).toBeVisible()
    await expect(page.locator('.calendar-day')).toHaveCount(42)
    await page.locator('.calendar-day').nth(10).click()
    await expect(page.getByRole('heading', { name: /^รายละเอียด / })).toBeVisible()
    await expectNoHorizontalOverflow(page)
    await page.getByRole('button', { name: 'ตามบุคลากร' }).click()
    await expect(page).toHaveURL(/view=PERSONNEL/)
    await page.getByRole('button', { name: 'สัปดาห์' }).click()
    await expect(page.locator('.calendar-day')).toHaveCount(7)
  })

  test('@r8 a can_view-only reader is refused the fleet calendar (OD-7) by URL too', async ({ browser, baseURL }) => {
    const page = await open(browser, baseURL, { 'X-Dev-Role': 'DRIVER', 'X-Dev-User-Id': 'USR-R8-DRIVER' })
    await page.goto('/resource-calendar')
    await expect(page.getByText('ไม่มีสิทธิ์เข้าถึง', { exact: true })).toBeVisible()
    await expect(page.locator('.calendar-day')).toHaveCount(0)
    const api = await page.request.get(`/api/v1/resource-calendar?from=${bangkokDate(0)}&to=${bangkokDate(1)}`)
    expect(api.status()).toBe(403)
    await page.context().close()
  })

  test('@r8 @mutation an E2 driver day appears on the calendar with its own interval', async ({ page, request }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'writes run once, on the desktop project')
    const day = bangkokDate(300)
    const created = await request.post('/api/v1/vehicles/VEH-1048/operational-driver-assignment-operations', {
      headers: { 'X-Request-Id': randomUUID() },
      data: { operation: 'CREATE', driver_id: 'DRV-TEST-901', mode: 'FULL_DAY', start_date: day, end_date: day },
    })
    expect(created.ok(), await created.text()).toBe(true)
    await page.goto(`/resource-calendar?scale=DAY&date=${day}`)
    await expect(page.getByText(/ผู้ขับทดสอบ หนึ่ง.*· คนขับ/)).toBeVisible()
    await expect(page.getByText('00:00 – 24:00').first()).toBeVisible()
    // The legacy ADMIN never holds the crew TEST grant: the crew panel is read-only.
    await page.goto('/vehicle/VEH-1048')
    await expect(page.getByRole('heading', { name: 'ทีมงานประจำเครน (Crew)' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'เพิ่มทีมงาน' })).toHaveCount(0)
    const refused = await request.post('/api/v1/vehicles/VEH-1048/crew-assignment-operations', {
      headers: { 'X-Request-Id': randomUUID() },
      data: { operation: 'CREATE', personnel_id: 'PER-TEST-911', crew_role: 'RIGGER', mode: 'FULL_DAY',
        start_date: day, end_date: day },
    })
    expect(refused.status()).toBe(403)
  })
})

// Access Management mode backend (ACCESS_MANAGEMENT_E2E=1 … --workers=1): every permission
// comes from a REAL root grant through the audited API.
test.describe('Access Management crew workflow (real audited grants)', () => {
  test.skip(!AM_E2E, 'needs the Access Management mode backend (ACCESS_MANAGEMENT_E2E=1)')

  const as = (user: string) => ({ 'X-Dev-Role': 'TECHNICIAN', 'X-Dev-User-Id': user })
  const MGR = as('USR-TEST-AM-MGR')
  const CLERK = as('USR-TEST-AM-CLERK')

  async function grantTo(request: APIRequestContext, personnelId: string, changes: Record<string, boolean>) {
    const revision = (await (await request.get('/api/v1/access/me', { headers: MGR })).json()).revision as number
    const response = await request.post('/api/v1/access/grants', {
      headers: { ...MGR, 'X-Request-Id': randomUUID() },
      data: { target: { kind: 'EMPLOYEE', personnel_id: personnelId }, changes, reason_th: 'R8 E2E',
        expected_revision: revision },
    })
    expect(response.ok(), await response.text()).toBe(true)
  }

  test('@r8 @mutation a granted employee adds a crew member; overlap is refused; the calendar shows it', async ({
    browser, baseURL, request,
  }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'writes run once, on the desktop project')
    const day = bangkokDate(310)
    await grantTo(request, 'PER-TEST-AM-CLERK', { can_view: true, can_assign_crane_crew: true })
    const page = await open(browser, baseURL, CLERK)
    await page.goto('/vehicle/VEH-1048')
    await page.getByRole('button', { name: 'เพิ่มทีมงาน' }).click()
    await expect(page.locator('#crew-personnel option')).not.toHaveCount(1)
    await page.locator('#crew-personnel').selectOption('PER-TEST-912')
    await page.locator('#crew-role').selectOption('SIGNALMAN')
    await page.locator('#crew-start').fill(day)
    await page.locator('#crew-end').fill(day)
    await page.getByRole('button', { name: 'บันทึก' }).click()
    await expect(page.getByText(/^บันทึกแล้ว/)).toBeVisible()
    await expect(page.locator('.crew-panel__item').filter({ hasText: 'Signalman' }).first()).toBeVisible()

    const overlap = await page.request.post('/api/v1/vehicles/VEH-1048/crew-assignment-operations', {
      headers: { ...CLERK, 'X-Request-Id': randomUUID() },
      data: { operation: 'CREATE', personnel_id: 'PER-TEST-912', crew_role: 'RIGGER', mode: 'FULL_DAY',
        start_date: day, end_date: day },
    })
    expect(overlap.status()).toBe(409)
    expect((await overlap.json()).error.code).toBe('RESOURCE_CONFLICT')

    await page.goto(`/resource-calendar?scale=DAY&date=${day}`)
    await expect(page.getByText(/· Signalman/)).toBeVisible()
    await expectNoHorizontalOverflow(page)
    await page.context().close()
  })
})
