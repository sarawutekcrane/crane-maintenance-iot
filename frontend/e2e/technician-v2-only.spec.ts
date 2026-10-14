import { expect, test } from '@playwright/test'
import { VEHICLE, expectResponsive, jobIdFrom, queueRow, recordApi } from './technician-v2-helpers'

/**
 * R2 Batch R2f-h4 B6 Rev2 — owner final decision: Technician V2 is the ONLY
 * assignment model. Replaces the retired cutover-OFF spec (technician-v2-off):
 * there is no V2 ON/OFF mode any more. The suite's mock backend runs WITHOUT the
 * former TECHNICIAN_ASSIGNMENT_V2_ENABLED variable — exactly the former default-OFF
 * condition — and every supported creation entry point still creates a
 * TECHNICIAN_V2 job through normal navigation, with no V2-disabled state shown and
 * no legacy fallback. Each test asserts only on the jobs it created itself.
 */

test('Repair Request: a reported problem is converted through the queue into a TECHNICIAN_V2 Repair; the request keeps its data', async ({
  page,
  browser,
  baseURL,
}, testInfo) => {
  const marker = `E2E V2-only convert ${testInfo.project.name}`
  const driver = await browser.newContext({ baseURL, extraHTTPHeaders: { 'X-Dev-Role': 'DRIVER', 'X-Dev-User-Id': `e2e-v2only-${testInfo.project.name}` } })
  const reported = await driver.request.post('/api/v1/repair-requests', { data: { vehicle_id: VEHICLE, symptom_th: marker } })
  expect(reported.status()).toBe(200)
  const requestId = (await reported.json()).request.repair_request_id as string
  await driver.close()

  const api = recordApi(page)
  await page.goto('/repair-request-queue')
  const card = page.locator('.card', { hasText: marker })
  await expect(card).toBeVisible()
  await expect(page.getByTestId('v2-creation-disabled')).toHaveCount(0)
  await expectResponsive(page)
  await card.getByRole('button', { name: 'เปิดใบงานซ่อม' }).click()
  await expect(page).toHaveURL(/\/repairs\/RPR-/)
  const repairId = jobIdFrom(page, /\/repairs\/([^/?#]+)/)

  const convert = api.find((e) => e.method === 'POST' && e.url === `/api/v1/repair-requests/${requestId}/convert`)
  expect(convert?.status).toBe(200)
  expect(convert?.body).toEqual({}) // no technician field
  const job = await (await page.request.get(`/api/v1/repairs/${repairId}`)).json()
  expect(job.repair.assignment_model).toBe('TECHNICIAN_V2')
  expect(job.repair.primary_technician ?? null).toBeNull()
  await expect(page.getByTestId('v2-current-set')).toContainText('ยังไม่ได้มอบหมายช่าง')

  // The Repair Request keeps its original data and records the conversion.
  const request = await (await page.request.get(`/api/v1/repair-requests/${requestId}`)).json()
  expect([request.symptom_th, request.request_status, request.repair_id]).toEqual([marker, 'CONVERTED', repairId])

  // The new job waits in U1 as NONE.
  await page.goto('/waiting-assignment')
  await expect(queueRow(page, 'REPAIR', repairId).getByTestId('v2-waiting-status')).toHaveAttribute('data-status', 'NONE')
})

test('Equipment Repair (always the direct create) creates a TECHNICIAN_V2 job with no technician field and no V2 switch', async ({ page }, testInfo) => {
  const api = recordApi(page)
  await page.goto('/equipment/EQP-0001/repairs/new')
  await expect(page.getByTestId('v2-creation-disabled')).toHaveCount(0)
  await expect(page.getByLabel(/ช่างผู้รับผิดชอบหลัก/)).toHaveCount(0)
  await page.getByLabel('อาการ/ปัญหาที่พบ').fill(`E2E V2-only equipment ${testInfo.project.name}`)
  await expectResponsive(page)
  await page.getByRole('button', { name: 'ส่งแจ้งซ่อม' }).click()
  await expect(page).toHaveURL(/\/repairs\/RPR-/)
  const repairId = jobIdFrom(page, /\/repairs\/([^/?#]+)/)
  const create = api.find((e) => e.method === 'POST' && e.url === '/api/v1/repairs')
  expect(create?.status).toBe(200)
  expect(create?.body).not.toHaveProperty('primary_technician')
  expect(create?.body).not.toHaveProperty('collaborators')
  const job = await (await page.request.get(`/api/v1/repairs/${repairId}`)).json()
  expect(job.repair.assignment_model).toBe('TECHNICIAN_V2')
  await expect(page.getByTestId('v2-current-set')).toBeVisible()
})

test('no silent legacy fallback: a legacy inline assignee is refused (zero writes are proven by backend test d3_02)', async ({ page }) => {
  const refused = await page.request.post('/api/v1/repairs', {
    data: { asset_type: 'VEHICLE', asset_id: VEHICLE, source_type: 'MANUAL', symptom: 'E2E legacy refused', primary_technician: 'legacy-e2e-user' },
  })
  expect(refused.status()).toBe(422)
  expect((await refused.json()).error.code).toBe('LEGACY_ASSIGNMENT_RETIRED')
})
