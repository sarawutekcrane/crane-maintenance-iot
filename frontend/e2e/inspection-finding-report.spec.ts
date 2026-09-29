import { expect, test, type Page, type Route } from '@playwright/test'

// Phase 7 Batch 7E2 — recorded inspection findings report
// "รายงานข้อบกพร่องจากการตรวจเช็ค (ประวัติที่บันทึก)" (/reports/inspection-findings).
//
// [mocked] tests intercept GET /api/v1/reports/inspection-findings with
// page.route() and return SYNTHETIC responses: paging past 50 rows, partial
// data, all-unreadable data, schema errors and read failures cannot be
// produced from the shared mock seed data without editing it. They exercise
// the real page/CSS in every configured viewport, not the backend.
//
// [unmocked smoke] runs against the real mock backend started by
// playwright.config.ts: it submits its own FAIL inspection through the
// existing API (test setup only — a write), then asserts that the REPORT
// page itself sends only GET /me and GET /reports/inspection-findings, and
// that both links round-trip to the same ids on the existing destinations.
//
// [destination characterization] is kept separate: it records that the
// existing inspection/vehicle/equipment detail pages send no non-GET
// request on load. That is existing behavior, not a report guarantee.
//
// The browser runs in America/New_York so times are proven to be shown in
// Asia/Bangkok, not browser-local time.
test.use({ timezoneId: 'America/New_York' })

const REPORT = /\/api\/v1\/reports\/inspection-findings(\?|$)/
const REPORT_PATH = '/api/v1/reports/inspection-findings'
const MENU = 'ประวัติข้อบกพร่องที่บันทึกไว้'
const TITLE = 'รายงานข้อบกพร่องจากการตรวจเช็ค (ประวัติที่บันทึก)'
const RANGE = /^แสดงรายการที่ \d+–\d+ จาก \d+ รายการข้อบกพร่องที่บันทึกไว้$/
const SUPPRESSED = '(ลิงก์ใช้ไม่ได้: รหัสมีอักขระที่หน้าปลายทางยังรองรับไม่ได้)'

interface SynItem {
  finding_id: string
  inspection_id: string
  result_id: string
  asset_type: 'VEHICLE' | 'EQUIPMENT'
  asset_id: string
  item_title: string
  recorded_status: 'OPEN'
  created_at: string
  flags: string[]
}

function synItem(i: number, overrides: Partial<SynItem> = {}): SynItem {
  return {
    finding_id: `SYN-FND-${String(i).padStart(4, '0')}`,
    inspection_id: `SYN-INS-${i}`,
    result_id: `SYN-RES-${i}`,
    asset_type: 'VEHICLE',
    asset_id: `SYN-VEH-${i % 7}`,
    item_title: 'รายการตรวจสังเคราะห์',
    recorded_status: 'OPEN',
    created_at: '2026-09-28T02:10:00Z',
    flags: [],
    ...overrides,
  }
}

function body(all: SynItem[], url: URL, extra: Record<string, unknown> = {}) {
  const page = Number(url.searchParams.get('page') ?? '1')
  const pageSize = Number(url.searchParams.get('page_size') ?? '50')
  return {
    timezone: 'Asia/Bangkok',
    filter: {
      asset_type: url.searchParams.get('asset_type'),
      created_from: url.searchParams.get('created_from'),
      created_to: url.searchParams.get('created_to'),
    },
    items: all.slice((page - 1) * pageSize, page * pageSize),
    page,
    page_size: pageSize,
    total_items: all.length,
    complete: true,
    population: { read_record_count: all.length, readable_count: all.length, issue_row_count: 0 },
    data_issues: {
      issue_defect_counts: {},
      issue_defect_counts_are_occurrences: true,
      issue_rows_without_usable_id: 0,
      sample_finding_ids: [],
    },
    ...extra,
  }
}

const fulfill = (route: Route, payload: unknown, status = 200) =>
  route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(payload) })

function trackReport(page: Page) {
  const params: Record<string, string>[] = []
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (url.pathname === REPORT_PATH) params.push(Object.fromEntries(url.searchParams))
  })
  return params
}

function trackApi(page: Page) {
  const requests: { method: string; path: string }[] = []
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (url.pathname.startsWith('/api/')) requests.push({ method: request.method(), path: url.pathname })
  })
  return requests
}

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

const ITEMS = Array.from({ length: 120 }, (_, i) => synItem(i + 1))

test('[mocked] menu reaches the report; drafts send nothing, submit resets paging, times shown in Bangkok', async ({ page }) => {
  const params = trackReport(page)
  await page.route(REPORT, (route) => fulfill(route, body(ITEMS, new URL(route.request().url()))))
  await page.goto('/')
  await openMenuIfCollapsed(page)
  await page.getByRole('link', { name: MENU }).click()
  await expect(page).toHaveURL(/\/reports\/inspection-findings$/)
  await expect(page.getByRole('heading', { name: TITLE })).toBeVisible()
  await expect(page.getByText(/เป็นประวัติ ไม่ใช่รายการงานค้าง$/)).toBeVisible()

  expect(await page.evaluate(() => Intl.DateTimeFormat().resolvedOptions().timeZone)).toBe('America/New_York')
  await expect(page.getByText('แสดงรายการที่ 1–50 จาก 120 รายการข้อบกพร่องที่บันทึกไว้')).toBeVisible()
  const first = page.getByRole('row').filter({ hasText: 'SYN-FND-0001' })
  await expect(first.getByText('28 ก.ย. 2569 09:10')).toBeVisible() // Bangkok, not New York
  await expectNoHorizontalOverflow(page)

  const pager = page.getByRole('navigation', { name: 'เปลี่ยนหน้ารายงานข้อบกพร่อง' })
  await pager.getByRole('button', { name: 'ถัดไป' }).click()
  await expect(page.getByText('แสดงรายการที่ 51–100 จาก 120 รายการข้อบกพร่องที่บันทึกไว้')).toBeVisible()

  const before = params.length
  await page.getByLabel('ประเภททรัพย์สิน').selectOption('EQUIPMENT')
  await page.getByLabel('บันทึกตั้งแต่วันที่').fill('2026-01-01')
  await page.getByLabel('ถึงวันที่').fill('2026-12-31')
  expect(params.length).toBe(before) // editing drafts sends nothing

  await page.getByRole('button', { name: 'โหลดข้อมูลใหม่' }).click() // applied filters, not drafts
  await expect(page.getByText('แสดงรายการที่ 51–100 จาก 120 รายการข้อบกพร่องที่บันทึกไว้')).toBeVisible()
  await page.getByRole('button', { name: 'แสดงรายงาน' }).click()
  await expect(page.getByText('แสดงรายการที่ 1–50 จาก 120 รายการข้อบกพร่องที่บันทึกไว้')).toBeVisible()
  await expect(
    page.getByText('เงื่อนไข: ประเภททรัพย์สิน เครื่องมือ/อุปกรณ์ · วันที่บันทึก (เวลาไทย) ตั้งแต่ 1 ม.ค. 2569 ถึง 31 ธ.ค. 2569'),
  ).toBeVisible()
  await expectNoHorizontalOverflow(page)

  // Mount (dev StrictMode may send the first GET twice), then one GET per action.
  const mount = params.findIndex((p) => p.page === '2')
  expect(mount).toBeGreaterThanOrEqual(1)
  expect(mount).toBeLessThanOrEqual(2)
  expect(params.slice(0, mount)).toEqual(Array(mount).fill({ page: '1', page_size: '50' }))
  expect(params.slice(mount)).toEqual([
    { page: '2', page_size: '50' },
    { page: '2', page_size: '50' },
    { asset_type: 'EQUIPMENT', created_from: '2026-01-01', created_to: '2026-12-31', page: '1', page_size: '50' },
  ])
})

test('[mocked] partial, all-unreadable, empty and out-of-range states; link suppression without overflow', async ({ page }) => {
  const long = 'SYN-' + 'X'.repeat(160)
  const rows = [
    synItem(1, { asset_id: long, finding_id: long, item_title: long, flags: ['DUPLICATE_FINDING_ID'] }),
    synItem(2, { asset_id: 'EQP/0002', asset_type: 'EQUIPMENT', inspection_id: 'INS 0010' }),
    synItem(3, { inspection_id: '', finding_id: '', flags: ['BLANK_FINDING_ID', 'BLANK_INSPECTION_ID'] }),
  ]
  let scenario = 'partial'
  await page.route(REPORT, (route) => {
    const url = new URL(route.request().url())
    if (scenario === 'partial') {
      return fulfill(route, body(rows, url, {
        complete: false,
        population: { read_record_count: 7, readable_count: 3, issue_row_count: 4 },
        data_issues: {
          issue_defect_counts: { BLANK_STATUS: 2, UNREPRESENTABLE_CREATED_AT: 3 },
          issue_defect_counts_are_occurrences: true,
          issue_rows_without_usable_id: 1,
          sample_finding_ids: ['SYN-BAD-1'],
        },
      }))
    }
    if (scenario === 'all-unreadable') {
      return fulfill(route, body([], url, { complete: false, population: { read_record_count: 4, readable_count: 0, issue_row_count: 4 } }))
    }
    if (scenario === 'empty') return fulfill(route, body([], url))
    if (scenario === 'filtered-empty') {
      return fulfill(route, body([], url, { population: { read_record_count: 3, readable_count: 3, issue_row_count: 0 } }))
    }
    return fulfill(route, { ...body(rows, url), items: [], page: 9 })
  })
  await page.goto('/reports/inspection-findings')
  await expect(page.getByText('ข้อมูลไม่ครบ: มี 4 แถวที่อ่านไม่ได้ จึงไม่แสดงในรายงาน')).toBeVisible()
  await expect(page.getByText('ประเภทปัญหา (นับตามปัญหา ไม่ใช่จำนวนรายการ)')).toBeVisible()
  await expect(page.getByText('วันที่บันทึกอยู่นอกช่วงที่ระบบแสดงได้: 3')).toBeVisible()
  await expect(page.getByText(SUPPRESSED)).toHaveCount(2)
  await expect(page.getByRole('link', { name: 'ดูรายละเอียด' })).toHaveCount(2)
  await expect(page.getByRole('link', { name: 'ดูรายละเอียด' }).first()).toHaveAttribute('href', `/vehicle/${long}`)
  await expect(page.getByRole('link', { name: 'ดูผลการตรวจ' })).toHaveCount(1)
  await expectNoHorizontalOverflow(page)

  scenario = 'all-unreadable'
  await page.getByRole('button', { name: 'โหลดข้อมูลใหม่' }).click()
  await expect(page.getByText('ไม่พบรายการที่อ่านได้ตามเงื่อนไข แต่มี 4 แถวที่อ่านไม่ได้ ซึ่งอาจตรงเงื่อนไข')).toBeVisible()
  await expect(page.getByText('ยังไม่มีข้อบกพร่องที่บันทึกไว้')).toHaveCount(0)

  scenario = 'empty'
  await page.getByRole('button', { name: 'โหลดข้อมูลใหม่' }).click()
  await expect(page.getByText('ยังไม่มีข้อบกพร่องที่บันทึกไว้')).toBeVisible()
  await expect(page.getByText(/ข้อมูลไม่ครบ/)).toHaveCount(0)

  scenario = 'filtered-empty'
  await page.getByRole('button', { name: 'โหลดข้อมูลใหม่' }).click()
  await expect(page.getByText('ไม่พบข้อบกพร่องที่บันทึกไว้ตามเงื่อนไข')).toBeVisible()

  scenario = 'out-of-range'
  await page.getByRole('button', { name: 'โหลดข้อมูลใหม่' }).click()
  await expect(page.getByText('ไม่มีรายการในหน้านี้')).toBeVisible()
  scenario = 'partial'
  await page.getByRole('button', { name: 'กลับไปหน้าแรก' }).click()
  await expect(page.getByText(RANGE)).toBeVisible()
  await expectNoHorizontalOverflow(page)
})

test('[mocked] schema error, read failure retry and permission denied never show report data', async ({ page }) => {
  let status = 500
  await page.route(REPORT, (route) => {
    if (status === 200) return fulfill(route, body(ITEMS.slice(0, 2), new URL(route.request().url())))
    const code = status === 500 ? 'INSPECTION_FINDING_SCHEMA_INVALID' : status === 503 ? 'INSPECTION_FINDING_READ_FAILED' : 'HTTP_ERROR'
    return fulfill(route, { error: { code, message: 'synthetic', details: null, request_id: `req-${status}` } }, status)
  })
  await page.goto('/reports/inspection-findings')
  await expect(page.getByText('โครงสร้างตารางข้อบกพร่องไม่ถูกต้อง จึงแสดงรายงานไม่ได้')).toBeVisible()
  await expect(page.getByText(RANGE)).toHaveCount(0)
  await expect(page.getByText(/จำนวนที่ใช้ประกอบรายงาน/)).toHaveCount(0)

  status = 503
  await page.getByRole('button', { name: 'ลองใหม่อีกครั้ง' }).click()
  await expect(page.getByText('อ่านข้อมูลข้อบกพร่องไม่สำเร็จ กรุณาลองใหม่')).toBeVisible()
  status = 200
  await page.getByRole('button', { name: 'ลองใหม่อีกครั้ง' }).click()
  await expect(page.getByText('แสดงรายการที่ 1–2 จาก 2 รายการข้อบกพร่องที่บันทึกไว้')).toBeVisible()

  status = 403
  await page.getByRole('button', { name: 'โหลดข้อมูลใหม่' }).click()
  await expect(page.getByText('ไม่มีสิทธิ์ดูรายงานนี้')).toBeVisible()
  await expect(page.getByText(RANGE)).toHaveCount(0)
  await expect(page.locator('.responsive-table')).toHaveCount(0)
  await expectNoHorizontalOverflow(page)
})

test('[mocked] a slow older response cannot replace a newer refresh', async ({ page }) => {
  let mode: 'fast' | 'slow' | 'new' = 'fast'
  let releaseSlow: () => void = () => {}
  const slowGate = new Promise<void>((resolve) => {
    releaseSlow = resolve
  })
  await page.route(REPORT, async (route) => {
    const url = new URL(route.request().url())
    if (mode === 'slow') {
      mode = 'new' // only the first refresh is held back
      await slowGate
      return fulfill(route, body([synItem(999, { finding_id: 'SYN-STALE' })], url))
    }
    if (mode === 'new') return fulfill(route, body([synItem(1000, { finding_id: 'SYN-NEW' })], url))
    return fulfill(route, body(ITEMS.slice(0, 1), url))
  })
  await page.goto('/reports/inspection-findings')
  await expect(page.getByText('SYN-FND-0001')).toBeVisible()
  mode = 'slow'
  await page.getByRole('button', { name: 'โหลดข้อมูลใหม่' }).click() // older, held back
  await expect(page.getByText('SYN-FND-0001')).toHaveCount(0) // old data hidden while loading
  await page.getByRole('button', { name: 'โหลดข้อมูลใหม่' }).click() // newer
  await expect(page.getByText('SYN-NEW')).toBeVisible()
  releaseSlow()
  await page.waitForTimeout(300)
  await expect(page.getByText('SYN-STALE')).toHaveCount(0)
  await expect(page.getByText('SYN-NEW')).toBeVisible()
})

// ---------------------------------------------------------------------------
// Real mock backend (no interception). Other specs share the backend and run
// in parallel; the smoke locates its own finding by the id the API returned.
// ---------------------------------------------------------------------------

async function submitFailInspection(page: Page, assetType: 'VEHICLE' | 'EQUIPMENT', assetId: string) {
  const checklist = await page.request.get(`/api/v1/checklists/active?asset_type=${assetType}`)
  expect(checklist.ok()).toBe(true)
  const items = ((await checklist.json()).items as { item_id: string }[]).map((item, i) => ({
    item_id: item.item_id,
    result: i === 0 ? 'FAIL' : 'PASS',
  }))
  const response = await page.request.post('/api/v1/inspections', {
    data: { asset_type: assetType, asset_id: assetId, items },
  })
  expect(response.ok()).toBe(true)
  const detail = await response.json()
  return { inspectionId: detail.header.inspection_id as string, findingId: detail.findings[0].finding_id as string }
}

test('[unmocked smoke] the report page sends only report GETs and its links round-trip to the same ids', async ({ page }) => {
  const project = test.info().project.name
  const vehicle = await submitFailInspection(page, 'VEHICLE', 'VEH-1046')
  const equipment = await submitFailInspection(page, 'EQUIPMENT', 'EQP-0001')

  const requests = trackApi(page)
  await page.goto('/')
  await openMenuIfCollapsed(page)
  await page.getByRole('link', { name: MENU }).click()
  await expect(page.getByRole('heading', { name: TITLE })).toBeVisible()
  await expect(page.getByText(/^เงื่อนไข: ประเภททรัพย์สิน/)).toBeVisible()
  const meRequests = requests.filter((r) => r.path === '/api/v1/me').length
  const reportRequests = requests.filter((r) => r.path === REPORT_PATH).length
  const measured = `GET /me=${meRequests}; GET /reports/inspection-findings=${reportRequests}`
  test.info().annotations.push({ type: 'request-count', description: measured })
  console.log(`[7E2 request-count ${project}] ${measured}`)
  expect(reportRequests).toBeGreaterThanOrEqual(1)
  expect(reportRequests).toBeLessThanOrEqual(2)

  // Newest first: the just-created rows are on page 1 (fewer than 50 newer
  // findings are created by the parallel specs).
  const vehicleRow = page.getByRole('row').filter({ hasText: vehicle.findingId }).first()
  await expect(vehicleRow).toBeVisible()
  await expect(vehicleRow.getByText(vehicle.inspectionId, { exact: true })).toBeVisible()
  await expect(vehicleRow.getByText('OPEN (ค่าที่บันทึก)')).toBeVisible()
  await expectNoHorizontalOverflow(page)

  // Report-only assertion: the page itself sent GETs to /me and the report only.
  expect(requests.every((r) => r.method === 'GET')).toBe(true)
  expect(requests.every((r) => r.path === '/api/v1/me' || r.path === REPORT_PATH)).toBe(true)

  await vehicleRow.getByRole('link', { name: 'ดูผลการตรวจ' }).click()
  await expect(page).toHaveURL(new RegExp(`/inspections/${vehicle.inspectionId}$`))
  await expect(page.getByRole('heading', { name: 'ผลการตรวจเช็ค' })).toBeVisible()
  await expect(page.getByText(`รหัสผลการตรวจ: ${vehicle.inspectionId}`)).toBeVisible()
  await page.goBack()
  const again = page.getByRole('row').filter({ hasText: vehicle.findingId }).first()
  await again.getByRole('link', { name: 'ดูรายละเอียด' }).click()
  await expect(page).toHaveURL(/\/vehicle\/VEH-1046$/)

  await page.goto('/reports/inspection-findings')
  await page.getByLabel('ประเภททรัพย์สิน').selectOption('EQUIPMENT')
  await page.getByRole('button', { name: 'แสดงรายงาน' }).click()
  const equipmentRow = page.getByRole('row').filter({ hasText: equipment.findingId }).first()
  await expect(equipmentRow).toBeVisible()
  await equipmentRow.getByRole('link', { name: 'ดูรายละเอียด' }).click()
  await expect(page).toHaveURL(/\/equipment\/EQP-0001$/)
})

test('[destination characterization] existing inspection, vehicle and equipment detail pages send no non-GET request on load', async ({ page }) => {
  const { inspectionId } = await submitFailInspection(page, 'VEHICLE', 'VEH-1047')
  const requests = trackApi(page)
  await page.goto(`/inspections/${inspectionId}`)
  await expect(page.getByText(`รหัสผลการตรวจ: ${inspectionId}`)).toBeVisible()
  await page.goto('/vehicle/VEH-1047')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await page.goto('/equipment/EQP-0001')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await page.waitForLoadState('networkidle')
  expect(requests.length).toBeGreaterThan(0)
  expect(requests.filter((r) => r.method !== 'GET')).toEqual([])
})
