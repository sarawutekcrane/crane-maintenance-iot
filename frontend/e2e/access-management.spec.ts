import { expect, test, type APIRequestContext, type Browser, type Page } from '@playwright/test'
import { expectNoHorizontalOverflow, uuidFrom } from './r3Support'

/**
 * Access Management + L11 (Owner-approved Mock implementation).
 *
 * Runs ONLY in the dedicated invocation whose backend is in Access Management
 * mode (fresh mock backend, synthetic Access Management seed):
 *   ACCESS_MANAGEMENT_E2E=1 npx playwright test e2e/access-management.spec.ts --workers=1
 * The `@mutation` tests write and run on the desktop project only; the layout check
 * runs in every viewport. Mock TEST evidence only — never production evidence.
 */
const ENABLED = process.env.ACCESS_MANAGEMENT_E2E === '1'
const as = (user: string) => ({ 'X-Dev-Role': 'TECHNICIAN', 'X-Dev-User-Id': user })
const MGR = as('USR-TEST-AM-MGR')
const OPM = as('USR-TEST-AM-OPM')
const DRV1 = as('USR-TEST-AM-DRV1')
const CLERK = as('USR-TEST-AM-CLERK')
const TECH1 = as('USR-TEST-911')

test.skip(!ENABLED, 'needs the Access Management mode backend (ACCESS_MANAGEMENT_E2E=1)')

async function open(browser: Browser, baseURL: string | undefined, headers: Record<string, string>): Promise<Page> {
  const context = await browser.newContext({ baseURL, extraHTTPHeaders: headers })
  return context.newPage()
}

async function revision(request: APIRequestContext, headers: Record<string, string>): Promise<number> {
  return (await (await request.get('/api/v1/access/me', { headers })).json()).revision as number
}

async function grant(request: APIRequestContext, actor: Record<string, string>, personnelId: string, changes: Record<string, boolean>) {
  const response = await request.post('/api/v1/access/grants', {
    headers: { ...actor, 'X-Request-Id': uuidFrom(`am-e2e-${personnelId}-${JSON.stringify(changes)}-${Date.now()}`) },
    data: { target: { kind: 'EMPLOYEE', personnel_id: personnelId }, changes, reason_th: 'E2E', expected_revision: await revision(request, actor) },
  })
  expect(response.ok(), await response.text()).toBe(true)
}

async function caps(request: APIRequestContext, headers: Record<string, string>): Promise<string[]> {
  return (await (await request.get('/api/v1/me', { headers })).json()).capabilities as string[]
}

test('the single screen fits every viewport and offers department → position → employee', async ({ browser, baseURL }) => {
  const page = await open(browser, baseURL, MGR)
  await page.goto('/access-management')
  await expect(page.getByRole('heading', { name: 'จัดการสิทธิ์ผู้ใช้งาน' })).toBeVisible()
  await page.getByLabel('1. แผนก').selectOption('DEPT-TEST-OPS')
  await expect(page.getByLabel('3. พนักงาน')).toBeEnabled()
  await page.getByLabel('3. พนักงาน').selectOption('__ALL__')
  await expect(page.getByTestId('access-category-J')).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await page.context().close()
})

test.describe('@mutation', () => {
  test.beforeEach(({ baseURL: _baseURL }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'writes run once, on the desktop project')
  })

  test('a department bulk grant previews, confirms and applies on the next request without re-login', async ({ browser, baseURL, request }) => {
    expect(await caps(request, DRV1)).toEqual([])
    const page = await open(browser, baseURL, MGR)
    await page.goto('/access-management')
    await page.getByLabel('1. แผนก').selectOption('DEPT-TEST-OPS')
    await page.getByLabel('3. พนักงาน').selectOption('__ALL__')
    await page.getByRole('switch', { name: 'แจ้งปัญหา/แจ้งซ่อม' }).click()
    await page.getByRole('button', { name: 'ตรวจสอบก่อนบันทึก' }).click()
    await expect(page.getByTestId('access-preview')).toContainText('มีผลกับพนักงาน 3 คน')
    await page.getByLabel('เหตุผลของการเปลี่ยนสิทธิ์ (จำเป็น)').fill('ทุกคนในแผนกแจ้งซ่อมได้')
    await page.getByRole('button', { name: 'บันทึกการเปลี่ยนสิทธิ์' }).click()
    await page.getByRole('button', { name: 'ยืนยันบันทึก' }).click()
    await expect(page.getByTestId('access-saved')).toContainText('กับพนักงาน 3 คน')
    expect(await caps(request, DRV1)).toEqual(['can_report_repair'])
    await expect(page.getByRole('switch', { name: 'แจ้งปัญหา/แจ้งซ่อม' })).toHaveText('เปิด')
    await expect(page.getByTestId('access-audit')).toContainText('ให้สิทธิ์')
    await page.context().close()
  })

  test('a delegate administers only the delegated list in the delegated department and never themself', async ({ browser, baseURL, request }) => {
    const root = await open(browser, baseURL, MGR)
    await root.goto('/access-management')
    await root.getByLabel('1. แผนก').selectOption('DEPT-TEST-OPS')
    await root.getByLabel('3. พนักงาน').selectOption('PER-TEST-AM-OPM')
    await root.getByText('มอบอำนาจจัดการสิทธิ์ให้').click()
    await root.getByLabel('แผนกที่มอบอำนาจ').selectOption('DEPT-TEST-OPS')
    await root.locator('.access-delegation-form').getByLabel('ดูข้อมูล รายงาน และประวัติ').check()
    await root.getByLabel('เหตุผลการมอบอำนาจ (จำเป็น)').fill('หัวหน้าปฏิบัติการดูแลสิทธิ์ดูข้อมูล')
    await root.getByRole('button', { name: 'มอบอำนาจ', exact: true }).click()
    await expect(root.getByText(/มอบอำนาจให้ .* แล้ว/)).toBeVisible()
    await root.context().close()

    const delegate = await open(browser, baseURL, OPM)
    await delegate.goto('/access-management')
    await expect(delegate.getByTestId('access-authority')).toContainText('ห้ามมอบต่อ')
    await delegate.getByLabel('1. แผนก').selectOption('DEPT-TEST-OPS')
    await delegate.getByLabel('3. พนักงาน').selectOption('PER-TEST-AM-OPM')
    await expect(delegate.getByTestId('access-self-locked')).toBeVisible()
    await delegate.getByLabel('3. พนักงาน').selectOption('__ALL__')
    await expect(delegate.getByTestId('access-bulk-excluded')).toContainText('แก้ไขสิทธิ์ของตนเองไม่ได้') // D1: never silent
    await delegate.getByLabel('3. พนักงาน').selectOption('PER-TEST-AM-DRV2')
    await expect(delegate.getByRole('switch', { name: 'แจ้งปัญหา/แจ้งซ่อม' })).toBeDisabled() // not delegated
    await delegate.getByRole('switch', { name: 'ดูข้อมูล รายงาน และประวัติ' }).click()
    await delegate.getByRole('button', { name: 'ตรวจสอบก่อนบันทึก' }).click()
    await delegate.getByLabel('เหตุผลของการเปลี่ยนสิทธิ์ (จำเป็น)').fill('ให้ดูข้อมูล')
    await delegate.getByRole('button', { name: 'บันทึกการเปลี่ยนสิทธิ์' }).click()
    await delegate.getByRole('button', { name: 'ยืนยันบันทึก' }).click()
    await expect(delegate.getByTestId('access-saved')).toBeVisible()
    expect(await caps(request, as('USR-TEST-AM-DRV2'))).toContain('can_view')
    const outside = await request.get('/api/v1/access/employees?department_id=DEPT-TEST-MNT', { headers: OPM })
    expect(outside.status()).toBe(403)
    await delegate.context().close()
  })

  test('L11: a Finding delegate opens a round from an R3 Finding but has no MANUAL repair authority', async ({ browser, baseURL, request }) => {
    await grant(request, MGR, 'PER-TEST-911', { can_record_inspection: true, can_view: true })
    await grant(request, MGR, 'PER-TEST-AM-CLERK', { can_manage_finding_repair: true, can_view: true })
    const form = await (await request.get('/api/v1/inspections/form?asset_type=VEHICLE&asset_id=VEH-1046', { headers: TECH1 })).json()
    const items = (form.items as { item: { item_id: string } }[]).map((entry, index) => ({
      item_id: entry.item.item_id, result: index === 0 ? 'FAIL' : 'PASS', remark: index === 0 ? 'น้ำมันรั่ว - E2E AM' : null,
    }))
    const submitted = await request.post('/api/v1/inspections', {
      headers: { ...TECH1, 'X-Request-Id': uuidFrom(`am-e2e-inspection-${Date.now()}`) },
      data: { asset_type: 'VEHICLE', asset_id: 'VEH-1046', items },
    })
    expect(submitted.ok(), await submitted.text()).toBe(true)
    const findingId = (await submitted.json()).findings[0].finding_id as string

    const clerk = await open(browser, baseURL, CLERK)
    await clerk.goto(`/findings/${findingId}`)
    await clerk.getByRole('button', { name: 'เปิดใบงานซ่อมจากรายการนี้' }).click()
    await expect(clerk).toHaveURL(/\/repairs\/RPR-/)
    await clerk.context().close()
    const manual = await request.post('/api/v1/repairs', {
      headers: CLERK, data: { asset_type: 'VEHICLE', asset_id: 'VEH-1047', source_type: 'MANUAL' },
    })
    expect(manual.status()).toBe(403)
  })

  test('B1: an account-link grantee can neither unlink nor relink the root holder', async ({ request }) => {
    await grant(request, MGR, 'PER-TEST-AM-CLERK', { can_link_personnel_account: true })
    for (const data of [
      { operation: 'UNLINK', expected_user_id: 'USR-TEST-AM-MGR', reason_th: 'E2E' },
      { operation: 'RELINK', expected_user_id: 'USR-TEST-AM-MGR', new_user_id: 'USR-TEST-901', reason_th: 'E2E' },
    ]) {
      const attack = await request.post('/api/v1/personnel/PER-TEST-AM-MGR/account-links', {
        headers: { ...CLERK, 'X-Request-Id': uuidFrom(`am-e2e-b1-${data.operation}-${Date.now()}`) }, data,
      })
      expect(attack.status()).toBe(403)
      expect((await attack.json()).error.code).toBe('ACCESS_ROOT_PROTECTED')
    }
    expect((await (await request.get('/api/v1/access/me', { headers: MGR })).json()).is_root).toBe(true)
  })

  test('an effective department transfer ends every permission of the moved employee', async ({ request }) => {
    await grant(request, MGR, 'PER-TEST-AM-MGR', { can_move_personnel_department: true })
    await grant(request, MGR, 'PER-TEST-AM-DRV1', { can_view: true })
    expect(await caps(request, DRV1)).toContain('can_view')
    const moved = await request.post('/api/v1/personnel/PER-TEST-AM-DRV1/department-events', {
      headers: { ...MGR, 'X-Request-Id': uuidFrom(`am-e2e-transfer-${Date.now()}`) },
      data: { operation: 'TRANSFER', department_id: 'DEPT-TEST-MNT', effective: { mode: 'NOW' }, expected_current_department_id: 'DEPT-TEST-OPS', reason_th: 'ย้าย' },
    })
    expect(moved.ok(), await moved.text()).toBe(true)
    expect(await caps(request, DRV1)).toEqual([])
  })
})
