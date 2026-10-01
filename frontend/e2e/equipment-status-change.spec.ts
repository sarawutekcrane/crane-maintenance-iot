import { expect, test, type Page } from '@playwright/test'

// Phase 7 Batch 7K2 — equipment status change outcomes (DEC-K6(a)).
// The success case runs against the REAL mock backend (no route mocking).
// It uses a SAME-STATUS change on EQP-0003 (seeded MAINTENANCE) so the shared
// backend's equipment statuses stay as other specs expect; history rows are
// appended, so assertions use a reason unique to the project + run.
// Failure envelopes are produced by mocking ONLY the POST; the detail and
// history GETs still reach the real mock backend unless a test says otherwise.

const STATUS_URL = '**/api/v1/equipment/EQP-0003/status'

function envelope(code: string, details: Record<string, unknown> | null) {
  return JSON.stringify({ error: { code, message: code, details, request_id: 'req-e2e-7k2' } })
}

async function openDialog(page: Page) {
  await page.goto('/equipment/EQP-0003')
  await expect(page.getByRole('heading', { name: /เครื่องเชื่อม/ })).toBeVisible()
  await page.getByRole('button', { name: 'เปลี่ยนสถานะการใช้งาน' }).click()
  await expect(page.getByRole('alertdialog')).toBeVisible()
}

function trackRequests(page: Page) {
  const seen: { method: string; path: string }[] = []
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (url.pathname.startsWith('/api/v1/equipment/EQP-0003')) seen.push({ method: request.method(), path: url.pathname })
  })
  return seen
}

test('[real mock backend] a status change closes the dialog and the reason appears in the history', async ({
  page,
}, testInfo) => {
  const reason = `e2e-7k2-${testInfo.project.name}-${Date.now()}`
  await openDialog(page)
  await page.getByLabel('เหตุผล (ไม่บังคับ)').fill(reason)
  await page.getByRole('button', { name: 'ยืนยันเปลี่ยนสถานะ' }).click()
  await expect(page.getByRole('alertdialog')).toBeHidden()
  await page.getByText(/ประวัติการเปลี่ยนสถานะ \(\d+\)/).click()
  await expect(page.getByText(reason, { exact: false })).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('a rejected update keeps the dialog open with its values and does not reload', async ({ page }) => {
  const seen = trackRequests(page)
  await page.route(STATUS_URL, (route) =>
    route.fulfill({ status: 503, contentType: 'application/json',
      body: envelope('EQUIPMENT_MASTER_WRITE_FAILED', { equipment_write_outcome: 'rejected' }) }),
  )
  await openDialog(page)
  await page.getByLabel('สถานะใหม่').selectOption({ label: 'งดใช้งานชั่วคราว' })
  await page.getByLabel('เหตุผล (ไม่บังคับ)').fill('0007')
  await page.getByRole('button', { name: 'ยืนยันเปลี่ยนสถานะ' }).click()

  const dialog = page.getByRole('alertdialog')
  await expect(dialog.getByRole('alert')).toContainText('Google Sheets ปฏิเสธคำขอเปลี่ยนสถานะ')
  await expect(page.getByLabel('สถานะใหม่')).toHaveValue('OUT_OF_SERVICE')
  await expect(page.getByLabel('เหตุผล (ไม่บังคับ)')).toHaveValue('0007')
  const post = seen.findIndex((r) => r.method === 'POST')
  expect(seen.slice(post + 1)).toEqual([])
  expect(seen.filter((r) => r.method === 'POST')).toHaveLength(1)
})

test('an unknown history outcome shows a page warning, refreshes once and never repeats the POST', async ({
  page,
}) => {
  const seen = trackRequests(page)
  await page.route(STATUS_URL, (route) =>
    route.fulfill({ status: 503, contentType: 'application/json',
      body: envelope('EQUIPMENT_STATUS_HISTORY_WRITE_FAILED', { equipment_status_updated: true, history_write_outcome: 'unknown' }) }),
  )
  await openDialog(page)
  await page.getByRole('button', { name: 'ยืนยันเปลี่ยนสถานะ' }).click()

  const warning = page.getByRole('alert').filter({ hasText: 'ไม่ทราบผลการบันทึกประวัติ' })
  await expect(warning).toBeVisible()
  await expect(warning).toBeInViewport()
  await expect(page.getByRole('alertdialog')).toBeHidden()
  // Exactly one refresh (detail + history) after the POST; the initial load may
  // run twice under React StrictMode in the dev server, so count after the POST.
  const afterPost = () => seen.slice(seen.findIndex((r) => r.method === 'POST') + 1)
  await expect.poll(() => afterPost().length).toBe(2)
  expect(afterPost().every((r) => r.method === 'GET')).toBe(true)
  expect(seen.filter((r) => r.method === 'POST')).toHaveLength(1)
  await page.getByRole('button', { name: 'ปิดคำเตือน' }).click()
  await expect(warning).toBeHidden()
})

test('a failed refresh keeps the shown equipment and warning and offers a manual reload', async ({ page }) => {
  let posted = false
  await page.route(STATUS_URL, (route) => {
    posted = true
    return route.fulfill({ status: 503, contentType: 'application/json',
      body: envelope('EQUIPMENT_MASTER_WRITE_FAILED', { equipment_write_outcome: 'unknown' }) })
  })
  await page.route('**/api/v1/equipment/EQP-0003', (route) =>
    posted
      ? route.fulfill({ status: 503, contentType: 'application/json', body: envelope('EQUIPMENT_MASTER_READ_FAILED', null) })
      : route.continue(),
  )
  await openDialog(page)
  await page.getByRole('button', { name: 'ยืนยันเปลี่ยนสถานะ' }).click()

  await expect(page.getByText('โหลดข้อมูลล่าสุดไม่สำเร็จ ข้อมูลที่แสดงอาจไม่เป็นปัจจุบัน')).toBeVisible()
  await expect(page.getByRole('heading', { name: /เครื่องเชื่อม/ })).toBeVisible()
  await expect(page.getByRole('alert').filter({ hasText: 'ไม่ทราบผลการเปลี่ยนสถานะ' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'โหลดใหม่' })).toBeVisible()

  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1)
})

test('a refresh whose history read fails keeps the shown equipment and history and shows both notices', async ({
  page,
}) => {
  // 7K2 correction (Finding 1): equipment detail succeeds, history fails.
  let posted = false
  await page.route(STATUS_URL, (route) => {
    posted = true
    return route.fulfill({ status: 503, contentType: 'application/json',
      body: envelope('EQUIPMENT_MASTER_WRITE_FAILED', { equipment_write_outcome: 'unknown' }) })
  })
  await page.route('**/api/v1/equipment/EQP-0003', (route) =>
    posted
      ? route.fulfill({ status: 200, contentType: 'application/json',
          body: JSON.stringify({ equipment_id: 'EQP-0003', equipment_code: 'WELD-01', name: 'ชื่อที่ไม่ควรแสดง',
            category: 'WELDING', serial_number: null, location: null, operational_status: 'MAINTENANCE',
            created_at: '2026-01-15T08:00:00Z', updated_at: '2026-01-15T08:00:00Z' }) })
      : route.continue(),
  )
  await page.route('**/api/v1/equipment/EQP-0003/status-history', (route) =>
    posted
      ? route.fulfill({ status: 500, contentType: 'application/json',
          body: envelope('EQUIPMENT_STATUS_HISTORY_DATA_INVALID', { issue_counts: { BLANK_STATUS: 1 } }) })
      : route.continue(),
  )
  await openDialog(page)
  const summary = page.getByText(/ประวัติการเปลี่ยนสถานะ \(\d+\)/)
  const before = (await summary.count()) > 0 ? await summary.textContent() : null
  await page.getByRole('button', { name: 'ยืนยันเปลี่ยนสถานะ' }).click()

  await expect(page.getByText('โหลดข้อมูลล่าสุดไม่สำเร็จ ข้อมูลที่แสดงอาจไม่เป็นปัจจุบัน')).toBeVisible()
  await expect(page.getByRole('button', { name: 'โหลดใหม่' })).toBeVisible()
  await expect(page.getByText('แสดงประวัติการเปลี่ยนสถานะไม่ได้', { exact: false })).toBeVisible()
  await expect(page.getByRole('heading', { name: /เครื่องเชื่อม/ })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'ชื่อที่ไม่ควรแสดง' })).toHaveCount(0)
  if (before !== null) await expect(summary).toHaveText(before)
  await expect(page.getByRole('alert').filter({ hasText: 'ไม่ทราบผลการเปลี่ยนสถานะ' })).toBeVisible()
})
