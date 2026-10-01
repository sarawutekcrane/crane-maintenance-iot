import { expect, test, type Page, type Route } from '@playwright/test'

// Phase 7 Batch 7M1 — vehicle-list link safety and recorded-findings wording.
//
// The [mocked] tests intercept only the vehicle-list GET calls with
// page.route() and return synthetic ids that the shared seed data does not
// contain (unsafe delimiters, percent sequences, dot segments, whitespace,
// non-ASCII). They exercise the real page and CSS in every configured
// Chromium viewport project. The [unmocked] test reads the real mock backend.

const NO_LINK_NOTE = '(ไม่มีลิงก์: ใช้รหัสนี้เปิดหน้าข้อมูลรถไม่ได้ เพราะมีอักขระที่ยังรองรับไม่ได้)'
const SAFE_IDS = ['0012', 'SYN-VEH-001', 'a.b_c~d']
const UNSAFE_IDS = [
  'VEH/1', 'VEH?1', 'VEH#1', 'VEH%201', '..', ' VEH-2', 'รถ-1',
  'SYN/VERY-LONG-IDENTIFIER-WITHOUT-BREAK-OPPORTUNITIES-0123456789-ABCDEFGHIJKLMNOP',
]

function vehicle(id: string, n: number) {
  return {
    vehicle_id: id,
    machine_no: `SYN-M-${n}`,
    model_id: 'SYN-MODEL-001',
    serial_number: null,
    operational_status: 'WORKING',
    created_at: '2026-01-15T08:00:00Z',
    updated_at: '2026-01-15T08:00:00Z',
  }
}

interface MockOptions {
  failFindings?: boolean
}

async function installMocks(page: Page, ids: string[], options: MockOptions = {}) {
  const fulfill = (route: Route, body: unknown, status = 200) =>
    route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
  const vehicles = ids.map((id, i) => vehicle(id, i + 1))
  await page.route(/\/api\/v1\/vehicles(\?|$)/, (route) =>
    fulfill(route, { items: vehicles, page: 1, page_size: 50, total_items: vehicles.length }),
  )
  await page.route(/\/api\/v1\/models(\?|$)/, (route) =>
    fulfill(route, {
      items: [{ model_id: 'SYN-MODEL-001', model_code: 'SYN001', model_name: 'รุ่นทดสอบ 001', brand: 'Synthetic',
        description: null, component_roles: [], created_at: '2026-01-15T08:00:00Z', updated_at: '2026-01-15T08:00:00Z' }],
      page: 1, page_size: 200, total_items: 1,
    }),
  )
  await page.route(/\/api\/v1\/repairs(\?|$)/, (route) =>
    fulfill(route, {
      items: [
        { repair_id: 'SYN-REP-1', asset_type: 'VEHICLE', asset_id: 'VEH/1', status: 'OPEN' },
        { repair_id: 'SYN-REP-2', asset_type: 'VEHICLE', asset_id: '0012', status: 'OPEN' },
      ],
      page: 1, page_size: 200, total_items: 2,
    }),
  )
  await page.route(/\/api\/v1\/pm\/work-orders(\?|$)/, (route) =>
    fulfill(route, {
      items: [{ pm_work_order_id: 'SYN-PM-1', asset_type: 'VEHICLE', asset_id: 'VEH%201' }],
      page: 1, page_size: 200, total_items: 1,
    }),
  )
  await page.route(/\/api\/v1\/findings(\?|$)/, (route) =>
    options.failFindings
      ? fulfill(route, { error: { code: 'INTERNAL_ERROR', message: 'synthetic failure' } }, 500)
      : fulfill(route, [
          { finding_id: 'SYN-F-1', asset_type: 'VEHICLE', asset_id: 'รถ-1' },
          { finding_id: 'SYN-F-2', asset_type: 'VEHICLE', asset_id: 'SYN-VEH-001' },
        ]),
  )
}

async function expectNoHorizontalOverflow(page: Page) {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1)
}

test('[mocked] rejected ids are shown as stored text without any vehicle link; accepted ids keep their links', async ({
  page,
}) => {
  await installMocks(page, [...SAFE_IDS, ...UNSAFE_IDS])
  await page.goto('/vehicles')
  await expect(page.getByRole('link', { name: 'SYN-VEH-001', exact: true })).toBeVisible()

  // Every rejected id is shown exactly as stored, outside any link, with the note.
  const storedTexts = await page.locator('.vehicle-list__id-text').evaluateAll((els) =>
    els.map((el) => ({ text: el.textContent, inLink: el.closest('a') !== null })),
  )
  expect(storedTexts).toEqual(UNSAFE_IDS.map((text) => ({ text, inLink: false })))
  await expect(page.getByText(NO_LINK_NOTE)).toHaveCount(UNSAFE_IDS.length)
  await page.getByText(NO_LINK_NOTE).first().scrollIntoViewIfNeeded()
  await expect(page.getByText(NO_LINK_NOTE).first()).toBeVisible()

  // Indicator counts of rejected ids stay visible but are not links.
  for (const text of ['ซ่อม 1', 'ใบงาน PM 1', 'ข้อบกพร่อง 1']) {
    const unlinked = page.locator('span.vehicle-indicators__badge', { hasText: text })
    await expect(unlinked.first()).toBeVisible()
  }

  // Only accepted ids produce vehicle hrefs, placed verbatim.
  const hrefs = await page.locator('a[href^="/vehicle/"]').evaluateAll((els) => els.map((el) => el.getAttribute('href')))
  expect(hrefs.sort()).toEqual(
    ['/vehicle/0012', '/vehicle/0012/repairs', '/vehicle/SYN-VEH-001', '/vehicle/SYN-VEH-001/inspections', '/vehicle/a.b_c~d'].sort(),
  )
  await expectNoHorizontalOverflow(page)

  // An accepted id with leading zeros navigates to its unchanged destination path.
  await page.getByRole('link', { name: '0012', exact: true }).click()
  await expect(page).toHaveURL(/\/vehicle\/0012$/)
})

test('[mocked] findings are described as recorded findings; counts, zero and unknown states are kept', async ({
  page,
}) => {
  await installMocks(page, ['SYN-VEH-001', 'SYN-VEH-002'])
  await page.goto('/vehicles')
  const row1 = page.locator('tr', { has: page.getByRole('link', { name: 'SYN-VEH-001', exact: true }) })
  const row2 = page.locator('tr', { has: page.getByRole('link', { name: 'SYN-VEH-002', exact: true }) })
  await expect(row1.getByRole('link', { name: 'ข้อบกพร่อง 1' })).toHaveAttribute('href', '/vehicle/SYN-VEH-001/inspections')
  await expect(row2.getByText('ไม่พบงานซ่อม/ใบงาน PM ที่เปิด หรือข้อบกพร่องที่บันทึกไว้')).toBeVisible()
  await expect(page.getByText(/ข้อบกพร่องที่บันทึกไว้ไม่ได้บอกว่าแก้ไขแล้วหรือยัง/)).toBeVisible()
  await expect(page.getByText(/การไม่พบรายการไม่ได้ยืนยันว่าไม่มีข้อบกพร่อง/)).toBeVisible()
  await expect(page.getByText(/ข้อบกพร่องที่ค้าง/)).toHaveCount(0)
  await expectNoHorizontalOverflow(page)
})

test('[mocked] a failed findings read stays unknown under the recorded-findings wording', async ({ page }) => {
  await installMocks(page, ['SYN-VEH-001', 'SYN-VEH-002'], { failFindings: true })
  await page.goto('/vehicles')
  await expect(page.getByText('ข้อบกพร่องที่บันทึกไว้: โหลดข้อมูลไม่สำเร็จ')).toBeVisible()
  await expect(page.getByText('ยังไม่ทราบจำนวน: ข้อบกพร่องที่บันทึกไว้', { exact: true })).toHaveCount(2)
  // No zero line mentions findings (zero lines carry .vehicle-indicators__none).
  await expect(page.locator('.vehicle-indicators__none', { hasText: 'ข้อบกพร่อง' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: /^ข้อบกพร่อง \d+$/ })).toHaveCount(0)
  await expect(page.getByText(/ข้อบกพร่องที่ค้าง/)).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'ลองโหลดสรุปงานอีกครั้ง' })).toBeVisible()
  await expectNoHorizontalOverflow(page)
})

test('[unmocked] the real vehicle list keeps seed links and uses the recorded-findings wording', async ({ page }) => {
  await page.goto('/vehicles')
  await expect(page.getByRole('link', { name: 'VEH-1046', exact: true })).toHaveAttribute('href', '/vehicle/VEH-1046')
  await expect(page.getByText(/สรุปงานนับเฉพาะงานซ่อมที่เปิด ใบงาน PM ที่เปิด และข้อบกพร่องที่บันทึกไว้ในระบบ/)).toBeVisible()
  await expect(page.getByText(/ข้อบกพร่องที่ค้าง/)).toHaveCount(0)
  await expect(page.getByText(NO_LINK_NOTE)).toHaveCount(0)
  await expectNoHorizontalOverflow(page)
})
