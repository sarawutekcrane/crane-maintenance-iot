import { expect, test, type Page, type Route } from '@playwright/test'

// Phase 7 Batch 7D2 — certificate expiry report "รายงานใบรับรองตามวันหมดอายุ"
// (/reports/certificate-expiry).
//
// [mocked] tests intercept GET /api/v1/reports/certificate-expiry with
// page.route() and return SYNTHETIC responses (SYN-* ids): paging past 50
// rows, partial data, schema errors and read failures cannot be produced
// from the shared mock seed data without editing it. They exercise the real
// page/CSS in every configured viewport, not the backend.
//
// [unmocked smoke] runs against the real mock backend started by
// playwright.config.ts: it creates its own certificates through the
// existing API (test setup only), then asserts that the REPORT page itself
// sends only GET /me and GET /reports/certificate-expiry.
//
// [destination characterization] is kept separate: it records that the
// EXISTING per-vehicle certificate page (a link target of the report) may
// write EXPIRED on read. That is existing behavior, not the report's.
//
// The browser runs in America/New_York so calendar dates are proven not to
// shift a day west of UTC.
test.use({ timezoneId: 'America/New_York' })

const REPORT = /\/api\/v1\/reports\/certificate-expiry(\?|$)/
const REPORT_PATH = '/api/v1/reports/certificate-expiry'
const RANGE = /^แสดงรายการที่ \d+–\d+ จาก \d+ รายการใบรับรอง$/
const MENU = 'ใบรับรองตามวันหมดอายุ'
const TITLE = 'รายงานใบรับรองตามวันหมดอายุ'

interface SynItem {
  certificate_id: string
  vehicle_id: string
  certificate_type_code: string | null
  certificate_type_name_th: string | null
  document_no: string | null
  expiry_date: string | null
  stored_status: 'ACTIVE' | 'EXPIRED'
  effective_status: 'ACTIVE' | 'EXPIRED'
  expiry_position: string
  flags: string[]
}

function synItem(i: number, overrides: Partial<SynItem> = {}): SynItem {
  return {
    certificate_id: `SYN-CERT-${String(i).padStart(4, '0')}`,
    vehicle_id: `SYN-VEH-${i % 7}`,
    certificate_type_code: 'SYN-TYPE-A',
    certificate_type_name_th: 'ใบอนุญาตสังเคราะห์',
    document_no: `00${i}`,
    expiry_date: '2026-03-10',
    stored_status: 'ACTIVE',
    effective_status: 'ACTIVE',
    expiry_position: 'TODAY',
    flags: [],
    ...overrides,
  }
}

const POPULATION = {
  read_record_count: 0,
  in_scope_count: 0,
  in_scope_with_expiry_date_count: 0,
  in_scope_without_expiry_date_count: 0,
  excluded_replaced_count: 0,
  excluded_status_blank_count: 0,
  issue_row_count: 0,
  excluded_rows_with_other_defects: 0,
  replaced_link_observations: 0,
}

function body(all: SynItem[], url: URL, extra: Record<string, unknown> = {}) {
  const page = Number(url.searchParams.get('page') ?? '1')
  const pageSize = Number(url.searchParams.get('page_size') ?? '50')
  const mode = url.searchParams.get('mode') ?? 'RANGE'
  const to = url.searchParams.get('expiry_to')
  return {
    as_of_date: '2026-03-10',
    timezone: 'Asia/Bangkok',
    filter: {
      mode,
      expiry_from: mode === 'RANGE' ? url.searchParams.get('expiry_from') : null,
      expiry_to_requested: mode === 'RANGE' ? to : null,
      expiry_to_resolved: mode === 'RANGE' ? (to ?? '2026-03-10') : null,
      expiry_to_is_default: mode === 'RANGE' && to === null,
      effective_status: url.searchParams.get('effective_status'),
    },
    items: all.slice((page - 1) * pageSize, page * pageSize),
    page,
    page_size: pageSize,
    total_items: all.length,
    complete: true,
    population: { ...POPULATION, read_record_count: all.length, in_scope_count: all.length, in_scope_with_expiry_date_count: all.length },
    data_issues: {
      issue_defect_counts: {},
      issue_defect_counts_are_occurrences: true,
      issue_rows_without_usable_id: 0,
      sample_certificate_ids: [],
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

test('[mocked] menu reaches the report; drafts send nothing, submit resets paging, New York dates do not shift', async ({ page }) => {
  const params = trackReport(page)
  await page.route(REPORT, (route) => fulfill(route, body(ITEMS, new URL(route.request().url()))))
  await page.goto('/')
  await openMenuIfCollapsed(page)
  await page.getByRole('link', { name: MENU }).click()
  await expect(page).toHaveURL(/\/reports\/certificate-expiry$/)
  await expect(page.getByRole('heading', { name: TITLE })).toBeVisible()
  await expect(page.getByText('นับเป็นรายการใบรับรอง (1 แถว = 1 ใบรับรอง) ไม่ใช่จำนวนรถ')).toBeVisible()

  expect(await page.evaluate(() => Intl.DateTimeFormat().resolvedOptions().timeZone)).toBe('America/New_York')
  await expect(page.getByText('ข้อมูล ณ วันที่ 10 มี.ค. 2569 (เวลาประเทศไทย)')).toBeVisible()
  await expect(page.getByText('แสดงรายการที่ 1–50 จาก 120 รายการใบรับรอง')).toBeVisible()
  await expect(page.getByRole('row').filter({ hasText: 'SYN-CERT-0001' }).getByText('10 มี.ค. 2569')).toBeVisible()
  await expectNoHorizontalOverflow(page)

  const pager = page.getByRole('navigation', { name: 'เปลี่ยนหน้ารายงานใบรับรอง' })
  await pager.getByRole('button', { name: 'ถัดไป' }).click()
  await expect(page.getByText('แสดงรายการที่ 51–100 จาก 120 รายการใบรับรอง')).toBeVisible()

  const before = params.length
  await page.getByLabel('วันหมดอายุตั้งแต่').fill('2026-01-01')
  await page.getByLabel('สถานะที่คำนวณ').selectOption('EXPIRED')
  await page.getByRole('radio', { name: 'ใบรับรองที่ไม่มีวันหมดอายุในระบบ' }).check()
  await page.getByRole('radio', { name: 'ตามช่วงวันหมดอายุ' }).check()
  expect(params.length).toBe(before) // editing drafts sends nothing

  await page.getByRole('button', { name: 'โหลดข้อมูลใหม่' }).click() // applied filters, not drafts
  await expect(page.getByText('แสดงรายการที่ 51–100 จาก 120 รายการใบรับรอง')).toBeVisible()
  await page.getByRole('button', { name: 'แสดงรายงาน' }).click()
  await expect(page.getByText('แสดงรายการที่ 1–50 จาก 120 รายการใบรับรอง')).toBeVisible()
  await expect(page.getByLabel('วันหมดอายุถึง')).toHaveValue('') // resolved end is never copied
  await expectNoHorizontalOverflow(page)

  // Mount (dev StrictMode may send the first GET twice), then one GET per action.
  const mount = params.findIndex((p) => p.page === '2')
  expect(mount).toBeGreaterThanOrEqual(1)
  expect(mount).toBeLessThanOrEqual(2)
  expect(params.slice(0, mount)).toEqual(Array(mount).fill({ mode: 'RANGE', page: '1', page_size: '50' }))
  expect(params.slice(mount)).toEqual([
    { mode: 'RANGE', page: '2', page_size: '50' },
    { mode: 'RANGE', page: '2', page_size: '50' },
    { mode: 'RANGE', expiry_from: '2026-01-01', effective_status: 'EXPIRED', page: '1', page_size: '50' },
  ])
})

test('[mocked] partial and empty states, out-of-range, link suppression and long values without overflow', async ({ page }) => {
  const long = 'SYN-' + 'X'.repeat(160)
  const rows = [
    synItem(1, { vehicle_id: long, certificate_id: long, document_no: long, flags: ['DUPLICATE_CERTIFICATE_ID', 'STORED_ACTIVE_PAST_EXPIRY'] }),
    synItem(2, { vehicle_id: 'รถ 1/ก' }),
    synItem(3, { vehicle_id: 'SYN-VEH-3\n' }),
  ]
  let scenario = 'partial'
  await page.route(REPORT, (route) => {
    const url = new URL(route.request().url())
    if (scenario === 'partial') {
      return fulfill(route, body(rows, url, {
        complete: false,
        population: { ...POPULATION, read_record_count: 7, in_scope_count: 3, in_scope_with_expiry_date_count: 3, issue_row_count: 4 },
        data_issues: {
          issue_defect_counts: { UNRECOGNIZED_STATUS: 3, UNMAPPABLE_ROW: 2 },
          issue_defect_counts_are_occurrences: true,
          issue_rows_without_usable_id: 1,
          sample_certificate_ids: ['SYN-BAD-1'],
        },
      }))
    }
    if (scenario === 'partial-empty') {
      return fulfill(route, body([], url, { complete: false, population: { ...POPULATION, read_record_count: 4, issue_row_count: 4 } }))
    }
    if (scenario === 'empty') return fulfill(route, body([], url))
    return fulfill(route, { ...body(rows, url), items: [], page: 9 })
  })
  await page.goto('/reports/certificate-expiry')
  await expect(page.getByText(/^มีข้อมูลใบรับรอง 4 รายการที่ระบบอ่านสถานะ วันหมดอายุ หรือข้อมูลอื่นไม่ได้/)).toBeVisible()
  await expect(page.getByText('ประเภทปัญหา (นับตามปัญหา ไม่ใช่จำนวนรายการ)')).toBeVisible()
  const suppressed = page.getByText('(ลิงก์ใช้ไม่ได้: รหัสมีอักขระที่หน้าปลายทางยังรองรับไม่ได้)')
  await expect(suppressed).toHaveCount(2)
  await expect(page.getByRole('link', { name: 'ดูใบรับรองของรถคันนี้' })).toHaveCount(1)
  await expect(page.getByRole('link', { name: 'ดูรายละเอียดรถ' })).toHaveAttribute('href', `/vehicle/${long}`)
  await expectNoHorizontalOverflow(page)

  scenario = 'partial-empty'
  await page.getByRole('button', { name: 'โหลดข้อมูลใหม่' }).click()
  await expect(
    page.getByText('ไม่พบรายการที่ตรงเงื่อนไขในข้อมูลที่อ่านได้ แต่มีข้อมูล 4 รายการที่อ่านไม่ได้และอาจตรงเงื่อนไข จึงยืนยันไม่ได้ว่าไม่มีรายการ'),
  ).toBeVisible()

  scenario = 'empty'
  await page.getByRole('button', { name: 'โหลดข้อมูลใหม่' }).click()
  await expect(page.getByText('ไม่มีใบรับรองที่วันหมดอายุอยู่ในช่วงที่เลือก', { exact: true })).toBeVisible()
  await expect(page.getByText(/รายงานอาจไม่ครบ/)).toHaveCount(0)

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
    const code = status === 500 ? 'VEHICLE_CERTIFICATE_SCHEMA_INVALID' : status === 503 ? 'VEHICLE_CERTIFICATE_READ_FAILED' : 'HTTP_ERROR'
    return fulfill(route, { error: { code, message: 'synthetic', details: null, request_id: `req-${status}` } }, status)
  })
  await page.goto('/reports/certificate-expiry')
  await expect(page.getByText('โครงสร้างข้อมูลใบรับรองไม่ถูกต้อง จึงไม่แสดงรายงานเพื่อป้องกันผลที่คลาดเคลื่อน กรุณาแจ้งผู้ดูแลระบบ')).toBeVisible()
  await expect(page.getByText(RANGE)).toHaveCount(0)
  await expect(page.getByText(/ข้อมูล ณ วันที่/)).toHaveCount(0)

  status = 503
  await page.getByRole('button', { name: 'ลองใหม่อีกครั้ง' }).click()
  await expect(page.getByText('ไม่สามารถอ่านข้อมูลใบรับรองได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง')).toBeVisible()
  status = 200
  await page.getByRole('button', { name: 'ลองใหม่อีกครั้ง' }).click()
  await expect(page.getByText('แสดงรายการที่ 1–2 จาก 2 รายการใบรับรอง')).toBeVisible()

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
      return fulfill(route, body([synItem(999, { certificate_id: 'SYN-STALE' })], url, { as_of_date: '2020-01-01' }))
    }
    if (mode === 'new') {
      return fulfill(route, body([synItem(1000, { certificate_id: 'SYN-NEW' })], url, { as_of_date: '2026-03-12' }))
    }
    return fulfill(route, body(ITEMS.slice(0, 1), url))
  })
  await page.goto('/reports/certificate-expiry')
  await expect(page.getByText('SYN-CERT-0001')).toBeVisible()
  mode = 'slow'
  await page.getByRole('button', { name: 'โหลดข้อมูลใหม่' }).click() // older, held back
  await expect(page.getByText('SYN-CERT-0001')).toHaveCount(0) // old data hidden while loading
  await page.getByRole('button', { name: 'โหลดข้อมูลใหม่' }).click() // newer
  await expect(page.getByText('SYN-NEW')).toBeVisible()
  releaseSlow()
  await page.waitForTimeout(300)
  await expect(page.getByText('SYN-STALE')).toHaveCount(0)
  await expect(page.getByText('ข้อมูล ณ วันที่ 12 มี.ค. 2569 (เวลาประเทศไทย)')).toBeVisible()
})

// ---------------------------------------------------------------------------
// Real mock backend (no interception). Other specs share the backend and run
// in parallel, so every created record carries a per-project unique tag.
// ---------------------------------------------------------------------------

async function createCertificate(page: Page, vehicleId: string, tag: string, expiry: string, status: 'ACTIVE' | 'EXPIRED') {
  const response = await page.request.post(`/api/v1/vehicles/${vehicleId}/certificates`, {
    data: {
      certificate_type_code: tag,
      certificate_type_name_th: 'ใบรับรองทดสอบ e2e 7D2',
      document_no: tag,
      expiry_date: expiry,
      certificate_status: status,
    },
  })
  expect(response.ok()).toBe(true)
  return (await response.json()).certificate_id as string
}

async function applyRange(page: Page, from: string, to: string) {
  await page.getByLabel('วันหมดอายุตั้งแต่').fill(from)
  await page.getByLabel('วันหมดอายุถึง').fill(to)
  await page.getByRole('button', { name: 'แสดงรายงาน' }).click()
}

test('[unmocked smoke] the report page sends only report GETs and shows created certificates', async ({ page }) => {
  const project = test.info().project.name
  const tag = `E2E7D2-${project}-${Date.now()}`
  const future = await createCertificate(page, 'VEH-1046', `${tag}-F`, '2091-01-15', 'ACTIVE')

  const requests = trackApi(page)
  await page.goto('/')
  await openMenuIfCollapsed(page)
  await page.getByRole('link', { name: MENU }).click()
  await expect(page.getByRole('heading', { name: TITLE })).toBeVisible()
  await expect(page.getByText(/^ข้อมูล ณ วันที่ /)).toBeVisible()
  const meRequests = requests.filter((r) => r.path === '/api/v1/me').length
  const reportRequests = requests.filter((r) => r.path === REPORT_PATH).length
  const measured = `GET /me=${meRequests}; GET /reports/certificate-expiry=${reportRequests}`
  test.info().annotations.push({ type: 'request-count', description: measured })
  console.log(`[7D2 request-count ${project}] ${measured}`)
  expect(reportRequests).toBeGreaterThanOrEqual(1)
  expect(reportRequests).toBeLessThanOrEqual(2)

  await applyRange(page, '2091-01-15', '2091-01-15')
  const row = page.getByRole('row').filter({ hasText: `${tag}-F` }).first()
  await expect(row).toBeVisible()
  await expect(row.getByText(future, { exact: true })).toBeVisible()
  await expect(row.getByText('15 ม.ค. 2634')).toBeVisible() // 2091 CE = 2634 BE, no day shift in New York
  await expect(row.getByRole('link', { name: 'ดูรายละเอียดรถ' })).toHaveAttribute('href', '/vehicle/VEH-1046')
  await expectNoHorizontalOverflow(page)

  // A stale ACTIVE certificate is REPORTED as computed EXPIRED while its
  // stored status stays ACTIVE. Parallel projects creating ACTIVE
  // certificates on the same vehicle reconcile it through the EXISTING
  // create path, so retry with a fresh record if that happened in between.
  await expect(async () => {
    const stale = `${tag}-S-${Date.now()}`
    await createCertificate(page, 'VEH-1048', stale, '2001-02-03', 'ACTIVE')
    await applyRange(page, '2001-02-03', '2001-02-03')
    const staleRow = page.getByRole('row').filter({ hasText: stale }).first()
    await expect(staleRow.getByText('บันทึกไว้: ยังใช้งานได้')).toBeVisible({ timeout: 5000 })
    await expect(staleRow.getByText('บันทึกว่ายังใช้งานได้ แต่วันหมดอายุผ่านไปแล้ว')).toBeVisible()
    await page.getByRole('button', { name: 'โหลดข้อมูลใหม่' }).click()
    await expect(staleRow.getByText('บันทึกไว้: ยังใช้งานได้')).toBeVisible({ timeout: 5000 }) // report reads did not write
  }).toPass({ timeout: 60_000 })

  // Report-only assertion: the page itself sent GETs to /me and the report only.
  expect(requests.every((r) => r.method === 'GET')).toBe(true)
  expect(requests.every((r) => r.path === '/api/v1/me' || r.path === REPORT_PATH)).toBe(true)
})

test('[destination characterization] the existing vehicle certificate page may write EXPIRED when opened from the report', async ({ page }) => {
  const project = test.info().project.name
  const tag = `E2E7D2-DEST-${project}-${Date.now()}`
  await createCertificate(page, 'VEH-1047', tag, '2001-03-04', 'ACTIVE')
  await page.goto('/reports/certificate-expiry')
  await expect(page.getByText(/^ข้อมูล ณ วันที่ /)).toBeVisible()
  await expect(page.getByText("หน้าใบรับรองของรถเป็นหน้าที่มีอยู่เดิม เมื่อเปิด ระบบอาจบันทึกสถานะใบรับรองที่วันหมดอายุอยู่ก่อนวันนี้ให้เป็น 'หมดอายุ'")).toBeVisible()
  await applyRange(page, '2001-03-04', '2001-03-04')
  const row = page.getByRole('row').filter({ hasText: tag }).first()
  await expect(row).toBeVisible()

  const destinationRequests = trackApi(page)
  await row.getByRole('link', { name: 'ดูใบรับรองของรถคันนี้' }).click()
  await expect(page).toHaveURL(/\/vehicle\/VEH-1047\/certificates$/)
  await expect(page.getByRole('heading', { name: 'เอกสาร/ใบรับรองยานพาหนะ' })).toBeVisible()
  const card = page.locator('.card').filter({ hasText: tag })
  await expect(card.getByText('หมดอายุ', { exact: true })).toBeVisible()
  // The destination issues a GET that reconciles (writes) server-side.
  expect(destinationRequests.some((r) => r.method === 'GET' && r.path === '/api/v1/vehicles/VEH-1047/certificates')).toBe(true)

  const after = await page.request.get(`${REPORT_PATH}?expiry_from=2001-03-04&expiry_to=2001-03-04&page_size=200`)
  expect(after.ok()).toBe(true)
  const item = (await after.json()).items.find((i: SynItem) => i.document_no === tag)
  expect(item.stored_status).toBe('EXPIRED')
  expect(item.flags).not.toContain('STORED_ACTIVE_PAST_EXPIRY')
})
