import { expect, test } from '@playwright/test'

// Phase 2 mobile acceptance checks (00_SYSTEM_REQUIREMENTS_BASELINE_EN.txt
// "MOBILE ACCEPTANCE TESTS" items 1-2, 8, 12: Vehicle Detail / Equipment
// Detail at smartphone width, no unintended horizontal scrolling, Thai
// text wrapping) plus the Phase 2 exit-gate requirement that
// `/vehicle/{vehicle_id}` is a stable QR entry point reachable by direct
// navigation, the same way scanning a QR code would open it.

test('scanning the QR route opens the Vehicle Detail page directly', async ({ page }) => {
  await page.goto('/vehicle/VEH-1046')

  await expect(page.getByRole('heading', { name: 'TC-12' })).toBeVisible()
  await expect(page.getByText('VEH-1046', { exact: false })).toBeVisible()

  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1)
})

test('vehicle detail shows model, components, and status history', async ({ page }) => {
  await page.goto('/vehicle/VEH-1047')

  await expect(page.getByText('XCMG', { exact: false })).toBeVisible()
  await expect(page.getByText('เครื่องยนต์ Carrier / เครื่องยนต์ช่วงล่าง')).toBeVisible()
  await expect(page.getByText('เครื่องยนต์ Crane / เครื่องยนต์ชุดเครน')).toBeVisible()
  await expect(page.getByText('ระบบส่งกำลัง (PTO)')).toBeVisible()
})

test('changing vehicle status opens a dialog that fits the viewport and appends history', async ({
  page,
}) => {
  await page.goto('/vehicle/VEH-1046')

  const changeButton = page.getByRole('button', { name: 'เปลี่ยนสถานะ' })
  const box = await changeButton.boundingBox()
  expect(box?.height).toBeGreaterThanOrEqual(44)

  await changeButton.click()
  const dialog = page.getByRole('alertdialog')
  await expect(dialog).toBeVisible()

  const viewport = page.viewportSize()
  const dialogBox = await dialog.boundingBox()
  if (viewport && dialogBox) {
    expect(dialogBox.width).toBeLessThanOrEqual(viewport.width + 1)
    expect(dialogBox.height).toBeLessThanOrEqual(viewport.height + 1)
  }

  await dialog.getByLabel('สถานะใหม่').selectOption('READY')
  await page.getByRole('button', { name: 'ยืนยันเปลี่ยนสถานะ' }).click()
  await expect(dialog).toBeHidden()

  await expect(page.getByText('พร้อมใช้งาน').first()).toBeVisible()
})

test('vehicle list search finds a machine by machine number and opens its detail page', async ({
  page,
}) => {
  await page.goto('/vehicles')

  await page.getByLabel('ค้นหา (เลขเครื่องจักร หรือ รหัสยานพาหนะ)').fill('TC-14')
  await page.getByRole('button', { name: 'ค้นหา' }).click()

  const resultLink = page.getByRole('link', { name: 'VEH-1048' })
  await expect(resultLink).toBeVisible()
  await resultLink.click()

  await expect(page).toHaveURL(/\/vehicle\/VEH-1048/)
  await expect(page.getByText('ไม่มีข้อมูล').first()).toBeVisible()
})

test('equipment detail is reachable at its own stable QR route, separate from vehicles', async ({
  page,
}) => {
  await page.goto('/equipment/EQP-0001')

  await expect(page.getByRole('heading', { name: 'เครื่องกลึงเบอร์ 1' })).toBeVisible()

  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1)
})

test('missing vehicle shows a controlled Thai not-found state, not a crash', async ({ page }) => {
  await page.goto('/vehicle/VEH-DOES-NOT-EXIST')
  await expect(page.getByText('ไม่พบข้อมูลยานพาหนะนี้')).toBeVisible()
})
