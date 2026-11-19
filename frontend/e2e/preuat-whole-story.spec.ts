import { readFileSync } from 'node:fs'
import { expect, test, type APIRequestContext, type Browser, type Page } from '@playwright/test'
import { expectNoHorizontalOverflow, uuidFrom } from './r3Support'

/**
 * R8 PRE-UAT (Owner approval Rev 1) — whole-web walk over the isolated synthetic UAT fixture
 * profile (`uat_r8`): fleet list across every status and branch, the vehicle hub, the master-data
 * page and a repair with its Store and classification panels. Read-only; every viewport project.
 * Dedicated invocation only:  PREUAT_E2E=1 npx playwright test e2e/preuat- --workers=1
 * Mock TEST evidence only — not PostgreSQL / production evidence.
 */
const ENABLED = process.env.PREUAT_E2E === '1'
const MGR = { 'X-Dev-Role': 'TECHNICIAN', 'X-Dev-User-Id': 'USR-TEST-AM-MGR' }

test.skip(!ENABLED, 'needs the PRE-UAT backend (PREUAT_E2E=1)')

async function ensureView(request: APIRequestContext) {
  const me = await (await request.get('/api/v1/me', { headers: MGR })).json()
  if ((me.capabilities as string[]).includes('can_view')) return
  const revision = (await (await request.get('/api/v1/access/me', { headers: MGR })).json()).revision as number
  const r = await request.post('/api/v1/access/grants', {
    headers: { ...MGR, 'X-Request-Id': uuidFrom(`preuat-ws-${Date.now()}-${Math.random()}`) },
    data: { target: { kind: 'EMPLOYEE', personnel_id: 'PER-TEST-AM-MGR' }, changes: { can_view: true }, reason_th: 'PRE-UAT E2E',
      expected_revision: revision },
  })
  // A parallel project may have granted it first (stale revision): re-check instead of failing.
  if (!r.ok()) expect((await (await request.get('/api/v1/me', { headers: MGR })).json()).capabilities).toContain('can_view')
}

async function open(browser: Browser, baseURL: string | undefined, path: string): Promise<Page> {
  const page = await (await browser.newContext({ baseURL, extraHTTPHeaders: MGR })).newPage()
  await page.goto(path)
  return page
}

test('fixture fleet: seven UAT vehicles across all statuses, a hub with location, and master data', async ({ browser, baseURL, request }) => {
  await ensureView(request)
  const page = await open(browser, baseURL, '/vehicles?q=UAT8')
  for (let n = 1; n <= 7; n += 1) await expect(page.getByText(`UAT8-VEH-0${n}`, { exact: true }).first()).toBeVisible()
  // UAT-S045: a machine number with a leading zero is shown exactly as stored (identity string preserved).
  await expect(page.getByText('UAT8/007', { exact: true }).first()).toBeVisible()
  await expectNoHorizontalOverflow(page)

  await page.goto('/vehicle/UAT8-VEH-01')
  await expect(page.getByRole('heading', { name: 'สรุปข้อมูลรถ' })).toBeVisible()
  await expectNoHorizontalOverflow(page)

  await page.goto('/master-data')
  await expect(page.getByText('UAT8-MDL-B')).toBeVisible()
  await page.getByRole('tab', { name: 'ช่าง' }).click()
  await expect(page.getByText('UAT8-TEC-01')).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await page.context().close()
})

test('a repair page shows the material panel and the TEST classification badge', async ({ browser, baseURL, request }) => {
  await ensureView(request)
  const repairs = await (await request.get('/api/v1/repairs?page_size=1', { headers: MGR })).json()
  test.skip(!repairs.items?.length, 'no repair in this backend yet')
  const page = await open(browser, baseURL, `/repairs/${repairs.items[0].repair_id}`)
  await expect(page.getByRole('heading', { name: /อะไหล่ของใบงาน/ })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'จัดประเภทงานซ่อม' })).toBeVisible()
  await expect(page.getByText(/TEST candidate/).first()).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await page.context().close()
})

test('the synthetic PDF fixtures for manual document testing carry the right signatures', () => {
  test.skip(test.info().project.name !== 'desktop', 'file check runs once')
  const read = (name: string) => readFileSync(new URL(`./fixtures/${name}`, import.meta.url))
  for (const name of ['test-certificate-valid.pdf', 'test-document-valid.pdf']) {
    const bytes = read(name)
    expect(bytes.subarray(0, 5).toString('latin1'), name).toBe('%PDF-')
    expect(bytes.toString('latin1'), name).toContain('TEST ONLY - SYNTHETIC')
  }
  expect(read('test-invalid-signature.pdf').subarray(0, 5).toString('latin1')).not.toBe('%PDF-')
})
