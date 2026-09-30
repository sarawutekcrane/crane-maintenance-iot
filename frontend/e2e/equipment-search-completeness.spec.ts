import { expect, test, type Page, type Route } from '@playwright/test'

// Phase 7 Batch 7F2 — equipment search completeness on the existing
// "/equipment" page.
//
// The [mocked] tests intercept ONLY the list request GET /api/v1/equipment
// (exact path, any query) with page.route() and return SYNTHETIC responses
// (SYN-* ids). More than 50 matches, read failures, a shrinking dataset and
// unsafe ids cannot be produced from the shared mock seed (3 equipment
// records) without editing it. They exercise the real page/CSS in every
// configured viewport, not the backend. The [unmocked smoke] test uses the
// real mock backend started by playwright.config.ts (no route handlers).

const LIST = /\/api\/v1\/equipment(\?|$)/
const LIST_PATH = '/api/v1/equipment'

interface SynEquipment {
  equipment_id: string
  equipment_code: string
  name: string
  category: string
  serial_number: null
  location: null
  operational_status: string
  created_at: string
  updated_at: string
}

function syn(id: string, category = 'LATHE', name = `เครื่องมือทดสอบ ${id}`): SynEquipment {
  return {
    equipment_id: id,
    equipment_code: `CODE-${id}`,
    name,
    category,
    serial_number: null,
    location: null,
    operational_status: 'READY',
    created_at: '2026-01-15T02:15:00Z',
    updated_at: '2026-01-15T02:15:00Z',
  }
}

function population(count: number, category = 'LATHE', prefix = 'SYN-EQP'): SynEquipment[] {
  return Array.from({ length: count }, (_, i) =>
    syn(`${prefix}-${String(i + 1).padStart(4, '0')}`, category, `เครื่องมือทดสอบ ${prefix}-${i + 1}`),
  )
}

const fulfill = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })

/** Backend-like: whole-population filter first, then the requested page. */
function pageOf(all: SynEquipment[], url: URL) {
  const q = (url.searchParams.get('q') ?? '').toLowerCase()
  const category = url.searchParams.get('category')
  const page = Number(url.searchParams.get('page') ?? '1')
  const size = Number(url.searchParams.get('page_size') ?? '20')
  const matching = all.filter(
    (e) =>
      (!q || e.name.toLowerCase().includes(q) || e.equipment_code.toLowerCase().includes(q)) &&
      (!category || e.category === category),
  )
  return { items: matching.slice((page - 1) * size, page * size), page, page_size: size, total_items: matching.length }
}

/** Page-owned list requests only (not /me, not detail requests). */
function trackList(page: Page) {
  const requests: { method: string; params: Record<string, string> }[] = []
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (url.pathname === LIST_PATH) {
      requests.push({ method: request.method(), params: Object.fromEntries(url.searchParams) })
    }
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

const range = (first: number, last: number, total: number) =>
  `พบ ${total} รายการที่ตรงกับเงื่อนไข · แสดงรายการที่ ${first}–${last} จาก ${total} รายการ`

test('[mocked] more than 50 matches: paging, combined filters and clear', async ({ page }) => {
  const all = [...population(60, 'LATHE', 'SYN-LAT'), ...population(70, 'WELDING', 'SYN-WLD')]
  await page.route(LIST, (route) => fulfill(route, pageOf(all, new URL(route.request().url()))))
  const list = trackList(page)
  await page.goto('/equipment')

  await expect(page.getByText(range(1, 50, 130))).toBeVisible()
  await expect(page.getByText('เงื่อนไขที่ใช้: ไม่กรองเงื่อนไข')).toBeVisible()
  await expect(page.getByText('หน้า 1 จาก 3')).toBeVisible()
  await expect(page.getByRole('button', { name: 'ก่อนหน้า' })).toBeDisabled()
  await page.getByRole('button', { name: 'ถัดไป' }).click()
  await expect(page.getByText(range(51, 100, 130))).toBeVisible()
  await page.getByRole('button', { name: 'ถัดไป' }).click()
  await expect(page.getByText(range(101, 130, 130))).toBeVisible()
  await expect(page.getByRole('button', { name: 'ถัดไป' })).toBeDisabled()
  await expectNoHorizontalOverflow(page)

  // Editing alone sends nothing; submit applies q + category from page 1.
  const before = list.length
  await page.getByLabel('ค้นหา (ชื่อ หรือ รหัส)').fill('SYN-WLD')
  await page.getByLabel('ประเภท').selectOption('WELDING')
  expect(list.length).toBe(before)
  await page.getByRole('button', { name: 'ค้นหา' }).click()
  await expect(page.getByText(range(1, 50, 70))).toBeVisible()
  await expect(page.getByText('เงื่อนไขที่ใช้: คำค้น "SYN-WLD" · ประเภท เครื่องเชื่อม')).toBeVisible()
  await page.getByRole('button', { name: 'ถัดไป' }).click()
  await expect(page.getByText(range(51, 70, 70))).toBeVisible()
  expect(list[list.length - 1].params).toMatchObject({ q: 'SYN-WLD', category: 'WELDING', page: '2', page_size: '50' })

  await page.getByRole('button', { name: 'ล้างตัวกรอง' }).click()
  await expect(page.getByText(range(1, 50, 130))).toBeVisible()
  await expect(page.getByLabel('ค้นหา (ชื่อ หรือ รหัส)')).toHaveValue('')
  await expect(page.getByLabel('ประเภท')).toHaveValue('')
  expect(list[list.length - 1].params).toEqual({ page: '1', page_size: '50' })
  expect(list.every((r) => r.method === 'GET')).toBe(true)
})

test('[mocked] read failure, retry of the applied request, and out-of-range after the data shrinks', async ({ page }) => {
  let total = 60
  let failNext = true
  await page.route(LIST, (route) => {
    const url = new URL(route.request().url())
    if (url.searchParams.get('page') === '2' && failNext) {
      failNext = false
      return fulfill(route, { error: { code: 'REPOSITORY_UNAVAILABLE', message: 'x', request_id: 'syn-req-1' } }, 503)
    }
    return fulfill(route, pageOf(population(total), url))
  })
  const list = trackList(page)
  await page.goto('/equipment')
  await expect(page.getByText(range(1, 50, 60))).toBeVisible()

  await page.getByRole('button', { name: 'ถัดไป' }).click()
  await expect(page.getByText('โหลดรายการเครื่องมือไม่สำเร็จ')).toBeVisible()
  await expect(page.getByText('รหัสอ้างอิง: syn-req-1')).toBeVisible()
  await expect(page.getByRole('table')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'ถัดไป' })).toHaveCount(0)

  // An unsent draft must not leak into the retry.
  await page.getByLabel('ค้นหา (ชื่อ หรือ รหัส)').fill('ไม่ได้ส่ง')
  await page.getByRole('button', { name: 'ลองใหม่อีกครั้ง' }).click()
  await expect(page.getByText(range(51, 60, 60))).toBeVisible()
  expect(list[list.length - 1].params).toEqual({ page: '2', page_size: '50' })

  // Data shrinks to one page; the next request for page 2 is out of range.
  total = 40
  await page.getByRole('button', { name: 'ก่อนหน้า' }).click()
  await expect(page.getByText(range(1, 40, 40))).toBeVisible()
  total = 60
  await page.getByRole('button', { name: 'ล้างตัวกรอง' }).click()
  await expect(page.getByText(range(1, 50, 60))).toBeVisible()
  total = 40
  await page.getByRole('button', { name: 'ถัดไป' }).click()
  await expect(page.getByText('ไม่มีรายการในหน้านี้')).toBeVisible()
  await expect(page.getByText('ขณะนี้ระบบส่งกลับ 40 รายการตามเงื่อนไขนี้')).toBeVisible()
  await page.getByRole('button', { name: 'กลับไปหน้าแรก' }).click()
  await expect(page.getByText(range(1, 40, 40))).toBeVisible()
  await expectNoHorizontalOverflow(page)
})

test('[mocked] a deliberately slow older search is superseded by a newer one', async ({ page }) => {
  let releaseOld: () => void = () => {}
  const oldGate = new Promise<void>((resolve) => {
    releaseOld = resolve
  })
  let oldFulfilled = false
  await page.route(LIST, async (route) => {
    const url = new URL(route.request().url())
    if (url.searchParams.get('q') === 'old') {
      await oldGate
      await fulfill(route, { items: population(7, 'LATHE', 'SYN-OLD'), page: 1, page_size: 50, total_items: 7 })
      oldFulfilled = true
      return
    }
    if (url.searchParams.get('q') === 'new') {
      return fulfill(route, { items: population(3, 'LATHE', 'SYN-NEW'), page: 1, page_size: 50, total_items: 3 })
    }
    return fulfill(route, { items: population(2), page: 1, page_size: 50, total_items: 2 })
  })
  await page.goto('/equipment')
  await expect(page.getByText(range(1, 2, 2))).toBeVisible()

  const q = page.getByLabel('ค้นหา (ชื่อ หรือ รหัส)')
  await q.fill('old')
  await page.getByRole('button', { name: 'ค้นหา' }).click()
  await expect(page.getByText('กำลังโหลดรายการเครื่องมือ...')).toBeVisible()
  await q.fill('new')
  await page.getByRole('button', { name: 'ค้นหา' }).click()
  await expect(page.getByText(range(1, 3, 3))).toBeVisible()
  await expect(page.getByText('เงื่อนไขที่ใช้: คำค้น "new"')).toBeVisible()

  releaseOld()
  await expect.poll(() => oldFulfilled).toBe(true)
  await page.waitForTimeout(200)
  await expect(page.getByText(range(1, 3, 3))).toBeVisible()
  await expect(page.getByText(/SYN-OLD/)).toHaveCount(0)
  await expect(page.getByText('เงื่อนไขที่ใช้: คำค้น "old"')).toHaveCount(0)
})

test('[mocked] link suppression keeps every row and original text; layout stays usable', async ({ page }) => {
  const items = [
    syn('SYN-OK-1'),
    syn('000123'),
    syn('SYN/SLASH'),
    syn('SYN%2F'),
    syn('SYN?Q'),
    syn('..'),
    syn('SYN SPACE'),
    syn('เครื่อง-1'),
    syn(''),
    syn('SYN-DUP', 'LATHE', 'ซ้ำ A'),
    syn('SYN-DUP', 'LATHE', 'ซ้ำ B'),
    syn('SYN-LONG-' + 'X'.repeat(80)),
  ]
  await page.route(LIST, (route) => fulfill(route, { items, page: 1, page_size: 50, total_items: items.length }))
  await page.goto('/equipment')
  await expect(page.getByText(range(1, 12, 12))).toBeVisible()
  await expect(page.locator('tbody tr')).toHaveCount(12)
  await expect(page.getByRole('link', { name: 'SYN-OK-1' })).toHaveAttribute('href', '/equipment/SYN-OK-1')
  await expect(page.getByRole('link', { name: '000123' })).toHaveAttribute('href', '/equipment/000123')
  // Only the three unreserved ids (incl. the long one) get detail links.
  await expect(page.locator('a[href^="/equipment/"]')).toHaveCount(3)
  await expect(page.getByText('(ไม่มีลิงก์: รหัสมีอักขระที่หน้ารายละเอียดยังรองรับไม่ได้)')).toHaveCount(6)
  await expect(page.getByText('(ไม่มีลิงก์: ไม่มีรหัส)')).toHaveCount(1)
  await expect(page.getByText('(ไม่มีลิงก์: รหัสนี้ซ้ำกันในหน้านี้)')).toHaveCount(2)
  await expect(page.getByText('SYN/SLASH', { exact: true })).toBeVisible()
  await expect(page.getByText('ซ้ำ B')).toBeVisible()
  await expectNoHorizontalOverflow(page)
})

test('[unmocked smoke] the real mock backend list opens a real equipment detail page', async ({ page }) => {
  const list = trackList(page)
  await page.goto('/equipment')
  await expect(page.getByRole('heading', { name: 'เครื่องมือ/อุปกรณ์ซ่อมบำรุง' })).toBeVisible()
  await expect(page.getByText('เงื่อนไขที่ใช้: ไม่กรองเงื่อนไข')).toBeVisible()
  await expect(page.getByText(/^พบ \d+ รายการที่ตรงกับเงื่อนไข · แสดงรายการที่ 1–\d+ จาก \d+ รายการ$/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'ถัดไป' })).toBeDisabled()
  // Development StrictMode may repeat the mount request; every list
  // request is a GET for unfiltered page 1.
  expect(list.length).toBeGreaterThanOrEqual(1)
  expect(list.every((r) => r.method === 'GET' && r.params.page === '1' && r.params.page_size === '50')).toBe(true)

  await page.getByRole('link', { name: 'EQP-0001' }).click()
  await expect(page).toHaveURL(/\/equipment\/EQP-0001$/)
  await expect(page.getByText('รหัสเครื่องมือ: EQP-0001')).toBeVisible()
  await expectNoHorizontalOverflow(page)
})
