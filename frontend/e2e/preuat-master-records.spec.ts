import { expect, test, type APIRequestContext, type Browser, type Page } from '@playwright/test'
import { expectNoHorizontalOverflow, uuidFrom } from './r3Support'

/**
 * R8 PRE-UAT (Owner approval Rev 1, workstream A) — TEST master records through the web UI.
 * Dedicated invocation only (Access Management mode + synthetic UAT fixture profile):
 *   PREUAT_E2E=1 npx playwright test e2e/preuat- --workers=1
 * Writes run once, on the desktop project. Mock TEST evidence only.
 */
const ENABLED = process.env.PREUAT_E2E === '1'
const as = (user: string) => ({ 'X-Dev-Role': 'TECHNICIAN', 'X-Dev-User-Id': user })
const MGR = as('USR-TEST-AM-MGR')
const CLERK = as('USR-TEST-AM-CLERK')

test.skip(!ENABLED, 'needs the PRE-UAT backend (PREUAT_E2E=1)')

async function grant(request: APIRequestContext, personnelId: string, changes: Record<string, boolean>) {
  const revision = (await (await request.get('/api/v1/access/me', { headers: MGR })).json()).revision as number
  const response = await request.post('/api/v1/access/grants', {
    headers: { ...MGR, 'X-Request-Id': uuidFrom(`preuat-mr-${personnelId}-${Date.now()}-${Math.random()}`) },
    data: { target: { kind: 'EMPLOYEE', personnel_id: personnelId }, changes, reason_th: 'PRE-UAT E2E', expected_revision: revision },
  })
  expect(response.ok(), await response.text()).toBe(true)
}

async function open(browser: Browser, baseURL: string | undefined, headers: Record<string, string>, path: string): Promise<Page> {
  const page = await (await browser.newContext({ baseURL, extraHTTPHeaders: headers })).newPage()
  await page.goto(path)
  return page
}

test.beforeAll(async ({ request }) => {
  if (!ENABLED) return
  await grant(request, 'PER-TEST-AM-MGR', { can_view: true, can_test_manage_master_records: true })
  await grant(request, 'PER-TEST-AM-CLERK', { can_view: true })
})

test('the master-data page lists the UAT fixture models and fits the viewport', async ({ browser, baseURL }) => {
  const page = await open(browser, baseURL, MGR, '/master-data')
  await expect(page.getByRole('heading', { level: 1, name: 'ข้อมูลหลัก' })).toBeVisible()
  await expect(page.getByText('UAT8-MDL-A')).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await page.context().close()
})

test.describe('@mutation', () => {
  test.beforeEach(({ baseURL: _b }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'writes run once, on the desktop project')
  })

  test('create a TEST vehicle in the UI, open it, and refuse a duplicate machine number', async ({ browser, baseURL }) => {
    const machineNo = `E2E/${Date.now() % 100000}`
    const page = await open(browser, baseURL, MGR, '/vehicles')
    await page.getByRole('button', { name: 'เพิ่มรถ (TEST)' }).click()
    await page.getByLabel('หมายเลขเครื่องจักร *').fill(machineNo)
    await page.getByLabel('รหัสรุ่น *').fill('UAT8-MDL-A')
    await page.getByLabel('สถานะ *').selectOption('READY')
    await page.getByRole('button', { name: 'บันทึก' }).click()
    await expect(page).toHaveURL(/\/vehicle\/VEH-TEST-\d+/)
    await expect(page.getByText(machineNo).first()).toBeVisible()

    await page.goto('/vehicles')
    await page.getByRole('button', { name: 'เพิ่มรถ (TEST)' }).click()
    await page.getByLabel('หมายเลขเครื่องจักร *').fill(machineNo)
    await page.getByLabel('รหัสรุ่น *').fill('UAT8-MDL-A')
    await page.getByLabel('สถานะ *').selectOption('READY')
    await page.getByRole('button', { name: 'บันทึก' }).click()
    await expect(page.getByText('มีข้อมูลที่ใช้ค่านี้อยู่แล้ว ไม่ได้บันทึก')).toBeVisible()
    await page.context().close()
  })

  test('create and edit a TEST branch on the master-data page; history records both', async ({ browser, baseURL, request }) => {
    const name = `สาขา E2E ${Date.now() % 100000}`
    const page = await open(browser, baseURL, MGR, '/master-data')
    await page.getByRole('tab', { name: 'สาขา' }).click()
    await page.getByRole('button', { name: 'เพิ่มสาขา (TEST)' }).click()
    await page.getByLabel('ชื่อสาขา *').fill(name)
    await page.getByRole('button', { name: 'บันทึก' }).click()
    const row = page.getByRole('row').filter({ hasText: name })
    await expect(row).toBeVisible()
    await row.getByRole('button', { name: 'แก้ไข' }).click()
    await page.getByLabel('ชื่อสาขา *').fill(`${name} แก้ไข`)
    await page.getByRole('button', { name: 'บันทึก' }).click()
    await expect(page.getByRole('row').filter({ hasText: `${name} แก้ไข` })).toBeVisible()
    const list = await (await request.get('/api/v1/master-records/branches', { headers: MGR })).json()
    const created = list.items.find((b: Record<string, string>) => b.branch_name === `${name} แก้ไข`)
    expect(created.scope).toBe('TEST')
    const history = await (await request.get(`/api/v1/master-records/branches/${created.branch_id}/history`, { headers: MGR })).json()
    expect(history.events.map((e: Record<string, string>) => e.action)).toEqual(['CREATE', 'UPDATE'])
    await page.context().close()
  })

  test('a plain reader sees no TEST controls and the API refuses them', async ({ browser, baseURL, request }) => {
    const page = await open(browser, baseURL, CLERK, '/vehicles')
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await expect(page.getByRole('button', { name: 'เพิ่มรถ (TEST)' })).toHaveCount(0)
    const refused = await request.post('/api/v1/master-records/branches', {
      headers: { ...CLERK, 'X-Request-Id': uuidFrom(`preuat-mr-clerk-${Date.now()}`) }, data: { branch_name: 'x' } })
    expect(refused.status()).toBe(403)
    const real = await request.patch('/api/v1/master-records/models/MODEL-0002', {
      headers: { ...MGR, 'X-Request-Id': uuidFrom(`preuat-mr-real-${Date.now()}`) }, data: { model_name: 'x' } })
    expect([real.status(), (await real.json()).error.code]).toEqual([409, 'MASTER_RECORD_NOT_TEST_SCOPED'])
    await page.context().close()
  })
})
