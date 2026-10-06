import { expect, test, type Page, type Route } from '@playwright/test'

// Phase 7 Batch 7O2c — responsible-branch actions end to end (contract Final
// Rev2 §6, §10; Outcome Classification Addendum; review clarification C-c3).
//
// The page, the vehicle detail, the reference lists and the FIRST branch-history
// read come from the real mock backend. Every MUTATION (POST branch-transfers,
// insertions, corrections, cancellations, reconciliations) is answered by a
// MOCKED NETWORK LAYER (page.route), and later branch-history reads are the real
// response with the mocked record appended: the five viewport projects run in
// parallel against one shared mock backend, and these tests must not change the
// synthetic data other specs read. Server-side writes are covered by the backend
// suites (mock repository and fake Sheets transport).

const VID = 'VEH-1046' // synthetic: history Rayong (baseline) → Bangna → Laem Chabang
const LATEST = 'ABH-' + 'a'.repeat(31) + '1'
const UNKNOWN = 'ยังไม่ทราบผลการบันทึก — ระบบจะตรวจสอบจากประวัติ'
const PENDING = /บันทึกในประวัติสาขาแล้ว แต่สาขาในข้อมูลทะเบียนรถยังไม่ตรงกับประวัติหรือยังระบุไม่ได้/
const APPLIED = 'บันทึกการเปลี่ยนแปลงสาขาเรียบร้อยแล้ว'
const ACTIONS = ['เพิ่มประวัติย้อนหลัง', 'แก้ไขประวัติ', 'ยกเลิกรายการ']

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

interface HistoryState {
  /** Request ids "recorded" by mocked mutations (appended to the real read). */
  ids: string[]
  consistency: string | null
}

/** Branch-history reads: the real response (read once, up front), plus the
 * mocked records. */
async function mockHistory(page: Page, state: HistoryState) {
  const real = await page.request.get(`/api/v1/vehicles/${VID}/branch-history`)
  expect(real.ok()).toBe(true)
  const base = JSON.stringify(await real.json())
  await page.route(`**/api/v1/vehicles/${VID}/branch-history`, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    const body = JSON.parse(base)
    for (const [n, rid] of state.ids.entries()) {
      body.records.push({
        record_id: `ABH-${String(n).padStart(32, 'e')}`, record_kind: 'ASSIGNMENT', entry_operation: 'TRANSFER',
        event_id: `ABH-${String(n).padStart(32, 'e')}`, revision_no: 1, supersedes_record_id: null, branch_id: 'BR-RAYONG',
        effective_at: '2026-09-15T17:00:00+00:00', recorded_from_branch_id: 'BR-LAEM-CHABANG', recorded_from_source: 'EVENT',
        recorded_at: '2026-10-05T00:00:00+00:00', recorded_by: 'dev-user', request_id: rid, related_request_id: null,
        reason_th: null, reconciled_old_master_branch_id: null,
      })
    }
    if (state.consistency) body.consistency = state.consistency
    await fulfillJson(route, 200, body)
  })
}

async function open(page: Page) {
  await page.goto(`/vehicle/${VID}`)
  await expect(page.getByRole('heading', { name: 'ทะเบียนและสาขาที่รับผิดชอบ' })).toBeVisible()
  await expect(page.getByTestId('branch-history-panel').getByText('เทียบกับข้อมูลทะเบียนรถ')).toBeVisible()
}

test('C-c3: the history panel is read-only and the management actions appear only after opening their area', async ({ page }) => {
  await open(page)
  const panel = page.getByTestId('branch-history-panel')
  await expect(panel.getByRole('button')).toHaveCount(0)
  const toggle = page.getByRole('button', { name: 'จัดการประวัติสาขา' })
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  for (const name of ACTIONS) await expect(page.getByRole('button', { name })).toHaveCount(0)
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  const area = page.getByTestId('branch-history-actions')
  for (const name of ACTIONS) await expect(area.getByRole('button', { name })).toBeVisible()
  await expect(panel.getByRole('button')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'ย้ายสาขา' })).toBeVisible()
  await noHorizontalScroll(page)
})

test('a transfer is sent once with its own request id and confirmed', async ({ page }) => {
  const state: HistoryState = { ids: [], consistency: null }
  await mockHistory(page, state)
  const seen: { id: string; body: unknown }[] = []
  await page.route(`**/api/v1/vehicles/${VID}/branch-transfers`, async (route) => {
    const id = route.request().headers()['x-request-id']
    seen.push({ id, body: route.request().postDataJSON() })
    state.ids = [id]
    await fulfillJson(route, 200, {
      request_id: id, changed: true, record_id: 'ABH-' + 'f'.repeat(32), event_id: 'ABH-' + 'f'.repeat(32),
      projection_write: 'WRITTEN', timeline_status_after: 'VALID', current_branch_id: 'BR-RAYONG', consistency: 'CONSISTENT',
    }, id)
  })
  await open(page)
  await page.getByRole('button', { name: 'ย้ายสาขา' }).click()
  const dialog = page.getByTestId('branch-change-dialog')
  await dialog.getByLabel('สาขา', { exact: true }).selectOption('BR-RAYONG')
  await dialog.getByLabel('ระบุวันที่', { exact: true }).check()
  await dialog.getByLabel('วันที่มีผล').fill('2026-09-16')
  await noHorizontalScroll(page)
  await dialog.getByRole('button', { name: 'ยืนยันการบันทึกสาขา' }).click()
  await expect(page.getByText(APPLIED)).toBeVisible()
  expect(seen).toHaveLength(1)
  expect(seen[0].id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
  expect(seen[0].body).toMatchObject({
    to_branch_id: 'BR-RAYONG', effective: { mode: 'DATE', date: '2026-09-16' }, expected_current_branch_id: 'BR-LAEM-CHABANG',
  })
  expect((seen[0].body as { expected_history_revision: string }).expected_history_revision).toMatch(/^BHR1-/)
  await expect(page.getByTestId('branch-intent-banner')).toHaveCount(0)
})

test('NOT_DETERMINED is shown as recorded but not yet consistent, never as success', async ({ page }) => {
  const state: HistoryState = { ids: [], consistency: null }
  await mockHistory(page, state)
  await page.route(`**/api/v1/vehicles/${VID}/branch-history/events/*/cancellations`, async (route) => {
    const id = route.request().headers()['x-request-id']
    expect(route.request().url()).toContain(`/events/${LATEST}/cancellations`)
    state.ids = [id]
    state.consistency = 'UNDETERMINED'
    await fulfillJson(route, 200, {
      request_id: id, changed: true, record_id: 'ABH-' + 'd'.repeat(32), event_id: LATEST, projection_write: 'NOT_DETERMINED',
      timeline_status_after: 'AMBIGUOUS_ORDER', current_branch_id: null, consistency: 'UNDETERMINED',
    }, id)
  })
  await open(page)
  await page.getByRole('button', { name: 'จัดการประวัติสาขา' }).click()
  await page.getByTestId('branch-history-actions').getByRole('button', { name: 'ยกเลิกรายการ' }).click()
  const dialog = page.getByTestId('branch-change-dialog')
  await dialog.getByLabel('รายการในประวัติ').selectOption(LATEST)
  await dialog.getByLabel('เหตุผล (บังคับ)').fill('บันทึกผิด (e2e)')
  await dialog.getByRole('button', { name: 'ยืนยันการบันทึกสาขา' }).click()
  const banner = page.getByTestId('branch-intent-banner')
  await expect(banner.getByText(PENDING)).toBeVisible()
  await expect(page.getByText(/ประวัติยังมีรายการที่มีผลเวลาเดียวกัน/)).toBeVisible()
  await expect(page.getByText(APPLIED)).toHaveCount(0)
  await page.reload()
  await expect(page.getByTestId('branch-intent-banner').getByText(PENDING)).toBeVisible() // survives a reload
})

test('I-OC-01 (branch): a 500 after a real write is uncertain until the history shows the record', async ({ page }) => {
  const state: HistoryState = { ids: [], consistency: null }
  await mockHistory(page, state)
  let sent = ''
  await page.route(`**/api/v1/vehicles/${VID}/branch-transfers`, async (route) => {
    sent = route.request().headers()['x-request-id']
    await fulfillJson(route, 500, { error: { code: 'INTERNAL_ERROR', message: 'x', details: null, request_id: sent } })
  })
  await open(page)
  await page.getByRole('button', { name: 'ย้ายสาขา' }).click()
  const dialog = page.getByTestId('branch-change-dialog')
  await dialog.getByLabel('สาขา', { exact: true }).selectOption('BR-RAYONG')
  await dialog.getByRole('button', { name: 'ยืนยันการบันทึกสาขา' }).click()
  const banner = page.getByTestId('branch-intent-banner')
  await expect(banner.getByText(UNKNOWN)).toBeVisible()
  await expect(banner.getByText(/ยังไม่พบคำขอนี้ในประวัติ/)).toBeVisible()
  state.ids = [sent] // the write had in fact happened
  await banner.getByRole('button', { name: 'ตรวจสอบผลจากประวัติสาขาอีกครั้ง' }).click()
  await expect(page.getByTestId('branch-intent-banner')).toHaveCount(0)
  await expect(page.getByTestId('branch-settlement-notice')).toContainText('ตรวจสอบจากประวัติสาขาแล้ว')
})
