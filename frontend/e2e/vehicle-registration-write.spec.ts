import { expect, test, type Page, type Route } from '@playwright/test'

// Phase 7 Batch 7O2b — registration editor end to end (contract Final Rev2
// §4.4, §4.6, §10; Outcome Classification Addendum, I-OC-01 registration case).
//
// The page, the vehicle detail and the reference lists come from the real mock
// backend. Every MUTATION (PATCH /registration, POST .../reconciliations) and
// the registration-history reads that follow it are answered by a MOCKED
// NETWORK LAYER (page.route): the five viewport projects run in parallel
// against one shared mock backend, and these tests must not change the
// synthetic registry data other specs read. Server-side writes are covered by
// the backend suites (mock repository and fake Sheets transport).

const VID = 'VEH-1047' // synthetic: กข-1234 / TH-99, no registration history
const UNKNOWN = 'ยังไม่ทราบผลการบันทึก — ระบบจะตรวจสอบจากประวัติ'

async function noHorizontalScroll(page: Page) {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1)
}

function history(requestIds: string[], consistency: string) {
  return {
    vehicle_id: VID,
    current: { registration_no: { state: 'RECORDED', value: 'กข-1234' }, registration_province: { state: 'RECORDED', value: 'TH-99' } },
    consistency: requestIds.length ? consistency : 'NO_HISTORY',
    history_revision: `RHR1-${requestIds.length.toString().padStart(20, '0')}`,
    items: requestIds.map((rid, n) => ({
      change_id: `VRH-${String(n).padStart(32, '0')}`, change_kind: n === 0 ? 'CHANGE' : 'RECONCILIATION_APPLY_RECORDED',
      old_registration_no: 'กข-1234', old_registration_province_code: 'TH-99', new_registration_no: 'กข 5678',
      new_registration_province_code: 'TH-21', recorded_at: `2026-10-05T0${n}:00:00.000001+00:00`, recorded_by: 'dev-user',
      request_id: rid, related_request_id: null, accepted_exceptions: [], note_th: n === 0 ? null : 'ปรับให้ตรง (e2e)',
    })),
    excluded_test_rows: 0,
    issues: {},
  }
}

async function fulfillJson(route: Route, status: number, body: unknown, requestId?: string) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    headers: requestId ? { 'X-Request-Id': requestId } : {},
    body: JSON.stringify(body),
  })
}

function errorBody(code: string, requestId: string, details: Record<string, unknown> | null = null) {
  return { error: { code, message: code, details, request_id: requestId } }
}

/** The registration-history read, answered from `state` (mutable by the test). */
async function mockHistory(page: Page, state: { ids: string[]; consistency: string }) {
  await page.route(`**/api/v1/vehicles/${VID}/registration-history`, (route) =>
    route.request().method() === 'GET' ? fulfillJson(route, 200, history(state.ids, state.consistency)) : route.fallback(),
  )
}

async function openEditor(page: Page) {
  await page.goto(`/vehicle/${VID}`)
  await expect(page.getByRole('heading', { name: 'ทะเบียนและสาขาที่รับผิดชอบ' })).toBeVisible()
  await page.getByRole('button', { name: 'เปลี่ยนทะเบียน' }).click()
  const input = page.getByLabel('ทะเบียนรถ', { exact: true })
  await expect(input).toHaveValue('กข-1234') // the stored text, exactly
  return input
}

test('a change is sent exactly once with its own request id and confirmed', async ({ page }) => {
  const state = { ids: [] as string[], consistency: 'NO_HISTORY' }
  await mockHistory(page, state)
  const seen: { id: string; body: unknown }[] = []
  await page.route(`**/api/v1/vehicles/${VID}/registration`, async (route) => {
    const id = route.request().headers()['x-request-id']
    seen.push({ id, body: route.request().postDataJSON() })
    state.ids = [id]
    state.consistency = 'CONSISTENT'
    await fulfillJson(route, 200, {
      request_id: id, changed: true, master_write: 'WRITTEN', warnings: [],
      change: { change_id: 'VRH-' + 'e'.repeat(32), recorded_at: '2026-10-05T00:00:00.000001+00:00', request_id: id },
    }, id)
  })
  const input = await openEditor(page)
  await input.fill(' กข 5678 ')
  await page.getByLabel('จังหวัดที่จดทะเบียน').selectOption('TH-21')
  await noHorizontalScroll(page)
  await page.getByRole('button', { name: 'บันทึกทะเบียน' }).click()
  await expect(page.getByText('บันทึกทะเบียนเรียบร้อยแล้ว')).toBeVisible()
  expect(seen).toHaveLength(1)
  expect(seen[0].id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
  expect(seen[0].body).toEqual({
    registration_no: ' กข 5678 ', registration_province_code: 'TH-21',
    expected_registration_no: 'กข-1234', expected_registration_province_code: 'TH-99',
  })
  await expect(page.getByTestId('registration-intent-banner')).toHaveCount(0)
})

test('a no-op is reported without a change', async ({ page }) => {
  await mockHistory(page, { ids: [], consistency: 'NO_HISTORY' })
  await page.route(`**/api/v1/vehicles/${VID}/registration`, (route) => {
    const id = route.request().headers()['x-request-id']
    return fulfillJson(route, 200, { request_id: id, changed: false, warnings: ['EXISTING_DUPLICATE_PAIR'] }, id)
  })
  await openEditor(page)
  await page.getByRole('button', { name: 'บันทึกทะเบียน' }).click()
  await expect(page.getByText(/ทะเบียนเท่ากับค่าปัจจุบันอยู่แล้ว/)).toBeVisible()
  await expect(page.getByText(/มีรถคันอื่นใช้ทะเบียนและจังหวัดเดียวกันอยู่แล้ว/)).toBeVisible()
})

test('a duplicate is refused inline and the typed value is kept', async ({ page }) => {
  await mockHistory(page, { ids: [], consistency: 'NO_HISTORY' })
  await page.route(`**/api/v1/vehicles/${VID}/registration`, (route) => {
    const id = route.request().headers()['x-request-id']
    return fulfillJson(route, 409, errorBody('REGISTRATION_DUPLICATE', id, { conflict_count: 1, conflict_vehicle_ids: ['VEH-1046'] }), id)
  })
  const input = await openEditor(page)
  await input.fill('0012')
  await page.getByRole('button', { name: 'บันทึกทะเบียน' }).click()
  await expect(page.getByText('ทะเบียนและจังหวัดนี้ถูกใช้กับรถคันอื่นอยู่แล้ว')).toBeVisible()
  await expect(page.getByRole('link', { name: 'VEH-1046' })).toHaveAttribute('href', '/vehicle/VEH-1046')
  await expect(input).toHaveValue('0012')
  await expect(page.getByTestId('registration-intent-banner')).toHaveCount(0)
})

test('a change made elsewhere first is reported as stale with a reload action', async ({ page }) => {
  await mockHistory(page, { ids: [], consistency: 'NO_HISTORY' })
  await page.route(`**/api/v1/vehicles/${VID}/registration`, (route) => {
    const id = route.request().headers()['x-request-id']
    return fulfillJson(route, 409, errorBody('VEHICLE_REGISTRY_STALE', id, { current_matches_request: false }), id)
  })
  const input = await openEditor(page)
  await input.fill('กข 1111')
  await page.getByRole('button', { name: 'บันทึกทะเบียน' }).click()
  await expect(page.getByText(/มีผู้อื่นแก้ไขทะเบียนของรถคันนี้ไปแล้ว/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'โหลดใหม่' })).toBeVisible()
  await expect(input).toHaveValue('กข 1111')
})

test('a master-write failure stays pending until an APPLY reconciliation makes the history consistent', async ({ page }) => {
  const state = { ids: [] as string[], consistency: 'NO_HISTORY' }
  await mockHistory(page, state)
  let original = ''
  await page.route(`**/api/v1/vehicles/${VID}/registration`, (route) => {
    original = route.request().headers()['x-request-id']
    state.ids = [original]
    state.consistency = 'MISMATCH' // recorded in history, master not written
    return fulfillJson(route, 503, errorBody('VEHICLE_MASTER_WRITE_FAILED', original, {
      history_recorded: true, change_id: 'VRH-' + '0'.repeat(32), master_write_outcome: 'rejected', request_id: original,
    }), original)
  })
  let reconcileBody: Record<string, unknown> = {}
  await page.route(`**/api/v1/vehicles/${VID}/registration-history/reconciliations`, (route) => {
    const id = route.request().headers()['x-request-id']
    reconcileBody = route.request().postDataJSON()
    state.ids = [original, id]
    state.consistency = 'CONSISTENT'
    return fulfillJson(route, 200, {
      request_id: id, changed: true, master_write: 'WRITTEN', warnings: [],
      change: { change_id: 'VRH-' + '1'.repeat(32), recorded_at: '2026-10-05T01:00:00.000001+00:00', request_id: id },
    }, id)
  })
  const input = await openEditor(page)
  await input.fill('กข 5678')
  await page.getByRole('button', { name: 'บันทึกทะเบียน' }).click()
  const banner = page.getByTestId('registration-intent-banner')
  await expect(banner.getByText(/บันทึกในประวัติแล้ว แต่ทะเบียนในข้อมูลทะเบียนรถยังไม่ตรงกับประวัติ/)).toBeVisible()
  await banner.getByRole('button', { name: 'ปรับข้อมูลให้ตรงกัน' }).click()
  const dialog = page.getByRole('alertdialog')
  await dialog.getByLabel(/ใช้ค่าตามประวัติล่าสุด/).check()
  await dialog.getByLabel('เหตุผล (บังคับ)').fill('ปรับให้ตรง (e2e)')
  await noHorizontalScroll(page)
  await dialog.getByRole('button', { name: 'ยืนยันการปรับข้อมูล' }).click()
  await expect(page.getByText('บันทึกทะเบียนเรียบร้อยแล้ว')).toBeVisible()
  expect(reconcileBody).toMatchObject({ mode: 'APPLY_RECORDED', related_request_id: original, reason_th: 'ปรับให้ตรง (e2e)' })
  // the original intent is settled by the consistent history, not by the audit link
  await expect(page.getByTestId('registration-intent-banner')).toHaveCount(0)
  await expect(page.getByTestId('registration-settlement-notice')).toContainText('ตรวจสอบจากประวัติแล้ว')
})

test('I-OC-01: a 500 after the write shows the uncertainty banner and the next history read settles it', async ({ page }) => {
  const state = { ids: [] as string[], consistency: 'NO_HISTORY' }
  await mockHistory(page, state)
  let sent = ''
  let requests = 0
  await page.route(`**/api/v1/vehicles/${VID}/registration`, (route) => {
    requests += 1
    sent = route.request().headers()['x-request-id']
    return fulfillJson(route, 500, errorBody('INTERNAL_ERROR', sent), sent)
  })
  const input = await openEditor(page)
  await input.fill('กข 5678')
  await page.getByRole('button', { name: 'บันทึกทะเบียน' }).click()
  const banner = page.getByTestId('registration-intent-banner')
  await expect(banner.getByText(UNKNOWN)).toBeVisible()
  await expect(page.getByText('ไม่ได้บันทึก', { exact: false })).toHaveCount(0)
  await noHorizontalScroll(page)
  // the write had in fact happened: the next history read carries its record
  state.ids = [sent]
  state.consistency = 'CONSISTENT'
  await banner.getByRole('button', { name: 'ตรวจสอบผลจากประวัติอีกครั้ง' }).click()
  await expect(page.getByTestId('registration-intent-banner')).toHaveCount(0)
  await expect(page.getByTestId('registration-settlement-notice')).toContainText(sent)
  expect(requests).toBe(1) // never resent automatically
})

test('the uncertainty banner survives a reload and the explicit resend reuses the request id', async ({ page }) => {
  await mockHistory(page, { ids: [], consistency: 'NO_HISTORY' })
  const ids: string[] = []
  await page.route(`**/api/v1/vehicles/${VID}/registration`, (route) => {
    const id = route.request().headers()['x-request-id']
    ids.push(id)
    return ids.length === 1
      ? route.fulfill({ status: 502, contentType: 'text/html', body: '<html>bad gateway</html>' })
      : fulfillJson(route, 409, errorBody('VEHICLE_REGISTRY_STALE', id), id)
  })
  const input = await openEditor(page)
  await input.fill('กข 5678')
  await page.getByRole('button', { name: 'บันทึกทะเบียน' }).click()
  await expect(page.getByTestId('registration-intent-banner').getByText(UNKNOWN)).toBeVisible()
  await page.reload()
  const banner = page.getByTestId('registration-intent-banner')
  await expect(banner.getByText(UNKNOWN)).toBeVisible()
  await banner.getByRole('button', { name: 'ส่งคำขอเดิมอีกครั้ง' }).click()
  await expect(page.getByText(/คำขอที่ส่งซ้ำถูกปฏิเสธ/)).toBeVisible()
  await expect(banner).toBeVisible() // a refused resend never removes the uncertainty
  expect(ids).toHaveLength(2)
  expect(ids[1]).toBe(ids[0])
})
