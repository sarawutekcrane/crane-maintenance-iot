import { expect, test, type Page, type Route } from '@playwright/test'

// Phase 7 Batch 7O2d — I-01 integration end to end (contract Final Rev2 §11,
// §13 I-01). It covers ONLY what the accepted 7O2a/7O2b/7O2c specs do not:
//   - historical insertion, correction and branch projection reconciliation
//     through the real page (transfer, cancellation, view, filter,
//     registration edit and registration reconciliation are covered by
//     vehicle-registry-read, vehicle-registration-write and
//     vehicle-branch-write);
//   - one cross-feature flow: a registration intent and a branch intent are
//     both uncertain on the same vehicle; a branch-history read settles ONLY the
//     branch intent, the registration intent is unaffected, the page stays on
//     the same vehicle and the reference labels stay resolved.
//
// As in 7O2b/7O2c, the page, detail, reference lists and FIRST history reads
// come from the real mock backend; every MUTATION is answered by a mocked
// network layer and later branch-history reads are the real response with the
// mocked records appended, so the five parallel viewport projects never change
// the shared synthetic data.

const VID = 'VEH-1046' // synthetic: TC-12, 0012 / ระยอง, history Rayong → Bangna → Laem Chabang
const INSERTED = 'ABH-' + 'a'.repeat(31) + '2' // the inserted (Bangna) event, corrected once in the seed
const UNKNOWN = 'ยังไม่ทราบผลการบันทึก — ระบบจะตรวจสอบจากประวัติ'
const APPLIED = 'บันทึกการเปลี่ยนแปลงสาขาเรียบร้อยแล้ว'
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

async function noHorizontalScroll(page: Page) {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1)
}

async function fulfillJson(route: Route, status: number, body: unknown, requestId?: string) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    headers: requestId ? { 'X-Request-Id': requestId } : {},
    body: JSON.stringify(body),
  })
}

function changed(id: string, extra: Record<string, unknown> = {}) {
  return {
    request_id: id, changed: true, record_id: 'ABH-' + 'f'.repeat(32), event_id: 'ABH-' + 'f'.repeat(32),
    projection_write: 'NOT_NEEDED', timeline_status_after: 'VALID', current_branch_id: 'BR-LAEM-CHABANG',
    consistency: 'CONSISTENT', ...extra,
  }
}

interface HistoryState {
  ids: string[]
  consistency: string | null
}

/** Branch-history reads: the real response (read once, up front) plus the mocked records. */
async function mockBranchHistory(page: Page, state: HistoryState) {
  const real = await page.request.get(`/api/v1/vehicles/${VID}/branch-history`)
  expect(real.ok()).toBe(true)
  const base = JSON.stringify(await real.json())
  await page.route(`**/api/v1/vehicles/${VID}/branch-history`, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    const body = JSON.parse(base)
    for (const [n, rid] of state.ids.entries()) {
      body.records.push({
        record_id: `ABH-${String(n).padStart(32, 'd')}`, record_kind: 'ASSIGNMENT', entry_operation: 'INSERTION',
        event_id: `ABH-${String(n).padStart(32, 'd')}`, revision_no: 1, supersedes_record_id: null, branch_id: 'BR-RAYONG',
        effective_at: '2026-08-24T17:00:00+00:00', recorded_from_branch_id: 'BR-BANGNA-KM6', recorded_from_source: 'EVENT',
        recorded_at: '2026-10-05T00:00:00+00:00', recorded_by: 'dev-user', request_id: rid, related_request_id: null,
        reason_th: 'e2e', reconciled_old_master_branch_id: null,
      })
    }
    if (state.consistency) body.consistency = state.consistency
    await fulfillJson(route, 200, body)
  })
}

async function open(page: Page) {
  await page.goto(`/vehicle/${VID}`)
  await expect(page.getByRole('heading', { name: 'TC-12' })).toBeVisible()
  await expect(page.getByTestId('branch-history-panel').getByText('เทียบกับข้อมูลทะเบียนรถ')).toBeVisible()
}

async function openManagement(page: Page, action: string) {
  await page.getByRole('button', { name: 'จัดการประวัติสาขา' }).click()
  await page.getByTestId('branch-history-actions').getByRole('button', { name: action }).click()
  return page.getByTestId('branch-change-dialog')
}

test('I-01 insertion: a historical event is recorded through the management area', async ({ page }) => {
  const state: HistoryState = { ids: [], consistency: null }
  await mockBranchHistory(page, state)
  const seen: { id: string; body: Record<string, unknown> }[] = []
  await page.route(`**/api/v1/vehicles/${VID}/branch-history/insertions`, async (route) => {
    const id = route.request().headers()['x-request-id']
    seen.push({ id, body: route.request().postDataJSON() })
    state.ids = [id]
    await fulfillJson(route, 200, changed(id), id)
  })
  await open(page)
  const dialog = await openManagement(page, 'เพิ่มประวัติย้อนหลัง')
  await expect(dialog.getByLabel('ตอนนี้')).toHaveCount(0) // NOW is transfer-only
  await dialog.getByLabel('สาขา', { exact: true }).selectOption('BR-RAYONG')
  await dialog.getByLabel('วันที่มีผล').fill('2026-08-25')
  await dialog.getByLabel('เหตุผล (บังคับ)').fill('บันทึกย้อนหลัง (e2e)')
  await noHorizontalScroll(page)
  await dialog.getByRole('button', { name: 'ยืนยันการบันทึกสาขา' }).click()
  await expect(page.getByText(APPLIED)).toBeVisible()
  expect(seen).toHaveLength(1)
  expect(seen[0].id).toMatch(UUID)
  expect(seen[0].body).toMatchObject({
    to_branch_id: 'BR-RAYONG', effective: { mode: 'DATE', date: '2026-08-25' }, reason_th: 'บันทึกย้อนหลัง (e2e)',
  })
  expect(seen[0].body).not.toHaveProperty('expected_master_branch_id')
  await expect(page.getByTestId('branch-intent-banner')).toHaveCount(0)
})

test('I-01 correction: an event is corrected with its id in the path and the event prefilled', async ({ page }) => {
  const state: HistoryState = { ids: [], consistency: null }
  await mockBranchHistory(page, state)
  const seen: { url: string; body: Record<string, unknown> }[] = []
  await page.route(`**/api/v1/vehicles/${VID}/branch-history/events/*/corrections`, async (route) => {
    const id = route.request().headers()['x-request-id']
    seen.push({ url: route.request().url(), body: route.request().postDataJSON() })
    state.ids = [id]
    await fulfillJson(route, 200, changed(id, { event_id: INSERTED }), id)
  })
  await open(page)
  const dialog = await openManagement(page, 'แก้ไขประวัติ')
  await dialog.getByLabel('รายการในประวัติ').selectOption(INSERTED)
  await expect(dialog.getByLabel('สาขา', { exact: true })).toHaveValue('BR-BANGNA-KM6') // prefilled from the event
  await dialog.getByLabel('ระบุวันที่', { exact: true }).check()
  await dialog.getByLabel('วันที่มีผล').fill('2026-08-22')
  await dialog.getByLabel('เหตุผล (บังคับ)').fill('แก้วันที่ (e2e)')
  await dialog.getByRole('button', { name: 'ยืนยันการบันทึกสาขา' }).click()
  await expect(page.getByText(APPLIED)).toBeVisible()
  expect(seen).toHaveLength(1)
  expect(seen[0].url).toContain(`/branch-history/events/${INSERTED}/corrections`)
  expect(seen[0].body).toMatchObject({
    to_branch_id: 'BR-BANGNA-KM6', effective: { mode: 'DATE', date: '2026-08-22' }, reason_th: 'แก้วันที่ (e2e)',
    expected_master_branch_id: 'BR-LAEM-CHABANG',
  })
})

test('I-01 projection reconciliation: offered only on a mismatch, and gone once consistent', async ({ page }) => {
  const state: HistoryState = { ids: [], consistency: 'PROJECTION_MISMATCH' }
  await mockBranchHistory(page, state)
  let body: Record<string, unknown> = {}
  await page.route(`**/api/v1/vehicles/${VID}/branch-projection/reconciliations`, async (route) => {
    const id = route.request().headers()['x-request-id']
    body = route.request().postDataJSON()
    state.ids = [id]
    state.consistency = 'CONSISTENT'
    await fulfillJson(route, 200, changed(id, { event_id: null, projection_write: 'WRITTEN' }), id)
  })
  await open(page)
  const reconcile = page.getByRole('button', { name: 'ปรับข้อมูลสาขาปัจจุบันให้ตรงกับประวัติ' })
  await reconcile.click()
  const dialog = page.getByTestId('branch-change-dialog')
  await dialog.getByLabel('เหตุผล (บังคับ)').fill('ปรับให้ตรง (e2e)')
  await noHorizontalScroll(page)
  await dialog.getByRole('button', { name: 'ยืนยันการบันทึกสาขา' }).click()
  await expect(page.getByText(APPLIED)).toBeVisible()
  expect(body).toMatchObject({ reason_th: 'ปรับให้ตรง (e2e)', expected_master_branch_id: 'BR-LAEM-CHABANG' })
  expect(String(body.expected_history_revision)).toMatch(/^BHR1-/)
  await expect(reconcile).toHaveCount(0) // the refreshed history is CONSISTENT
})

test('I-01 cross-feature: a branch-history read settles only the branch intent; the registration intent, the vehicle and the labels are unaffected', async ({ page }) => {
  const state: HistoryState = { ids: [], consistency: null }
  await mockBranchHistory(page, state)
  let registrationId = ''
  await page.route(`**/api/v1/vehicles/${VID}/registration`, async (route) => {
    registrationId = route.request().headers()['x-request-id']
    await fulfillJson(route, 500, { error: { code: 'INTERNAL_ERROR', message: 'x', details: null, request_id: registrationId } })
  })
  let branchId = ''
  await page.route(`**/api/v1/vehicles/${VID}/branch-transfers`, async (route) => {
    branchId = route.request().headers()['x-request-id']
    await fulfillJson(route, 500, { error: { code: 'INTERNAL_ERROR', message: 'x', details: null, request_id: branchId } })
  })
  await open(page)
  // 1. an uncertain registration change
  await page.getByRole('button', { name: 'เปลี่ยนทะเบียน' }).click()
  await page.getByLabel('ทะเบียนรถ', { exact: true }).fill('กข 5678')
  await page.getByRole('button', { name: 'บันทึกทะเบียน' }).click()
  const registrationBanner = page.getByTestId('registration-intent-banner')
  await expect(registrationBanner.getByText(UNKNOWN)).toBeVisible()
  // 2. an uncertain branch transfer
  await page.getByRole('button', { name: 'ย้ายสาขา' }).click()
  const dialog = page.getByTestId('branch-change-dialog')
  await dialog.getByLabel('สาขา', { exact: true }).selectOption('BR-RAYONG')
  await dialog.getByRole('button', { name: 'ยืนยันการบันทึกสาขา' }).click()
  const branchBanner = page.getByTestId('branch-intent-banner')
  await expect(branchBanner.getByText(UNKNOWN)).toBeVisible()
  // each banner lists only its own family's request
  await expect(registrationBanner).toContainText(registrationId)
  await expect(registrationBanner).not.toContainText(branchId)
  await expect(branchBanner).toContainText(branchId)
  await expect(branchBanner).not.toContainText(registrationId)
  // 3. the branch write had in fact happened; the branch history now shows it
  state.ids = [branchId]
  await branchBanner.getByRole('button', { name: 'ตรวจสอบผลจากประวัติสาขาอีกครั้ง' }).click()
  await expect(page.getByTestId('branch-intent-banner')).toHaveCount(0)
  await expect(page.getByTestId('branch-settlement-notice')).toContainText(branchId)
  // the registration intent is untouched by the branch read
  await expect(registrationBanner).toContainText(registrationId)
  await expect(registrationBanner.getByText(UNKNOWN)).toBeVisible()
  await expect(page.getByTestId('registration-settlement-notice')).toHaveCount(0)
  // same vehicle, labels still resolved
  expect(new URL(page.url()).pathname).toBe(`/vehicle/${VID}`)
  await expect(page.getByRole('heading', { name: 'TC-12' })).toBeVisible()
  const card = page.locator('.status-card__row', { hasText: 'สาขาที่รับผิดชอบ' }).first()
  await expect(card).toContainText('แหลมฉบัง')
  await expect(page.locator('.status-card__row', { hasText: 'จังหวัดที่จดทะเบียน' }).first()).toContainText('ระยอง')
  await expect(page.getByTestId('branch-history-panel').getByText(/แหลมฉบัง/).first()).toBeVisible()
  await noHorizontalScroll(page)
})
