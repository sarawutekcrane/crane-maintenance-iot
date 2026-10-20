import { expect, test, type Page } from '@playwright/test'
import { ensureCanonicalInspection, expectNoHorizontalOverflow } from './r3Support'

// R3 daily inspection (docs/project-governance/r3-implementation-contract.md §3–§6).
// Deliberate test migration from the Phase 3 spec: one inspection per asset per
// Bangkok date means the five viewport projects can no longer each submit their own
// inspection for the same asset. So:
// - [mocked] the form rendering (four results, touch targets, due reasons, notes,
//   no overflow) runs in every viewport against an intercepted form response;
// - [unmocked] read flows run in every viewport (missing checklist, not found,
//   history of the CANONICAL inspection of VEH-1047 — see r3Support.ts);
// - [unmocked, desktop only] ONE real UI submission per run, on EQP-0002, which no
//   other spec submits.
//
// NOTE: Playwright's getByRole name matching is substring-based by default
// ('ปกติ' is a substring of 'ผิดปกติ'), so `exact: true` is used throughout.

const FORM = {
  asset_type: 'VEHICLE',
  asset_id: 'VEH-1046',
  inspection_date: '2026-10-01',
  checklist: { checklist_id: 'CHK-0001', asset_type: 'VEHICLE', code: 'VEHICLE-PLACEHOLDER', name: 'รายการตรวจเช็คยานพาหนะ' },
  revision: { revision_id: 'REV-0001', checklist_id: 'CHK-0001', revision_number: 1, effective_date: '2026-01-01', created_at: '2026-01-01T00:00:00Z' },
  items: [1, 2, 4].map((n) => ({
    item: {
      item_id: `ITM-V-000${n}`, revision_id: 'REV-0001', sequence: n, title: `รายการตรวจสอบตัวอย่างที่ ${n}`,
      inspection_point: null, method: null, standard: null, instruction: null,
      frequency: n === 4 ? 'EVERY_7_DAYS' : 'DAILY', required_photo_on_fail: false, required_remark_on_fail: false,
      is_critical: false, reference_image: null, item_key: `KEY-ITM-V-000${n}`,
    },
    due_reason: n === 4 ? 'FIRST_WEEKLY' : 'DAILY',
    last_result_date: null,
  })),
  submitted_inspection_id: null,
}

async function mockForm(page: Page, body: unknown = FORM) {
  await page.route(/\/api\/v1\/inspections\/form\?/, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) }))
}

test('[mocked] the R3 form offers four large touch results, the due reason and the observation note', async ({ page }) => {
  await mockForm(page)
  await page.goto('/vehicle/VEH-1046/inspect')
  await expect(page.getByRole('heading', { name: /TC-12/ })).toBeVisible()
  await expect(page.getByText('รายการตรวจสอบตัวอย่างที่ 4')).toBeVisible()
  for (const label of ['ปกติ', 'ผิดปกติ', 'ใช้งานได้รอการแก้ไข', 'ไม่มีอุปกรณ์ติดตั้ง']) {
    await expect(page.getByRole('radio', { name: label, exact: true })).toHaveCount(3)
  }
  await expect(page.getByRole('radio', { name: /ไม่เกี่ยวข้อง/ })).toHaveCount(0) // legacy NA is never offered
  const box = await page.getByRole('radio', { name: 'ปกติ', exact: true }).first().boundingBox()
  expect(box?.height).toBeGreaterThanOrEqual(44)
  await expect(page.getByTestId('inspection-due-reason').nth(2)).toHaveText('ทุก 7 วัน (ตรวจครั้งแรก)')
  await expect(page.getByTestId('inspection-observation-note')).toContainText('ไม่ใช่การรับรองความปลอดภัย')

  const submit = page.getByRole('button', { name: 'ส่งผลการตรวจ' })
  await expect(submit).toBeDisabled()
  await page.getByRole('radio', { name: 'ใช้งานได้รอการแก้ไข', exact: true }).first().click()
  await expect(page.getByLabel('หมายเหตุ (จำเป็น)')).toBeVisible()
  await expect(page.getByText('รูปถ่ายหลักฐาน (ถ้ามี)')).toBeVisible()
  await page.getByRole('radio', { name: 'ไม่มีอุปกรณ์ติดตั้ง', exact: true }).nth(1).click()
  await expect(page.getByTestId('not-installed-note')).toContainText('ไม่ใช่การยกเว้นข้อกำหนดด้านความปลอดภัย')
  await page.getByRole('radio', { name: 'ปกติ', exact: true }).nth(2).click()
  await expect(submit).toBeEnabled()
  await expectNoHorizontalOverflow(page)
})

test('[mocked] a day that is already inspected shows the submitted inspection instead of answers', async ({ page }) => {
  await mockForm(page, { ...FORM, submitted_inspection_id: 'INS-0042' })
  await page.goto('/vehicle/VEH-1046/inspect')
  await expect(page.getByTestId('inspection-already-submitted')).toBeVisible()
  await expect(page.getByRole('link', { name: 'ดูผลการตรวจของวันนี้' })).toHaveAttribute('href', '/inspections/INS-0042')
  await expect(page.getByRole('radio')).toHaveCount(0)
  await expectNoHorizontalOverflow(page)
})

test('an asset without an assigned checklist shows the explicit missing-checklist message', async ({ page }) => {
  await page.goto('/equipment/EQP-0003/inspect')
  await expect(page.getByText(/ยังไม่มีรายการตรวจเช็คที่กำหนดให้กับรุ่นหรือเครื่องนี้/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'ส่งผลการตรวจ' })).toHaveCount(0)
  await expectNoHorizontalOverflow(page)
})

test('an unknown asset id shows a controlled Thai not-found message instead of the checklist form', async ({ page }) => {
  await page.goto('/vehicle/VEH-9999/inspect')
  await expect(page.getByText('ไม่พบข้อมูลยานพาหนะนี้')).toBeVisible()
  await expect(page.getByRole('button', { name: 'ส่งผลการตรวจ' })).toHaveCount(0)
  await page.goto('/inspections/INS-DOES-NOT-EXIST')
  await expect(page.getByText('ไม่พบข้อมูลผลการตรวจเช็คนี้')).toBeVisible()
})

test('history and detail show the R3 labels and the Finding episode of the canonical inspection', async ({ page }) => {
  const { inspectionId, findingId } = await ensureCanonicalInspection(page.request, 'VEHICLE', 'VEH-1047')
  await page.goto('/vehicle/VEH-1047/inspections')
  await expect(page.getByText('ผิดปกติ 1 รายการ').first()).toBeVisible()
  await page.goto(`/inspections/${inspectionId}`)
  await expect(page.getByText('ปกติ', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('ผิดปกติ', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('link', { name: `ดูการติดตาม ${findingId}` })).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await page.getByRole('link', { name: `ดูการติดตาม ${findingId}` }).click()
  await expect(page.getByRole('heading', { name: `รายการผิดปกติ ${findingId}` })).toBeVisible()
  await expect(page.getByTestId('finding-observations')).toContainText('ผิดปกติ')
  await expectNoHorizontalOverflow(page)
})

test('[desktop] one real UI submission: an abnormal result needs a remark, then the Finding is recorded', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'one UI submission per run (one inspection per asset per day)')
  await page.goto('/equipment/EQP-0002')
  await page.getByRole('link', { name: 'ตรวจเช็ค', exact: true }).click()
  await expect(page).toHaveURL(/\/equipment\/EQP-0002\/inspect/)
  await expect(page.getByRole('heading', { name: /ปั๊มลมโรงซ่อม/ })).toBeVisible()
  const normal = page.getByRole('radio', { name: 'ปกติ', exact: true })
  const count = await normal.count()
  expect(count).toBeGreaterThan(0)
  for (let i = 1; i < count; i += 1) await normal.nth(i).click()
  await page.getByRole('radio', { name: 'ผิดปกติ', exact: true }).first().click()
  await page.getByRole('button', { name: 'ส่งผลการตรวจ' }).click()
  await expect(page.getByText('กรุณาระบุหมายเหตุเมื่อผลตรวจผิดปกติหรือใช้งานได้รอการแก้ไข').first()).toBeVisible()
  await page.getByLabel('หมายเหตุ (จำเป็น)').fill('สายลมรั่ว - E2E R3')
  await page.getByRole('button', { name: 'ส่งผลการตรวจ' }).click()
  await expect(page).toHaveURL(/\/inspections\/INS-/)
  await expect(page.getByText('ข้อบกพร่องที่พบ')).toBeVisible()
  await expect(page.getByText('กำลังติดตาม').first()).toBeVisible()
  await page.goto('/equipment/EQP-0002/inspect')
  await expect(page.getByTestId('inspection-already-submitted')).toBeVisible() // R3-21: once per Bangkok day
})
