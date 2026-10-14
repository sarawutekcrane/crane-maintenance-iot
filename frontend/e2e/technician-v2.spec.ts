import { expect, test, type Page } from '@playwright/test'
import {
  LINKED,
  REAL_SEED_TECHNICIANS,
  TEST_TECHNICIANS,
  VEHICLE,
  asRole,
  expectResponsive,
  jobIdFrom,
  queueRow,
  recordApi,
  saveTrace,
} from './technician-v2-helpers'

/**
 * R2 Batch R2f-h4 B4 / B5 — Technician V2 against the dedicated mock backend
 * (playwright.config.ts; B6 Rev2: V2 is the only model, there is no V2 setting). B5:
 * every flow runs on the canonical pages reached by normal navigation. Every
 * happy-path step hits the real backend; `page.route` is used only in the
 * error-injection tests. Each test asserts on the jobs it created itself (the
 * mock state is shared by the parallel projects).
 */

/** Repair creation through normal navigation: Vehicle Detail → "แจ้งซ่อม". */
async function createRepair(page: Page, marker: string): Promise<string> {
  await page.goto(`/vehicle/${VEHICLE}`)
  await page.getByRole('link', { name: 'แจ้งซ่อม', exact: true }).click()
  await expect(page).toHaveURL(new RegExp(`/vehicle/${VEHICLE}/repairs/new`))
  await expect(page.getByTestId('v2-data-context')).toContainText('TEST')
  await expect(page.getByLabel(/ช่างผู้รับผิดชอบหลัก/)).toHaveCount(0) // no legacy inline technician
  await page.getByLabel('อาการ/ปัญหาที่พบ').fill(marker)
  await expectResponsive(page)
  await page.getByRole('button', { name: 'ส่งแจ้งซ่อม' }).click()
  await expect(page).toHaveURL(/\/repairs\/RPR-/)
  const id = jobIdFrom(page, /\/repairs\/([^/?#]+)/)
  const job = await (await page.request.get(`/api/v1/repairs/${id}`)).json()
  expect(job.repair.assignment_model).toBe('TECHNICIAN_V2') // persisted by the server
  await expect(page.getByTestId('v2-current-set')).toBeVisible()
  return id
}

/** PM creation through normal navigation: Vehicle Detail → "PM" → "เริ่มทำ PM". */
async function createPm(page: Page): Promise<string> {
  await page.goto(`/vehicle/${VEHICLE}`)
  await page.getByRole('link', { name: 'PM', exact: true }).click()
  await page.getByRole('button', { name: 'เริ่มทำ PM' }).first().click()
  await expect(page).toHaveURL(/\/pm\/work-orders\/PMWO-/)
  const id = jobIdFrom(page, /\/pm\/work-orders\/([^/?#]+)/)
  const job = await (await page.request.get(`/api/v1/pm/work-orders/${id}`)).json()
  expect(job.work_order.assignment_model).toBe('TECHNICIAN_V2')
  await expect(page.getByTestId('v2-current-set')).toBeVisible()
  return id
}

async function assign(page: Page, primary: string, collaborators: string[]) {
  await page.getByLabel(/ช่างหลัก \(PRIMARY\)/).selectOption(primary)
  for (const id of collaborators) await page.getByRole('checkbox', { name: new RegExp(id) }).check()
  await page.getByRole('button', { name: 'บันทึกการมอบหมายช่าง' }).click()
  await expect(page.getByTestId('v2-assignment-message-success')).toBeVisible()
}

test('/me reports TEST and no V2 ON/OFF flag; the menu leads to the V2 My Work and waiting queues; TEST is labelled', async ({ page }) => {
  const me = await (await page.request.get('/api/v1/me')).json()
  // R2 Batch R2f-h4 B6 Rev2 (deliberate test migration): the V2 cutover flag no longer exists.
  expect(me).not.toHaveProperty('technician_assignment_v2_enabled')
  expect(me.data_context).toBe('TEST')
  const api = recordApi(page)
  for (const [label, url, testId] of [
    ['รอมอบหมายช่าง', '/waiting-assignment', 'v2-waiting-REPAIR'],
    ['งานของฉัน', '/my-work', 'v2-data-context'],
  ] as const) {
    await page.goto('/')
    const toggle = page.getByRole('button', { name: 'เปิดเมนู' })
    if (await toggle.isVisible()) await toggle.click() // collapsed menu below tablet width
    await page.getByRole('navigation', { name: 'เมนูหลัก' }).getByRole('link', { name: label, exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`${url}$`))
    await expect(page.getByTestId(testId)).toBeVisible()
    await expect(page.getByTestId('v2-data-context')).toContainText('TEST — ข้อมูลทดสอบ')
    await expect(page.getByTestId('v2-data-context')).not.toContainText('REAL')
    await expect(page.getByTestId('v2-cutover-state')).toHaveCount(0) // no V2 ON/OFF state is shown
    await expectResponsive(page)
  }
  // Only the V2 reads; never the legacy My Work / waiting routes.
  const legacy = /\/repairs\/my-work|\/pm\/work-orders\/my-work|\/repairs\/waiting-assignment/
  expect(api.filter((e) => legacy.test(e.url))).toEqual([])
})

test('old B4 /v2 bookmarks only redirect to the canonical pages (nothing is created or changed)', async ({ page }, testInfo) => {
  const repairId = await createRepair(page, `E2E V2 bookmark ${testInfo.project.name}`)
  const api = recordApi(page)
  for (const [from, to] of [
    [`/v2/repairs/${repairId}`, `/repairs/${repairId}`],
    [`/v2/vehicle/${VEHICLE}/repairs/new`, `/vehicle/${VEHICLE}/repairs/new`],
    [`/v2/vehicle/${VEHICLE}/pm`, `/vehicle/${VEHICLE}/pm`],
    ['/v2/my-work', '/my-work'],
    ['/v2/waiting-assignment', '/waiting-assignment'],
    ['/v2', '/'],
  ] as const) {
    await page.goto(from)
    await expect(page).toHaveURL(new RegExp(`${to.replace(/\//g, '\\/')}$`))
  }
  expect(api.filter((e) => e.method !== 'GET')).toEqual([])
})

test('Repair V2: create → U1 NONE → picker (in-batch TEST only) → PRIMARY + COLLABORATOR → readback / history → leaves U1 → My Work', async ({
  page,
  browser,
  baseURL,
}, testInfo) => {
  const api = recordApi(page)
  const repairId = await createRepair(page, `E2E V2 repair ${testInfo.project.name}`)
  await expect(page.getByTestId('v2-current-set')).toContainText('ยังไม่ได้มอบหมายช่าง')

  // The create request carried no technician field.
  const create = api.find((e) => e.method === 'POST' && e.url === '/api/v1/repairs')
  expect(create?.status).toBe(200)
  expect(Object.keys((create?.body ?? {}) as object).sort()).toEqual(['asset_id', 'asset_type', 'category', 'source_id', 'source_type', 'symptom'])

  // U1 before assignment: NONE.
  await page.goto('/waiting-assignment')
  await expect(queueRow(page, 'REPAIR', repairId).getByTestId('v2-waiting-status')).toHaveAttribute('data-status', 'NONE')
  await expectResponsive(page)
  await queueRow(page, 'REPAIR', repairId).getByRole('link', { name: repairId, exact: true }).click()
  await expect(page).toHaveURL(new RegExp(`/repairs/${repairId}$`))

  // Picker: exactly the in-batch TEST technicians the server returned (never the REAL seed rows).
  const primarySelect = page.getByLabel(/ช่างหลัก \(PRIMARY\)/)
  await expect(primarySelect.locator('option')).toHaveCount(TEST_TECHNICIANS.length + 1) // + the "choose" placeholder
  const values = await primarySelect.locator('option').evaluateAll((options) => options.map((o) => (o as HTMLOptionElement).value).filter(Boolean))
  expect(values.sort()).toEqual([...TEST_TECHNICIANS].sort())
  for (const real of REAL_SEED_TECHNICIANS) expect(values).not.toContain(real)
  await expect(primarySelect.locator('option', { hasText: 'TEC-TEST-911' })).toContainText(LINKED[0].name)
  await expectResponsive(page)

  await assign(page, 'TEC-TEST-911', ['TEC-TEST-912'])
  const post = api.find((e) => e.method === 'POST' && e.url === `/api/v1/repairs/${repairId}/technician-assignments`)
  expect(post?.status).toBe(200)
  expect(post?.body).toEqual({
    primary_technician_id: 'TEC-TEST-911',
    collaborator_technician_ids: ['TEC-TEST-912'],
    expected_current: null,
  })

  // Readback (UI and API) and history.
  const current = page.getByTestId('v2-current-set')
  await expect(current).toContainText('TEC-TEST-911')
  await expect(current).toContainText(LINKED[0].name)
  await expect(current).toContainText('TEC-TEST-912')
  await expect(current).toContainText(LINKED[1].name)
  await expect(page.getByTestId('v2-assignment-history').locator('tbody tr')).toHaveCount(1)
  const readback = await (await page.request.get(`/api/v1/repairs/${repairId}/technician-assignments`)).json()
  expect(readback.status).toBe('VALID')
  expect(readback.current.primary_technician_id).toBe('TEC-TEST-911')
  expect(readback.current.collaborator_technician_ids).toEqual(['TEC-TEST-912'])
  expect(readback.sets).toHaveLength(1)

  // After assignment the job leaves U1.
  await page.goto('/waiting-assignment')
  await expect(page.getByTestId('v2-waiting-REPAIR').getByText(/ทั้งหมด \d+ รายการ/)).toBeVisible()
  await expect(queueRow(page, 'REPAIR', repairId)).toHaveCount(0)

  // V2 My Work for both linked TEST accounts.
  for (const [index, section] of [[0, 'v2-my-work-primary'], [1, 'v2-my-work-collaborator']] as const) {
    const tech = await asRole(browser, baseURL!, 'TECHNICIAN', LINKED[index].userId)
    await tech.page.goto('/my-work')
    await expect(tech.page.getByTestId('v2-my-technician-id')).toHaveText(LINKED[index].technicianId)
    await expect(tech.page.getByTestId(section).getByRole('link', { name: new RegExp(repairId) })).toBeVisible()
    await expect(tech.page.getByTestId('v2-data-context')).toContainText('TEST')
    await expectResponsive(tech.page)
    await tech.context.close()
  }
  saveTrace(testInfo, 'repair-happy-path', { repairId, api, readback })
})

test('PM V2: create → U1 NONE → assign → leaves U1 → My Work (PRIMARY 912, COLLABORATOR 911)', async ({ page, browser, baseURL }, testInfo) => {
  const api = recordApi(page)
  const workOrderId = await createPm(page)
  const create = api.find((e) => e.method === 'POST' && e.url === '/api/v1/pm/work-orders')
  expect(create?.status).toBe(200)
  expect(Object.keys((create?.body ?? {}) as object).sort()).toEqual(['asset_id', 'asset_type', 'pm_plan_id'])

  await page.goto('/waiting-assignment')
  await expect(queueRow(page, 'PM', workOrderId).getByTestId('v2-waiting-status')).toHaveAttribute('data-status', 'NONE')
  await queueRow(page, 'PM', workOrderId).getByRole('link', { name: workOrderId, exact: true }).click()

  await assign(page, 'TEC-TEST-912', ['TEC-TEST-911'])
  await expect(page.getByTestId('v2-assignment-history').locator('tbody tr')).toHaveCount(1)
  const readback = await (await page.request.get(`/api/v1/pm/work-orders/${workOrderId}/technician-assignments`)).json()
  expect(readback.current.primary_technician_id).toBe('TEC-TEST-912')
  expect(readback.current.collaborator_technician_ids).toEqual(['TEC-TEST-911'])

  await page.goto('/waiting-assignment')
  await expect(page.getByTestId('v2-waiting-PM').getByText(/ทั้งหมด \d+ รายการ/)).toBeVisible()
  await expect(queueRow(page, 'PM', workOrderId)).toHaveCount(0)

  for (const [index, section] of [[1, 'v2-my-work-primary'], [0, 'v2-my-work-collaborator']] as const) {
    const tech = await asRole(browser, baseURL!, 'TECHNICIAN', LINKED[index].userId)
    await tech.page.goto('/my-work')
    await expect(tech.page.getByTestId(section).getByRole('link', { name: new RegExp(workOrderId) })).toBeVisible()
    await tech.context.close()
  }
  saveTrace(testInfo, 'pm-happy-path', { workOrderId, api, readback })
})

test('stale expected_current: the second writer gets a conflict, nothing is overwritten, reload + reconfirm succeeds', async ({
  page,
  browser,
  baseURL,
}, testInfo) => {
  const repairId = await createRepair(page, `E2E V2 stale ${testInfo.project.name}`)
  const other = await browser.newContext({ baseURL })
  const otherPage = await other.newPage()
  await otherPage.goto(`/repairs/${repairId}`)
  await expect(otherPage.getByRole('button', { name: 'บันทึกการมอบหมายช่าง' })).toBeVisible()

  // Writer A assigns first.
  await page.reload()
  await assign(page, 'TEC-TEST-911', [])

  // Writer B still holds the old view (no current set) → stale.
  const otherApi = recordApi(otherPage)
  await otherPage.getByLabel(/ช่างหลัก \(PRIMARY\)/).selectOption('TEC-TEST-912')
  await otherPage.getByRole('button', { name: 'บันทึกการมอบหมายช่าง' }).click()
  await expect(otherPage.getByTestId('v2-assignment-message-stale')).toBeVisible()
  await expect(otherPage.getByRole('button', { name: 'บันทึกการมอบหมายช่าง' })).toBeDisabled()
  const conflict = otherApi.find((e) => e.method === 'POST')
  expect(conflict?.status).toBe(409)
  expect((conflict?.body as { expected_current?: unknown } | undefined)?.expected_current).toBeNull()
  let readback = await (await page.request.get(`/api/v1/repairs/${repairId}/technician-assignments`)).json()
  expect(readback.current.primary_technician_id).toBe('TEC-TEST-911') // never silently overwritten
  expect(readback.sets).toHaveLength(1)

  // Reload, see the new current set, reconfirm the kept selection.
  await otherPage.getByRole('button', { name: 'โหลดข้อมูลล่าสุด' }).click()
  await expect(otherPage.getByTestId('v2-current-set')).toContainText('TEC-TEST-911')
  await expect(otherPage.getByLabel(/ช่างหลัก \(PRIMARY\)/)).toHaveValue('TEC-TEST-912')
  await otherPage.getByRole('button', { name: 'บันทึกการมอบหมายช่าง' }).click()
  await expect(otherPage.getByTestId('v2-assignment-message-success')).toBeVisible()
  const second = otherApi.filter((e) => e.method === 'POST')[1]
  expect(second?.status).toBe(200)
  expect((second?.body as { expected_current?: unknown } | undefined)?.expected_current).toEqual({
    primary_technician_id: 'TEC-TEST-911',
    collaborator_technician_ids: [],
  })
  readback = await (await page.request.get(`/api/v1/repairs/${repairId}/technician-assignments`)).json()
  expect(readback.current.primary_technician_id).toBe('TEC-TEST-912')
  expect(readback.sets).toHaveLength(2)
  await other.close()
})

test('access denied fails closed: a TECHNICIAN gets no create form, no queue, a read-only panel, and the server refuses a direct write', async ({
  page,
  browser,
  baseURL,
}, testInfo) => {
  const repairId = await createRepair(page, `E2E V2 denied ${testInfo.project.name}`)
  const tech = await asRole(browser, baseURL!, 'TECHNICIAN', 'USR-TEST-911')
  // A TECHNICIAN (no can_manage_repair) gets only the unchanged problem report on a vehicle, never a direct create.
  await tech.page.goto(`/vehicle/${VEHICLE}/repairs/new`)
  await expect(tech.page.getByRole('heading', { name: 'แจ้งปัญหา/แจ้งซ่อม' })).toBeVisible()
  await expect(tech.page.getByLabel('หมวดหมู่ (ถ้ามี)')).toHaveCount(0)
  await tech.page.goto('/waiting-assignment')
  await expect(tech.page.getByText('ไม่มีสิทธิ์เข้าถึง', { exact: true })).toBeVisible()
  await tech.page.goto(`/repairs/${repairId}`)
  await expect(tech.page.getByTestId('v2-current-set')).toBeVisible()
  await expect(tech.page.getByRole('button', { name: 'บันทึกการมอบหมายช่าง' })).toHaveCount(0)
  const direct = await tech.page.request.post(`/api/v1/repairs/${repairId}/technician-assignments`, {
    headers: { 'X-Request-Id': '00000000-0000-4000-8000-0000000000b4' },
    data: { primary_technician_id: 'TEC-TEST-911', collaborator_technician_ids: [], expected_current: null },
  })
  expect(direct.status()).toBe(403)
  const queue = await tech.page.request.get('/api/v1/repairs/v2-waiting-assignment')
  expect(queue.status()).toBe(403)
  await tech.context.close()
})

test('corrupted / ambiguous data fails closed (error injection by route stub only)', async ({ page }, testInfo) => {
  const repairId = await createRepair(page, `E2E V2 corrupt ${testInfo.project.name}`)

  // AMBIGUOUS current set → no control.
  await page.route(`**/api/v1/repairs/${repairId}/technician-assignments`, (route) =>
    route.request().method() === 'GET'
      ? route.fulfill({ json: { job_id: repairId, assignment_model: 'TECHNICIAN_V2', status: 'AMBIGUOUS', current: null, sets: [] } })
      : route.fallback(),
  )
  await page.reload()
  await expect(page.getByText(/ระบุทีมช่างปัจจุบันไม่ได้/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'บันทึกการมอบหมายช่าง' })).toHaveCount(0)
  await page.unrouteAll()

  // An unknown assignment_model → explicit error, no V2 read, no control.
  await page.route(`**/api/v1/repairs/${repairId}`, async (route) => {
    const response = await route.fetch()
    const json = await response.json()
    json.repair.assignment_model = 'BROKEN'
    await route.fulfill({ response, json })
  })
  await page.reload()
  await expect(page.getByText('รูปแบบการมอบหมายของงานนี้ไม่ถูกต้อง')).toBeVisible()
  await expect(page.getByText('รหัสข้อผิดพลาด: ASSIGNMENT_MODEL_INVALID')).toBeVisible()
  await expect(page.getByRole('button', { name: 'บันทึกการดำเนินการ' })).toBeVisible() // the rest of the job stays usable
  await expect(page.getByRole('button', { name: 'บันทึกการมอบหมายช่าง' })).toHaveCount(0)
  await page.unrouteAll()

  // A whole-queue 500 → ErrorState with code + request id, no rows.
  await page.route('**/api/v1/repairs/v2-waiting-assignment*', (route) =>
    route.fulfill({
      status: 500,
      json: { error: { code: 'TECHNICIAN_ASSIGNMENT_DATA_INVALID', message: 'x', details: { issues: { SET_INCOMPLETE: 1 } }, request_id: 'REQ-E2E-DI' } },
    }),
  )
  await page.goto('/waiting-assignment')
  const repairs = page.getByTestId('v2-waiting-REPAIR')
  await expect(repairs.getByText('รหัสข้อผิดพลาด: TECHNICIAN_ASSIGNMENT_DATA_INVALID')).toBeVisible()
  await expect(repairs.getByText('รหัสอ้างอิง: REQ-E2E-DI')).toBeVisible()
  await expect(repairs.locator('tbody tr')).toHaveCount(0)
  await page.unrouteAll()

  // A DATA_INVALID / AMBIGUOUS item is shown distinctly with its codes, never reinterpreted.
  await page.route('**/api/v1/repairs/v2-waiting-assignment*', async (route) => {
    const response = await route.fetch()
    const json = await response.json()
    json.items = json.items.map((item: { job_id: string }) =>
      item.job_id === repairId ? { ...item, assignment_status: 'DATA_INVALID', issues: { SET_DIGEST_MISMATCH: 2 } } : item,
    )
    await route.fulfill({ response, json })
  })
  await page.reload()
  const row = queueRow(page, 'REPAIR', repairId)
  await expect(row.getByTestId('v2-waiting-status')).toHaveAttribute('data-status', 'DATA_INVALID')
  await expect(row).toContainText('SET_DIGEST_MISMATCH × 2')
})

test('transport failure on save: UNKNOWN (never success), intent kept, explicit resend with the same request id', async ({ page }, testInfo) => {
  const repairId = await createRepair(page, `E2E V2 transport ${testInfo.project.name}`)
  const api = recordApi(page)
  let abort = true
  await page.route(`**/api/v1/repairs/${repairId}/technician-assignments`, (route) =>
    route.request().method() === 'POST' && abort ? route.abort('connectionreset') : route.fallback(),
  )
  await page.getByLabel(/ช่างหลัก \(PRIMARY\)/).selectOption('TEC-TEST-911')
  await page.getByRole('button', { name: 'บันทึกการมอบหมายช่าง' }).click()
  await expect(page.getByTestId('v2-assignment-message-unknown')).toBeVisible()
  await expect(page.getByTestId('v2-assignment-message-success')).toHaveCount(0)
  await expect(page.getByTestId('v2-assignment-pending')).toBeVisible()
  await page.reload()
  await expect(page.getByTestId('v2-assignment-pending')).toBeVisible() // survives a reload
  abort = false
  await page.getByRole('button', { name: 'ส่งคำขอเดิมอีกครั้ง' }).click()
  await expect(page.getByTestId('v2-assignment-message-success')).toBeVisible()
  await expect(page.getByTestId('v2-assignment-pending')).toHaveCount(0)
  const posts = api.filter((e) => e.method === 'POST')
  expect(posts).toHaveLength(2)
  expect(posts[1].body).toEqual(posts[0].body)
  const readback = await (await page.request.get(`/api/v1/repairs/${repairId}/technician-assignments`)).json()
  expect(readback.sets).toHaveLength(1)
})

test('a CLOSED V2 job offers no assignment control', async ({ page }, testInfo) => {
  const repairId = await createRepair(page, `E2E V2 closed ${testInfo.project.name}`)
  const closed = await page.request.post(`/api/v1/repairs/${repairId}/close`, { data: { close_note: 'E2E' } })
  expect(closed.status()).toBe(200)
  await page.reload()
  await expect(page.getByTestId('v2-assignment-closed')).toContainText('CLOSED')
  await expect(page.getByRole('button', { name: 'บันทึกการมอบหมายช่าง' })).toHaveCount(0)
})
