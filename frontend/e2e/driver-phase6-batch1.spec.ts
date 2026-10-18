import { expect, test } from '@playwright/test'

// Web/API Phase 6 Batch 1 — Driver / Operator master mobile workflows. Runs
// across every viewport project configured in playwright.config.ts, which all
// share one backend/mock repository process — every test below therefore
// creates its own project-unique driver (via a direct API call) rather than
// asserting exact counts against shared seeded rows.
//
// R2 Batch R2-C3 (A2-8 / A2-10, owner decisions D1-D4) retired the Phase 6
// vehicle<->driver assignment page, link and routes; their workflow tests are
// replaced by one cutover test proving they are gone and that the two R2
// panels (permanent responsible driver, E2 day / shift) replace them.

async function createDriver(page: import('@playwright/test').Page, label: string) {
  const suffix = `${test.info().project.name}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  const response = await page.request.post('/api/v1/drivers', {
    data: { driver_name_th: `E2E ${label} ${suffix}` },
  })
  return (await response.json()) as { driver_id: string; driver_name_th: string }
}

test('R2-C3: the retired Phase 6 vehicle-driver page, link and API are gone; the two R2 panels replace them', async ({
  page,
  request,
}) => {
  const api: string[] = []
  page.on('request', (r) => api.push(new URL(r.url()).pathname))
  await page.goto('/vehicle/VEH-1048')
  await expect(page.getByRole('heading', { name: 'ผู้รับผิดชอบรถประจำ' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'การมอบหมายผู้ขับรถตามวัน/กะ' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'คนขับ/ผู้ควบคุม', exact: true })).toHaveCount(0)
  await expect(page.locator('a[href="/vehicle/VEH-1048/drivers"]')).toHaveCount(0)
  // The old URL no longer renders the legacy page (no redirect, no fallback).
  await page.goto('/vehicle/VEH-1046/drivers')
  await expect(page.getByRole('button', { name: '+ มอบหมายคนขับ/ผู้ควบคุม' })).toHaveCount(0)
  expect(api.some((p) => /\/driver-assignments$|\/vehicle-driver-assignments\//.test(p))).toBe(false)
  // The three retired routes answer 404 and write nothing.
  expect((await request.get('/api/v1/vehicles/VEH-1046/driver-assignments')).status()).toBe(404)
  expect((await request.post('/api/v1/vehicles/VEH-1046/driver-assignments', { data: { driver_id: 'DRV-0001' } })).status()).toBe(404)
  expect((await request.post('/api/v1/vehicle-driver-assignments/VDRV-0001/end')).status()).toBe(404)
})

test('Driver list search opens a driver detail page and an edit round-trips through the API', async ({
  page,
}) => {
  const driver = await createDriver(page, 'ค้นหา')

  await page.goto('/drivers')
  await page.getByLabel('ค้นหา (ชื่อ/เบอร์โทร/เลขใบขับขี่)').fill(driver.driver_name_th)
  await page.getByRole('button', { name: 'ค้นหา' }).click()

  await page.getByRole('link', { name: driver.driver_name_th }).click()
  await expect(page).toHaveURL(new RegExp(`/drivers/${driver.driver_id}`))

  await page.getByRole('button', { name: 'แก้ไขข้อมูล' }).click()
  await page.getByLabel('เบอร์โทร').fill('080-111-9999')
  await page.getByRole('button', { name: 'บันทึก' }).click()

  await expect(page.locator('.status-card__row', { hasText: 'เบอร์โทร' })).toContainText(
    '080-111-9999',
  )
})
