import { expect, test, type APIRequestContext, type Browser, type Page } from '@playwright/test'
import { expectNoHorizontalOverflow, uuidFrom } from './r3Support'

/**
 * R3 — Finding follow-up and repair rounds (docs/project-governance/r3-implementation-contract.md §7–§10).
 *
 * - The read-only follow-up page check runs in every viewport.
 * - `@mutation` tests write for real and run ONLY in a dedicated invocation on a
 *   FRESH mock backend (they own VEH-1046, VEH-1047, VEH-1048 and EQP-0001 for that run):
 *     R3_MUTATION=1 npx playwright test e2e/r3-inspection-finding.spec.ts --project=desktop --workers=1 --grep @mutation
 * Mock TEST evidence only — never production evidence (L3, R11).
 */
const MUTATION_RUN = process.env.R3_MUTATION === '1'
const LEAD = { 'X-Dev-Role': 'TECHNICIAN', 'X-Dev-User-Id': 'USR-TEST-911' } // linked to TEC-TEST-911
const MEMBER = { 'X-Dev-Role': 'TECHNICIAN', 'X-Dev-User-Id': 'USR-TEST-912' } // linked to TEC-TEST-912

async function submitWithFail(request: APIRequestContext, assetType: 'VEHICLE' | 'EQUIPMENT', assetId: string) {
  const form = await (await request.get(`/api/v1/inspections/form?asset_type=${assetType}&asset_id=${assetId}`)).json()
  const items = (form.items as { item: { item_id: string } }[]).map((entry, index) => ({
    item_id: entry.item.item_id,
    result: index === 0 ? 'FAIL' : 'PASS',
    remark: index === 0 ? 'น้ำมันรั่ว - E2E R3' : null,
  }))
  const response = await request.post('/api/v1/inspections', {
    data: { asset_type: assetType, asset_id: assetId, items },
    headers: { 'X-Request-Id': uuidFrom(`r3-mutation-${assetId}-${Date.now()}`) },
  })
  expect(response.ok(), await response.text()).toBe(true)
  return (await response.json()).findings[0].finding_id as string
}

async function asUser(browser: Browser, baseURL: string | undefined, headers: Record<string, string>): Promise<Page> {
  const context = await browser.newContext({ baseURL, extraHTTPHeaders: headers })
  return context.newPage()
}

test('the follow-up page lists active Findings in two groups without priority or due dates', async ({ page }) => {
  test.skip(MUTATION_RUN, 'the dedicated mutation invocation runs only the @mutation tests')
  await page.goto('/findings/follow-up')
  await expect(page.getByRole('heading', { name: 'ติดตามรายการผิดปกติ' })).toBeVisible()
  await expect(page.getByRole('heading', { name: /รอพิจารณาเปิดงานซ่อม/ })).toBeVisible()
  await expect(page.getByRole('heading', { name: /อยู่ระหว่างซ่อม/ })).toBeVisible()
  await expect(page.getByText(/ความสำคัญ|เส้นตาย/).first()).toContainText('ไม่มีการจัดลำดับความสำคัญหรือกำหนดเส้นตาย')
  await expectNoHorizontalOverflow(page)
})

test.describe('R3 Finding rounds @mutation', () => {
  test.describe.configure({ mode: 'serial' })

  test.skip(!MUTATION_RUN, 'runs only in the dedicated R3_MUTATION=1 invocation on a fresh backend')
  test.beforeEach(({ browserName }, info) => {
    void browserName // Playwright requires a destructured fixture argument
    test.skip(info.project.name !== 'desktop' || info.config.workers !== 1, 'desktop, one worker')
  })

  test('F-001 → round → lead completion ends F-001 → a later abnormal is F-002 while RPR-001 is still OPEN @mutation', async ({ page, browser, baseURL }) => {
    const f1 = await submitWithFail(page.request, 'VEHICLE', 'VEH-1046')

    await page.goto('/findings/follow-up')
    await expect(page.getByTestId('followup-AWAITING_REPAIR_DECISION')).toContainText(f1)

    await page.goto(`/findings/${f1}`)
    await page.getByRole('button', { name: 'เปิดใบงานซ่อมจากรายการนี้' }).click()
    await expect(page).toHaveURL(/\/repairs\/RPR-/)
    const rpr1 = page.url().split('/').pop()!
    await expect(page.getByTestId('r3-round-finding-link')).toHaveText(f1)
    // A second round from the same active Finding is refused.
    const duplicate = await page.request.post('/api/v1/repairs', {
      data: { asset_type: 'VEHICLE', asset_id: 'VEH-1046', source_type: 'FINDING', source_id: f1 },
    })
    expect((await duplicate.json()).error.code).toBe('FINDING_ACTIVE_REPAIR_EXISTS')

    const assigned = await page.request.post(`/api/v1/repairs/${rpr1}/technician-assignments`, {
      data: { primary_technician_id: 'TEC-TEST-911', collaborator_technician_ids: ['TEC-TEST-912'], expected_current: null },
      headers: { 'X-Request-Id': uuidFrom(`r3-assign-${rpr1}`) },
    })
    expect(assigned.ok(), await assigned.text()).toBe(true)

    const member = await asUser(browser, baseURL, MEMBER)
    await member.goto(`/repairs/${rpr1}`)
    await member.getByRole('button', { name: 'ส่งงานซ่อมเสร็จ' }).click()
    await expect(member.getByRole('alert')).toContainText('เฉพาะช่างหลัก')

    const lead = await asUser(browser, baseURL, LEAD)
    await lead.goto(`/repairs/${rpr1}`)
    await lead.getByLabel('หมายเหตุการส่งงาน (ถ้ามี)').fill('เปลี่ยนซีลแล้ว')
    await lead.getByRole('button', { name: 'ส่งงานซ่อมเสร็จ' }).click()
    await expect(lead.getByTestId('r3-completion-submitted')).toContainText('ส่งงานแล้ว รอปิดงาน')
    await expect(lead.getByText('ไม่ใช่การยืนยันว่าแก้ไขสำเร็จ').first()).toBeVisible()
    // The round is frozen: no further work form is offered.
    await expect(lead.getByRole('button', { name: /บันทึกการดำเนินการ/ })).toHaveCount(0)

    await page.goto(`/findings/${f1}`)
    await expect(page.getByTestId('finding-end-reason')).toContainText('สิ้นสุดรอบติดตาม — ช่างส่งงานซ่อมแล้ว')

    // A new abnormal inspection on a later day would create F-002; on the same day the
    // asset already has its one inspection, so the next episode is proven by the backend
    // tests. Here the Finding is ENDED and RPR-001 is still OPEN awaiting closure:
    const repair = await (await page.request.get(`/api/v1/repairs/${rpr1}`)).json()
    expect(repair.repair.status).toBe('OPEN')

    await page.goto(`/repairs/${rpr1}`)
    await page.getByRole('button', { name: 'ปิดใบแจ้งซ่อม' }).click()
    await expect(page.getByText('ปิดงานแล้ว').first()).toBeVisible()
    await expect(page.getByTestId('r3-completion-submitted')).toContainText('ช่างส่งงานซ่อมแล้ว')
  })

  test('a round cancelled before any work leaves the Finding waiting for a repair decision @mutation', async ({ page }) => {
    const finding = await submitWithFail(page.request, 'VEHICLE', 'VEH-1048')
    await page.goto(`/findings/${finding}`)
    await page.getByRole('button', { name: 'เปิดใบงานซ่อมจากรายการนี้' }).click()
    await expect(page).toHaveURL(/\/repairs\/RPR-/)
    await page.getByLabel('เหตุผลในการยกเลิกใบงาน (จำเป็น)').fill('เปิดซ้ำโดยไม่ตั้งใจ')
    await page.getByRole('button', { name: 'ยกเลิกใบงานซ่อม' }).click()
    await expect(page.getByTestId('r3-round-cancelled')).toContainText('เปิดซ้ำโดยไม่ตั้งใจ')
    await expect(page.getByText('ยกเลิกแล้ว (ก่อนเริ่มงาน)').first()).toBeVisible()
    await page.goto(`/findings/${finding}`)
    await expect(page.getByTestId('finding-status')).toContainText('รอพิจารณาเปิดงานซ่อม')
  })

  test('manual termination needs a reason and ends the episode without a verification claim @mutation', async ({ page }) => {
    const finding = await submitWithFail(page.request, 'EQUIPMENT', 'EQP-0001')
    await page.goto(`/findings/${finding}`)
    await page.getByRole('button', { name: 'ยุติการติดตาม' }).click()
    await expect(page.getByRole('alert')).toContainText('กรุณาระบุเหตุผล')
    await page.getByLabel('เหตุผลในการยุติการติดตาม (จำเป็น)').fill('รายการถูกยกเลิกในรุ่นใหม่')
    await page.getByRole('button', { name: 'ยุติการติดตาม' }).click()
    await expect(page.getByTestId('finding-end-reason')).toContainText('ยุติการติดตามโดยผู้มีสิทธิ์')
    await expect(page.getByText('การสิ้นสุดรอบติดตามไม่ใช่การยืนยันว่าแก้ไขสำเร็จ')).toBeVisible()
  })

  test('L9 + L10: the lead is replaced, never withdrawn; the duplicate request is cancelled by the manager @mutation', async ({ page, browser, baseURL }) => {
    const finding = await submitWithFail(page.request, 'VEHICLE', 'VEH-1047')
    const opened = await page.request.post('/api/v1/repairs', {
      data: { asset_type: 'VEHICLE', asset_id: 'VEH-1047', source_type: 'FINDING', source_id: finding },
    })
    const repairId = (await opened.json()).repair.repair_id as string
    // L9: no repair work before a lead is assigned.
    const early = await page.request.post(`/api/v1/repairs/${repairId}/actions`, { data: { action_text: 'ถอดฝาครอบ' } })
    expect((await early.json()).error.code).toBe('REPAIR_LEAD_NOT_ASSIGNED')
    const assignUrl = `/api/v1/repairs/${repairId}/technician-assignments`
    const first = await page.request.post(assignUrl, {
      data: { primary_technician_id: 'TEC-TEST-911', collaborator_technician_ids: ['TEC-TEST-912'], expected_current: null },
      headers: { 'X-Request-Id': uuidFrom(`l9-first-${repairId}`) },
    })
    expect(first.ok(), await first.text()).toBe(true)
    const withdrawn = await page.request.post(`/api/v1/repairs/${repairId}/technician-assignment-withdrawals`, {
      data: { expected_current: { primary_technician_id: 'TEC-TEST-911', collaborator_technician_ids: ['TEC-TEST-912'] } },
      headers: { 'X-Request-Id': uuidFrom(`l9-withdraw-${repairId}`) },
    })
    expect((await withdrawn.json()).error.code).toBe('TECHNICIAN_ASSIGNMENT_PRIMARY_REQUIRED_ON_R3_ROUND')
    const replaced = await page.request.post(assignUrl, {
      data: {
        primary_technician_id: 'TEC-TEST-912', collaborator_technician_ids: ['TEC-TEST-911'],
        expected_current: { primary_technician_id: 'TEC-TEST-911', collaborator_technician_ids: ['TEC-TEST-912'] },
      },
      headers: { 'X-Request-Id': uuidFrom(`l9-replace-${repairId}`) },
    })
    expect(replaced.ok(), await replaced.text()).toBe(true)

    // L10: a duplicate report of the same Finding, cancelled by the manager by hand.
    const reported = await page.request.post('/api/v1/repair-requests', {
      data: { vehicle_id: 'VEH-1047', symptom_th: 'น้ำมันรั่ว (แจ้งซ้ำ)', source_type: 'FINDING', source_id: finding },
      headers: LEAD,
    })
    expect(reported.ok(), await reported.text()).toBe(true)
    const requestId = (await reported.json()).request.repair_request_id as string
    await page.goto(`/repair-requests/${requestId}`)
    await page.getByLabel('เหตุผลในการยกเลิก (จำเป็น)').fill('ซ้ำกับใบงานที่กำลังซ่อม')
    await page.getByLabel(/เลขใบงานซ่อมที่ดำเนินการกับข้อบกพร่องเดียวกัน/).fill(repairId)
    await page.getByRole('button', { name: 'ยกเลิกคำขอแจ้งซ่อม' }).click()
    await expect(page.getByTestId('repair-request-cancelled')).toContainText('ซ้ำกับใบงานที่กำลังซ่อม')
    await expect(page.getByRole('link', { name: repairId })).toBeVisible()
    const queue = await (await page.request.get('/api/v1/repair-requests/pending?page_size=200')).json()
    expect((queue.items as { repair_request_id: string }[]).map((i) => i.repair_request_id)).not.toContain(requestId)

    // Only the new lead completes; the former lead is refused.
    const oldLead = await asUser(browser, baseURL, LEAD)
    await oldLead.goto(`/repairs/${repairId}`)
    await oldLead.getByRole('button', { name: 'ส่งงานซ่อมเสร็จ' }).click()
    await expect(oldLead.getByRole('alert')).toContainText('เฉพาะช่างหลัก')
    const newLead = await asUser(browser, baseURL, MEMBER)
    await newLead.goto(`/repairs/${repairId}`)
    await newLead.getByRole('button', { name: 'ส่งงานซ่อมเสร็จ' }).click()
    await expect(newLead.getByTestId('r3-completion-submitted')).toContainText('TEC-TEST-912')
  })
})
