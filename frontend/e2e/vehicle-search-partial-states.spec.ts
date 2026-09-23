import { expect, test, type Page, type Route } from '@playwright/test'

// Phase 7 Batch 7A — vehicle search, pagination and honest partial states.
//
// Most tests below are MOCKED browser tests: they intercept the listed
// /api/v1 GET calls with page.route() and return controlled, synthetic
// (SYN-*) responses, because >50 vehicles, >200 models and >200 open
// repairs cannot be produced from the shared seed data without editing
// it. They exercise the real page/CSS in each configured viewport, not the
// backend. The last test is an unmocked smoke case against the real mock
// backend started by playwright.config.ts.

const SEARCH_LABEL = 'ค้นหา (เลขเครื่องจักร หรือ รหัสยานพาหนะ)'

function syntheticVehicle(n: number, status = 'WORKING', modelId = 'SYN-MODEL-001') {
  const id = String(n).padStart(3, '0')
  return {
    vehicle_id: `SYN-VEH-${id}`,
    machine_no: `SYN-${id}`,
    model_id: modelId,
    serial_number: null,
    operational_status: status,
    created_at: '2026-01-15T08:00:00Z',
    updated_at: '2026-01-15T08:00:00Z',
  }
}

function syntheticModel(n: number) {
  const id = String(n).padStart(3, '0')
  return {
    model_id: `SYN-MODEL-${id}`,
    model_code: `SYN${id}`,
    model_name: `รุ่นทดสอบ ${id}`,
    brand: 'Synthetic',
    description: null,
    component_roles: ['CARRIER_ENGINE'],
    created_at: '2026-01-15T08:00:00Z',
    updated_at: '2026-01-15T08:00:00Z',
  }
}

function paginate<T>(items: T[], url: URL) {
  const page = Number(url.searchParams.get('page') ?? '1')
  const pageSize = Number(url.searchParams.get('page_size') ?? '20')
  const start = (page - 1) * pageSize
  return { items: items.slice(start, start + pageSize), page, page_size: pageSize, total_items: items.length }
}

const VEHICLES = Array.from({ length: 120 }, (_, i) =>
  syntheticVehicle(i + 1, i % 2 === 0 ? 'WORKING' : 'READY', i === 0 ? 'SYN-MODEL-230' : 'SYN-MODEL-001'),
)
const MODELS = Array.from({ length: 230 }, (_, i) => syntheticModel(i + 1))

interface MockOptions {
  failPm?: () => boolean
  vehicleDelayForQuery?: Record<string, number>
}

async function installMocks(page: Page, options: MockOptions = {}) {
  const apiRequests: { method: string; path: string }[] = []
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (url.pathname.startsWith('/api/')) {
      apiRequests.push({ method: request.method(), path: url.pathname })
    }
  })

  const fulfill = (route: Route, body: unknown, status = 200) =>
    route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })

  await page.route(/\/api\/v1\/vehicles(\?|$)/, async (route) => {
    const url = new URL(route.request().url())
    const q = (url.searchParams.get('q') ?? '').toLowerCase()
    const status = url.searchParams.get('status')
    const modelId = url.searchParams.get('model_id')
    const delay = options.vehicleDelayForQuery?.[q]
    if (delay) await new Promise((resolve) => setTimeout(resolve, delay))
    const filtered = VEHICLES.filter(
      (v) =>
        (!q || v.machine_no.toLowerCase().includes(q) || v.vehicle_id.toLowerCase().includes(q)) &&
        (!status || v.operational_status === status) &&
        (!modelId || v.model_id === modelId),
    )
    await fulfill(route, paginate(filtered, url))
  })
  await page.route(/\/api\/v1\/models(\?|$)/, async (route) => {
    await fulfill(route, paginate(MODELS, new URL(route.request().url())))
  })
  await page.route(/\/api\/v1\/repairs(\?|$)/, async (route) => {
    // 250 open repairs exist but only the first 200 fit in one page.
    const items = Array.from({ length: 200 }, (_, i) => ({
      repair_id: `SYN-REP-${i}`,
      asset_type: 'VEHICLE',
      asset_id: 'SYN-VEH-001',
      status: 'OPEN',
    }))
    await fulfill(route, { items, page: 1, page_size: 200, total_items: 250 })
  })
  await page.route(/\/api\/v1\/pm\/work-orders(\?|$)/, async (route) => {
    if (options.failPm?.()) {
      await fulfill(route, { error: { code: 'INTERNAL_ERROR', message: 'synthetic failure' } }, 500)
      return
    }
    await fulfill(route, {
      items: [{ pm_work_order_id: 'SYN-PM-1', asset_type: 'VEHICLE', asset_id: 'SYN-VEH-002' }],
      page: 1,
      page_size: 200,
      total_items: 1,
    })
  })
  await page.route(/\/api\/v1\/findings(\?|$)/, async (route) => {
    await fulfill(route, [{ finding_id: 'SYN-F-1', asset_type: 'VEHICLE', asset_id: 'SYN-VEH-001' }])
  })

  return apiRequests
}

async function expectNoHorizontalOverflow(page: Page) {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1)
}

test('[mocked] paginates, filters, loads more models and keeps controls usable', async ({ page }) => {
  const apiRequests = await installMocks(page)
  await page.goto('/vehicles')

  await expect(page.getByText('แสดงรายการที่ 1–50 จาก 120 คันที่ตรงกับเงื่อนไข')).toBeVisible()
  await expect(page.getByText('หน้า 1 จาก 3')).toBeVisible()
  await expect(page.getByRole('button', { name: 'ก่อนหน้า' })).toBeDisabled()
  await expectNoHorizontalOverflow(page)

  for (const name of ['ค้นหา', 'ถัดไป', 'โหลดรายการรุ่นเพิ่ม']) {
    const box = await page.getByRole('button', { name, exact: true }).boundingBox()
    expect(box?.height).toBeGreaterThanOrEqual(44)
  }

  await page.getByRole('button', { name: 'ถัดไป' }).click()
  await expect(page.getByText('แสดงรายการที่ 51–100 จาก 120 คันที่ตรงกับเงื่อนไข')).toBeVisible()
  await expect(page.getByRole('link', { name: 'SYN-VEH-051' })).toHaveAttribute(
    'href',
    '/vehicle/SYN-VEH-051',
  )

  // Status filter resets to page 1 and composes with the model filter.
  await page.getByLabel('สถานะ').selectOption('WORKING')
  await expect(page.getByText('แสดงรายการที่ 1–50 จาก 60 คันที่ตรงกับเงื่อนไข')).toBeVisible()

  await expect(page.getByText('โหลดรายการรุ่นแล้ว 200 จาก 230 รุ่น')).toBeVisible()
  await page.getByRole('button', { name: 'โหลดรายการรุ่นเพิ่ม' }).click()
  await expect(page.getByText('โหลดรายการรุ่นแล้ว 230 จาก 230 รุ่น')).toBeVisible()
  await page.getByLabel('รุ่น').selectOption('SYN-MODEL-230')
  await expect(page.getByText('แสดงรายการที่ 1–1 จาก 1 คันที่ตรงกับเงื่อนไข')).toBeVisible()
  await expect(page.getByLabel('รุ่น')).toHaveValue('SYN-MODEL-230')
  await expect(
    page.getByText('เงื่อนไขที่ใช้: สถานะ ใช้งานอยู่ · รุ่น รุ่นทดสอบ 230'),
  ).toBeVisible()

  await page.getByRole('link', { name: 'SYN-VEH-001' }).click()
  await expect(page).toHaveURL(/\/vehicle\/SYN-VEH-001$/)

  expect(apiRequests.every((r) => r.method === 'GET')).toBe(true)
})

test('[mocked] truncated and failed categories never show as zero; retry recovers', async ({
  page,
}) => {
  let pmFails = true
  const apiRequests = await installMocks(page, { failPm: () => pmFails })
  await page.goto('/vehicles')

  const row1 = page.locator('tr', { has: page.getByRole('link', { name: 'SYN-VEH-001', exact: true }) })
  await expect(row1.getByText('ยังไม่ทราบจำนวน: งานซ่อมที่เปิด, ใบงาน PM ที่เปิด')).toBeVisible()
  // The complete category (findings) stays useful.
  await expect(row1.getByRole('link', { name: 'ข้อบกพร่อง 1' })).toBeVisible()
  await expect(row1.getByText(/^ซ่อม \d+$/)).toHaveCount(0)
  await expect(page.getByText(/งานซ่อมที่เปิด: ข้อมูลยังไม่ครบ/)).toBeVisible()
  await expect(page.getByText('ใบงาน PM ที่เปิด: โหลดข้อมูลไม่สำเร็จ')).toBeVisible()
  await expect(page.getByText('ไม่พบงานซ่อม/ใบงาน PM ที่เปิด หรือข้อบกพร่องที่ค้าง')).toHaveCount(0)
  await expect(page.getByText('ไม่มีงานค้าง', { exact: true })).toHaveCount(0)
  await expectNoHorizontalOverflow(page)

  pmFails = false
  await page.getByRole('button', { name: 'ลองโหลดสรุปงานอีกครั้ง' }).click()
  const row2 = page.locator('tr', { has: page.getByRole('link', { name: 'SYN-VEH-002', exact: true }) })
  await expect(row2.getByRole('link', { name: 'ใบงาน PM 1' })).toHaveAttribute(
    'href',
    '/vehicle/SYN-VEH-002/pm',
  )
  // Repairs are still truncated, so they remain unknown after the retry.
  await expect(row2.getByText('ยังไม่ทราบจำนวน: งานซ่อมที่เปิด')).toBeVisible()

  // One call per endpoint per load; never one call per vehicle row.
  const perVehicleCalls = apiRequests.filter((r) => /\/vehicles\/SYN-VEH/.test(r.path))
  expect(perVehicleCalls).toHaveLength(0)
  expect(apiRequests.filter((r) => r.path === '/api/v1/repairs').length).toBeLessThanOrEqual(3)
  expect(apiRequests.every((r) => r.method === 'GET')).toBe(true)
})

test('[mocked] a slow older search cannot replace a newer result', async ({ page }) => {
  await installMocks(page, { vehicleDelayForQuery: { 'syn-01': 1500 } })
  await page.goto('/vehicles')
  await expect(page.getByText('แสดงรายการที่ 1–50 จาก 120 คันที่ตรงกับเงื่อนไข')).toBeVisible()

  const input = page.getByLabel(SEARCH_LABEL)
  await input.fill('SYN-01')
  await page.getByRole('button', { name: 'ค้นหา', exact: true }).click()
  await input.fill('SYN-020')
  await page.getByRole('button', { name: 'ค้นหา', exact: true }).click()
  await expect(page.getByText('แสดงรายการที่ 1–1 จาก 1 คันที่ตรงกับเงื่อนไข')).toBeVisible()

  // Wait past the slow response, then confirm the newer result stands.
  await page.waitForTimeout(1800)
  await expect(page.getByText('แสดงรายการที่ 1–1 จาก 1 คันที่ตรงกับเงื่อนไข')).toBeVisible()
  await expect(page.getByRole('link', { name: 'SYN-VEH-020' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'SYN-VEH-010' })).toHaveCount(0)
  await expect(page.getByText('เงื่อนไขที่ใช้: คำค้น “SYN-020”')).toBeVisible()
})

test('[unmocked smoke] navigate to the vehicle list from the menu and open a vehicle', async ({
  page,
}) => {
  const apiRequests: string[] = []
  page.on('request', (request) => {
    if (new URL(request.url()).pathname.startsWith('/api/')) apiRequests.push(request.method())
  })
  await page.goto('/')

  const toggle = page.getByRole('button', { name: 'เปิดเมนู' })
  if (await toggle.isVisible()) await toggle.click()
  await page.getByRole('link', { name: 'ยานพาหนะ', exact: true }).click()
  await expect(page).toHaveURL(/\/vehicles$/)

  await expect(page.getByText(/^แสดงรายการที่ 1–\d+ จาก \d+ คันที่ตรงกับเงื่อนไข$/)).toBeVisible()
  await expect(page.getByText('เงื่อนไขที่ใช้: ไม่มีตัวกรอง (แสดงรถทุกคันในรายการ)')).toBeVisible()
  await expect(page.getByText('ไม่มีงานค้าง', { exact: true })).toHaveCount(0)
  await expectNoHorizontalOverflow(page)

  const link = page.getByRole('link', { name: 'VEH-1046', exact: true })
  await expect(link).toHaveAttribute('href', '/vehicle/VEH-1046')
  await link.click()
  await expect(page).toHaveURL(/\/vehicle\/VEH-1046$/)
  expect(apiRequests.every((method) => method === 'GET')).toBe(true)
})
