import { randomUUID } from 'node:crypto'
import { expect, test, type APIRequestContext } from '@playwright/test'

// Phase 5 Parts/Lifetime/Transfer mobile workflows
// (05_PHASE5_PARTS_LIFETIME_TRANSFER_EN.txt acceptance tests: consumable
// does not require instance, position lifetime does not require every
// serial, instance can start on demand, transfer preserves accumulated
// usage, repair pause behaves correctly, no preload of every physical
// part is required). Runs across every viewport project configured in
// playwright.config.ts.
//
// R6 (deliberate migration, FINAL plan §7.2a / §7.5, Owner decisions A-2(i) / A-3 OFF): vehicle part
// writes need the vehicle in the request's TEST/REAL scope (the mock's TEST-scoped vehicle is
// VEH-1048; VEH-1046/1047 are REAL-scoped references); an IN_REPAIR part is returned from repair before
// it can be installed; and because this backend is shared by every viewport project, each instance is
// registered with a unique tag label so identical-looking instances stay distinguishable (R3-05).

// R4 PM Workflow (Owner E01 A3, EV-044 / EV-045 — deliberate test migration): a Technician V2
// PM item is recorded only after the work order has a valid current V2 team and is STARTed
// (IN_PROGRESS), and each item is a truthful Performed / Not Performed outcome. The default
// dev user (`can_manage_pm`) assigns the seeded synthetic TEST team and starts the job here;
// the same pattern as e2e/pm-repair.spec.ts.
async function assignTeamAndStart(request: APIRequestContext, workOrderId: string): Promise<void> {
  const assigned = await request.post(`/api/v1/pm/work-orders/${workOrderId}/technician-assignments`, {
    data: { primary_technician_id: 'TEC-TEST-911', collaborator_technician_ids: ['TEC-TEST-912'], expected_current: null },
    headers: { 'X-Request-Id': randomUUID() },
  })
  expect(assigned.ok(), await assigned.text()).toBe(true)
  const started = await request.post(`/api/v1/pm/work-orders/${workOrderId}/start`, {
    data: {},
    headers: { 'X-Request-Id': randomUUID() },
  })
  expect(started.ok(), await started.text()).toBe(true)
}

function workOrderIdOf(url: string): string {
  const match = /\/pm\/work-orders\/(PMWO-[^/?#]+)/.exec(url)
  expect(match, 'on a PM work order page').not.toBeNull()
  return match![1]
}

test('Part Master: search the catalog and open a CONSUMABLE part with no instance concept', async ({
  page,
}) => {
  await page.goto('/parts')
  await page.getByLabel('ค้นหา (ชื่อ/รหัสอะไหล่)').fill('ไส้กรองน้ำมันเครื่อง')
  await page.getByRole('button', { name: 'ค้นหา' }).click()

  await expect(page.getByRole('link', { name: 'OIL-FILTER-A' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'OIL-FILTER-B' })).toBeVisible()

  await page.getByRole('link', { name: 'OIL-FILTER-A' }).click()
  await expect(page).toHaveURL(/\/parts\/PART-0002/)
  const modeRow = page.locator('.status-card__row', { hasText: 'โหมดการติดตามอายุการใช้งาน' })
  await expect(modeRow).toContainText('วัสดุสิ้นเปลือง')
  // CONSUMABLE never shows an instance-registration action.
  await expect(page.getByText('+ ลงทะเบียนชิ้นงานใหม่')).toHaveCount(0)

  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1)
})

test('INSTANCE_TRACKED: register a part instance on demand, install it, then transfer it to another vehicle', async ({
  page,
}) => {
  await page.goto('/parts/PART-0005')
  await expect(page.getByText('ติดตามรายชิ้น (มีรหัสชิ้นงานเฉพาะ)')).toBeVisible()

  const registerButton = page.getByRole('link', { name: '+ ลงทะเบียนชิ้นงานใหม่' })
  const registerBox = await registerButton.boundingBox()
  expect(registerBox?.height).toBeGreaterThanOrEqual(44)
  await registerButton.click()

  await expect(page).toHaveURL(/\/parts\/PART-0005\/instances\/new/)
  await page.getByLabel('ป้ายระบุชิ้น (ถ้ามี)').fill(`E2E-TAG-${randomUUID()}`)
  await page.getByLabel('ประวัติการใช้งานก่อนเริ่มติดตาม').selectOption('UNKNOWN')
  await page.getByRole('button', { name: 'ลงทะเบียนชิ้นงาน' }).click()

  await expect(page).toHaveURL(/\/part-instances\/PINST-/)
  await expect(page.getByText('พร้อมติดตั้ง', { exact: true }).first()).toBeVisible()

  // Install on VEH-1048 — asset selection is searchable/selectable (Core
  // Demo Fixes, PART INSTANCE / LIFETIME CORRECTIONS), never raw ID typing.
  await page.getByRole('button', { name: 'ติดตั้ง', exact: true }).click()
  await page.getByLabel('ค้นหายานพาหนะ/อุปกรณ์').fill('VEH-1048')
  await page.getByRole('button', { name: /VEH-1048/ }).first().click()
  await page.getByLabel('ตำแหน่งติดตั้ง (ถ้ามี)').fill(`MAIN-PUMP-${randomUUID()}`)
  await page.getByRole('button', { name: 'ยืนยันการติดตั้ง' }).click()
  await expect(page.getByText('ติดตั้งใช้งานอยู่').first()).toBeVisible()
  await expect(page.getByText(/VEH-1048/).first()).toBeVisible()

  // Transfer to workshop equipment EQP-0002 (the mock's TEST-scoped equipment; R6 CG-1) — the previous installation segment
  // on VEH-1048 remains readable afterward (append-oriented history, same cycle).
  await page.getByRole('button', { name: 'โยกย้ายไปยานพาหนะ/อุปกรณ์อื่น' }).click()
  await page.getByLabel('ประเภทสินทรัพย์ปลายทาง').selectOption('EQUIPMENT')
  await page.getByLabel('ค้นหายานพาหนะ/อุปกรณ์').fill('EQP-0002')
  await page.getByRole('button', { name: /EQP-0002/ }).first().click()
  await page.getByRole('button', { name: 'ยืนยันการโยกย้าย' }).click()

  await expect(page.getByText('ติดตั้งอยู่ปัจจุบัน')).toBeVisible()
  await expect(page.getByText('สิ้นสุดการติดตั้งแล้ว')).toBeVisible()
  const rows = page.locator('li:has-text("VEH-1048"), li:has-text("EQP-0002")')
  await expect(rows).toHaveCount(2)
  await expect(page.getByText(/รอบที่ \d/)).toHaveCount(1) // a transfer never opens a cycle
})

test('an instance removed into IN_REPAIR shows no active installation and can be re-installed afterward', async ({
  page,
}) => {
  await page.goto('/parts/PART-0005/instances/new')
  await page.getByLabel('ป้ายระบุชิ้น (ถ้ามี)').fill(`E2E-TAG-${randomUUID()}`)
  await page.getByRole('button', { name: 'ลงทะเบียนชิ้นงาน' }).click()
  await expect(page).toHaveURL(/\/part-instances\/PINST-/)

  await page.getByRole('button', { name: 'ติดตั้ง', exact: true }).click()
  await page.getByLabel('ค้นหายานพาหนะ/อุปกรณ์').fill('VEH-1048')
  await page.getByRole('button', { name: /VEH-1048/ }).first().click()
  await page.getByRole('button', { name: 'ยืนยันการติดตั้ง' }).click()
  await expect(page.getByText('ติดตั้งใช้งานอยู่').first()).toBeVisible()

  await page.getByRole('button', { name: 'ถอดออก', exact: true }).click()
  await page.getByLabel('สถานะหลังถอดออก').selectOption('IN_REPAIR')
  await page.getByLabel('เหตุผล (ถ้ามี)').fill('ตรวจสภาพตามปกติ')
  await page.getByRole('button', { name: 'ยืนยันการถอดออก' }).click()

  await expect(page.getByText('อยู่ระหว่างซ่อม').first()).toBeVisible()
  // No ACTIVE segment remains visible — the pump cannot be accumulating
  // any host vehicle's operating hours while IN_REPAIR.
  await expect(page.getByText('ติดตั้งอยู่ปัจจุบัน')).toHaveCount(0)

  // A-2(i): no direct install from IN_REPAIR — the part is returned from repair first (a normal
  // repair, no new-cycle approval), which never starts a new cycle.
  await expect(page.getByRole('button', { name: 'ติดตั้ง', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'รับกลับจากซ่อม' }).click()
  await page.getByRole('button', { name: 'ยืนยันรับกลับจากซ่อม' }).click()
  await expect(page.getByText('พร้อมติดตั้ง').first()).toBeVisible()

  // The asset picker keeps its prior selection (VEH-1048) across the
  // remove/re-install cycle, so re-installing on the same asset needs no
  // new search — only a different target would need "เปลี่ยน" first.
  await page.getByRole('button', { name: 'ติดตั้ง', exact: true }).click()
  await expect(page.getByText('เลือกแล้ว: VEH-1048')).toBeVisible()
  await page.getByRole('button', { name: 'ยืนยันการติดตั้ง' }).click()
  await expect(page.getByText('ติดตั้งใช้งานอยู่').first()).toBeVisible()
  await expect(page.getByText(/รอบที่ \d/)).toHaveCount(1) // a normal repair never resets the cycle
})

test('POSITION_LIFETIME: enroll asset+position lifetime tracking without any part instance', async ({
  page,
}) => {
  await page.goto('/vehicle/VEH-1048')
  await page.getByRole('link', { name: 'อะไหล่/อายุการใช้งาน' }).click()
  await expect(page).toHaveURL(/\/vehicle\/VEH-1048\/parts/)

  const addButton = page.getByRole('button', { name: '+ ลงทะเบียนอายุการใช้งานตามตำแหน่ง' })
  const addBox = await addButton.boundingBox()
  expect(addBox?.height).toBeGreaterThanOrEqual(44)
  await addButton.click()

  // Unique per test run (this backend instance is shared across all 5
  // viewport projects, so a fixed position code would collide).
  const positionCode = `BOOM-CYL-E2E-${test.info().project.name}`
  await page.getByLabel('ตำแหน่ง (position code)').fill(positionCode)
  await page.getByLabel('รหัสอะไหล่ (ถ้ามี)').fill('PART-0004')
  await page.getByRole('button', { name: 'บันทึก' }).click()

  const card = page.locator('.card', { hasText: `ตำแหน่ง: ${positionCode}` })
  await expect(card).toBeVisible()
  await expect(card.getByText('ไม่ทราบค่า').first()).toBeVisible()
  // R6: no real threshold exists — the page says so instead of guessing (G01/G02).
  await expect(card.getByText(/ไม่มีการเดาค่า/)).toBeVisible()

  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1)
})

test('PM actual part entry can link to a Part Instance', async ({ page }) => {
  await page.goto('/parts/PART-0005/instances/new')
  await page.getByLabel('ป้ายระบุชิ้น (ถ้ามี)').fill(`E2E-TAG-${randomUUID()}`)
  await page.getByRole('button', { name: 'ลงทะเบียนชิ้นงาน' }).click()
  await expect(page).toHaveURL(/\/part-instances\/(PINST-\d+)/)
  const instanceId = new URL(page.url()).pathname.split('/').pop() as string

  await page.goto('/vehicle/VEH-1046/pm')
  await page.getByRole('button', { name: 'เริ่มทำ PM' }).click()
  await expect(page).toHaveURL(/\/pm\/work-orders\/PMWO-/)
  // R2 Batch R2f-h4 B5 (deliberate test migration): with the cutover ON the job is created as a
  // Technician V2 job, so its detail shows the V2 team area (never the legacy free-text assignment).
  await expect(page.getByTestId('v2-current-set')).toBeVisible()
  // R4: the team is assigned and the work order STARTed before any item is recorded.
  await assignTeamAndStart(page.request, workOrderIdOf(page.url()))
  await page.reload()

  // R4: the item is a truthful Performed outcome ("เปลี่ยน / เติม" — the part was replaced).
  await page.getByRole('radio', { name: 'ดำเนินการแล้ว' }).first().click()
  await page.getByRole('checkbox', { name: 'เปลี่ยน / เติม' }).first().check()
  await page.getByText('+ เพิ่มอะไหล่ที่ใช้').first().click()
  await page.getByLabel('ชื่ออะไหล่').first().fill('ปั๊มไฮดรอลิกหลัก (ตัวอย่าง)')
  await page.getByLabel('รหัสชิ้นงาน (Part Instance) — ถ้ามี').first().fill(instanceId)
  await page.getByRole('button', { name: 'บันทึกผลงาน' }).first().click()

  await expect(page.getByText('ผลงาน: ดำเนินการแล้ว')).toBeVisible()
  await expect(page.getByText('ปั๊มไฮดรอลิกหลัก (ตัวอย่าง)')).toBeVisible()
  await expect(page.getByRole('link', { name: instanceId })).toBeVisible()
})
