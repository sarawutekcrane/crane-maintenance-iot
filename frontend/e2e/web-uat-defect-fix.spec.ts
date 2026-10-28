import { randomUUID } from 'node:crypto'
import { expect, test, type APIRequestContext } from '@playwright/test'

// Web UAT Defect Fix — mandatory real-browser regression coverage for
// UAT-F1 (HIGH: Finding source dropped on the Repair-Request flow),
// UAT-F2 (reporter can re-open a submitted Repair Request), and UAT-F3
// (PM-defect "already reported" derived from persisted state, not
// client-only React state that disappears on reload). These deliberately
// use a real browser context carrying the app's own dev-role headers
// (X-Dev-Role/X-Dev-User-Id) — never API calls standing in for UI
// actions — because the original UAT-F1 defect only reproduces for a
// non-Maintenance actor (DRIVER/TECHNICIAN), and the rest of this repo's
// E2E suite runs entirely as the default ADMIN dev-user.

const TECH_HEADERS = { 'X-Dev-Role': 'TECHNICIAN', 'X-Dev-User-Id': 'e2e-tech-1' }
const DRIVER_HEADERS = { 'X-Dev-Role': 'DRIVER', 'X-Dev-User-Id': 'e2e-driver-1' }

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

test('UAT-F1: a Finding reported via a non-Maintenance actor keeps its source through submission and reload', async ({
  browser,
}, testInfo) => {
  // R3 (deliberate test migration): one inspection per asset per Bangkok day, and a
  // Finding may be reported once (Decision B) — so this UI flow runs once per run, on
  // VEH-1046, which no other spec submits. R3 labels; the abnormal result needs a remark.
  test.skip(testInfo.project.name !== 'desktop', 'one inspection per asset per day')
  const context = await browser.newContext({ extraHTTPHeaders: TECH_HEADERS })
  const page = await context.newPage()

  await page.goto('/vehicle/VEH-1046/inspect')
  const passButtons = page.getByRole('radio', { name: 'ปกติ', exact: true })
  const failButtons = page.getByRole('radio', { name: 'ผิดปกติ', exact: true })
  await passButtons.first().waitFor({ state: 'visible' })
  const itemCount = await passButtons.count()
  for (let i = 0; i < itemCount - 1; i += 1) await passButtons.nth(i).click()
  await failButtons.nth(itemCount - 1).click()
  await page.getByLabel('หมายเหตุ (จำเป็น)').fill('พบความผิดปกติ - E2E UAT-F1')
  await page.getByRole('button', { name: 'ส่งผลการตรวจ' }).click()
  await expect(page).toHaveURL(/\/inspections\/INS-/)
  await expect(page.getByText('ข้อบกพร่องที่พบ')).toBeVisible()

  await page.getByRole('link', { name: 'แจ้งซ่อม', exact: true }).click()
  await expect(page).toHaveURL(/\/vehicle\/VEH-1046\/repairs\/new\?source_type=FINDING/)
  // A non-Maintenance actor (TECHNICIAN, no can_manage_repair) lands on
  // the Repair-Request flow, not a direct Repair — heading differs.
  await expect(page.getByText('แจ้งปัญหา/แจ้งซ่อม')).toBeVisible()
  await expect(page.getByText(/รายการนี้เชื่อมโยงมาจาก ข้อบกพร่องจากการตรวจเช็ค/)).toBeVisible()

  await page.getByLabel('อาการ/ปัญหาที่พบ').fill('พบข้อบกพร่องระหว่างตรวจเช็ค - E2E UAT-F1')
  await page.getByRole('button', { name: 'ส่งแจ้งซ่อม' }).click()
  await expect(page.getByText(/บันทึกการแจ้งปัญหาแล้ว/)).toBeVisible()

  // Follow the new UAT-F2 link straight to the created Request's own
  // detail page, then reload it — this is the core UAT-F1 regression
  // assertion: the FINDING source must still be there, not silently
  // dropped, and must survive a real browser reload.
  await page.getByRole('link', { name: 'ดูรายละเอียดคำขอ' }).click()
  await expect(page).toHaveURL(/\/repair-requests\/RRQ-/)
  await expect(page.getByText(/แหล่งที่มา/)).toBeVisible()
  await expect(page.getByText(/ข้อบกพร่องจากการตรวจเช็ค \(FND-/)).toBeVisible()

  await page.reload()
  await expect(page.getByText(/ข้อบกพร่องจากการตรวจเช็ค \(FND-/)).toBeVisible()

  await context.close()
})

test('UAT-F2: a DRIVER can navigate away and return through normal UI to see their submitted Repair Request', async ({
  browser,
}, testInfo) => {
  // Multiple viewport projects share one backend/mock-repository instance
  // (see playwright.config.ts), so this actor's request list can already
  // contain rows from earlier project runs — a unique symptom per run
  // keeps the text lookups below unambiguous.
  const symptom = `ทดสอบ UAT-F2 การกลับมาดูคำขอ (${testInfo.project.name})`
  const context = await browser.newContext({ extraHTTPHeaders: DRIVER_HEADERS })
  const page = await context.newPage()

  await page.goto('/vehicle/VEH-1047/repairs/new')
  await expect(page.getByText('แจ้งปัญหา/แจ้งซ่อม')).toBeVisible()
  await page.getByLabel('อาการ/ปัญหาที่พบ').fill(symptom)
  await page.getByRole('button', { name: 'ส่งแจ้งซ่อม' }).click()
  await expect(page.getByText(/บันทึกการแจ้งปัญหาแล้ว/)).toBeVisible()
  // Capture which request this run created, from the confirmation link's
  // own href — used below to find the right row without depending on
  // page-wide text uniqueness (this actor may already have earlier rows
  // from other viewport projects sharing the same mock backend).
  const confirmationHref = await page
    .getByRole('link', { name: 'ดูรายละเอียดคำขอ' })
    .getAttribute('href')
  expect(confirmationHref).toMatch(/^\/repair-requests\/RRQ-/)

  // Navigate away entirely, then return through a normal app route (the
  // existing "My Work" page every reporter can already open from the
  // nav — separately verified in responsive-shell.spec.ts) rather than
  // remembering the request's own URL, satisfying the master test plan's
  // "return through normal UI" acceptance criterion.
  await page.goto('/')
  await page.goto('/my-work')
  await expect(page.getByRole('heading', { name: 'คำขอแจ้งซ่อมของฉัน' })).toBeVisible()
  const rowLink = page.locator(`a[href="${confirmationHref}"]`)
  await expect(rowLink).toBeVisible()
  await expect(page.getByText(symptom)).toBeVisible()

  await rowLink.click()
  await expect(page).toHaveURL(confirmationHref!)
  await expect(page.getByText('รอตรวจรับ').first()).toBeVisible()

  await page.reload()
  await expect(page.getByText(symptom)).toBeVisible()
  await expect(page.getByText('รอตรวจรับ').first()).toBeVisible()

  await context.close()
})

test('UAT-F3: PM-defect "already reported" survives a reload instead of resetting to a fresh report form', async ({
  page,
}) => {
  // Default ADMIN context: holds can_manage_pm (to open the work order)
  // and can_report_repair (to report the defect) at once, keeping this
  // test focused on the reload-persistence behavior itself.
  await page.goto('/vehicle/VEH-1048/pm')
  await page.getByRole('button', { name: 'เริ่มทำ PM' }).click()
  await expect(page).toHaveURL(/\/pm\/work-orders\/PMWO-/)
  // R2 Batch R2f-h4 B5 (deliberate test migration): with the cutover ON the job is created as a
  // Technician V2 job, so its detail shows the V2 team area (never the legacy free-text assignment).
  await expect(page.getByTestId('v2-current-set')).toBeVisible()
  const workOrderUrl = page.url()
  const workOrderId = /\/pm\/work-orders\/(PMWO-[^/?#]+)/.exec(workOrderUrl)![1]
  // R4: the team is assigned and the work order STARTed before any item is recorded.
  await assignTeamAndStart(page.request, workOrderId)
  await page.reload()

  // R4 (was: the first item saved as "ยังไม่เสร็จสิ้น / พบปัญหา"): a Not Performed item needs
  // a previously saved, genuinely Performed item (zero-Performed rule), so item 1 is Performed
  // and item 2 — the problem item — is Not Performed with the approved reason
  // "พบความผิดปกติ รอซ่อม" and the same remark. The defect is reported for item 2.
  await page.getByRole('radio', { name: 'ดำเนินการแล้ว' }).first().click()
  await page.getByRole('checkbox', { name: 'ตรวจเช็ค' }).first().check()
  await page.getByRole('button', { name: 'บันทึกผลงาน' }).first().click()
  await expect(page.getByText('ผลงาน: ดำเนินการแล้ว').first()).toBeVisible()

  await page.getByRole('radio', { name: 'ไม่ได้ดำเนินการ' }).first().click()
  await page.getByLabel('เหตุผลที่ไม่ได้ดำเนินการ (เลือก 1 เหตุผล)').first().selectOption('พบความผิดปกติ รอซ่อม')
  await page.getByLabel('หมายเหตุ (ถ้ามี)').first().fill('พบปัญหาระหว่าง PM - E2E UAT-F3')
  await page.getByRole('button', { name: 'บันทึกผลงาน' }).first().click()
  await expect(page.getByText('ผลงาน: ไม่ได้ดำเนินการ').first()).toBeVisible()
  await expect(page.getByText('พบปัญหาระหว่าง PM - E2E UAT-F3')).toBeVisible()

  // Item 1 (Performed) and item 2 (Not Performed) each offer a defect report; use item 2's.
  const defectButtons = page.getByRole('button', { name: 'แจ้งซ่อม (พบข้อบกพร่องระหว่าง PM)' })
  await expect(defectButtons).toHaveCount(2)
  await defectButtons.nth(1).click()
  await page.getByLabel('อาการ/ข้อบกพร่องที่พบระหว่าง PM').fill('พบข้อบกพร่อง - E2E UAT-F3')
  await page.getByRole('button', { name: 'ส่งแจ้งซ่อม' }).click()
  await expect(page.getByText(/แจ้งซ่อมแล้ว/).first()).toBeVisible()
  await expect(page.getByRole('link', { name: /RRQ-/ }).first()).toBeVisible()

  // Leave the page entirely and come back (not just reload in place) —
  // this is the exact scenario that used to lose the client-only
  // `defectSubmitted` state and re-show a fresh, submittable form.
  await page.goto('/')
  await page.goto(workOrderUrl)
  await expect(page.getByText(/แจ้งซ่อมแล้ว/).first()).toBeVisible()
  await expect(page.getByRole('link', { name: /RRQ-/ }).first()).toBeVisible()
  // The defect-report button for that same task must not reappear (R4: only item 1's own,
  // never-reported button remains — was: no button at all, when item 2 was the only result).
  await expect(page.getByText(/แจ้งซ่อมแล้ว/)).toHaveCount(1)
  await expect(page.getByRole('button', { name: 'แจ้งซ่อม (พบข้อบกพร่องระหว่าง PM)' })).toHaveCount(
    1,
  )

  await page.reload()
  await expect(page.getByText(/แจ้งซ่อมแล้ว/).first()).toBeVisible()
  await expect(page.getByText(/แจ้งซ่อมแล้ว/)).toHaveCount(1)
  await expect(page.getByRole('button', { name: 'แจ้งซ่อม (พบข้อบกพร่องระหว่าง PM)' })).toHaveCount(
    1,
  )
})
