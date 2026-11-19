import { expect, test, type APIRequestContext, type Browser, type Page } from '@playwright/test'
import { uuidFrom } from './r3Support'

/**
 * R8 PRE-UAT (Owner approval Rev 1, Decisions 1 and 2) — repair material (Store) workflow and the
 * TEST-CANDIDATE-R1 repair classification, through the real web UI, plus fail-closed rejections.
 *
 * Runs ONLY in the dedicated invocation (Access Management mode + synthetic UAT fixture profile):
 *   PREUAT_E2E=1 npx playwright test e2e/preuat- --workers=1
 * Writes run once, on the desktop project. Mock TEST evidence only — not PostgreSQL / production evidence.
 */
const ENABLED = process.env.PREUAT_E2E === '1'
const as = (user: string) => ({ 'X-Dev-Role': 'TECHNICIAN', 'X-Dev-User-Id': user })
const MGR = as('USR-TEST-AM-MGR')
const CLERK = as('USR-TEST-AM-CLERK')
const TECH1 = as('USR-TEST-911')
const STORE_GRANTS = { can_view: true, can_manage_repair: true, can_close_repair: true, can_test_store_approve: true,
  can_test_store_issue: true, can_test_store_receive_return: true, can_test_classify_repair: true }

test.skip(!ENABLED, 'needs the PRE-UAT backend (PREUAT_E2E=1)')
test.describe.configure({ mode: 'serial' })
test.beforeEach(({ baseURL: _b }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'writes run once, on the desktop project')
})

let seq = 0
const rid = (tag: string) => uuidFrom(`preuat-sc-${tag}-${Date.now()}-${seq++}`)

async function grant(request: APIRequestContext, personnelId: string, changes: Record<string, boolean>) {
  const revision = (await (await request.get('/api/v1/access/me', { headers: MGR })).json()).revision as number
  const response = await request.post('/api/v1/access/grants', {
    headers: { ...MGR, 'X-Request-Id': rid('grant') },
    data: { target: { kind: 'EMPLOYEE', personnel_id: personnelId }, changes, reason_th: 'PRE-UAT E2E', expected_revision: revision },
  })
  expect(response.ok(), await response.text()).toBe(true)
}

async function post(request: APIRequestContext, headers: Record<string, string>, path: string, data: unknown, requestId = rid(path)) {
  return request.post(`/api/v1${path}`, { headers: { ...headers, 'X-Request-Id': requestId }, data })
}

async function openRepair(request: APIRequestContext): Promise<string> {
  const opened = await post(request, MGR, '/repairs', { asset_type: 'VEHICLE', asset_id: 'VEH-1047', source_type: 'MANUAL' })
  expect(opened.ok(), await opened.text()).toBe(true)
  const id = (await opened.json()).repair.repair_id as string
  const team = await post(request, MGR, `/repairs/${id}/technician-assignments`,
    { primary_technician_id: 'TEC-TEST-911', collaborator_technician_ids: ['TEC-TEST-912'], expected_current: null })
  expect(team.ok(), await team.text()).toBe(true)
  return id
}

async function open(browser: Browser, baseURL: string | undefined, headers: Record<string, string>, path: string): Promise<Page> {
  const page = await (await browser.newContext({ baseURL, extraHTTPHeaders: headers })).newPage()
  await page.goto(path)
  return page
}

async function lineStep(page: Page, step: string, fields: Record<string, string>) {
  await page.getByRole('button', { name: step, exact: true }).first().click()
  const form = page.getByRole('form', { name: step })
  for (const [label, value] of Object.entries(fields)) {
    const field = form.getByLabel(label)
    if (await field.evaluate((el) => el.tagName === 'SELECT')) await field.selectOption(value)
    else await field.fill(value)
  }
  await form.getByRole('button', { name: 'บันทึก' }).click()
  await expect(page.getByText(`${step}แล้ว`, { exact: true })).toBeVisible()
}

test.beforeAll(async ({ request }) => {
  if (!ENABLED) return
  await grant(request, 'PER-TEST-AM-MGR', STORE_GRANTS)
  for (const p of ['PER-TEST-911', 'PER-TEST-912', 'PER-TEST-AM-CLERK']) await grant(request, p, { can_view: true })
})

test('request → approve → issue → close → use → reconcile → classify (TEST-CANDIDATE-R1) in the web UI', async ({ browser, baseURL, request }) => {
  const repairId = await openRepair(request)
  const tech = await open(browser, baseURL, TECH1, `/repairs/${repairId}`)
  const requestForm = tech.getByRole('form', { name: 'ขอเบิกอะไหล่' })
  await requestForm.getByLabel('รหัสอะไหล่ (ถ้ามี) แถว 1').fill('PART-0001')
  await requestForm.getByLabel('รายละเอียด แถว 1').fill('ไส้กรองทดสอบ E2E')
  await requestForm.getByLabel('จำนวน แถว 1').fill('1')
  await requestForm.getByLabel('หน่วย แถว 1').fill('ชิ้น')
  await requestForm.getByRole('button', { name: 'ส่งคำขอเบิก' }).click()
  await expect(tech.getByText('ไส้กรองทดสอบ E2E (PART-0001)')).toBeVisible()

  const mgr = await open(browser, baseURL, MGR, `/repairs/${repairId}`)
  await lineStep(mgr, 'อนุมัติ', { 'จำนวน (ชิ้น) *': '1' })
  await lineStep(mgr, 'จ่ายอะไหล่', { 'จำนวน (ชิ้น) *': '1', 'รหัสอะไหล่ที่จ่ายจริง *': 'PART-0001' })
  const closed = await post(request, MGR, `/repairs/${repairId}/close`, {})
  expect(closed.ok(), await closed.text()).toBe(true)

  const blocked = await (await request.get(`/api/v1/repairs/${repairId}/classification`, { headers: MGR })).json()
  expect(blocked.state).toBe('BLOCKED_STORE_UNRECONCILED')
  await tech.reload()
  await lineStep(tech, 'ยืนยันใช้จริง', { 'จำนวน (ชิ้น) *': '1', 'อะไหล่ (ตามที่จ่ายจริง) *': 'PART-0001|', 'ตำแหน่งที่ติดตั้ง *': 'ล้อหน้าซ้าย' })
  await expect(tech.getByText('สถานะกระทบยอด: ครบแล้ว')).toBeVisible()

  await mgr.reload()
  await expect(mgr.getByText('TEST candidate — ไม่อนุมัติสำหรับ REAL').first()).toBeVisible()
  await mgr.getByLabel('1 ระบบหลัก').selectOption('ACM')
  await mgr.getByLabel('2 ชุดอุปกรณ์').selectOption('AC')
  await mgr.getByLabel('3 จุดที่ผิดปกติ').selectOption('P052')
  await mgr.getByLabel(/^S01 —/).check()
  await mgr.getByLabel(/^A03 —/).check()
  await mgr.getByRole('button', { name: 'เพิ่มจุดเสียในรายการ' }).click()
  await mgr.getByRole('button', { name: /บันทึกร่าง/ }).click()
  await expect(mgr.getByText('บันทึกร่างแล้ว')).toBeVisible()
  await mgr.getByRole('button', { name: 'ยืนยันจัดประเภท' }).click()
  await expect(mgr.getByText('จัดประเภทเรียบร้อย (TEST)')).toBeVisible()
  await expect(mgr.getByRole('list', { name: 'ผลการจัดประเภท' })).toContainText('ACM-AC-P052')

  const state = await (await request.get(`/api/v1/repairs/${repairId}/classification`, { headers: MGR })).json()
  expect(state.state).toBe('CLASSIFIED')
  expect(state.final.catalogue_rule).toBe('TEST-CANDIDATE-R1')
  await mgr.context().close()
  await tech.context().close()
})

test('fail-closed: unreconciled block, non-candidate / bad symptom / unknown code, replay, duplicate issue, permission', async ({ request }) => {
  const repairId = await openRepair(request)
  const created = await post(request, TECH1, `/repairs/${repairId}/store-requests`,
    { lines: [{ part_id: 'PART-0001', part_description: 'x', quantity: 1, unit: 'ชิ้น' }] })
  const line = (await created.json()).events[0].requisition_line_id as string
  expect((await post(request, MGR, `/repairs/${repairId}/store-lines/${line}/approvals`, { quantity: 1 })).ok()).toBe(true)
  const issueId = rid('issue')
  const issue = { quantity: 1, part_id: 'PART-0001' }
  const first = await post(request, MGR, `/repairs/${repairId}/store-lines/${line}/issues`, issue, issueId)
  const again = await post(request, MGR, `/repairs/${repairId}/store-lines/${line}/issues`, issue, issueId)
  expect((await again.json()).replayed).toBe(true)
  expect((await again.json()).events[0].event_id).toBe((await first.json()).events[0].event_id)
  const over = await post(request, MGR, `/repairs/${repairId}/store-lines/${line}/issues`, issue)
  expect([over.status(), (await over.json()).error.code]).toEqual([409, expect.stringMatching(/^STORE_/)])
  const clerk = await post(request, CLERK, `/repairs/${repairId}/store-lines/${line}/approvals`, { quantity: 1 })
  expect(clerk.status()).toBe(403)
  expect((await post(request, MGR, `/repairs/${repairId}/close`, {})).ok()).toBe(true)

  const row = (over: Record<string, unknown> = {}) => ({ system: 'ACM', assembly: 'AC', point: 'P052', symptoms: ['S01'],
    actions: ['A03'], position: {}, ...over })
  const stage = (rows: unknown[]) => post(request, MGR, `/repairs/${repairId}/classification-drafts`, { expected_revision: 0, rows })
  const blocked = await stage([row()])
  expect([blocked.status(), (await blocked.json()).error.code]).toEqual([409, 'CLASSIFICATION_BLOCKED_STORE_UNRECONCILED'])
  await post(request, TECH1, `/repairs/${repairId}/store-lines/${line}/use-confirmations`,
    { quantity: 1, part_id: 'PART-0001', position_code: 'P1' })
  for (const [body, status, code] of [
    [row({ point: 'P135' }), 422, 'REPAIR_CODE_ENTRY_NOT_IN_TEST_SUBSET'],
    [row({ symptoms: ['S03'] }), 422, 'REPAIR_SYMPTOM_NOT_ALLOWED'],
    [row({ point: 'P999' }), 422, 'REPAIR_CODE_UNKNOWN'],
    [row({ actions: ['A99'] }), 422, 'REPAIR_ACTION_UNKNOWN'],
  ] as const) {
    const refused = await stage([body])
    expect([refused.status(), (await refused.json()).error.code], JSON.stringify(body)).toEqual([status, code])
  }
  const noGrant = await post(request, CLERK, `/repairs/${repairId}/classification-drafts`, { expected_revision: 0, rows: [row()] })
  expect(noGrant.status()).toBe(403)
  const events = await (await request.get('/api/v1/store-material-events?limit=500', { headers: MGR })).json()
  const issued = (events.items ?? events.events).filter((e: Record<string, string>) => e.requisition_line_id === line && e.event_type === 'ISSUED')
  expect(issued).toHaveLength(1)
  expect(issued[0]).not.toHaveProperty('fingerprint')
})
