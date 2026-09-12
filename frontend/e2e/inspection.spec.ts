import { expect, test } from '@playwright/test'

// Phase 3 mobile inspection workflow: QR scan -> Vehicle/Equipment Detail
// -> "ตรวจเช็ค" -> checklist -> "ส่งผลการตรวจ" (baseline "MOBILE
// INSPECTION" + Phase 3 acceptance tests). Runs across every viewport
// project configured in playwright.config.ts (smartphone portrait/
// landscape, tablet portrait/landscape, desktop).
//
// NOTE: "ผ่าน" (PASS) is a substring of "ไม่ผ่าน" (FAIL) and "ตรวจเช็ค"
// is a substring of "ประวัติการตรวจเช็ค" — Playwright's getByRole name
// matching is substring-based by default, so `exact: true` is required
// throughout this file to avoid ambiguous matches.

test('ตรวจเช็ค loads the active checklist automatically and submits an all-PASS inspection', async ({
  page,
}) => {
  await page.goto('/vehicle/VEH-1046')
  await page.getByRole('link', { name: 'ตรวจเช็ค', exact: true }).click()

  await expect(page).toHaveURL(/\/vehicle\/VEH-1046\/inspect/)
  await expect(page.getByRole('heading', { name: /TC-12/ })).toBeVisible()
  await expect(page.getByText('รายการตรวจสอบตัวอย่างที่ 1')).toBeVisible()

  const passButtons = page.getByRole('radio', { name: 'ผ่าน', exact: true })
  await expect(passButtons).toHaveCount(5)

  // PASS/FAIL/N/A must be large, easy-to-tap controls (baseline mobile
  // acceptance test #4).
  const firstPassBox = await passButtons.first().boundingBox()
  expect(firstPassBox?.height).toBeGreaterThanOrEqual(44)

  for (let i = 0; i < 5; i += 1) {
    await passButtons.nth(i).click()
  }

  const submitButton = page.getByRole('button', { name: 'ส่งผลการตรวจ' })
  await expect(submitButton).toBeEnabled()
  await submitButton.click()

  await expect(page).toHaveURL(/\/inspections\/INS-/)
  await expect(page.getByText('รายการตรวจสอบตัวอย่างที่ 1')).toBeVisible()
  await expect(page.getByText('ข้อบกพร่องที่พบ')).toHaveCount(0)

  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1)
})

test('marking an item FAIL shows remark/photo controls immediately and creates a finding', async ({
  page,
}) => {
  // CORRECTION (post-Phase-3 verification): no placeholder/seed checklist
  // item requires a remark or a photo (both are per-item, source-data
  // -driven flags — see backend/app/repositories/mock/seed_data.py). This
  // test attaches a remark and a photo voluntarily to prove FAIL +
  // optional remark + optional evidence still creates a linked finding.
  await page.goto('/vehicle/VEH-1048/inspect')
  await expect(page.getByText('รายการตรวจสอบตัวอย่างที่ 5')).toBeVisible()

  const passButtons = page.getByRole('radio', { name: 'ผ่าน', exact: true })
  for (let i = 0; i < 4; i += 1) {
    await passButtons.nth(i).click()
  }

  const failButtons = page.getByRole('radio', { name: 'ไม่ผ่าน', exact: true })
  await failButtons.nth(4).click()

  const remarkField = page.getByLabel('หมายเหตุ (ถ้ามี)')
  await expect(remarkField).toBeVisible()
  await remarkField.fill('พบรอยรั่วที่จุดตรวจระหว่างทดสอบ')

  await expect(page.getByText('รูปถ่ายหลักฐาน (ถ้ามี)')).toBeVisible()
  await page
    .locator('input[type="file"]')
    .setInputFiles({ name: 'evidence.png', mimeType: 'image/png', buffer: Buffer.from('fake') })
  await expect(page.getByRole('button', { name: 'ลบรูป' })).toBeVisible()

  const submitButton = page.getByRole('button', { name: 'ส่งผลการตรวจ' })
  const submitBox = await submitButton.boundingBox()
  expect(submitBox?.height).toBeGreaterThanOrEqual(44)
  await submitButton.click()

  await expect(page).toHaveURL(/\/inspections\/INS-/)
  await expect(page.getByText('ข้อบกพร่องที่พบ')).toBeVisible()
  await expect(page.getByText('หมายเหตุ: พบรอยรั่วที่จุดตรวจระหว่างทดสอบ')).toBeVisible()
})

test('FAIL is accepted without a remark or photo when the item does not require them', async ({
  page,
}) => {
  await page.goto('/vehicle/VEH-1046/inspect')
  await expect(page.getByText('รายการตรวจสอบตัวอย่างที่ 1')).toBeVisible()

  const passButtons = page.getByRole('radio', { name: 'ผ่าน', exact: true })
  for (let i = 1; i < 5; i += 1) {
    await passButtons.nth(i).click()
  }
  const failButtons = page.getByRole('radio', { name: 'ไม่ผ่าน', exact: true })
  await failButtons.nth(0).click()

  const submitButton = page.getByRole('button', { name: 'ส่งผลการตรวจ' })
  await expect(submitButton).toBeEnabled()
  await submitButton.click()

  await expect(page).toHaveURL(/\/inspections\/INS-/)
  await expect(page.getByText('ข้อบกพร่องที่พบ')).toBeVisible()
})

test('an unknown asset id shows a controlled Thai not-found message instead of the checklist form', async ({
  page,
}) => {
  await page.goto('/vehicle/VEH-9999/inspect')
  await expect(page.getByText('ไม่พบข้อมูลยานพาหนะนี้')).toBeVisible()
  await expect(page.getByRole('button', { name: 'ส่งผลการตรวจ' })).toHaveCount(0)
})

test('inspection history is reachable from Vehicle Detail and lists a submitted inspection', async ({
  page,
}) => {
  await page.goto('/vehicle/VEH-1047/inspect')
  const passButtons = page.getByRole('radio', { name: 'ผ่าน', exact: true })
  await expect(passButtons).toHaveCount(5)
  for (let i = 0; i < 5; i += 1) {
    await passButtons.nth(i).click()
  }
  await page.getByRole('button', { name: 'ส่งผลการตรวจ' }).click()
  await expect(page).toHaveURL(/\/inspections\/INS-/)

  await page.goto('/vehicle/VEH-1047/inspections')
  await expect(page.getByText('ผ่านทุกรายการ').first()).toBeVisible()
})

test('the same inspection engine supports workshop equipment', async ({ page }) => {
  await page.goto('/equipment/EQP-0002')
  await page.getByRole('link', { name: 'ตรวจเช็ค', exact: true }).click()

  await expect(page).toHaveURL(/\/equipment\/EQP-0002\/inspect/)
  await expect(page.getByRole('heading', { name: /ปั๊มลมโรงซ่อม/ })).toBeVisible()

  const passButtons = page.getByRole('radio', { name: 'ผ่าน', exact: true })
  await expect(passButtons).toHaveCount(4)
  for (let i = 0; i < 4; i += 1) {
    await passButtons.nth(i).click()
  }
  await page.getByRole('button', { name: 'ส่งผลการตรวจ' }).click()
  await expect(page).toHaveURL(/\/inspections\/INS-/)
})

test('missing checklist item selection is blocked and a Thai not-found record shows for an unknown inspection id', async ({
  page,
}) => {
  await page.goto('/vehicle/VEH-1046/inspect')
  const submitButton = page.getByRole('button', { name: 'ส่งผลการตรวจ' })
  await expect(submitButton).toBeDisabled()

  await page.goto('/inspections/INS-DOES-NOT-EXIST')
  await expect(page.getByText('ไม่พบข้อมูลผลการตรวจเช็คนี้')).toBeVisible()
})
