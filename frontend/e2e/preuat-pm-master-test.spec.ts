import { randomUUID } from 'node:crypto'
import { expect, test, type APIRequestContext, type Browser, type Page } from '@playwright/test'

/**
 * R8 PRE-UAT SG-PM (Owner Consolidated Source Expansion Gate 2026-11-18) — the PM Master TEST profile in the
 * browser: register the synthetic source → decide the REVIEW entry → publish → approve the model variant →
 * assign the vehicle (separate grant) → vehicle PM Due → open a Master-sourced PM Work Order → its page.
 * Dedicated invocation only (Access Management + uat_r8 + PM_MASTER_TEST_PROFILE):
 *   PREUAT_E2E=1 npx playwright test e2e/preuat- --workers=1
 * Writes run once, on the desktop project. Mock TEST evidence only (synthetic source, not a real PM standard).
 */
const ENABLED = process.env.PREUAT_E2E === '1'
const as = (user: string) => ({ 'X-Dev-Role': 'TECHNICIAN', 'X-Dev-User-Id': user })
const MGR = as('USR-TEST-AM-MGR')
const OPM = as('USR-TEST-AM-OPM')

test.skip(!ENABLED, 'needs the PRE-UAT backend (PREUAT_E2E=1)')
test.describe.configure({ mode: 'serial' })
test.beforeEach(({ baseURL: _b }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'writes run once, on the desktop project')
})

async function grant(request: APIRequestContext, personnelId: string, changes: Record<string, boolean>) {
  const revision = (await (await request.get('/api/v1/access/me', { headers: MGR })).json()).revision as number
  const r = await request.post('/api/v1/access/grants', { headers: { ...MGR, 'X-Request-Id': randomUUID() },
    data: { target: { kind: 'EMPLOYEE', personnel_id: personnelId }, changes, reason_th: 'PRE-UAT E2E PM Master',
      expected_revision: revision } })
  expect(r.ok(), await r.text()).toBe(true)
}

async function open(browser: Browser, baseURL: string | undefined, headers: Record<string, string>, path: string): Promise<Page> {
  const page = await (await browser.newContext({ baseURL, extraHTTPHeaders: headers })).newPage()
  await page.goto(path)
  return page
}

test('before any grant: the page is read-only and the API refuses every Master write', async ({ browser, baseURL, request }) => {
  await grant(request, 'PER-TEST-AM-OPM', { can_view: true })
  const page = await open(browser, baseURL, OPM, '/pm-master-test')
  await expect(page.getByText(/โปรไฟล์ทดสอบแผน PM หลัก/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'ลงทะเบียนต้นทางสังเคราะห์' })).toHaveCount(0)
  const refused = await request.post('/api/v1/pm-master-test/previews', { headers: { ...OPM, 'X-Request-Id': randomUUID() },
    data: { reason: 'x' } })
  expect([refused.status(), (await refused.json()).error.code]).toEqual([403, 'PM_MASTER_AUTHORITY_UNPROVEN'])
  await page.context().close()
})

test('preview → review → publish → variant → assign → due → open a PM Work Order in the browser', async ({ browser, baseURL, request }) => {
  await grant(request, 'PER-TEST-AM-MGR', { can_view: true, can_test_pm_master_publish: true, can_manage_pm: true })
  await grant(request, 'PER-TEST-AM-OPM', { can_view: true, can_test_pm_master_assign: true })
  const editor = await open(browser, baseURL, MGR, '/pm-master-test')
  await editor.getByRole('button', { name: 'ลงทะเบียนต้นทางสังเคราะห์' }).click()
  await expect(editor.getByText('ลงทะเบียนตัวอย่างแล้ว')).toBeVisible()
  await expect(editor.getByRole('button', { name: /เผยแพร่ฉบับที่ 1/ })).toBeDisabled() // REVIEW still open
  await editor.getByLabel('มิเตอร์ที่ใช้').selectOption('CARRIER')
  await editor.getByRole('button', { name: 'ยืนยันมิเตอร์' }).click()
  await expect(editor.getByText('บันทึกการตัดสินใจแล้ว')).toBeVisible()
  await editor.getByRole('button', { name: /เผยแพร่ฉบับที่ 1/ }).click()
  await expect(editor.getByText('เผยแพร่แล้ว')).toBeVisible()
  await expect(editor.getByRole('heading', { name: 'ฉบับที่ใช้งาน: 1' })).toBeVisible()
  await expect(editor.getByText('UAT8-V-A|CRANE|A')).toBeVisible()
  await editor.getByRole('button', { name: 'อนุมัติ UAT8-V-A' }).click()
  await expect(editor.getByText('อนุมัติรุ่นแล้ว')).toBeVisible()
  await expect(editor.getByRole('button', { name: /กำหนดแผนให้/ })).toHaveCount(0) // the editor cannot assign

  const assigner = await open(browser, baseURL, OPM, '/pm-master-test')
  await assigner.getByRole('button', { name: 'กำหนดแผนให้ UAT8-VEH-01' }).click()
  await expect(assigner.getByText('กำหนดแผนแล้ว')).toBeVisible()
  await expect(assigner.getByRole('link', { name: /ดูกำหนด PM และเปิดใบงานจากแผนหลัก/ })).toBeVisible()

  await editor.goto('/vehicle/UAT8-VEH-01/pm/due')
  await expect(editor.getByRole('heading', { name: 'แผน PM หลัก (ทดสอบ)' })).toBeVisible()
  await editor.getByLabel('UAT8-V-A|CRANE|A').check()
  await editor.getByLabel('UAT8-V-A|CARRIER|A').check()
  await editor.getByRole('button', { name: 'เปิดใบงาน PM จากแผนหลัก' }).click()
  const link = editor.getByRole('link', { name: /^PMWO-/ })
  await expect(link).toBeVisible()
  const job = (await link.innerText()).trim()
  const detail = await request.get(`/api/v1/pm/work-orders/${job}`, { headers: MGR })
  expect(detail.ok(), await detail.text()).toBe(true)
  expect((await detail.json()).work_order.asset_id).toBe('UAT8-VEH-01')
  await link.click()
  await expect(editor).toHaveURL(new RegExp(`/pm/work-orders/${job}$`))
  // Due stays UNKNOWN until a verified completion (no IoT meter source in the application — R9).
  const due = await (await request.get('/api/v1/pm-master-test/vehicles/UAT8-VEH-01/due', { headers: MGR })).json()
  expect(new Set(due.sets.map((s: { status: string }) => s.status))).toEqual(new Set(['UNKNOWN']))
  await editor.context().close()
  await assigner.context().close()
})
