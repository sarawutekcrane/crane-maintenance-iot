import { randomUUID } from 'node:crypto'
import { expect, test, type APIRequestContext } from '@playwright/test'

/**
 * R8 PRE-UAT (Owner approval Rev 1, workstream F) — part-set editor and part maintenance events.
 *
 * Default invocation (legacy mode): the UI drives the EXISTING routes end to end — a part set with
 * REQUIRED / ALTERNATIVE items and an applicability, and an inspection / in-place repair that never
 * opens or closes a lifecycle. Dedicated PRE-UAT invocation (Access Management mode, PG-5 P-A): the same
 * UI succeeds only for a verified employee holding can_test_manage_parts; others see no control and get 403.
 * Desktop project only, serial. Mock TEST evidence only.
 */
const PREUAT = process.env.PREUAT_E2E === '1'
test.describe.configure({ mode: 'serial' })
test.skip(() => test.info().project.name !== 'desktop', 'writes run once, on the desktop project')

async function registerInstance(request: APIRequestContext): Promise<string> {
  const repair = await request.post('/api/v1/repairs', {
    data: { asset_type: 'VEHICLE', asset_id: 'VEH-1048', source_type: 'MANUAL', symptom: 'PRE-UAT E2E (ทดสอบ)' } })
  expect(repair.ok(), await repair.text()).toBe(true)
  const created = await request.post('/api/v1/part-instances', {
    headers: { 'X-Request-Id': randomUUID() },
    data: { part_id: 'PART-0005', tag_label: `PREUAT-${randomUUID()}`,
      prior_usage: { quality: 'KNOWN', value: 0, evidence_type: 'NEW_PART', as_of: '2026-01-01',
        evidence_reference: (await repair.json()).repair.repair_id } },
  })
  expect(created.ok(), await created.text()).toBe(true)
  return (await created.json()).instance.part_instance_id as string
}

test.describe('legacy mode UI', () => {
  test.skip(PREUAT, 'the parts writes are D6 fail-closed in Access Management mode')

  test('build a part set with an alternative item and an applicability from the part page', async ({ page }) => {
    await page.goto('/parts/PART-0001')
    await page.getByLabel('รหัสชุด', { exact: true }).fill(`SET-E2E-${Date.now() % 100000}`)
    await page.getByLabel('ชื่อชุด', { exact: true }).fill('ชุดทดสอบ PRE-UAT')
    await page.getByRole('button', { name: 'สร้างชุดอะไหล่' }).click()
    await expect(page.getByText(/สร้างชุดอะไหล่แล้ว: /)).toBeVisible()
    await page.getByRole('button', { name: 'เพิ่มรายการ' }).click()
    await page.getByLabel('รหัสอะไหล่ แถว 2').fill('PART-0002')
    await page.getByLabel('ความจำเป็น แถว 2').selectOption('ALTERNATIVE')
    await page.getByLabel('ทดแทนแถวที่ (เริ่ม 0) แถว 2').fill('0')
    // An effective date of today makes the revision active at once (a future date is saved but not yet active).
    const today = new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Bangkok' })
    await page.getByLabel('วันที่มีผล', { exact: true }).fill(today)
    await page.getByRole('button', { name: 'บันทึกฉบับปรับปรุง' }).click()
    await expect(page.getByText('บันทึกฉบับปรับปรุงแล้ว')).toBeVisible()
    await expect(page.getByText(new RegExp(`ฉบับที่ 1 มีผล ${today}`))).toBeVisible()
    await page.getByLabel('รหัสรุ่น', { exact: true }).fill('MODEL-0002')
    await page.getByLabel('มีผลตั้งแต่', { exact: true }).fill('2026-12-01')
    await page.getByRole('button', { name: 'บันทึกรุ่นที่ใช้ได้' }).click()
    await expect(page.getByText('บันทึกรุ่นที่ใช้ได้แล้ว')).toBeVisible()
  })

  test('an in-place repair is recorded against a REPAIR rule without opening or closing a lifecycle', async ({ page, request }) => {
    // A synthetic TEST REPAIR rule scoped to MODEL-0002 (never VEH-1048's model, so no R6 counter is affected).
    const note = `SYNTHETIC TEST REPAIR RULE (PRE-UAT e2e) ${randomUUID().slice(0, 8)}`
    const rule = await request.post('/api/v1/lifetime-rules', {
      data: { part_id: 'PART-0005', scope: 'MODEL', model_id: 'MODEL-0002', trigger_type: 'ENGINE_HOUR',
        component_role: 'CARRIER_ENGINE', interval_value: 250, interval_unit: 'HOUR', due_action: 'REPAIR', note } })
    expect(rule.ok(), await rule.text()).toBe(true)
    const ruleId = (await rule.json()).lifetime_rule_id as string
    const id = await registerInstance(request)
    const before = await (await request.get(`/api/v1/part-instances/${id}`)).json()
    await page.goto(`/part-instances/${id}`)
    await expect(page.getByText(/เริ่มรอบการใช้งานใหม่/)).toHaveCount(0) // R6 A-2(ii)
    await page.getByRole('button', { name: 'บันทึกการตรวจ/ซ่อมในที่ (ไม่รีเซ็ตอายุ)' }).click()
    await page.locator('#maint-action').selectOption('REPAIRED_IN_PLACE')
    await page.locator('#maint-target').selectOption(`rule:${ruleId}`)
    await page.locator('#maint-outcome').fill('ปกติ')
    const saved = page.waitForResponse((r) => r.url().endsWith(`/part-instances/${id}/maintenance-events`))
    await page.getByRole('button', { name: 'บันทึก', exact: true }).click()
    expect((await saved).status()).toBe(200)
    const after = await (await request.get(`/api/v1/part-instances/${id}`)).json()
    expect(after.lifecycles.length).toBe(before.lifecycles.length)
    expect(after.instance.current_lifecycle_id).toBe(before.instance.current_lifecycle_id)
  })
})

test.describe('Access Management mode (PG-5 P-A: explicit TEST grant)', () => {
  test.skip(!PREUAT, 'needs the PRE-UAT backend (PREUAT_E2E=1)')
  const MGR = { 'X-Dev-Role': 'TECHNICIAN', 'X-Dev-User-Id': 'USR-TEST-AM-MGR' }
  const CLERK = { 'X-Dev-Role': 'TECHNICIAN', 'X-Dev-User-Id': 'USR-TEST-AM-CLERK' }

  async function grant(request: APIRequestContext, personnelId: string, changes: Record<string, boolean>) {
    const revision = (await (await request.get('/api/v1/access/me', { headers: MGR })).json()).revision as number
    const r = await request.post('/api/v1/access/grants', { headers: { ...MGR, 'X-Request-Id': randomUUID() },
      data: { target: { kind: 'EMPLOYEE', personnel_id: personnelId }, changes, reason_th: 'PRE-UAT E2E PG-5',
        expected_revision: revision } })
    expect(r.ok(), await r.text()).toBe(true)
  }

  test('without the grant the controls are hidden and the API refuses; other R6 writes stay unresolved', async ({ browser, baseURL, request }) => {
    await grant(request, 'PER-TEST-AM-CLERK', { can_view: true, can_manage_repair: true })
    const page = await (await browser.newContext({ baseURL, extraHTTPHeaders: CLERK })).newPage()
    await page.goto('/part-instances/UAT8-PINST-01')
    await expect(page.getByText('UAT8-SN-P01').first()).toBeVisible()
    await expect(page.getByText('บันทึกการตรวจ/ซ่อมในที่ (ไม่รีเซ็ตอายุ)')).toHaveCount(0)
    await page.goto('/parts/PART-0001')
    await expect(page.getByRole('heading', { name: 'ชุดอะไหล่ (Part Set)' })).toHaveCount(0)
    for (const path of ['/api/v1/part-sets', '/api/v1/part-instances/UAT8-PINST-01/maintenance-events']) {
      const r = await request.post(path, { headers: { ...CLERK, 'X-Request-Id': randomUUID() }, data: {} })
      expect([r.status(), (await r.json()).error.code], path).toEqual([403, 'PREUAT_ACTION_NOT_AUTHORIZED'])
    }
    const status = await request.post('/api/v1/part-instances/UAT8-PINST-01/status',
      { headers: { ...MGR, 'X-Request-Id': randomUUID() }, data: {} })
    expect([status.status(), (await status.json()).error.code]).toEqual([403, 'ACCESS_CAPABILITY_MAPPING_UNRESOLVED'])
    await page.context().close()
  })

  test('a grant holder builds a part set and records an in-place repair in the browser', async ({ browser, baseURL, request }) => {
    await grant(request, 'PER-TEST-AM-MGR', { can_view: true, can_manage_repair: true, can_test_manage_parts: true })
    const page = await (await browser.newContext({ baseURL, extraHTTPHeaders: MGR })).newPage()
    await page.goto('/parts/PART-0001')
    await page.getByLabel('รหัสชุด', { exact: true }).fill(`SET-AM-${Date.now() % 100000}`)
    await page.getByLabel('ชื่อชุด', { exact: true }).fill('ชุดทดสอบ AM')
    await page.getByRole('button', { name: 'สร้างชุดอะไหล่' }).click()
    await expect(page.getByText(/สร้างชุดอะไหล่แล้ว: /)).toBeVisible()
    await page.goto('/part-instances/UAT8-PINST-01')
    const before = await (await request.get('/api/v1/part-instances/UAT8-PINST-01', { headers: MGR })).json()
    await page.getByRole('button', { name: 'บันทึกการตรวจ/ซ่อมในที่ (ไม่รีเซ็ตอายุ)' }).click()
    await page.locator('#maint-action').selectOption('REPAIRED_IN_PLACE')
    await page.locator('#maint-target').selectOption('rule:UAT8-LTR-REPAIR')
    const saved = page.waitForResponse((r) => r.url().endsWith('/part-instances/UAT8-PINST-01/maintenance-events'))
    await page.getByRole('button', { name: 'บันทึก', exact: true }).click()
    expect((await saved).status()).toBe(200)
    const after = await (await request.get('/api/v1/part-instances/UAT8-PINST-01', { headers: MGR })).json()
    expect(after.lifecycles.length).toBe(before.lifecycles.length)
    await page.context().close()
  })
})
