import { expect, test, type Page } from '@playwright/test'

// Phase 7 Batch 7J2 — flexible vehicle and equipment search against the REAL
// mock backend started by playwright.config.ts (no page.route() handlers),
// so the matching itself is the backend's. Seed data (mock repository):
// VEH-1046 TC-12 "Zoomlion QY50 ...", VEH-1047 TC-13 "XCMG XCT80 ...",
// VEH-1048 TC-14 "Tadano GR-250 รถเครนล้อยาง 25 ตัน"; EQP-0001 LATHE-01
// "เครื่องกลึงเบอร์ 1", EQP-0002 COMP-01 "ปั๊มลมโรงซ่อม", EQP-0003 WELD-01.
// vehicle-equipment.spec.ts changes VEH-1046's STATUS on the shared backend
// in parallel, so no query here combines a status filter with VEH-1046.

const VEHICLE_SEARCH_LABEL = 'ค้นหา (เลขเครื่องจักร รหัสยานพาหนะ หรือรุ่น)'
const EQUIPMENT_SEARCH_LABEL = 'ค้นหา (ชื่อ หรือ รหัส)'

type ListRequest = { method: string; path: string; params: Record<string, string> }

function trackLists(page: Page, path: '/api/v1/vehicles' | '/api/v1/equipment'): ListRequest[] {
  const seen: ListRequest[] = []
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (url.pathname === path) {
      seen.push({ method: request.method(), path: url.pathname, params: Object.fromEntries(url.searchParams) })
    }
  })
  return seen
}

async function searchVehicles(page: Page, q: string) {
  await page.getByLabel(VEHICLE_SEARCH_LABEL).fill(q)
  await page.getByRole('button', { name: 'ค้นหา', exact: true }).click()
}

async function searchEquipment(page: Page, q: string) {
  await page.getByLabel(EQUIPMENT_SEARCH_LABEL).fill(q)
  await page.getByRole('button', { name: 'ค้นหา', exact: true }).click()
}

test('[real mock backend] vehicle search by model name, Thai+digit term, identifier tolerance and cross-field terms', async ({
  page,
}) => {
  const requests = trackLists(page, '/api/v1/vehicles')
  await page.goto('/vehicles')
  await expect(page.getByLabel(VEHICLE_SEARCH_LABEL)).toHaveAttribute('placeholder', 'เช่น TC-12 หรือชื่อรุ่น')
  await expect(page.getByText(/แสดงรายการที่ 1–\d+ จาก \d+ คันที่ตรงกับเงื่อนไข/)).toBeVisible()

  // Model name only (no model dropdown).
  await searchVehicles(page, 'Tadano')
  await expect(page.getByText('แสดงรายการที่ 1–1 จาก 1 คันที่ตรงกับเงื่อนไข')).toBeVisible()
  await expect(page.getByRole('link', { name: 'VEH-1048' })).toBeVisible()

  // D-11: Thai + digits inside one model name.
  await searchVehicles(page, 'รถเครน25')
  await expect(page.getByText('แสดงรายการที่ 1–1 จาก 1 คันที่ตรงกับเงื่อนไข')).toBeVisible()
  await expect(page.getByRole('link', { name: 'VEH-1048' })).toBeVisible()

  // Identifier tolerance: TC13 finds machine number TC-13.
  await searchVehicles(page, 'TC13')
  await expect(page.getByText('แสดงรายการที่ 1–1 จาก 1 คันที่ตรงกับเงื่อนไข')).toBeVisible()
  await expect(page.getByRole('link', { name: 'VEH-1047' })).toBeVisible()

  // Cross-field AND: model name term + machine number term, any order.
  await searchVehicles(page, '  tc-12   zoomlion ')
  await expect(page.getByText('แสดงรายการที่ 1–1 จาก 1 คันที่ตรงกับเงื่อนไข')).toBeVisible()
  await expect(page.getByRole('link', { name: 'VEH-1046' })).toBeVisible()
  await searchVehicles(page, 'zoomlion tc-13')
  await expect(page.getByText('ไม่มีรถที่ตรงกับเงื่อนไขที่เลือก ลองเปลี่ยนคำค้นหาหรือล้างตัวกรอง')).toBeVisible()

  // A query made only of hyphens matches nothing.
  await searchVehicles(page, '-')
  await expect(page.getByText('ไม่มีรถที่ตรงกับเงื่อนไขที่เลือก ลองเปลี่ยนคำค้นหาหรือล้างตัวกรอง')).toBeVisible()

  // q combines with the model filter.
  await page.getByRole('button', { name: 'ล้างตัวกรอง' }).click()
  await expect(page.getByText(/แสดงรายการที่ 1–\d+ จาก \d+ คันที่ตรงกับเงื่อนไข/)).toBeVisible()
  await page.getByLabel(VEHICLE_SEARCH_LABEL).fill('tc')
  await page.getByLabel('รุ่น', { exact: true }).selectOption({ label: 'Tadano GR-250 รถเครนล้อยาง 25 ตัน' })
  await expect(page.getByText('แสดงรายการที่ 1–1 จาก 1 คันที่ตรงกับเงื่อนไข')).toBeVisible()
  await expect(page.getByRole('link', { name: 'VEH-1048' })).toBeVisible()

  expect(requests.every((r) => r.method === 'GET')).toBe(true)
  expect(requests.some((r) => r.params.q === 'รถเครน25')).toBe(true)
  expect(requests.some((r) => r.params.q === 'TC13')).toBe(true)
})

test('[real mock backend] equipment search: Thai+digit term, spaced terms, identifiers, draft category', async ({
  page,
}) => {
  const requests = trackLists(page, '/api/v1/equipment')
  await page.goto('/equipment')
  await expect(page.getByText('เงื่อนไขที่ใช้: ไม่กรองเงื่อนไข')).toBeVisible()

  await searchEquipment(page, 'กลึง1')
  await expect(page.getByText('พบ 1 รายการที่ตรงกับเงื่อนไข · แสดงรายการที่ 1–1 จาก 1 รายการ')).toBeVisible()
  await expect(page.getByRole('link', { name: 'EQP-0001' })).toBeVisible()

  await searchEquipment(page, '1 กลึง')
  await expect(page.getByText('พบ 1 รายการที่ตรงกับเงื่อนไข · แสดงรายการที่ 1–1 จาก 1 รายการ')).toBeVisible()

  await searchEquipment(page, 'LATHE01')
  await expect(page.getByRole('link', { name: 'EQP-0001' })).toBeVisible()

  await searchEquipment(page, 'eqp 0002')
  await expect(page.getByText('พบ 1 รายการที่ตรงกับเงื่อนไข · แสดงรายการที่ 1–1 จาก 1 รายการ')).toBeVisible()
  await expect(page.getByRole('link', { name: 'EQP-0002' })).toBeVisible()

  await searchEquipment(page, '--')
  await expect(page.getByText('ไม่พบเครื่องมือที่ตรงกับเงื่อนไข')).toBeVisible()

  // The category remains a draft until "ค้นหา" is pressed.
  await page.getByLabel(EQUIPMENT_SEARCH_LABEL).fill('เครื่อง')
  const before = requests.length
  await page.getByLabel('ประเภท').selectOption({ label: 'เครื่องเชื่อม' })
  expect(requests.length).toBe(before)
  await page.getByRole('button', { name: 'ค้นหา', exact: true }).click()
  await expect(page.getByText('พบ 1 รายการที่ตรงกับเงื่อนไข · แสดงรายการที่ 1–1 จาก 1 รายการ')).toBeVisible()
  await expect(page.getByRole('link', { name: 'EQP-0003' })).toBeVisible()

  expect(requests.every((r) => r.method === 'GET')).toBe(true)
  expect(requests.some((r) => r.params.q === 'กลึง1')).toBe(true)
})

test('[real mock backend] picker-style request (page_size=10) uses the same flexible vehicle search', async ({
  page,
}) => {
  // AssetSearchSelect sends GET /vehicles?page_size=10&q=<trimmed text>; its
  // own runtime logic is unchanged and covered by its unit suite.
  await page.goto('/vehicles')
  const response = await page.request.get('/api/v1/vehicles?page_size=10&q=xcmg')
  expect(response.status()).toBe(200)
  const body = await response.json()
  expect(body.items.map((v: { vehicle_id: string }) => v.vehicle_id)).toEqual(['VEH-1047'])
  expect(body.total_items).toBe(1)
})
