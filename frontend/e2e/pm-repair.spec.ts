import { expect, test } from '@playwright/test'

// Phase 4 PM/Repair mobile workflows (00_SYSTEM_REQUIREMENTS_BASELINE_EN.txt
// MOBILE VEHICLE DETAIL / MOBILE REPAIR REPORTING + Phase 4 acceptance
// tests: PM work order works, task result points to exact revision,
// snapshot captured, manual repair works, finding can link/convert to
// repair, action history is append-only, close preserves history, PM and
// Repair remain separate). Runs across every viewport project configured
// in playwright.config.ts.

test('PM: start a work order from Vehicle Detail, capture a meter reading and an actual part, then close it', async ({
  page,
}) => {
  await page.goto('/vehicle/VEH-1046')
  await page.getByRole('link', { name: 'PM', exact: true }).click()

  await expect(page).toHaveURL(/\/vehicle\/VEH-1046\/pm/)
  await expect(page.getByText(/แผนบำรุงรักษาเชิงป้องกัน PLAN1/)).toBeVisible()
  await expect(page.getByText(/E02.*E03.*E04/)).toBeVisible()

  const startButton = page.getByRole('button', { name: 'เริ่มทำ PM' })
  const startBox = await startButton.boundingBox()
  expect(startBox?.height).toBeGreaterThanOrEqual(44)
  await startButton.click()

  await expect(page).toHaveURL(/\/pm\/work-orders\/PMWO-/)
  await expect(page.getByText('งานบำรุงรักษาตัวอย่างที่ 1 (PLAN1)')).toBeVisible()

  // Core Demo Fixes APPROVED CORE RULE: the machine-state snapshot is
  // backend-derived and shown read-only here — never a manually-typed
  // counter/GPS field. Only the dimensions this vehicle's own
  // components actually define appear (ENGINE_HOUR from CARRIER_ENGINE),
  // never a fabricated field.
  await expect(page.getByText('ค่ามาตรวัดปัจจุบัน (อ่านอย่างเดียว)')).toBeVisible()
  await expect(page.getByText('ชั่วโมงเครื่องยนต์')).toBeVisible()

  await page.getByText('+ เพิ่มอะไหล่ที่ใช้').first().click()
  await page.getByLabel('ชื่ออะไหล่').first().fill('ไส้กรองน้ำมันเครื่อง (ตัวอย่าง)')

  await page.getByRole('button', { name: 'บันทึกผลงาน' }).first().click()
  await expect(page.getByText('ผลงาน: เสร็จสิ้น')).toBeVisible()
  await expect(page.getByText('ไส้กรองน้ำมันเครื่อง (ตัวอย่าง)')).toBeVisible()
  await expect(page.getByText(/บันทึกค่ามาตรวัดแล้ว/)).toBeVisible()

  // Submit the remaining two placeholder tasks with defaults.
  await page.getByRole('button', { name: 'บันทึกผลงาน' }).first().click()
  await page.getByRole('button', { name: 'บันทึกผลงาน' }).first().click()
  await expect(page.getByRole('button', { name: 'บันทึกผลงาน' })).toHaveCount(0)

  await page.getByRole('button', { name: 'ปิดใบสั่งงาน PM' }).click()
  await expect(page.getByText('ปิดงานแล้ว')).toBeVisible()

  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1)
})

test('PM history lists a closed work order for the vehicle', async ({ page }) => {
  await page.goto('/vehicle/VEH-1047/pm')
  await page.getByRole('button', { name: 'เริ่มทำ PM' }).click()
  await expect(page).toHaveURL(/\/pm\/work-orders\/PMWO-/)
  await page.getByRole('button', { name: 'ปิดใบสั่งงาน PM' }).click()
  await expect(page.getByText('ปิดงานแล้ว')).toBeVisible()

  await page.goto('/vehicle/VEH-1047/pm/history')
  await expect(page.getByText('ปิดงานแล้ว').first()).toBeVisible()
})

test('Repair: report a MANUAL repair, append an action and a part, then close it', async ({
  page,
}) => {
  await page.goto('/vehicle/VEH-1047')
  await page.getByRole('link', { name: 'แจ้งซ่อม', exact: true }).click()

  await expect(page).toHaveURL(/\/vehicle\/VEH-1047\/repairs\/new/)
  await expect(page.getByText('แจ้งซ่อมด้วยตนเอง')).toBeVisible()
  await page.getByLabel('อาการ/ปัญหาที่พบ').fill('มีเสียงดังผิดปกติบริเวณเครื่องยนต์')

  await page.getByRole('button', { name: 'ส่งแจ้งซ่อม' }).click()
  await expect(page).toHaveURL(/\/repairs\/RPR-/)
  await expect(page.getByText('กำลังดำเนินการ')).toBeVisible()

  await page.getByLabel('เพิ่มการดำเนินการ').fill('ตรวจสอบเบื้องต้นและถอดตรวจ')
  await page.getByRole('button', { name: 'บันทึกการดำเนินการ' }).click()
  await expect(page.getByText('ตรวจสอบเบื้องต้นและถอดตรวจ')).toBeVisible()

  // Standard interaction is search/select from Part Master; free text is
  // an explicit fallback for an unregistered part (Core Demo Fixes,
  // REPAIR PARTS section E).
  await page
    .getByRole('button', {
      name: 'ไม่พบอะไหล่ในระบบ — ระบุชื่อเอง (สำหรับอะไหล่ที่ยังไม่ได้ลงทะเบียน)',
    })
    .click()
  await page.getByLabel('ชื่ออะไหล่').fill('สายพานพัดลม (ตัวอย่าง)')
  await page.getByRole('button', { name: '+ เพิ่มอะไหล่' }).click()
  await expect(page.getByText('สายพานพัดลม (ตัวอย่าง)')).toBeVisible()

  await page.getByRole('button', { name: 'ปิดใบแจ้งซ่อม' }).click()
  await expect(page.getByText('ปิดงานแล้ว')).toBeVisible()
  // Previous action remains readable after closing (append-only history).
  await expect(page.getByText('ตรวจสอบเบื้องต้นและถอดตรวจ')).toBeVisible()
})

test('a Finding on an inspection can link to a new repair without auto-creating one', async ({
  page,
}) => {
  await page.goto('/vehicle/VEH-1048/inspect')
  const passButtons = page.getByRole('radio', { name: 'ผ่าน', exact: true })
  await expect(passButtons).toHaveCount(5)
  for (let i = 0; i < 4; i += 1) {
    await passButtons.nth(i).click()
  }
  await page.getByRole('radio', { name: 'ไม่ผ่าน', exact: true }).nth(4).click()
  await page.getByRole('button', { name: 'ส่งผลการตรวจ' }).click()
  await expect(page).toHaveURL(/\/inspections\/INS-/)

  await expect(page.getByText('ข้อบกพร่องที่พบ')).toBeVisible()
  await page.getByRole('link', { name: 'แจ้งซ่อม', exact: true }).click()

  await expect(page).toHaveURL(/\/vehicle\/VEH-1048\/repairs\/new\?source_type=FINDING/)
  await expect(page.getByText('ข้อบกพร่องจากการตรวจเช็ค').first()).toBeVisible()
  await expect(page.getByText(/รายการนี้เชื่อมโยงมาจาก/)).toBeVisible()

  await page.getByRole('button', { name: 'ส่งแจ้งซ่อม' }).click()
  await expect(page).toHaveURL(/\/repairs\/RPR-/)
  await expect(page.getByText('ข้อบกพร่องจากการตรวจเช็ค').first()).toBeVisible()
})

test('workshop equipment reaches PM (empty state) and Repair from Equipment Detail', async ({
  page,
}) => {
  await page.goto('/equipment/EQP-0001')
  await page.getByRole('link', { name: 'PM', exact: true }).click()
  await expect(page).toHaveURL(/\/equipment\/EQP-0001\/pm/)
  // No PM plan applies to workshop equipment yet (PLAN1 is VEHICLE-only) —
  // a clean empty state, not a fabricated equipment PM plan.
  await expect(page.getByText('ยังไม่มีแผนบำรุงรักษาที่ใช้งานสำหรับสินทรัพย์นี้')).toBeVisible()

  await page.goto('/equipment/EQP-0001')
  await page.getByRole('link', { name: 'แจ้งซ่อม', exact: true }).click()
  await expect(page).toHaveURL(/\/equipment\/EQP-0001\/repairs\/new/)
  // Equipment has no approved counter model (C03 deferred) — no meter
  // capture fields are rendered for equipment.
  await expect(page.getByText('เลขไมล์ (ODOMETER)')).toHaveCount(0)
  await page.getByLabel('อาการ/ปัญหาที่พบ').fill('มอเตอร์มีเสียงดัง')
  await page.getByRole('button', { name: 'ส่งแจ้งซ่อม' }).click()
  await expect(page).toHaveURL(/\/repairs\/RPR-/)
})
