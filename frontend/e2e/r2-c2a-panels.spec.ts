import { expect, test, type APIRequestContext, type Page, type Request } from '@playwright/test'

/**
 * R2 Batch R2-C2a — relationship / history panels against the REAL mock
 * (TEST) backend started by playwright.config.ts (reuseExistingServer: false,
 * so every invocation starts its own fresh backend).
 *
 * Owner safety correction C2a-3:
 * - READ-ONLY tests (all five viewport projects) never mutate the backend.
 *   Only one test performs a write, and that write is intercepted in the
 *   browser (it never reaches the backend).
 * - `@mutation` tests write to the backend for real. They run ONLY in a
 *   dedicated invocation, sequentially, with nothing else against that fresh
 *   backend:
 *     R2_C2A_MUTATION=1 npx playwright test e2e/r2-c2a-panels.spec.ts --project=desktop --workers=1 --grep @mutation
 *   and refuse to run otherwise (env flag, desktop project, one worker). They
 *   first prove the backend is Mock/TEST and untouched (empty histories).
 *   The R2f histories are append-only: TRANSFER → END restores the CURRENT
 *   state, never the history — the records they create are expected, kept and
 *   checked, and the backend process is simply ended by Playwright afterwards.
 * - The Technician / Account links of PER-TEST-911 / 912 (used by the
 *   Technician V2 specs) are never changed; only the PER-TEST-912 driver link is.
 */

const API = '/api/v1'
const MUTATION_RUN = process.env.R2_C2A_MUTATION === '1'

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

// ---------------------------------------------------------------------------
// Read-only (all viewport projects)
// ---------------------------------------------------------------------------

test.describe('R2-C2a read-only panels (real Mock/TEST backend)', () => {
  test.skip(MUTATION_RUN, 'the dedicated mutation invocation runs only the @mutation tests')

  test('personnel list → detail: TEST personnel only, relationships, histories and department history', async ({ page }) => {
    const api = recordApi(page)
    await page.goto('/personnel')
    await expect(page.getByRole('link', { name: 'PER-TEST-911' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'PER-TEST-912' })).toBeVisible()
    await expect(page.getByText('PER-TEST-001')).toHaveCount(0) // a REAL-scope row never appears in TEST
    await page.getByRole('link', { name: 'PER-TEST-911' }).click()
    await expect(page).toHaveURL(/\/personnel\/PER-TEST-911$/)

    const links = page.getByTestId('personnel-links')
    await expect(page.getByRole('heading', { name: 'ความเชื่อมโยงข้อมูลบุคลากร' })).toBeVisible()
    await expect(links.getByTestId('link-technician-id')).toContainText('TEC-TEST-911')
    await expect(links.getByTestId('link-technician-id')).toContainText('ช่างทดสอบ ลำดับหนึ่ง')
    await expect(links.getByTestId('link-account-id')).toContainText('USR-TEST-911')
    await expect(links.getByTestId('link-driver-resolution')).toHaveText('ยังไม่ได้เชื่อมโยง')
    await expect(links.getByText('ยังไม่มีประวัติความเชื่อมโยง')).toHaveCount(3)
    await expect(page.getByTestId('v2-data-context').first()).toContainText('TEST')

    await expect(page.getByRole('heading', { name: 'ประวัติการสังกัดแผนก' })).toBeVisible()
    await expect(page.getByTestId('department-history').getByText('ยังไม่มีประวัติการสังกัดแผนก').first()).toBeVisible()

    const paths = api.map((r) => new URL(r.url()).pathname)
    expect(paths.some((p) => p.startsWith(`${API}/departments`))).toBe(false) // no department-detail lookup in TEST
    expect(paths.some((p) => p.includes('operational-driver'))).toBe(false) // no E2
    expect(writes(api)).toHaveLength(0)
    await expectNoHorizontalOverflow(page)
  })

  test('a role without the account-link capability sees the account id hidden and no link controls', async ({ page }) => {
    await page.setExtraHTTPHeaders({ 'X-Dev-Role': 'DRIVER' })
    await page.goto('/personnel/PER-TEST-912')
    const links = page.getByTestId('personnel-links')
    await expect(links.getByTestId('link-account-id')).toContainText('ซ่อนไว้')
    await expect(links.getByTestId('link-account-resolution')).toHaveText('เชื่อมโยงแล้ว')
    await expect(links).not.toContainText('USR-TEST-912')
    await expect(links.getByTestId('link-technician-id')).toContainText('TEC-TEST-912') // still readable (can_view)
    for (const kind of ['technician', 'account', 'driver']) await expect(links.getByTestId(`link-${kind}-actions`)).toHaveCount(0)
  })

  test('PER-TEST-001 (REAL scope) is not readable in the TEST context', async ({ page }) => {
    await page.goto('/personnel/PER-TEST-001')
    await expect(page.getByText('ไม่พบข้อมูลบุคลากร', { exact: false }).first()).toBeVisible()
    await expect(page.getByTestId('personnel-links')).toHaveCount(0)
  })

  test('equipment caretaker: EQP-0002 (TEST) readable with controls; EQP-0001 (REAL) fails closed', async ({ page }) => {
    const api = recordApi(page)
    await page.goto('/equipment/EQP-0002')
    await expect(page.getByRole('heading', { name: 'ผู้ดูแลอุปกรณ์และประวัติ' })).toBeVisible()
    await expect(page.getByTestId('caretaker-current')).toHaveText('ยังไม่มีข้อมูล')
    await expect(page.getByTestId('caretaker-actions').getByRole('button', { name: 'กำหนดผู้ดูแล' })).toBeVisible()
    await expectNoHorizontalOverflow(page)
    await page.goto('/equipment/EQP-0001')
    await expect(page.getByTestId('r2-scope-unproven')).toBeVisible()
    await expect(page.getByTestId('caretaker-actions')).toHaveCount(0)
    expect(writes(api)).toHaveLength(0)
  })

  test('permanent responsible driver: VEH-1048 (TEST) with the not-driving note; VEH-1046 fails closed; legacy link kept', async ({ page }) => {
    const api = recordApi(page)
    // The permanent panel's data contract: its own R2f-f route, never an E2 route.
    const permanentRead = page.waitForResponse((r) => new URL(r.url()).pathname === `${API}/vehicles/VEH-1048/responsible-drivers`)
    await page.goto('/vehicle/VEH-1048')
    await expect(page.getByRole('heading', { name: 'ผู้รับผิดชอบรถประจำ' })).toBeVisible()
    await expect(page.getByTestId('responsible-driver-note')).toHaveText('ผู้รับผิดชอบรถประจำ ไม่ได้ยืนยันว่าเป็นผู้ขับรถจริงในแต่ละวัน')
    await expect(page.getByTestId('responsible-driver-current')).toHaveText('ยังไม่มีข้อมูล')
    await expect(page.getByRole('link', { name: /คนขับ\/ผู้ควบคุม/ }).first()).toHaveAttribute('href', '/vehicle/VEH-1048/drivers')

    // R2-C2b (owner-authorized guard update): E2 is an independent SIBLING panel. The page-wide
    // "no E2 heading / no operational-driver request" guards written before R2-C2b are replaced
    // by checks that the permanent panel itself shows only permanent responsibility, from its own
    // endpoint, and that the two panels never contain each other.
    const permanent = await permanentRead
    expect(permanent.status()).toBe(200)
    const body = await permanent.json()
    expect(Object.keys(body).sort()).toEqual(['current_driver_id', 'current_since', 'current_status', 'events', 'timeline_status', 'vehicle_id'])
    expect(body).toMatchObject({ vehicle_id: 'VEH-1048', current_driver_id: null, current_status: 'NONE' }) // what the panel shows
    expect(JSON.stringify(body)).not.toMatch(/assigned_driver_id|intervals|label_date|operational/) // no E2 fields
    const panels = await page.evaluate(() => {
      const note = document.querySelector('[data-testid="responsible-driver-note"]')
      const card = note?.closest('.r2-panel') ?? null
      const e2 = document.querySelector('.e2-panel')
      return {
        permanentIsE2: card?.classList.contains('e2-panel') ?? null,
        e2ElementsInPermanent: card?.querySelectorAll('[data-testid^="e2-"]').length ?? null,
        e2TextInPermanent: card?.textContent?.includes('การมอบหมายผู้ขับรถตามวัน/กะ') ?? null,
        permanentElementsInE2: e2?.querySelectorAll('[data-testid^="responsible-driver"]').length ?? null,
        nested: !!card && !!e2 && (card.contains(e2) || e2.contains(card)),
      }
    })
    expect(panels).toEqual({ permanentIsE2: false, e2ElementsInPermanent: 0, e2TextInPermanent: false, permanentElementsInE2: 0, nested: false })
    // The E2 panel exists separately, with its own heading and its own backend authority.
    await expect(page.locator('.e2-panel').getByRole('heading', { name: 'การมอบหมายผู้ขับรถตามวัน/กะ' })).toBeVisible()
    expect(api.some((r) => new URL(r.url()).pathname === `${API}/vehicles/VEH-1048/operational-driver-assignments`)).toBe(true)
    await expectNoHorizontalOverflow(page)
    await page.goto('/vehicle/VEH-1046')
    await expect(page.getByTestId('r2-scope-unproven')).toBeVisible()
    await expect(page.getByTestId('responsible-driver-actions')).toHaveCount(0)
    expect(writes(api)).toHaveLength(0)
  })

  test('driver → vehicles: DRV-TEST-901 (TEST) has no current vehicle; DRV-0001 (REAL) fails closed', async ({ page }) => {
    await page.goto('/drivers/DRV-TEST-901')
    await expect(page.getByRole('heading', { name: 'รถที่รับผิดชอบประจำ' })).toBeVisible()
    await expect(page.getByText('ไม่มีรถที่รับผิดชอบประจำในปัจจุบัน')).toBeVisible()
    await expectNoHorizontalOverflow(page)
    await page.goto('/drivers/DRV-0001')
    await expect(page.getByTestId('r2-scope-unproven')).toBeVisible()
  })

  test('an uncertain write (intercepted, never reaching the backend) stays pending and is resent unchanged', async ({ page }) => {
    const sent: { rid: string; body: string }[] = []
    await page.route('**/api/v1/vehicles/VEH-1048/responsible-driver-events', async (route) => {
      sent.push({ rid: route.request().headers()['x-request-id'], body: route.request().postData() ?? '' })
      await route.abort('failed') // a transport failure: the outcome is unknown
    })
    await page.goto('/vehicle/VEH-1048')
    await page.getByTestId('responsible-driver-actions').getByRole('button', { name: 'กำหนดผู้รับผิดชอบ' }).click()
    const dialog = page.getByTestId('timeline-event-dialog')
    await dialog.getByLabel('รหัสคนขับ/ผู้ควบคุม').selectOption('DRV-TEST-901')
    await dialog.getByRole('button', { name: /^ยืนยัน/ }).click()
    const pending = page.getByTestId('r2-pending-intent')
    await expect(pending).toContainText('ยังไม่ทราบผล')
    await expect(page.getByTestId('responsible-driver-actions')).toHaveCount(0) // no new intent while unresolved
    await pending.getByRole('button', { name: 'ส่งคำขอเดิมอีกครั้ง' }).click()
    await expect.poll(() => sent.length).toBe(2)
    expect(sent[1]).toEqual(sent[0]) // same request id, same exact body
    // Without a history record it stays pending (never assumed successful).
    await page.reload()
    await expect(page.getByTestId('r2-pending-intent')).toContainText(sent[0].rid)
    await page.evaluate(() => window.localStorage.clear())
  })
})

// ---------------------------------------------------------------------------
// @mutation — dedicated fresh backend, desktop, one worker, sequential
// ---------------------------------------------------------------------------

test.describe('R2-C2a real writes @mutation', () => {
  test.describe.configure({ mode: 'serial' })
  test.beforeEach(() => {
    const info = test.info()
    test.skip(!MUTATION_RUN || info.project.name !== 'desktop' || info.config.workers !== 1,
      'real writes run only in the dedicated R2_C2A_MUTATION=1 --project=desktop --workers=1 invocation')
  })

  const before: Record<string, unknown> = {}

  test('the dedicated backend is Mock/TEST and untouched before the first write', async ({ request }) => {
    const me = await readJson(request, '/me')
    expect(me.data_context).toBe('TEST')
    expect((await readJson(request, '/equipment/EQP-0002/caretakers')).events).toEqual([])
    expect((await readJson(request, '/vehicles/VEH-1048/responsible-drivers')).events).toEqual([])
    expect((await readJson(request, '/personnel/PER-TEST-912/driver-links/history')).events).toEqual([])
    for (const p of ['PER-TEST-911', 'PER-TEST-912']) {
      before[`${p}:technician`] = await readJson(request, `/personnel/${p}/technician-links/history`)
      before[`${p}:account`] = await readJson(request, `/personnel/${p}/account-links/history`)
      before[`${p}:relationships`] = await readJson(request, `/personnel/${p}/relationships`)
    }
  })

  test('equipment caretaker TRANSFER then END on EQP-0002; history retained; exact replay', async ({ page, request }) => {
    const api = recordApi(page)
    await page.goto('/equipment/EQP-0002')
    await page.getByTestId('caretaker-actions').getByRole('button', { name: 'กำหนดผู้ดูแล' }).click()
    let dialog = page.getByTestId('timeline-event-dialog')
    await dialog.getByLabel('รหัสช่าง').selectOption('TEC-TEST-912')
    await dialog.getByRole('button', { name: /^ยืนยัน/ }).dblclick() // a double click must still send ONE request
    await expect(page.getByTestId('r2-write-message')).toContainText('บันทึกเรียบร้อยแล้ว')
    await expect(page.getByTestId('caretaker-current')).toContainText('TEC-TEST-912')
    expect(writes(api)).toHaveLength(1)
    const transfer = writes(api)[0]
    expect(transfer.postDataJSON()).toEqual({ operation: 'TRANSFER', technician_id: 'TEC-TEST-912', effective: { mode: 'NOW' },
      expected_current_technician_id: null })

    // Effective "NOW" is whole seconds: an END in the same second as the TRANSFER would be
    // (correctly) refused as the same instant, so step past the second boundary first.
    await page.waitForTimeout(1100)
    await page.getByTestId('caretaker-actions').getByRole('button', { name: 'สิ้นสุดการดูแล' }).click()
    dialog = page.getByTestId('timeline-event-dialog')
    const ended = page.waitForResponse((r) => r.url().endsWith('/caretaker-events') && r.request().method() === 'POST')
    await dialog.getByRole('button', { name: /^ยืนยัน/ }).click()
    expect((await ended).status()).toBe(200)
    await expect(page.getByTestId('caretaker-current')).toHaveText('สิ้นสุดแล้ว')
    const history = await readJson(request, '/equipment/EQP-0002/caretakers')
    expect(history.events.map((e: { entry_operation: string }) => e.entry_operation).sort()).toEqual(['END', 'TRANSFER'])
    await expect(page.getByTestId('caretaker-panel').getByRole('row')).toHaveCount(3) // header + 2 retained rows

    // Exact replay of the TRANSFER: same request id and body → replayed, nothing new recorded.
    const replay = await request.post(`${API}/equipment/EQP-0002/caretaker-events`, {
      headers: { 'Content-Type': 'application/json', 'X-Request-Id': transfer.headers()['x-request-id'] },
      data: transfer.postData() ?? '',
    })
    expect(replay.status()).toBe(200)
    const body = await replay.json()
    expect(body.replayed).toBe(true)
    expect((await readJson(request, '/equipment/EQP-0002/caretakers')).events).toHaveLength(2)
  })

  test('permanent responsible driver VEH-1048 ↔ DRV-TEST-901 in both directions, then END; history retained', async ({ page, request }) => {
    await page.goto('/vehicle/VEH-1048')
    await page.getByTestId('responsible-driver-actions').getByRole('button', { name: 'กำหนดผู้รับผิดชอบ' }).click()
    const dialog = page.getByTestId('timeline-event-dialog')
    await dialog.getByLabel('รหัสคนขับ/ผู้ควบคุม').selectOption('DRV-TEST-901') // explicit choice
    await dialog.getByRole('button', { name: /^ยืนยัน/ }).click()
    const current = page.getByTestId('responsible-driver-current')
    await expect(current.getByRole('link', { name: 'DRV-TEST-901' })).toBeVisible()

    // Vehicle → Driver → Vehicle navigation over the same authority.
    await current.getByRole('link', { name: 'DRV-TEST-901' }).click()
    await expect(page).toHaveURL(/\/drivers\/DRV-TEST-901$/)
    await expect(page.getByTestId('driver-vehicles').getByRole('link', { name: 'VEH-1048' })).toBeVisible()
    await page.getByTestId('driver-vehicles').getByRole('link', { name: 'VEH-1048' }).click()
    await expect(page).toHaveURL(/\/vehicle\/VEH-1048$/)

    await page.waitForTimeout(1100) // END must not share the TRANSFER's whole-second instant
    await page.getByTestId('responsible-driver-actions').getByRole('button', { name: 'สิ้นสุดความรับผิดชอบ' }).click()
    const ended = page.waitForResponse((r) => r.url().endsWith('/responsible-driver-events') && r.request().method() === 'POST')
    await page.getByTestId('timeline-event-dialog').getByRole('button', { name: /^ยืนยัน/ }).click()
    expect((await ended).status()).toBe(200)
    await expect(page.getByTestId('responsible-driver-current')).toHaveText('สิ้นสุดแล้ว')
    expect((await readJson(request, '/drivers/DRV-TEST-901/vehicles')).items).toEqual([]) // reverse lookup after END
    const history = await readJson(request, '/vehicles/VEH-1048/responsible-drivers')
    expect(history.events).toHaveLength(2) // TRANSFER + END retained (append-only)
    await page.goto('/drivers/DRV-TEST-901')
    await expect(page.getByText('ไม่มีรถที่รับผิดชอบประจำในปัจจุบัน')).toBeVisible()
  })

  test('PER-TEST-912 driver link LINK then UNLINK; link history retained with request ids', async ({ page, request }) => {
    const api = recordApi(page)
    await page.goto('/personnel/PER-TEST-912')
    const section = page.getByTestId('link-driver')
    await section.getByRole('button', { name: 'เชื่อมโยง' }).click()
    let dialog = page.getByTestId('link-dialog')
    await dialog.getByLabel('รหัสคนขับ/ผู้ควบคุม').selectOption('DRV-TEST-902')
    await dialog.getByLabel('เหตุผล (บังคับ)').fill('ทดสอบเชื่อมโยง (E2E, TEST)')
    await dialog.getByRole('button', { name: 'ยืนยันเชื่อมโยง' }).click()
    await expect(section.getByTestId('link-driver-resolution')).toHaveText('เชื่อมโยงแล้ว')
    await expect(section.getByTestId('link-driver-id')).toContainText('DRV-TEST-902')

    await section.getByRole('button', { name: 'ยกเลิกการเชื่อมโยง' }).click()
    dialog = page.getByTestId('link-dialog')
    await dialog.getByLabel('เหตุผล (บังคับ)').fill('ทดสอบยกเลิก (E2E, TEST)')
    await dialog.getByRole('button', { name: 'ยืนยันยกเลิกการเชื่อมโยง' }).click()
    await expect(section.getByTestId('link-driver-resolution')).toHaveText('ยังไม่ได้เชื่อมโยง')

    const history = await readJson(request, '/personnel/PER-TEST-912/driver-links/history')
    expect(history.events.map((e: { event_kind: string }) => e.event_kind)).toEqual(['LINK', 'UNLINK'])
    const sentIds = writes(api).map((r) => r.headers()['x-request-id'])
    expect(history.events.map((e: { request_id: string }) => e.request_id)).toEqual(sentIds)
    await expect(section.getByRole('row')).toHaveCount(3) // header + 2 retained rows
  })

  test('the Technician / Account links of PER-TEST-911 / 912 were never changed', async ({ request }) => {
    for (const p of ['PER-TEST-911', 'PER-TEST-912']) {
      expect(await readJson(request, `/personnel/${p}/technician-links/history`)).toEqual(before[`${p}:technician`])
      expect(await readJson(request, `/personnel/${p}/account-links/history`)).toEqual(before[`${p}:account`])
      const relationships = await readJson(request, `/personnel/${p}/relationships`)
      const original = before[`${p}:relationships`] as typeof relationships
      expect(relationships.technician).toEqual(original.technician)
      expect(relationships.account).toEqual(original.account)
    }
  })
})
