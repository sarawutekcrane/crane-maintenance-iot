import { expect, test } from '@playwright/test'

// Web/API Phase 6 Batch 1 — Driver / Operator master + vehicle<->driver
// assignment history mobile workflows. Runs across every viewport project
// configured in playwright.config.ts, which all share one backend/mock
// repository process — every test below therefore creates its own
// project-unique driver (via a direct API call, mirroring
// parts-lifetime.spec.ts's own `${test.info().project.name}` uniqueness
// technique) rather than asserting exact counts against the shared seeded
// VEH-1046/VEH-1047 rows, which other parallel projects running this same
// file also mutate. Project decision (targeted correction): creating a
// new assignment (PRIMARY or not) never modifies/ends any other
// assignment, and ending an assignment is idempotent — both proven with
// full isolation by the backend's own tests/test_driver_phase6_batch1.py;
// this file's job is the mobile/responsive UI workflow.

async function createDriver(page: import('@playwright/test').Page, label: string) {
  const suffix = `${test.info().project.name}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  const response = await page.request.post('/api/v1/drivers', {
    data: { driver_name_th: `E2E ${label} ${suffix}` },
  })
  return (await response.json()) as { driver_id: string; driver_name_th: string }
}

test('Vehicle Detail links to the driver/operator assignment history, which shows the seeded active period', async ({
  page,
}) => {
  await page.goto('/vehicle/VEH-1046')
  const driverLink = page.getByRole('link', { name: 'คนขับ/ผู้ควบคุม' })
  const linkBox = await driverLink.boundingBox()
  expect(linkBox?.height).toBeGreaterThanOrEqual(44)
  await driverLink.click()

  await expect(page).toHaveURL(/\/vehicle\/VEH-1046\/drivers/)
  await expect(page.getByRole('link', { name: 'DRV-0001' })).toBeVisible()
  // At least one currently-active assignment is shown (seeded).
  await expect(page.getByText('ยังคงมอบหมายอยู่').first()).toBeVisible()

  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1)
})

test('assigning a new PRIMARY driver appears in the vehicle history as an active period', async ({
  page,
}) => {
  const driver = await createDriver(page, 'PRIMARY')

  await page.goto('/vehicle/VEH-1046/drivers')
  await page.getByRole('button', { name: '+ มอบหมายคนขับ/ผู้ควบคุม' }).click()
  await page.getByLabel('รหัสคนขับ/ผู้ควบคุม (driver_id)').fill(driver.driver_id)
  await page.getByLabel('เป็นผู้ขับ/ผู้ควบคุมหลัก (PRIMARY)').check()
  await page.getByRole('button', { name: 'บันทึก' }).click()

  const newRow = page.locator('.card', { hasText: driver.driver_id })
  await expect(newRow).toBeVisible()
  await expect(newRow.getByText('ยังคงมอบหมายอยู่')).toBeVisible()
  await expect(newRow.getByText('ผู้ขับ/ผู้ควบคุมหลัก (PRIMARY)')).toBeVisible()
})

test('ending an assignment preserves it in the history instead of removing it', async ({ page }) => {
  const driver = await createDriver(page, 'END')

  await page.goto('/vehicle/VEH-1047/drivers')
  await page.getByRole('button', { name: '+ มอบหมายคนขับ/ผู้ควบคุม' }).click()
  await page.getByLabel('รหัสคนขับ/ผู้ควบคุม (driver_id)').fill(driver.driver_id)
  await page.getByRole('button', { name: 'บันทึก' }).click()

  const row = page.locator('.card', { hasText: driver.driver_id })
  await expect(row).toBeVisible()
  await expect(row.getByRole('button', { name: 'สิ้นสุดการมอบหมาย' })).toBeVisible()
  await row.getByRole('button', { name: 'สิ้นสุดการมอบหมาย' }).click()

  // The row is still shown — ended (no more end-button), not deleted.
  await expect(row).toBeVisible()
  await expect(row.getByRole('button', { name: 'สิ้นสุดการมอบหมาย' })).toHaveCount(0)
  await expect(row.getByText('ยังคงมอบหมายอยู่')).toHaveCount(0)
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
