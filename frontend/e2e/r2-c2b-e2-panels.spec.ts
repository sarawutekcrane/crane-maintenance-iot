import { expect, test, type APIRequestContext, type Locator, type Page, type Request } from '@playwright/test'

/**
 * R2 Batch R2-C2b — the E2 operational driver assignment panels against the
 * REAL mock (TEST) backend started by playwright.config.ts
 * (reuseExistingServer: false: every invocation starts its own fresh backend).
 *
 * Isolation (owner decision D6, same pattern as R2-C2a C2a-3):
 * - READ-ONLY tests (all five viewport projects) never write to the backend;
 *   the one write they make is intercepted in the browser and never reaches it.
 * - `@mutation` tests write for real and run ONLY in a dedicated invocation:
 *     R2_C2B_MUTATION=1 npx playwright test e2e/r2-c2b-e2-panels.spec.ts --project=desktop --workers=1 --grep @mutation
 *   They refuse to run otherwise (env flag, desktop project, one worker) and
 *   first prove the backend is Mock/TEST with an empty E2 history.
 * - The E2 history is append-only: a CANCEL, EARLY_END or VOID adds rows and
 *   never restores the history; the rows these tests create are expected,
 *   kept and checked, and the backend process simply ends with the run.
 * - Dates are computed from Bangkok "today" at run time, one window per test.
 */

const API = '/api/v1'
const MUTATION_RUN = process.env.R2_C2B_MUTATION === '1'
const VEH = 'VEH-1048'
const E2_NOTE = 'เป็นข้อมูลการมอบหมาย ไม่ใช่การยืนยันว่าได้ขับรถจริง'

const bangkokToday = () => new Date(Date.now() + 7 * 3600_000).toISOString().slice(0, 10)
const addDays = (day: string, n: number) => {
  const d = new Date(`${day}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}

async function readJson(request: APIRequestContext, path: string) {
  const response = await request.get(`${API}${path}`)
  expect(response.status(), path).toBe(200)
  return response.json()
}

async function expectNoHorizontalOverflow(page: Page) {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1)
}

function recordApi(page: Page): Request[] {
  const requests: Request[] = []
  page.on('request', (request) => {
    if (new URL(request.url()).pathname.startsWith(API)) requests.push(request)
  })
  return requests
}
const writes = (requests: Request[]) => requests.filter((r) => r.method() !== 'GET')
const e2Panel = (page: Page) => page.locator('.e2-panel')

// ---------------------------------------------------------------------------
// Read-only (all viewport projects)
// ---------------------------------------------------------------------------

test.describe('R2-C2b E2 read-only panels (real Mock/TEST backend)', () => {
  test.skip(MUTATION_RUN, 'the dedicated mutation invocation runs only the @mutation tests')

  test('Vehicle Detail: the E2 panel is separate from the permanent driver panel and the legacy link', async ({ page }) => {
    const api = recordApi(page)
    await page.goto(`/vehicle/${VEH}`)
    const panel = e2Panel(page)
    await expect(panel.getByRole('heading', { name: 'การมอบหมายผู้ขับรถตามวัน/กะ' })).toBeVisible()
    await expect(panel.getByTestId('e2-note')).toHaveText(E2_NOTE)
    await expect(panel.getByTestId('e2-current-status')).toBeVisible()
    await expect(panel.getByTestId('e2-history')).toBeVisible()
    // The R2f-f permanent panel and the legacy Phase 6 link stay, separately.
    await expect(page.getByRole('heading', { name: 'ผู้รับผิดชอบรถประจำ' })).toBeVisible()
    await expect(page.locator(`a[href="/vehicle/${VEH}/drivers"]`).first()).toBeVisible()
    await expect(panel.getByRole('button', { name: 'มอบหมายใหม่' })).toBeVisible() // dev ADMIN holds can_assign_crane_driver
    const paths = api.map((r) => new URL(r.url()).pathname)
    expect(paths).toContain(`${API}/vehicles/${VEH}/operational-driver-assignments`)
    expect(paths).toContain(`${API}/vehicles/${VEH}/operational-driver-assignment-history`)
    expect(paths.some((p) => /\/vehicles\/[^/]+\/driver-assignments$/.test(p))).toBe(false) // never the legacy data
    expect(writes(api)).toHaveLength(0)
    await expectNoHorizontalOverflow(page)
  })

  test('the default Bangkok window is today -7 .. +30 and the filter re-reads the chosen range', async ({ page }) => {
    const api = recordApi(page)
    await page.goto(`/vehicle/${VEH}`)
    const panel = e2Panel(page)
    await expect(panel.getByTestId('e2-current-status')).toBeVisible()
    const today = bangkokToday()
    await expect(panel.getByLabel('ตั้งแต่วันที่')).toHaveValue(addDays(today, -7))
    await expect(panel.getByLabel('ถึงวันที่')).toHaveValue(addDays(today, 30))
    await panel.getByLabel('ตั้งแต่วันที่').fill(today)
    await panel.getByLabel('ถึงวันที่').fill(addDays(today, 3))
    await panel.getByLabel('รูปแบบ').selectOption('NIGHT_SHIFT')
    const reread = page.waitForRequest((r) => r.url().includes('/operational-driver-assignments?') && r.url().includes('mode=NIGHT_SHIFT'))
    await panel.getByRole('button', { name: 'แสดงตามช่วงที่เลือก' }).click()
    expect(new URL((await reread).url()).search).toBe(`?from=${today}&to=${addDays(today, 3)}&mode=NIGHT_SHIFT`)
    expect(writes(api)).toHaveLength(0)
  })

  test('a REAL-scoped vehicle shows the scope state and no E2 controls; a role without the capability sees none', async ({ page }) => {
    await page.goto('/vehicle/VEH-1046')
    await expect(e2Panel(page).getByTestId('e2-scope-unproven')).toBeVisible()
    await expect(e2Panel(page).getByRole('button', { name: 'มอบหมายใหม่' })).toHaveCount(0)
    await page.setExtraHTTPHeaders({ 'X-Dev-Role': 'DRIVER' })
    await page.goto(`/vehicle/${VEH}`)
    await expect(e2Panel(page).getByTestId('e2-current-status')).toBeVisible()
    await expect(e2Panel(page).getByTestId('e2-actions')).toHaveCount(0)
  })

  test('Driver Detail: the read-only E2 panel across vehicles; an out-of-scope driver gets the scope state', async ({ page }) => {
    const api = recordApi(page)
    await page.goto('/drivers/DRV-TEST-901')
    const panel = e2Panel(page)
    await expect(panel.getByRole('heading', { name: 'การมอบหมายขับรถตามวัน/กะ (ทุกคัน)' })).toBeVisible()
    await expect(panel.getByTestId('e2-note')).toHaveText(E2_NOTE)
    await expect(panel.getByTestId('e2-driver-schedule')).toBeVisible()
    await expect(panel.getByRole('button', { name: /มอบหมาย|ยกเลิก|แก้ไข|สิ้นสุด/ })).toHaveCount(0)
    // Separate from the R2f-f "vehicles under permanent responsibility" panel.
    await expect(page.getByRole('heading', { name: 'รถที่รับผิดชอบประจำ' })).toBeVisible()
    expect(writes(api)).toHaveLength(0)
    await expectNoHorizontalOverflow(page)
    await page.goto('/drivers/DRV-0001')
    await expect(e2Panel(page).getByTestId('e2-scope-unproven')).toBeVisible()
  })

  test('an uncertain write (intercepted, never reaching the backend) stays pending and is resent unchanged', async ({ page }) => {
    const sent: { rid: string; body: string }[] = []
    await page.route(`**/api/v1/vehicles/${VEH}/operational-driver-assignment-operations`, async (route) => {
      sent.push({ rid: route.request().headers()['x-request-id'], body: route.request().postData() ?? '' })
      await route.abort('failed') // a transport failure: the outcome is unknown
    })
    await page.goto(`/vehicle/${VEH}`)
    const panel = e2Panel(page)
    await panel.getByRole('button', { name: 'มอบหมายใหม่' }).click()
    const dialog = page.getByTestId('e2-operation-dialog')
    await dialog.getByLabel('ผู้ขับที่ได้รับมอบหมาย').selectOption('DRV-TEST-901') // explicit choice, never automatic
    await dialog.getByLabel('รูปแบบการมอบหมาย').selectOption('FULL_DAY')
    await dialog.getByLabel('วันที่เริ่มต้น').fill(addDays(bangkokToday(), 200))
    await dialog.getByLabel('วันที่สิ้นสุด (รวมวันนี้)').fill(addDays(bangkokToday(), 200))
    await dialog.getByRole('button', { name: /^ยืนยัน/ }).click()
    const pending = panel.getByTestId('e2-pending-intent')
    await expect(pending).toContainText('ยังไม่ทราบผล')
    await expect(panel.getByTestId('e2-actions')).toHaveCount(0) // no new intent while unresolved
    await pending.getByRole('button', { name: 'ส่งคำขอเดิมอีกครั้ง' }).click()
    await expect.poll(() => sent.length).toBe(2)
    expect(sent[1]).toEqual(sent[0]) // same request id, same exact body
    await page.reload()
    await expect(e2Panel(page).getByTestId('e2-pending-intent')).toContainText(sent[0].rid) // never assumed successful
    await page.evaluate(() => window.localStorage.clear())
  })
})

// ---------------------------------------------------------------------------
// @mutation — dedicated fresh backend, desktop, one worker, sequential
// ---------------------------------------------------------------------------

test.describe('R2-C2b E2 real writes @mutation', () => {
  test.describe.configure({ mode: 'serial' })
  test.beforeEach(() => {
    const info = test.info()
    test.skip(!MUTATION_RUN || info.project.name !== 'desktop' || info.config.workers !== 1,
      'real writes run only in the dedicated R2_C2B_MUTATION=1 --project=desktop --workers=1 invocation')
  })

  const T = bangkokToday()
  const sentIds: string[] = []
  const before: Record<string, unknown> = {}

  /** One operation through the UI; returns the backend answer of the POST. */
  async function operate(page: Page, open: (panel: Locator) => Promise<void>, fill: (dialog: Locator) => Promise<void>) {
    const panel = e2Panel(page)
    await open(panel)
    const dialog = page.getByTestId('e2-operation-dialog')
    await fill(dialog)
    const answer = page.waitForResponse((r) => r.url().endsWith('/operational-driver-assignment-operations') && r.request().method() === 'POST')
    await dialog.getByRole('button', { name: /^ยืนยัน/ }).click()
    const response = await answer
    sentIds.push(response.request().headers()['x-request-id'])
    return { status: response.status(), body: await response.json(), request: response.request() }
  }
  const create = (page: Page, fields: { driver: string; mode: string; start: string; end: string; shift?: [string, string, '0' | '1'];
    reason?: string; predecessor?: string }) =>
    operate(page, (panel) => panel.getByRole('button', { name: 'มอบหมายใหม่' }).click(), async (dialog) => {
      await dialog.getByLabel('ผู้ขับที่ได้รับมอบหมาย').selectOption(fields.driver)
      await dialog.getByLabel('รูปแบบการมอบหมาย').selectOption(fields.mode)
      await dialog.getByLabel('วันที่เริ่มต้น').fill(fields.start)
      await dialog.getByLabel('วันที่สิ้นสุด (รวมวันนี้)').fill(fields.end)
      if (fields.shift) {
        await dialog.getByLabel('เวลาเริ่มกะ').fill(fields.shift[0])
        await dialog.getByLabel('เวลาสิ้นสุดกะ').fill(fields.shift[1])
        await dialog.getByLabel('กะสิ้นสุด').selectOption(fields.shift[2])
      }
      if (fields.predecessor) {
        await dialog.getByLabel(/ส่งต่อจากการมอบหมายก่อนหน้า/).check()
        await dialog.getByLabel('การมอบหมายก่อนหน้า', { exact: true }).selectOption(fields.predecessor)
      }
      if (fields.reason) await dialog.getByLabel(/^เหตุผล/).fill(fields.reason)
    })
  const onRow = (page: Page, eventId: string, operation: string, fill: (dialog: Locator) => Promise<void>) =>
    operate(page, (panel) => panel.getByTestId(`e2-row-actions-${eventId}`).getByRole('button', { name: operation }).click(), fill)
  const history = async (request: APIRequestContext) => readJson(request, `/vehicles/${VEH}/operational-driver-assignment-history`)

  test('the dedicated backend is Mock/TEST and the E2 history is empty before the first write', async ({ request }) => {
    expect((await readJson(request, '/me')).data_context).toBe('TEST')
    expect(await history(request)).toEqual({ vehicle_id: VEH, events: [], records: [] })
    before.permanent = await readJson(request, `/vehicles/${VEH}/responsible-drivers`)
    before.legacy = await readJson(request, `/vehicles/${VEH}/driver-assignments`)
  })

  test('CREATE today: assigned now, warnings shown; a duplicate is a no-op; exact replay; overlap and INACTIVE refused', async ({ page, request }) => {
    await page.goto(`/vehicle/${VEH}`)
    const created = await create(page, { driver: 'DRV-TEST-901', mode: 'FULL_DAY', start: T, end: addDays(T, 1) })
    expect(created.status).toBe(200)
    expect(created.request.postDataJSON()).toEqual({ operation: 'CREATE', driver_id: 'DRV-TEST-901', mode: 'FULL_DAY', start_date: T, end_date: addDays(T, 1) })
    const panel = e2Panel(page)
    await expect(panel.getByTestId('e2-write-message')).toContainText('บันทึกเรียบร้อยแล้ว')
    await expect(panel.getByTestId('e2-write-warnings')).toContainText('ยังไม่มีผู้รับผิดชอบรถประจำ')
    await expect(panel.getByTestId('e2-current-status').getByRole('link', { name: 'DRV-TEST-901' })).toBeVisible()
    let h = await history(request)
    expect(h.records).toHaveLength(1)
    expect(h.records[0].request_id).toBe(created.request.headers()['x-request-id'])

    // B27: the identical active assignment is not duplicated.
    const duplicate = await create(page, { driver: 'DRV-TEST-901', mode: 'FULL_DAY', start: T, end: addDays(T, 1) })
    expect(duplicate.body).toMatchObject({ changed: false, existing_event_id: created.body.event_ids[0] })
    await expect(panel.getByTestId('e2-write-message')).toContainText('มีการมอบหมายเดียวกันอยู่แล้ว')

    // Exact replay of the CREATE: same id and body → replayed with the original record ids, nothing new.
    const replay = await request.post(`${API}/vehicles/${VEH}/operational-driver-assignment-operations`, {
      headers: { 'Content-Type': 'application/json', 'X-Request-Id': created.request.headers()['x-request-id'] },
      data: created.request.postData() ?? '',
    })
    expect(await replay.json()).toMatchObject({ replayed: true, record_ids: created.body.record_ids })

    // A vehicle-axis overlap is refused with its details; nothing is written.
    const overlap = await create(page, { driver: 'DRV-TEST-902', mode: 'DAY_SHIFT', start: addDays(T, 1), end: addDays(T, 1), shift: ['08:00', '17:00', '0'] })
    expect(overlap.status).toBe(409)
    await expect(page.getByTestId('e2-overlap')).toContainText(created.body.event_ids[0])
    await page.getByTestId('e2-operation-dialog').getByRole('button', { name: 'ปิด' }).click()

    // An INACTIVE driver is refused for future work.
    const inactive = await create(page, { driver: 'DRV-TEST-903', mode: 'FULL_DAY', start: addDays(T, 40), end: addDays(T, 40) })
    expect(inactive.body.error.code).toBe('DRIVER_NOT_ACTIVE')
    await expect(page.getByTestId('e2-operation-dialog').getByRole('alert')).toContainText('ไม่อยู่ในสถานะใช้งาน')
    await page.getByTestId('e2-operation-dialog').getByRole('button', { name: 'ปิด' }).click()
    h = await history(request)
    expect(h.records).toHaveLength(1)
  })

  test('a future day shift: split from a date, exclude a unit, substitute a whole shift, extend, cancel', async ({ page, request }) => {
    await page.goto(`/vehicle/${VEH}`)
    const [s, e] = [addDays(T, 10), addDays(T, 14)]
    const created = await create(page, { driver: 'DRV-TEST-901', mode: 'DAY_SHIFT', start: s, end: e, shift: ['08:00', '16:00', '0'] })
    const id = created.body.event_ids[0]

    const split = await onRow(page, id, 'แก้ไขการมอบหมาย', async (dialog) => {
      await dialog.getByLabel(/เปลี่ยนเวลากะตั้งแต่วันที่กำหนด/).check()
      await dialog.getByLabel('เริ่มใช้เวลากะใหม่ตั้งแต่วันที่').fill(addDays(T, 12))
      await dialog.getByLabel('เวลาเริ่มกะ').fill('09:00')
      await dialog.getByLabel('เวลาสิ้นสุดกะ').fill('17:00')
      await dialog.getByLabel(/^เหตุผล/).fill('เปลี่ยนเวลากะ (E2E, TEST)')
    })
    expect(split.request.postDataJSON()).toEqual({ operation: 'REVISE', event_id: id, expected_revision_no: '1', reason_th: 'เปลี่ยนเวลากะ (E2E, TEST)',
      driver_id: 'DRV-TEST-901', start_date: s, end_date: e, shift: { start_time: '09:00', end_time: '17:00', end_day_offset: 0 },
      split_from_date: addDays(T, 12) })
    const segment = split.body.event_ids.find((x: string) => x !== id)

    const exclude = await onRow(page, id, 'แก้ไขการมอบหมาย', async (dialog) => {
      await dialog.getByLabel(/ตัดวัน\/กะที่บันทึกผิดออก/).check()
      await dialog.getByLabel('วันที่ที่ต้องการตัดออก').fill(addDays(T, 11))
      await dialog.getByRole('button', { name: 'เพิ่มวันที่' }).click()
      await dialog.getByLabel(/^เหตุผล/).fill('ตัดวันที่บันทึกผิด (E2E, TEST)')
    })
    expect(exclude.request.postDataJSON()).toMatchObject({ exclude_dates: [addDays(T, 11)], expected_revision_no: '2', end_date: addDays(T, 11) })

    const substitute = await onRow(page, segment, 'มอบหมายผู้ขับแทนรายวัน/รายกะ', async (dialog) => {
      await dialog.getByLabel(/วัน\/กะที่ให้ผู้ขับแทน/).fill(addDays(T, 13))
      await dialog.getByRole('button', { name: 'เพิ่มวันที่' }).click()
      await dialog.getByLabel('ผู้ขับแทน', { exact: true }).selectOption('DRV-TEST-902')
      await dialog.getByLabel(/^เหตุผล/).fill('ผู้ขับลา (E2E, TEST)')
    })
    expect(substitute.status).toBe(200)
    expect(substitute.request.postDataJSON()).toEqual({ operation: 'SUBSTITUTE', event_id: segment, expected_revision_no: '1',
      dates: [addDays(T, 13)], driver_id: 'DRV-TEST-902', reason_th: 'ผู้ขับลา (E2E, TEST)' })

    const extend = await onRow(page, segment, 'แก้ไขการมอบหมาย', async (dialog) => {
      await dialog.getByLabel('วันที่สิ้นสุด (รวมวันนี้)').fill(addDays(T, 15))
      await dialog.getByLabel(/^เหตุผล/).fill('ขยายการมอบหมาย (E2E, TEST)')
    })
    expect(extend.status).toBe(200)
    expect(extend.request.postDataJSON()).toMatchObject({ end_date: addDays(T, 15), expected_revision_no: '2' })

    const cancel = await onRow(page, id, 'ยกเลิกการมอบหมายก่อนเริ่ม', async (dialog) => {
      await dialog.getByLabel(/^เหตุผล/).fill('ยกเลิกช่วงแรก (E2E, TEST)')
    })
    expect(cancel.status).toBe(200)
    const h = await history(request)
    const events = Object.fromEntries(h.events.map((x: { event_id: string; lifecycle: string }) => [x.event_id, x.lifecycle]))
    expect(events[id]).toBe('CANCELLED')
    expect(events[segment]).toBe('ACTIVE')
    // The original rows are retained (append-only): CREATE, split head, exclusion, cancellation of the first event.
    expect(h.records.filter((r: { event_id: string }) => r.event_id === id).map((r: { entry_operation: string }) => r.entry_operation))
      .toEqual(['CREATE', 'REVISE', 'REVISE', 'CANCEL'])
    await expect(e2Panel(page).getByTestId(`e2-row-actions-${id}`)).toHaveCount(0) // cancelled: no further operations
  })

  test('H2 handover, a back-dated create with a reason, then EARLY_END now and VOID of the started assignment', async ({ page, request }) => {
    await page.goto(`/vehicle/${VEH}`)
    const day = await create(page, { driver: 'DRV-TEST-902', mode: 'FULL_DAY', start: addDays(T, 20), end: addDays(T, 21) })
    const night = await create(page, { driver: 'DRV-TEST-901', mode: 'NIGHT_SHIFT', start: addDays(T, 21), end: addDays(T, 22),
      shift: ['20:00', '06:00', '1'], predecessor: day.body.event_ids[0] })
    expect(night.status).toBe(200)
    expect(night.request.postDataJSON()).toMatchObject({ handover: { predecessor_event_id: day.body.event_ids[0], expected_revision_no: '1' },
      shift: { start_time: '20:00', end_time: '06:00', end_day_offset: 1 } })
    await expect(e2Panel(page).getByTestId('e2-history')).toContainText('H2 — ทั้งวันวันสุดท้าย')
    const schedule = await readJson(request, `/vehicles/${VEH}/operational-driver-assignments?from=${addDays(T, 21)}&to=${addDays(T, 21)}`)
    const clipped = schedule.intervals.find((i: { event_id: string }) => i.event_id === day.body.event_ids[0])
    expect(clipped.effective_end).toBe(schedule.intervals.find((i: { mode: string }) => i.mode === 'NIGHT_SHIFT').effective_start)

    // A back-dated create needs a reason (A2-5.4).
    const past = await create(page, { driver: 'DRV-TEST-902', mode: 'FULL_DAY', start: addDays(T, -3), end: addDays(T, -3), reason: 'บันทึกย้อนหลัง (E2E, TEST)' })
    expect(past.status).toBe(200)
    expect(past.request.postDataJSON()).toMatchObject({ reason_th: 'บันทึกย้อนหลัง (E2E, TEST)' })

    // The started assignment of today: EARLY_END now, then VOID (whole erroneous record).
    const todays = (await history(request)).records.find((r: { start_date: string; entry_operation: string }) => r.start_date === T && r.entry_operation === 'CREATE')
    const ended = await onRow(page, todays.event_id, 'สิ้นสุดการมอบหมายก่อนกำหนด', async (dialog) => {
      await dialog.getByLabel('ตอนนี้', { exact: true }).check()
      await dialog.getByLabel(/^เหตุผล/).fill('สิ้นสุดก่อนกำหนด (E2E, TEST)')
    })
    expect(ended.request.postDataJSON()).toEqual({ operation: 'EARLY_END', event_id: todays.event_id, expected_revision_no: '1',
      end: { mode: 'NOW' }, reason_th: 'สิ้นสุดก่อนกำหนด (E2E, TEST)' })
    expect(ended.status).toBe(200)
    const voided = await onRow(page, todays.event_id, 'แก้ไขการมอบหมาย', async (dialog) => {
      await dialog.getByLabel(/ยกเลิกรายการที่บันทึกผิดทั้งรายการ/).check()
      await dialog.getByLabel(/^เหตุผล/).fill('บันทึกผิด (E2E, TEST)')
    })
    expect(voided.request.postDataJSON()).toEqual({ operation: 'REVISE', event_id: todays.event_id, expected_revision_no: '2',
      reason_th: 'บันทึกผิด (E2E, TEST)', void_elapsed: true })
    const h = await history(request)
    expect(h.events.find((x: { event_id: string }) => x.event_id === todays.event_id).lifecycle).toBe('VOIDED')
    await expect(e2Panel(page).getByTestId('e2-current-status')).toContainText('ไม่มีการมอบหมายในขณะนี้')
  })

  test('history persistence: every accepted request id is recorded once; the driver axis, R2f-f and legacy data are separate', async ({ page, request }) => {
    const h = await history(request)
    const recorded = new Set(h.records.map((r: { request_id: string }) => r.request_id))
    // Every recorded request id came from this run's UI writes (plus nothing else).
    for (const rid of recorded) expect(sentIds).toContain(rid)
    // One logical request = one operation_id (no duplicate append for a replayed or duplicate submission).
    const ops = new Map<string, Set<string>>()
    for (const r of h.records) ops.set(r.request_id, (ops.get(r.request_id) ?? new Set()).add(r.operation_id))
    for (const set of ops.values()) expect(set.size).toBe(1)
    // E2 never writes the R2f-f permanent history or the legacy Phase 6 data.
    expect(await readJson(request, `/vehicles/${VEH}/responsible-drivers`)).toEqual(before.permanent)
    expect(await readJson(request, `/vehicles/${VEH}/driver-assignments`)).toEqual(before.legacy)
    // The driver axis lists DRV-TEST-901's units with a link back to the vehicle.
    await page.goto('/drivers/DRV-TEST-901')
    const panel = e2Panel(page)
    await panel.getByLabel('ถึงวันที่').fill(addDays(T, 25))
    await panel.getByRole('button', { name: 'แสดงตามช่วงที่เลือก' }).click()
    await expect(panel.getByTestId('e2-intervals').getByRole('link', { name: VEH }).first()).toHaveAttribute('href', `/vehicle/${VEH}`)
    await expect(panel.getByTestId('e2-intervals')).toContainText('กะกลางคืน')
    await expect(panel.getByTestId('e2-intervals')).toContainText('(+1 วัน)')
  })
})
