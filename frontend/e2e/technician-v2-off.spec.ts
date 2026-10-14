import { expect, test } from '@playwright/test'
import { VEHICLE, expectResponsive, recordApi } from './technician-v2-helpers'

/**
 * R2 Batch R2f-h4 B4 / B5 — the cutover-OFF state against the isolated mock
 * backend with the V2 setting at its default (OFF) (playwright.config.ts
 * `cutover-off-*` projects). Every supported job-creation entry point — direct
 * Repair, PM start and Repair-Request conversion — is blocked with
 * "การมอบหมายช่างยังไม่เปิดใช้งาน", sends no create request and never falls
 * back to the legacy create. A LEGACY job is shown read-only.
 */

test('/me reports the flag OFF (and TEST); Repair creation from Vehicle Detail is blocked with no create request', async ({ page }) => {
  const me = await (await page.request.get('/api/v1/me')).json()
  expect(me.technician_assignment_v2_enabled).toBe(false)
  expect(me.data_context).toBe('TEST')
  await page.goto(`/vehicle/${VEHICLE}`)
  const api = recordApi(page)
  await page.getByRole('link', { name: 'แจ้งซ่อม', exact: true }).click()
  await expect(page.getByTestId('v2-creation-disabled')).toContainText('การมอบหมายช่างยังไม่เปิดใช้งาน')
  await expect(page.getByTestId('v2-data-context')).toContainText('TEST')
  await expect(page.getByRole('button', { name: 'ส่งแจ้งซ่อม' })).toHaveCount(0)
  await expect(page.getByLabel('อาการ/ปัญหาที่พบ')).toHaveCount(0)
  await expect(page.getByLabel(/ช่างผู้รับผิดชอบหลัก/)).toHaveCount(0) // no legacy fallback form
  await expectResponsive(page)
  expect(api.filter((e) => e.method !== 'GET')).toEqual([])
  await page.goto(`/equipment/EQP-0001/repairs/new`)
  await expect(page.getByTestId('v2-creation-disabled')).toBeVisible()
  expect(api.filter((e) => e.method !== 'GET')).toEqual([])
})

test('PM: the plan status stays readable, but no start control and no create request', async ({ page }) => {
  const api = recordApi(page)
  await page.goto(`/vehicle/${VEHICLE}/pm`)
  await expect(page.getByText(/แผนบำรุงรักษาเชิงป้องกัน PLAN1/)).toBeVisible()
  await expect(page.getByTestId('v2-creation-disabled').first()).toContainText('การมอบหมายช่างยังไม่เปิดใช้งาน')
  await expect(page.getByRole('button', { name: 'เริ่มทำ PM' })).toHaveCount(0)
  expect(api.filter((e) => e.method !== 'GET')).toEqual([])
})

test('Repair Request conversion is blocked (no convert control, no request); the request itself stays', async ({ page, browser, baseURL }, testInfo) => {
  const driver = await browser.newContext({ baseURL, extraHTTPHeaders: { 'X-Dev-Role': 'DRIVER', 'X-Dev-User-Id': `e2e-off-${testInfo.project.name}` } })
  const reported = await driver.request.post('/api/v1/repair-requests', { data: { vehicle_id: VEHICLE, symptom_th: `E2E OFF ${testInfo.project.name}` } })
  expect(reported.status()).toBe(200)
  await driver.close()
  const api = recordApi(page)
  await page.goto('/repair-request-queue')
  await expect(page.getByText(`E2E OFF ${testInfo.project.name}`)).toBeVisible()
  await expect(page.getByTestId('v2-creation-disabled').first()).toContainText('การมอบหมายช่างยังไม่เปิดใช้งาน')
  await expect(page.getByRole('button', { name: 'เปิดใบงานซ่อม' })).toHaveCount(0)
  expect(api.filter((e) => e.method !== 'GET')).toEqual([])
})

test('a LEGACY job is shown read-only (LEGACY_USER_ID) on its normal detail page, with no V2 read and no control', async ({ page }) => {
  const created = await page.request.post('/api/v1/repairs', {
    data: { asset_type: 'VEHICLE', asset_id: VEHICLE, source_type: 'MANUAL', symptom: 'E2E legacy', primary_technician: 'legacy-e2e-user' },
  })
  expect(created.status()).toBe(200)
  const repairId = (await created.json()).repair.repair_id as string
  const api = recordApi(page)
  await page.goto(`/repairs/${repairId}`)
  await expect(page.getByTestId('legacy-assignment-readonly')).toBeVisible()
  await expect(page.getByText('legacy-e2e-user')).toBeVisible()
  await expect(page.getByRole('button', { name: 'บันทึกการมอบหมายช่าง' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'บันทึกการมอบหมาย' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'บันทึกการดำเนินการ' })).toBeVisible() // the job's work stays
  expect(api.some((e) => e.url.includes('technician-assignments') || e.url.endsWith('/assign'))).toBe(false)
})
