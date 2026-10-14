import { expect, test, type Browser, type Page } from '@playwright/test'
import { LINKED, VEHICLE, asRole, expectResponsive, jobIdFrom, queueRow, recordApi, saveTrace } from './technician-v2-helpers'

/**
 * R2 Batch R2f-h4 B6 — owner D2 (withdraw the whole assignment of an OPEN job)
 * and owner D1 (a CLOSED job permits no assignment change), plus the retired
 * legacy assignment routes (D3), against the dedicated mock backend with
 * TECHNICIAN_ASSIGNMENT_V2_ENABLED=true. Every step hits the real backend through
 * normal navigation; each test asserts only on the jobs it created itself.
 */

async function createRepair(page: Page, marker: string): Promise<string> {
  await page.goto(`/vehicle/${VEHICLE}`)
  await page.getByRole('link', { name: 'แจ้งซ่อม', exact: true }).click()
  await page.getByLabel('อาการ/ปัญหาที่พบ').fill(marker)
  await page.getByRole('button', { name: 'ส่งแจ้งซ่อม' }).click()
  await expect(page).toHaveURL(/\/repairs\/RPR-/)
  await expect(page.getByTestId('v2-current-set')).toBeVisible()
  return jobIdFrom(page, /\/repairs\/([^/?#]+)/)
}

async function createPm(page: Page): Promise<string> {
  await page.goto(`/vehicle/${VEHICLE}`)
  await page.getByRole('link', { name: 'PM', exact: true }).click()
  await page.getByRole('button', { name: 'เริ่มทำ PM' }).first().click()
  await expect(page).toHaveURL(/\/pm\/work-orders\/PMWO-/)
  await expect(page.getByTestId('v2-current-set')).toBeVisible()
  return jobIdFrom(page, /\/pm\/work-orders\/([^/?#]+)/)
}

async function assign(page: Page, primary: string, collaborators: string[]) {
  await page.getByLabel(/ช่างหลัก \(PRIMARY\)/).selectOption(primary)
  for (const id of collaborators) await page.getByRole('checkbox', { name: new RegExp(id) }).check()
  await page.getByRole('button', { name: 'บันทึกการมอบหมายช่าง' }).click()
  await expect(page.getByTestId('v2-assignment-message-success')).toBeVisible()
}

async function withdrawAll(page: Page, reason: string) {
  await page.getByRole('button', { name: 'ถอนการมอบหมายช่างทั้งหมด' }).click()
  const dialog = page.getByTestId('v2-withdraw-dialog')
  await expect(dialog).toBeVisible()
  await dialog.getByLabel('เหตุผล (ถ้ามี)').fill(reason)
  await expectResponsive(page)
  await dialog.getByTestId('v2-withdraw-confirm').click()
  await expect(page.getByTestId('v2-assignment-message-success')).toContainText('ถอนการมอบหมายช่างทั้งหมดเรียบร้อยแล้ว')
  await expect(page.getByTestId('v2-current-set')).toContainText('ยังไม่ได้มอบหมายช่าง')
}

async function myWorkHas(browser: Browser, baseURL: string, index: number, jobId: string): Promise<boolean> {
  const tech = await asRole(browser, baseURL, 'TECHNICIAN', LINKED[index].userId)
  await tech.page.goto('/my-work')
  await expect(tech.page.getByTestId('v2-my-technician-id')).toHaveText(LINKED[index].technicianId)
  await expectResponsive(tech.page)
  const count = await tech.page.getByRole('link', { name: new RegExp(jobId) }).count()
  await tech.context.close()
  return count > 0
}

test('Repair D2: assign → withdraw all (confirmed) → U1 NONE → gone from My Work → history kept → reassign via the picker', async ({
  page,
  browser,
  baseURL,
}, testInfo) => {
  const repairId = await createRepair(page, `E2E B6 withdraw repair ${testInfo.project.name}`)
  await assign(page, 'TEC-TEST-911', ['TEC-TEST-912'])
  expect(await myWorkHas(browser, baseURL!, 0, repairId)).toBe(true)

  const api = recordApi(page)
  await withdrawAll(page, 'E2E ถอนทีมช่าง')
  const posts = api.filter((e) => e.method === 'POST')
  expect(posts).toHaveLength(1)
  expect(posts[0].url).toBe(`/api/v1/repairs/${repairId}/technician-assignment-withdrawals`)
  expect(posts[0].status).toBe(200)
  expect(posts[0].body).toEqual({
    expected_current: { primary_technician_id: 'TEC-TEST-911', collaborator_technician_ids: ['TEC-TEST-912'] },
    reason_th: 'E2E ถอนทีมช่าง',
  })

  // History and audit: the old set and the withdrawal (actor, time, reason) stay readable.
  await expect(page.getByTestId('v2-assignment-history').locator('tbody tr')).toHaveCount(1)
  await expect(page.getByTestId('v2-withdrawal-history')).toContainText('E2E ถอนทีมช่าง')
  const readback = await (await page.request.get(`/api/v1/repairs/${repairId}/technician-assignments`)).json()
  expect([readback.status, readback.current, readback.sets.length, readback.withdrawals.length]).toEqual(['NONE', null, 1, 1])
  const job = await (await page.request.get(`/api/v1/repairs/${repairId}`)).json()
  expect(job.repair.status).toBe('OPEN') // the job stays OPEN

  // U1 shows NONE again; both former members lose the job from V2 My Work.
  await page.goto('/waiting-assignment')
  await expect(queueRow(page, 'REPAIR', repairId).getByTestId('v2-waiting-status')).toHaveAttribute('data-status', 'NONE')
  expect(await myWorkHas(browser, baseURL!, 0, repairId)).toBe(false)
  expect(await myWorkHas(browser, baseURL!, 1, repairId)).toBe(false)

  // Reassignment through the standard picker (expected_current null after the withdrawal).
  await queueRow(page, 'REPAIR', repairId).getByRole('link', { name: repairId, exact: true }).click()
  const reassignApi = recordApi(page)
  await assign(page, 'TEC-TEST-912', [])
  const reassign = reassignApi.find((e) => e.method === 'POST')
  expect(reassign?.url).toBe(`/api/v1/repairs/${repairId}/technician-assignments`)
  expect((reassign?.body as { expected_current?: unknown } | undefined)?.expected_current).toBeNull()
  expect(await myWorkHas(browser, baseURL!, 1, repairId)).toBe(true)
  await page.goto('/waiting-assignment')
  await expect(page.getByTestId('v2-waiting-REPAIR').getByText(/ทั้งหมด \d+ รายการ/)).toBeVisible()
  await expect(queueRow(page, 'REPAIR', repairId)).toHaveCount(0)
  saveTrace(testInfo, 'b6-repair-withdrawal', { repairId, posts, readback })
})

test('PM D2: assign → withdraw all → U1 NONE → gone from My Work → reassign', async ({ page, browser, baseURL }) => {
  const workOrderId = await createPm(page)
  await assign(page, 'TEC-TEST-912', ['TEC-TEST-911'])
  const api = recordApi(page)
  await withdrawAll(page, 'E2E PM withdraw')
  expect(api.filter((e) => e.method === 'POST').map((e) => [e.url, e.status])).toEqual([
    [`/api/v1/pm/work-orders/${workOrderId}/technician-assignment-withdrawals`, 200],
  ])
  await page.goto('/waiting-assignment')
  await expect(queueRow(page, 'PM', workOrderId).getByTestId('v2-waiting-status')).toHaveAttribute('data-status', 'NONE')
  expect(await myWorkHas(browser, baseURL!, 1, workOrderId)).toBe(false)
  await queueRow(page, 'PM', workOrderId).getByRole('link', { name: workOrderId, exact: true }).click()
  await assign(page, 'TEC-TEST-911', [])
  const readback = await (await page.request.get(`/api/v1/pm/work-orders/${workOrderId}/technician-assignments`)).json()
  expect([readback.status, readback.current.primary_technician_id, readback.sets.length, readback.withdrawals.length]).toEqual([
    'VALID',
    'TEC-TEST-911',
    2,
    1,
  ])
})

test('stale withdrawal: a second manager holding the old set is refused, nothing is withdrawn, reload shows the new set', async ({
  page,
  browser,
  baseURL,
}, testInfo) => {
  const repairId = await createRepair(page, `E2E B6 stale withdraw ${testInfo.project.name}`)
  await assign(page, 'TEC-TEST-911', [])
  const other = await browser.newContext({ baseURL })
  const otherPage = await other.newPage()
  await otherPage.goto(`/repairs/${repairId}`)
  await expect(otherPage.getByRole('button', { name: 'ถอนการมอบหมายช่างทั้งหมด' })).toBeVisible()
  await page.reload()
  await assign(page, 'TEC-TEST-912', []) // the current set changes under the other manager
  await otherPage.getByRole('button', { name: 'ถอนการมอบหมายช่างทั้งหมด' }).click()
  await otherPage.getByTestId('v2-withdraw-confirm').click()
  await expect(otherPage.getByTestId('v2-assignment-message-stale')).toBeVisible()
  const readback = await (await page.request.get(`/api/v1/repairs/${repairId}/technician-assignments`)).json()
  expect([readback.status, readback.current.primary_technician_id, readback.withdrawals.length]).toEqual(['VALID', 'TEC-TEST-912', 0])
  await otherPage.getByRole('button', { name: 'โหลดข้อมูลล่าสุด' }).click()
  await expect(otherPage.getByTestId('v2-current-set')).toContainText('TEC-TEST-912')
  await other.close()
})

test('D1: a CLOSED job offers no withdrawal or assignment control and the server refuses both (JOB_CLOSED), history unchanged', async ({
  page,
}, testInfo) => {
  const repairId = await createRepair(page, `E2E B6 closed ${testInfo.project.name}`)
  await assign(page, 'TEC-TEST-911', [])
  const closed = await page.request.post(`/api/v1/repairs/${repairId}/close`, { data: { close_note: 'E2E' } })
  expect(closed.status()).toBe(200)
  const before = await (await page.request.get(`/api/v1/repairs/${repairId}/technician-assignments`)).json()
  await page.reload()
  await expect(page.getByTestId('v2-assignment-closed')).toContainText('CLOSED')
  await expect(page.getByRole('button', { name: 'ถอนการมอบหมายช่างทั้งหมด' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'บันทึกการมอบหมายช่าง' })).toHaveCount(0)
  await expect(page.getByTestId('v2-assignment-history').locator('tbody tr')).toHaveCount(1) // history stays readable
  const expected = { primary_technician_id: before.current.primary_technician_id, collaborator_technician_ids: [] }
  const withdraw = await page.request.post(`/api/v1/repairs/${repairId}/technician-assignment-withdrawals`, {
    headers: { 'X-Request-Id': '00000000-0000-4000-8000-0000000000b6' },
    data: { expected_current: expected },
  })
  const reassign = await page.request.post(`/api/v1/repairs/${repairId}/technician-assignments`, {
    headers: { 'X-Request-Id': '00000000-0000-4000-8000-0000000000b7' },
    data: { primary_technician_id: 'TEC-TEST-912', collaborator_technician_ids: [], expected_current: expected },
  })
  for (const response of [withdraw, reassign]) {
    expect(response.status()).toBe(409)
    expect((await response.json()).error.code).toBe('TECHNICIAN_ASSIGNMENT_JOB_CLOSED')
  }
  const after = await (await page.request.get(`/api/v1/repairs/${repairId}/technician-assignments`)).json()
  expect(after).toEqual(before)
})

test('D3: the retired legacy assignment write / queue routes answer 410 and change nothing; a TECHNICIAN cannot withdraw', async ({
  page,
  browser,
  baseURL,
}, testInfo) => {
  const repairId = await createRepair(page, `E2E B6 retired ${testInfo.project.name}`)
  await assign(page, 'TEC-TEST-911', [])
  const before = await (await page.request.get(`/api/v1/repairs/${repairId}/technician-assignments`)).json()
  const retired = [
    await page.request.post(`/api/v1/repairs/${repairId}/assign`, { data: { primary_technician: 'dev-user', collaborators: [] } }),
    await page.request.get('/api/v1/repairs/my-work'),
    await page.request.get('/api/v1/repairs/waiting-assignment'),
    await page.request.get('/api/v1/pm/work-orders/my-work'),
  ]
  for (const response of retired) {
    expect(response.status()).toBe(410)
    expect((await response.json()).error.code).toBe('LEGACY_ASSIGNMENT_RETIRED')
  }
  const tech = await asRole(browser, baseURL!, 'TECHNICIAN', LINKED[0].userId)
  await tech.page.goto(`/repairs/${repairId}`)
  await expect(tech.page.getByTestId('v2-current-set')).toContainText('TEC-TEST-911')
  await expect(tech.page.getByRole('button', { name: 'ถอนการมอบหมายช่างทั้งหมด' })).toHaveCount(0)
  const direct = await tech.page.request.post(`/api/v1/repairs/${repairId}/technician-assignment-withdrawals`, {
    headers: { 'X-Request-Id': '00000000-0000-4000-8000-0000000000b8' },
    data: { expected_current: { primary_technician_id: 'TEC-TEST-911', collaborator_technician_ids: [] } },
  })
  expect(direct.status()).toBe(403)
  await tech.context.close()
  expect(await (await page.request.get(`/api/v1/repairs/${repairId}/technician-assignments`)).json()).toEqual(before)
})
