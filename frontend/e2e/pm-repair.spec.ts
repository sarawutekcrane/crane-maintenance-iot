import { randomUUID } from 'node:crypto'
import { expect, test, type APIRequestContext, type Browser, type Page } from '@playwright/test'

// Phase 4 PM/Repair mobile workflows (00_SYSTEM_REQUIREMENTS_BASELINE_EN.txt
// MOBILE VEHICLE DETAIL / MOBILE REPAIR REPORTING + Phase 4 acceptance
// tests: PM work order works, task result points to exact revision,
// snapshot captured, manual repair works, finding can link/convert to
// repair, action history is append-only, close preserves history, PM and
// Repair remain separate). Runs across every viewport project configured
// in playwright.config.ts.
//
// R4 PM Workflow (Owner E01 A3, deliberate test migration): a Technician V2 PM work order is now
// STARTed, every in-scope item is saved as a truthful Performed / Not Performed outcome, the
// current PRIMARY submits it for review and a `can_manage_pm` reviewer closes it (was: save
// every task as "เสร็จสิ้น", then close directly). The browser's default dev user is the
// reviewer (MAINTENANCE); the seeded synthetic TEST technicians form the V2 team.
const PRIMARY_HEADERS = { 'X-Dev-Role': 'TECHNICIAN', 'X-Dev-User-Id': 'USR-TEST-911' } // TEC-TEST-911
const PERFORMED_ACTION = 'ตรวจเช็ค'

function workOrderIdOf(page: Page): string {
  const match = /\/pm\/work-orders\/(PMWO-[^/?#]+)/.exec(page.url())
  expect(match, 'on a PM work order page').not.toBeNull()
  return match![1]
}

async function assignTeam(request: APIRequestContext, workOrderId: string): Promise<string> {
  const response = await request.post(`/api/v1/pm/work-orders/${workOrderId}/technician-assignments`, {
    data: { primary_technician_id: 'TEC-TEST-911', collaborator_technician_ids: ['TEC-TEST-912'], expected_current: null },
    headers: { 'X-Request-Id': randomUUID() },
  })
  expect(response.ok(), await response.text()).toBe(true)
  return (await response.json()).current.assignment_set_id
}

/** Assign the V2 team and START the work order through its own API (setup only). */
async function assignAndStart(request: APIRequestContext, workOrderId: string): Promise<string> {
  const setId = await assignTeam(request, workOrderId)
  const started = await request.post(`/api/v1/pm/work-orders/${workOrderId}/start`, {
    data: {},
    headers: { 'X-Request-Id': randomUUID() },
  })
  expect(started.ok(), await started.text()).toBe(true)
  return setId
}

/** Save the first still-editable item as Performed through the UI. */
async function savePerformedItem(page: Page) {
  await page.getByRole('radio', { name: 'ดำเนินการแล้ว' }).first().click()
  await page.getByRole('checkbox', { name: PERFORMED_ACTION }).first().check()
  await page.getByRole('button', { name: 'บันทึกผลงาน' }).first().click()
}

/** The current PRIMARY submits the work order from its own browser session. */
async function submitAsPrimary(browser: Browser, baseURL: string | undefined, workOrderId: string) {
  const context = await browser.newContext({ baseURL, extraHTTPHeaders: PRIMARY_HEADERS })
  const primaryPage = await context.newPage()
  await primaryPage.goto(`/pm/work-orders/${workOrderId}`)
  await primaryPage.getByRole('button', { name: 'ส่งตรวจสอบ' }).click()
  await expect(primaryPage.getByText('รอตรวจสอบ').first()).toBeVisible()
  await context.close()
}

test('PM: start a work order from Vehicle Detail, capture a meter reading and an actual part, then close it', async ({
  page,
  browser,
  baseURL,
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
  // R2 Batch R2f-h4 B5 (deliberate test migration): with the cutover ON the job is created as a
  // Technician V2 job, so its detail shows the V2 team area (never the legacy free-text assignment).
  await expect(page.getByTestId('v2-current-set')).toBeVisible()
  await expect(page.getByText('งานบำรุงรักษาตัวอย่างที่ 1 (PLAN1)')).toBeVisible()

  // Core Demo Fixes APPROVED CORE RULE: the machine-state snapshot is
  // backend-derived and shown read-only here — never a manually-typed
  // counter/GPS field. Only the dimensions this vehicle's own
  // components actually define appear (ENGINE_HOUR from CARRIER_ENGINE),
  // never a fabricated field.
  await expect(page.getByText('ค่ามาตรวัดปัจจุบัน (อ่านอย่างเดียว)')).toBeVisible()
  await expect(page.getByText('ชั่วโมงเครื่องยนต์')).toBeVisible()

  // R4: assign the V2 team, then START from the page (items stay locked until IN_PROGRESS).
  const workOrderId = workOrderIdOf(page)
  await assignTeam(page.request, workOrderId)
  await page.reload()
  await expect(page.getByRole('button', { name: 'บันทึกผลงาน' })).toHaveCount(0)
  await page.getByRole('button', { name: 'เริ่มงาน' }).click()
  await expect(page.getByText('กำลังดำเนินการ').first()).toBeVisible()

  await page.getByText('+ เพิ่มอะไหล่ที่ใช้').first().click()
  await page.getByLabel('ชื่ออะไหล่').first().fill('ไส้กรองน้ำมันเครื่อง (ตัวอย่าง)')

  await savePerformedItem(page)
  await expect(page.getByText('ผลงาน: ดำเนินการแล้ว')).toBeVisible()
  await expect(page.getByText(`สิ่งที่ทำ: ${PERFORMED_ACTION}`)).toBeVisible()
  await expect(page.getByText('ไส้กรองน้ำมันเครื่อง (ตัวอย่าง)')).toBeVisible()
  await expect(page.getByText(/บันทึกค่ามาตรวัดแล้ว/)).toBeVisible()

  // Save the remaining two placeholder tasks as Performed.
  await savePerformedItem(page)
  await expect(page.getByText('ผลงาน: ดำเนินการแล้ว')).toHaveCount(2)
  await savePerformedItem(page)
  await expect(page.getByRole('button', { name: 'บันทึกผลงาน' })).toHaveCount(0)

  // Only the current PRIMARY submits; the reviewer (this page's user) then closes.
  await submitAsPrimary(browser, baseURL, workOrderId)
  await page.reload()
  await expect(page.getByRole('heading', { name: 'ปิดใบสั่งงาน PM' })).toHaveCount(0) // no direct close
  await page.getByRole('button', { name: 'อนุมัติและปิดงาน' }).click()
  await expect(page.getByText('ปิดงานแล้ว').first()).toBeVisible()

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
  // R2 Batch R2f-h4 B5 (deliberate test migration): with the cutover ON the job is created as a
  // Technician V2 job, so its detail shows the V2 team area (never the legacy free-text assignment).
  await expect(page.getByTestId('v2-current-set')).toBeVisible()
  // R4 (was: an empty work order closed directly): a partial PM — every item Performed except
  // the last, Not Performed — is submitted by the PRIMARY and closed by the reviewer. It shows as
  // CLOSED with one Outstanding item, never as fully completed.
  const workOrderId = workOrderIdOf(page)
  const setId = await assignAndStart(page.request, workOrderId)
  const detail = await (await page.request.get(`/api/v1/pm/work-orders/${workOrderId}`)).json()
  const tasks: string[] = detail.work_order.scope_task_ids
  for (const [index, task] of tasks.entries()) {
    const last = index === tasks.length - 1
    const saved = await page.request.post(`/api/v1/pm/work-orders/${workOrderId}/items/${task}/outcome`, {
      data: last
        ? { disposition: 'NOT_PERFORMED', reason_code: 'รออะไหล่' }
        : { disposition: 'PERFORMED', performed_actions: [PERFORMED_ACTION] },
      headers: PRIMARY_HEADERS,
    })
    expect(saved.ok(), await saved.text()).toBe(true)
  }
  const submitted = await page.request.post(`/api/v1/pm/work-orders/${workOrderId}/submit`, {
    data: { expected_set_id: setId },
    headers: { ...PRIMARY_HEADERS, 'X-Request-Id': randomUUID() },
  })
  expect(submitted.ok(), await submitted.text()).toBe(true)
  await page.reload()
  await page.getByRole('button', { name: 'อนุมัติและปิดงาน' }).click()
  await expect(page.getByText('ปิดงานแล้ว').first()).toBeVisible()
  await expect(page.getByRole('heading', { name: 'รายการค้างจาก PM นี้' })).toBeVisible()
  await expect(page.getByRole('note')).toContainText('ยังมีรายการค้าง 1 รายการ')
  await expect(page.getByText('ผลงาน: ไม่ได้ดำเนินการ')).toBeVisible()

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
  // R2 Batch R2f-h4 B5 (deliberate test migration): with the cutover ON the job is created as a
  // Technician V2 job, so its detail shows the V2 team area (never the legacy free-text assignment).
  await expect(page.getByTestId('v2-current-set')).toBeVisible()
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
}, testInfo) => {
  // R3 (deliberate test migration): one inspection per asset per Bangkok day and one
  // active repair round per Finding — this flow runs once per run, on VEH-1048, which
  // no other spec submits. R3 labels; the abnormal result needs a remark.
  test.skip(testInfo.project.name !== 'desktop', 'one inspection per asset per day')
  await page.goto('/vehicle/VEH-1048/inspect')
  const passButtons = page.getByRole('radio', { name: 'ปกติ', exact: true })
  await expect(passButtons).toHaveCount(5)
  for (let i = 0; i < 4; i += 1) {
    await passButtons.nth(i).click()
  }
  await page.getByRole('radio', { name: 'ผิดปกติ', exact: true }).nth(4).click()
  await page.getByLabel('หมายเหตุ (จำเป็น)').fill('พบความผิดปกติ - E2E PM/Repair')
  await page.getByRole('button', { name: 'ส่งผลการตรวจ' }).click()
  await expect(page).toHaveURL(/\/inspections\/INS-/)

  await expect(page.getByText('ข้อบกพร่องที่พบ')).toBeVisible()
  await page.getByRole('link', { name: 'แจ้งซ่อม', exact: true }).click()

  await expect(page).toHaveURL(/\/vehicle\/VEH-1048\/repairs\/new\?source_type=FINDING/)
  await expect(page.getByText('ข้อบกพร่องจากการตรวจเช็ค').first()).toBeVisible()
  await expect(page.getByText(/รายการนี้เชื่อมโยงมาจาก/)).toBeVisible()

  await page.getByRole('button', { name: 'ส่งแจ้งซ่อม' }).click()
  await expect(page).toHaveURL(/\/repairs\/RPR-/)
  // R2 Batch R2f-h4 B5 (deliberate test migration): with the cutover ON the job is created as a
  // Technician V2 job, so its detail shows the V2 team area (never the legacy free-text assignment).
  await expect(page.getByTestId('v2-current-set')).toBeVisible()
  await expect(page.getByText('ข้อบกพร่องจากการตรวจเช็ค').first()).toBeVisible()
  // R3: a Work Order opened from an R3 Finding is a Finding round (contract §9 P1).
  await expect(page.getByTestId('r3-round-finding-link')).toBeVisible()
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
  // R2 Batch R2f-h4 B5 (deliberate test migration): with the cutover ON the job is created as a
  // Technician V2 job, so its detail shows the V2 team area (never the legacy free-text assignment).
  await expect(page.getByTestId('v2-current-set')).toBeVisible()
})

// Final Cross-Phase Integration Fix — F2: evidence uploaded against a
// Repair action or a PM task result must remain visible after reload, not
// just for the rest of the same in-memory session. A 1x1 PNG keeps this
// fast and independent of any fixture file on disk.
const TINY_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
  'base64',
)

test('Repair: uploaded action evidence remains visible after reload', async ({ page }) => {
  await page.goto('/vehicle/VEH-1046/repairs/new')
  await page.getByLabel('อาการ/ปัญหาที่พบ').fill('ทดสอบหลักฐานรูปถ่ายในการดำเนินการซ่อม')
  await page.getByRole('button', { name: 'ส่งแจ้งซ่อม' }).click()
  await expect(page).toHaveURL(/\/repairs\/RPR-/)
  // R2 Batch R2f-h4 B5 (deliberate test migration): with the cutover ON the job is created as a
  // Technician V2 job, so its detail shows the V2 team area (never the legacy free-text assignment).
  await expect(page.getByTestId('v2-current-set')).toBeVisible()

  await page.getByLabel('เพิ่มการดำเนินการ').fill('ตรวจสอบและถ่ายรูปหลักฐาน')
  await page.locator('#action-photo').setInputFiles({
    name: 'evidence.png',
    mimeType: 'image/png',
    buffer: TINY_PNG,
  })
  await expect(page.getByText('แนบแล้ว 1 รูป')).toBeVisible()
  await page.getByRole('button', { name: 'บันทึกการดำเนินการ' }).click()
  await expect(page.getByText('ตรวจสอบและถ่ายรูปหลักฐาน')).toBeVisible()
  await expect(page.getByAltText('รูปแนบการดำเนินการ')).toBeVisible()

  await page.reload()
  await expect(page.getByText('ตรวจสอบและถ่ายรูปหลักฐาน')).toBeVisible()
  // The evidence photo must still render after reload — the backend
  // response only carries attachment IDs, so this proves the frontend
  // resolves them via the by-source attachment endpoint on every load,
  // not only immediately after upload.
  await expect(page.getByAltText('รูปแนบการดำเนินการ')).toBeVisible()
})

test('PM: uploaded task-result evidence remains visible after reload', async ({ page }) => {
  await page.goto('/vehicle/VEH-1047/pm')
  await page.getByRole('button', { name: 'เริ่มทำ PM' }).click()
  await expect(page).toHaveURL(/\/pm\/work-orders\/PMWO-/)
  // R2 Batch R2f-h4 B5 (deliberate test migration): with the cutover ON the job is created as a
  // Technician V2 job, so its detail shows the V2 team area (never the legacy free-text assignment).
  await expect(page.getByTestId('v2-current-set')).toBeVisible()
  // R4: items are recorded only while the work order is IN_PROGRESS.
  await assignAndStart(page.request, workOrderIdOf(page))
  await page.reload()

  await page.locator('input[id^="pm-evidence-"]').first().setInputFiles({
    name: 'evidence.png',
    mimeType: 'image/png',
    buffer: TINY_PNG,
  })
  await expect(page.getByText('แนบแล้ว 1 รูป').first()).toBeVisible()
  await savePerformedItem(page)
  await expect(page.getByText('ผลงาน: ดำเนินการแล้ว').first()).toBeVisible()
  await expect(page.getByAltText(/หลักฐานสำหรับ/).first()).toBeVisible()

  await page.reload()
  await expect(page.getByText('ผลงาน: ดำเนินการแล้ว').first()).toBeVisible()
  await expect(page.getByAltText(/หลักฐานสำหรับ/).first()).toBeVisible()
})
