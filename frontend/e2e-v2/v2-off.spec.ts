import { expect, test } from '@playwright/test'
import { VEHICLE, expectResponsive, recordApi } from './helpers'

/**
 * R2 Batch R2f-h4 B4 — the cutover-OFF state against a dedicated mock backend
 * with the V2 setting at its default (OFF): V2 creation is blocked with no
 * create request and no legacy fallback, and a LEGACY job is shown read-only.
 */

test('/me reports the flag OFF (and TEST); V2 Repair creation is blocked with no create request', async ({ page }) => {
  const me = await (await page.request.get('/api/v1/me')).json()
  expect(me.technician_assignment_v2_enabled).toBe(false)
  expect(me.data_context).toBe('TEST')
  const api = recordApi(page)
  await page.goto(`/v2/vehicle/${VEHICLE}/repairs/new`)
  await expect(page.getByTestId('v2-creation-disabled')).toContainText('การมอบหมายช่างยังไม่เปิดใช้งาน')
  await expect(page.getByTestId('v2-data-context')).toContainText('TEST')
  await expect(page.getByRole('button', { name: 'เปิดใบงานซ่อม' })).toHaveCount(0)
  await expect(page.getByLabel('อาการ/ปัญหาที่พบ')).toHaveCount(0)
  await expect(page.getByLabel(/ช่างผู้รับผิดชอบหลัก/)).toHaveCount(0) // no legacy fallback form
  await expectResponsive(page)
  // Only GET /me (the dev build may issue it more than once); no create, no plan read.
  expect(api.filter((e) => e.method !== 'GET')).toEqual([])
  expect([...new Set(api.map((e) => e.url))]).toEqual(['/api/v1/me'])
})

test('V2 PM creation is blocked with no plan read and no create request', async ({ page }) => {
  const api = recordApi(page)
  await page.goto(`/v2/vehicle/${VEHICLE}/pm`)
  await expect(page.getByTestId('v2-creation-disabled')).toBeVisible()
  await expect(page.getByRole('button', { name: /เริ่มทำ PM/ })).toHaveCount(0)
  expect(api.filter((e) => e.method !== 'GET')).toEqual([])
  expect([...new Set(api.map((e) => e.url))]).toEqual(['/api/v1/me'])
})

test('a LEGACY job is shown read-only (LEGACY_USER_ID), with no V2 read and no control', async ({ page }) => {
  const created = await page.request.post('/api/v1/repairs', {
    data: { asset_type: 'VEHICLE', asset_id: VEHICLE, source_type: 'MANUAL', symptom: 'E2E legacy', primary_technician: 'legacy-e2e-user' },
  })
  expect(created.status()).toBe(200)
  const repairId = (await created.json()).repair.repair_id as string
  const api = recordApi(page)
  await page.goto(`/v2/repairs/${repairId}`)
  await expect(page.getByTestId('v2-assignment-model')).toHaveText('LEGACY')
  await expect(page.getByTestId('v2-legacy-readonly')).toBeVisible()
  await expect(page.getByText('legacy-e2e-user')).toBeVisible()
  await expect(page.getByRole('button', { name: 'บันทึกการมอบหมายช่าง' })).toHaveCount(0)
  expect(api.some((e) => e.url.includes('technician-assignments'))).toBe(false)
})
