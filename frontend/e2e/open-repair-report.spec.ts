import { expect, test, type Page, type Route } from '@playwright/test'

// Phase 7 Batch 7C2 — open-repair report "งานซ่อมค้าง" (/open-repair-queue).
//
// The [mocked] tests intercept GET /api/v1/repairs/open-queue with
// page.route() and return synthetic responses (SYN-* ids), because paging
// beyond 50 rows, schema errors and read failures cannot be produced from
// the shared mock seed data without editing it. They exercise the real
// page/CSS in every configured viewport, not the backend. The
// [unmocked smoke] test runs against the real mock backend started by
// playwright.config.ts, as an authorized maintenance actor.
//
// The browser runs in America/New_York so that Thailand-time display is
// proven independent of the viewer's zone (UTC 02:15 -> Bangkok 09:15).
test.use({ timezoneId: 'America/New_York' })

const QUEUE = /\/api\/v1\/repairs\/open-queue(\?|$)/
const RANGE = /^แสดงรายการที่ \d+–\d+ จาก \d+ ใบงานที่ระบบส่งกลับ$/

interface SynRepair {
  repair_id: string
  asset_type: 'VEHICLE' | 'EQUIPMENT'
  asset_id: string
  source_type: string
  source_id: null
  status: 'OPEN'
  opened_at: string
  closed_at: null
  action_count: number
  primary_technician: string | null
  collaborators: string[]
  symptom: string | null
}

function synRepair(i: number, assetType: 'VEHICLE' | 'EQUIPMENT' = 'VEHICLE'): SynRepair {
  return {
    repair_id: `SYN-RPR-${String(i).padStart(4, '0')}`,
    asset_type: assetType,
    asset_id: assetType === 'VEHICLE' ? `SYN-VEH-${i % 7}` : `SYN-EQP-${i % 3}`,
    source_type: 'MANUAL',
    source_id: null,
    status: 'OPEN',
    opened_at: '2026-01-15T02:15:00Z',
    closed_at: null,
    action_count: 0,
    primary_technician: null,
    collaborators: [],
    symptom: 'เสียงดังผิดปกติ',
  }
}

/** A synthetic population served page by page from the request's params. */
function serve(population: (assetType: string | null) => SynRepair[]) {
  return async (route: Route) => {
    const url = new URL(route.request().url())
    const page = Number(url.searchParams.get('page') ?? '1')
    const pageSize = Number(url.searchParams.get('page_size') ?? '50')
    const all = population(url.searchParams.get('asset_type'))
    const items = all.slice((page - 1) * pageSize, page * pageSize)
    await fulfill(route, { items, page, page_size: pageSize, total_items: all.length })
  }
}

const fulfill = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })

function trackQueue(page: Page) {
  const params: Record<string, string>[] = []
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (url.pathname === '/api/v1/repairs/open-queue') params.push(Object.fromEntries(url.searchParams))
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

const VEHICLES = Array.from({ length: 120 }, (_, i) => synRepair(i + 1))
const EQUIPMENT = Array.from({ length: 70 }, (_, i) => synRepair(i + 501, 'EQUIPMENT'))

test('[mocked] menu reaches the report; paging, filter reset/persistence and Bangkok time', async ({ page }) => {
  const queue = trackQueue(page)
  await page.route(
    QUEUE,
    serve((assetType) => (assetType === 'EQUIPMENT' ? EQUIPMENT : assetType === 'VEHICLE' ? VEHICLES : [...VEHICLES, ...EQUIPMENT])),
  )
  await page.goto('/')
  await openMenuIfCollapsed(page)
  await page.getByRole('link', { name: 'งานซ่อมค้าง' }).click()
  await expect(page).toHaveURL(/\/open-repair-queue$/)
  await expect(page.getByRole('heading', { name: 'งานซ่อมค้าง' })).toBeVisible()
  await expect(page.getByText('นับเป็นจำนวนใบงานซ่อม ไม่ใช่จำนวนคัน รถหนึ่งคันอาจมีหลายใบงาน')).toBeVisible()

  await expect(page.getByText('แสดงรายการที่ 1–50 จาก 190 ใบงานที่ระบบส่งกลับ')).toBeVisible()
  await expect(page.getByText('หน้า 1 จาก 4')).toBeVisible()
  // Browser zone is New York; the report shows Thailand time.
  expect(await page.evaluate(() => Intl.DateTimeFormat().resolvedOptions().timeZone)).toBe('America/New_York')
  await expect(page.getByText('15 ม.ค. 2569 09:15').first()).toBeVisible()
  await expectNoHorizontalOverflow(page)

  const pager = page.getByRole('navigation', { name: 'เปลี่ยนหน้ารายการงานซ่อมค้าง' })
  await pager.getByRole('button', { name: 'ถัดไป' }).click()
  await expect(page.getByText('แสดงรายการที่ 51–100 จาก 190 ใบงานที่ระบบส่งกลับ')).toBeVisible()

  await page.getByLabel('ประเภทสินทรัพย์').selectOption('EQUIPMENT')
  await expect(page.getByText('แสดงรายการที่ 1–50 จาก 70 ใบงานที่ระบบส่งกลับ')).toBeVisible()
  await pager.getByRole('button', { name: 'ถัดไป' }).click()
  await expect(page.getByText('แสดงรายการที่ 51–70 จาก 70 ใบงานที่ระบบส่งกลับ')).toBeVisible()
  await expect(pager.getByRole('button', { name: 'ถัดไป' })).toBeDisabled()
  await expect(page.getByRole('link', { name: 'เครื่องมือ/อุปกรณ์ SYN-EQP-0' }).first()).toHaveAttribute(
    'href',
    '/equipment/SYN-EQP-0',
  )

  await page.getByRole('button', { name: 'โหลดข้อมูลใหม่' }).click()
  await expect(page.getByText('แสดงรายการที่ 51–70 จาก 70 ใบงานที่ระบบส่งกลับ')).toBeVisible()
  await expectNoHorizontalOverflow(page)

  // Mount (StrictMode may send the first GET twice), then exactly one GET
  // per user action: next, filter (reset to page 1), next (filter kept), refresh.
  const mount = queue.findIndex((p) => p.page === '2')
  expect(mount).toBeGreaterThanOrEqual(1)
  expect(mount).toBeLessThanOrEqual(2)
  expect(queue.slice(0, mount).every((p) => p.page === '1' && !p.asset_type)).toBe(true)
  expect(queue.slice(mount)).toEqual([
    { page: '2', page_size: '50' },
    { page: '1', page_size: '50', asset_type: 'EQUIPMENT' },
    { page: '2', page_size: '50', asset_type: 'EQUIPMENT' },
    { page: '2', page_size: '50', asset_type: 'EQUIPMENT' },
  ])
})

test('[mocked] empty, out-of-range and guarded links; long values never overflow', async ({ page }) => {
  let phase: 'rows' | 'shrunk' | 'empty' = 'rows'
  const longId = `SYN-RPR-${'X'.repeat(120)}`
  const rows: SynRepair[] = [
    { ...synRepair(1), repair_id: 'SYN/RPR 1#', asset_id: 'SYN VEH/1' },
    { ...synRepair(2), repair_id: 'SYN-RPR-DUP' },
    { ...synRepair(3), repair_id: 'SYN-RPR-DUP', asset_id: 'SYN-VEH-3' },
    { ...synRepair(4), repair_id: '  ', asset_id: '' },
    { ...synRepair(5), repair_id: longId, symptom: 'ย'.repeat(200), opened_at: '1970-01-01T00:00:00Z' },
    ...Array.from({ length: 45 }, (_, i) => synRepair(i + 10)),
  ]
  await page.route(QUEUE, async (route) => {
    const url = new URL(route.request().url())
    const pageNo = Number(url.searchParams.get('page'))
    if (phase === 'empty') return fulfill(route, { items: [], page: pageNo, page_size: 50, total_items: 0 })
    if (phase === 'shrunk' && pageNo === 2) return fulfill(route, { items: [], page: 2, page_size: 50, total_items: 30 })
    if (phase === 'shrunk') return fulfill(route, { items: rows.slice(0, 30), page: 1, page_size: 50, total_items: 30 })
    if (pageNo === 1) return fulfill(route, { items: rows, page: 1, page_size: 50, total_items: 60 })
    return fulfill(route, { items: Array.from({ length: 10 }, (_, i) => synRepair(i + 100)), page: 2, page_size: 50, total_items: 60 })
  })
  await page.goto('/open-repair-queue')
  await expect(page.getByText('แสดงรายการที่ 1–50 จาก 60 ใบงานที่ระบบส่งกลับ')).toBeVisible()

  await expect(page.getByRole('link', { name: 'SYN/RPR 1#' })).toHaveAttribute('href', '/repairs/SYN%2FRPR%201%23')
  await expect(page.getByRole('link', { name: 'ยานพาหนะ SYN VEH/1' })).toHaveAttribute('href', '/vehicle/SYN%20VEH%2F1')
  await expect(page.getByText('เลขที่ใบงานซ้ำในข้อมูล — เปิดรายละเอียดจากรายการนี้ไม่ได้')).toHaveCount(2)
  await expect(page.getByRole('link', { name: 'SYN-RPR-DUP' })).toHaveCount(0)
  await expect(page.getByText('(ไม่มีเลขที่ใบงาน)')).toBeVisible()
  await expect(page.getByText('ยานพาหนะ (ไม่มีรหัสสินทรัพย์)')).toBeVisible()
  await expect(page.getByText('ไม่มีวันที่เปิดใบงานที่อ่านได้')).toBeVisible()
  await expect(page.locator('.responsive-table tbody tr')).toHaveCount(50)
  await expectNoHorizontalOverflow(page)

  phase = 'shrunk'
  await page.getByRole('button', { name: 'ถัดไป' }).click()
  await expect(page.getByText('หน้านี้ไม่มีรายการแล้ว')).toBeVisible()
  await expect(page.getByText('ข้อมูลอาจเปลี่ยนไประหว่างเปลี่ยนหน้า ขณะนี้ระบบส่งกลับ 30 ใบงานตามเงื่อนไขนี้')).toBeVisible()
  await expect(page.getByText(RANGE)).toHaveCount(0)
  await page.getByRole('button', { name: 'กลับไปหน้าแรก' }).click()
  await expect(page.getByText('แสดงรายการที่ 1–30 จาก 30 ใบงานที่ระบบส่งกลับ')).toBeVisible()

  phase = 'empty'
  await page.getByRole('button', { name: 'โหลดข้อมูลใหม่' }).click()
  await expect(page.getByText('ระบบไม่พบใบงานซ่อมที่ยังไม่ปิดงาน')).toBeVisible()
  await page.getByLabel('ประเภทสินทรัพย์').selectOption('VEHICLE')
  await expect(page.getByText('ไม่พบใบงานซ่อมที่ยังไม่ปิดงานสำหรับประเภทสินทรัพย์นี้')).toBeVisible()
  await expectNoHorizontalOverflow(page)
})

test('[mocked] schema error, 503 retry and permission denied never show rows or totals', async ({ page }) => {
  let phase: 'schema' | 'read' | 'denied' | 'ok' = 'schema'
  await page.route(QUEUE, async (route) => {
    if (phase === 'schema') {
      return fulfill(
        route,
        {
          error: {
            code: 'REPAIR_ORDER_SCHEMA_INVALID',
            message: 'synthetic',
            details: { tab: 'repair_order', problem: 'MISSING_HEADERS', headers: ['status'] },
            request_id: 'req-e2e-schema',
          },
        },
        500,
      )
    }
    if (phase === 'read') {
      return fulfill(route, { error: { code: 'REPAIR_ORDER_READ_FAILED', message: 'synthetic', request_id: 'req-e2e-read' } }, 503)
    }
    if (phase === 'denied') {
      return fulfill(route, { error: { code: 'HTTP_ERROR', message: 'denied', request_id: 'req-e2e-403' } }, 403)
    }
    return serve(() => VEHICLES.slice(0, 3))(route)
  })
  await page.goto('/open-repair-queue')

  const alert = page.getByRole('alert')
  await expect(alert.getByText('ไม่แสดงรายการงานซ่อมค้าง')).toBeVisible()
  await expect(alert.getByText(/โครงสร้างข้อมูลใบงานซ่อมไม่ถูกต้อง/)).toBeVisible()
  await expect(alert.getByText('รหัสอ้างอิง: req-e2e-schema')).toBeVisible()
  await expect(page.getByText(RANGE)).toHaveCount(0)
  await expect(page.locator('.responsive-table')).toHaveCount(0)
  await expectNoHorizontalOverflow(page)

  phase = 'read'
  await page.getByRole('button', { name: 'ลองใหม่อีกครั้ง' }).click()
  await expect(alert.getByText('โหลดงานซ่อมค้างไม่สำเร็จ')).toBeVisible()
  await expect(alert.getByText('ไม่สามารถอ่านข้อมูลใบงานซ่อมได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง')).toBeVisible()
  await expect(alert.getByText('รหัสอ้างอิง: req-e2e-read')).toBeVisible()

  phase = 'ok'
  await page.getByRole('button', { name: 'ลองใหม่อีกครั้ง' }).click()
  await expect(page.getByText('แสดงรายการที่ 1–3 จาก 3 ใบงานที่ระบบส่งกลับ')).toBeVisible()

  phase = 'denied'
  await page.getByRole('button', { name: 'โหลดข้อมูลใหม่' }).click()
  await expect(page.getByText('ไม่มีสิทธิ์เข้าถึง', { exact: true })).toBeVisible()
  await expect(page.getByText(RANGE)).toHaveCount(0)
  await expect(page.locator('.responsive-table')).toHaveCount(0)
  await expectNoHorizontalOverflow(page)
})

test.describe('as an authorized maintenance actor', () => {
  test.use({ extraHTTPHeaders: { 'X-Dev-Role': 'MAINTENANCE', 'X-Dev-User-Id': 'e2e-7c2-maint' } })

  test('[unmocked smoke] total matches the API and repair/asset links open', async ({ page }) => {
    // Create one vehicle and one equipment work order on the shared mock backend.
    const created: Record<'VEHICLE' | 'EQUIPMENT', string> = { VEHICLE: '', EQUIPMENT: '' }
    for (const [assetType, assetId] of [['VEHICLE', 'VEH-1046'], ['EQUIPMENT', 'EQP-0001']] as const) {
      const response = await page.request.post('/api/v1/repairs', {
        data: { asset_type: assetType, asset_id: assetId, source_type: 'MANUAL', symptom: 'e2e 7C2 smoke' },
      })
      expect(response.ok()).toBe(true)
      created[assetType] = (await response.json()).repair.repair_id
    }

    const requests = trackApi(page)
    await page.goto('/')
    await openMenuIfCollapsed(page)
    await page.getByRole('link', { name: 'งานซ่อมค้าง' }).click()
    await expect(page).toHaveURL(/\/open-repair-queue$/)
    await expect(page.getByText(RANGE)).toBeVisible()
    await expectNoHorizontalOverflow(page)

    // Shell GET /me and the page-owned open-queue GETs are reported
    // separately; the dev server's StrictMode may repeat the mount (<= 2).
    const meRequests = requests.filter((r) => r.path === '/api/v1/me').length
    const queueRequests = requests.filter((r) => r.path === '/api/v1/repairs/open-queue').length
    const measured = `GET /me=${meRequests}; GET /repairs/open-queue=${queueRequests}`
    test.info().annotations.push({ type: 'request-count', description: measured })
    console.log(`[7C2 request-count ${test.info().project.name}] ${measured}`)
    expect(requests.every((r) => r.path === '/api/v1/me' || r.path === '/api/v1/repairs/open-queue')).toBe(true)
    expect(queueRequests).toBeGreaterThanOrEqual(1)
    expect(queueRequests).toBeLessThanOrEqual(2)

    // Other specs create/close repairs on the shared backend in parallel:
    // compare a fresh page read with a fresh API read, retrying if data moved.
    await expect(async () => {
      await page.getByRole('button', { name: 'โหลดข้อมูลใหม่' }).click()
      const text = await page.getByText(RANGE).innerText({ timeout: 5000 })
      const shown = Number(/จาก (\d+) ใบงาน/.exec(text)?.[1])
      const api = await page.request.get('/api/v1/repairs/open-queue?page_size=1')
      expect(api.ok()).toBe(true)
      expect(shown).toBe((await api.json()).total_items)
    }).toPass({ timeout: 60_000 })

    // Vehicle: repair link, then asset link.
    await page.getByLabel('ประเภทสินทรัพย์').selectOption('VEHICLE')
    await page.getByRole('link', { name: created.VEHICLE, exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`/repairs/${created.VEHICLE}$`))
    await expect(page.getByText(`รหัสใบแจ้งซ่อม: ${created.VEHICLE}`)).toBeVisible()
    await page.goBack()
    await expect(page.getByText(RANGE)).toBeVisible()
    await page.getByRole('row').filter({ hasText: created.VEHICLE }).getByRole('link', { name: 'ยานพาหนะ VEH-1046' }).click()
    await expect(page).toHaveURL(/\/vehicle\/VEH-1046$/)
    await expect(page.getByText('รหัสยานพาหนะ: VEH-1046')).toBeVisible()

    // Equipment: asset link opens the equipment detail.
    await page.goto('/open-repair-queue')
    await page.getByLabel('ประเภทสินทรัพย์').selectOption('EQUIPMENT')
    const row = page.getByRole('row').filter({ hasText: created.EQUIPMENT })
    await expect(row.getByRole('link', { name: created.EQUIPMENT, exact: true })).toHaveAttribute(
      'href',
      `/repairs/${created.EQUIPMENT}`,
    )
    await row.getByRole('link', { name: 'เครื่องมือ/อุปกรณ์ EQP-0001' }).click()
    await expect(page).toHaveURL(/\/equipment\/EQP-0001$/)
    await expect(page.getByText('รหัสเครื่องมือ: EQP-0001')).toBeVisible()

    expect(requests.every((r) => r.method === 'GET')).toBe(true)
  })
})
