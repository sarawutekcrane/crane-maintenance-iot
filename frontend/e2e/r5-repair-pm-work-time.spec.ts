import { randomUUID } from 'node:crypto'
import { expect, test, type Browser, type BrowserContext, type Page } from '@playwright/test'
import { expectResponsive, jobIdFrom } from './technician-v2-helpers'

/**
 * R5 — combined PM + Repair work-time flow against the dedicated Mock TEST backend
 * (synthetic data only). Every viewport project runs the Work Order flow; because all
 * projects share one backend and the cross-Work-Order overlap rule is global per
 * technician, each project records its work periods on its own day window. The vehicle
 * status / downtime steps mutate the one TEST-scoped vehicle (VEH-1048) and run on
 * desktop only, with assertions that stay true when other specs change that vehicle
 * concurrently. API calls are used only for setup steps (PM item outcomes, the Repair
 * handover) and to prove server refusals; every R5 feature is driven through the UI.
 */

const PROJECTS = ['smartphone-portrait', 'smartphone-landscape', 'tablet-portrait', 'tablet-landscape', 'desktop']
const TINY_PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', 'base64')
const T911 = { role: 'TECHNICIAN', user: 'USR-TEST-911', technician: 'TEC-TEST-911' }
const T912 = { role: 'TECHNICIAN', user: 'USR-TEST-912', technician: 'TEC-TEST-912' }
const REPAIR_VEHICLE = 'VEH-1046'
const STATUS_VEHICLE = 'VEH-1048' // the seed's TEST-scoped vehicle (Mock runs in the TEST context)

/** Asia/Bangkok calendar date `days` from today, YYYY-MM-DD. */
function bangkokDate(days: number): string {
  return new Date(Date.now() + 7 * 3600_000 + days * 86400_000).toISOString().slice(0, 10)
}

async function actor(browser: Browser, baseURL: string, role: string, user: string): Promise<{ context: BrowserContext; page: Page }> {
  const context = await browser.newContext({ baseURL, extraHTTPHeaders: { 'X-Dev-Role': role, 'X-Dev-User-Id': user } })
  return { context, page: await context.newPage() }
}

async function recordEntry(page: Page, start: string, end: string, opts: { overtime?: boolean; breaks?: [string, string][]; text?: string } = {}) {
  await page.getByRole('button', { name: 'บันทึกเวลาทำงานของฉัน' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('เริ่มทำงาน').fill(start)
  await dialog.getByLabel('สิ้นสุด').fill(end)
  if (opts.overtime) await dialog.getByLabel('ประเภทเวลา').selectOption('OVERTIME')
  await dialog.getByLabel('รายละเอียดงานที่ทำ').fill(opts.text ?? 'งานซ่อมจริง')
  if (opts.breaks?.length) {
    await dialog.getByLabel('มีพัก', { exact: true }).check()
    for (const [index, [from, to]] of opts.breaks.entries()) {
      if (index > 0) await dialog.getByRole('button', { name: 'เพิ่มช่วงพัก' }).click()
      await dialog.getByLabel(`พักครั้งที่ ${index + 1} เริ่ม`).fill(from)
      await dialog.getByLabel(`พักครั้งที่ ${index + 1} สิ้นสุด`).fill(to)
    }
  } else {
    await dialog.getByLabel('ไม่มีพัก', { exact: true }).check()
  }
  await dialog.getByRole('button', { name: 'บันทึก' }).click()
}

test('R5 combined flow: Repair + PM teams, substates, regular / OT / breaks / midnight, overlap, confirmation gate, post-close correction, totals', async ({ browser, baseURL }, testInfo) => {
  test.setTimeout(240_000)
  // Own day window per project (and per --repeat-each repetition): the overlap rule is global per technician.
  const idx = Math.max(PROJECTS.indexOf(testInfo.project.name), 0) + testInfo.repeatEachIndex * PROJECTS.length
  const D = bangkokDate(-(8 + idx * 5))
  const D1 = bangkokDate(-(7 + idx * 5))
  const D2 = bangkokDate(-(6 + idx * 5))
  const manager = await actor(browser, baseURL!, 'MAINTENANCE', `USR-E2E-R5-MGR-${idx}`)
  const tech911 = await actor(browser, baseURL!, T911.role, T911.user)
  const tech912 = await actor(browser, baseURL!, T912.role, T912.user)

  // 1–2. Open a Repair Work Order and assign PRIMARY + COLLABORATOR (UI).
  const m = manager.page
  await m.goto(`/vehicle/${REPAIR_VEHICLE}/repairs/new`)
  await m.getByLabel('อาการ/ปัญหาที่พบ').fill(`R5 e2e ${testInfo.project.name}`)
  await m.getByRole('button', { name: 'ส่งแจ้งซ่อม' }).click()
  await expect(m).toHaveURL(/\/repairs\/RPR-/)
  const repairId = jobIdFrom(m, /\/repairs\/([^/?#]+)/)
  await m.getByLabel(/ช่างหลัก \(PRIMARY\)/).selectOption(T911.technician)
  await m.getByRole('checkbox', { name: new RegExp(T912.technician) }).check()
  await m.getByRole('button', { name: 'บันทึกการมอบหมายช่าง' }).click()
  await expect(m.getByTestId('v2-assignment-message-success')).toBeVisible()

  // 6. Substate กำลังซ่อม (now), recorded by the lead technician.
  const t = tech911.page
  await t.goto(`/repairs/${repairId}`)
  await t.getByRole('button', { name: 'เริ่ม/กลับมาซ่อม (ตอนนี้)' }).click()
  await expect(t.getByTestId('substate-current')).toHaveText('กำลังซ่อม')

  // 7–9. Backdated REGULAR with an explicit break, OVERTIME, and work across midnight.
  await recordEntry(t, `${D}T08:00`, `${D}T17:00`, { breaks: [[`${D}T12:00`, `${D}T13:00`]] })
  await expect(t.getByTestId('wt-entry')).toHaveCount(1)
  await recordEntry(t, `${D}T17:00`, `${D}T19:00`, { overtime: true })
  await expect(t.getByTestId('wt-entry')).toHaveCount(2)
  await recordEntry(t, `${D1}T22:00`, `${D2}T02:00`, { overtime: true, text: 'งานกลางคืน' })
  await expect(t.getByTestId('wt-entry')).toHaveCount(3)
  await expect(t.getByTestId('wt-team-total')).toHaveText('14 ชม. (ปกติ 8 ชม. / ล่วงเวลา 6 ชม.)')
  await expect(t.getByTestId('wt-technicians')).toContainText('3 วัน') // D, D1 and D2 (midnight)

  // 11. รออะไหล่ (now) creates no labor.
  await t.waitForTimeout(1_100) // a substate period has a positive length (whole seconds): never switch within the same second
  const waiting = t.waitForResponse((r) => r.url().endsWith(`/repairs/${repairId}/substates`) && r.request().method() === 'POST')
  await t.getByRole('button', { name: 'รออะไหล่ (ตอนนี้)' }).click()
  const waitingResponse = await waiting
  expect(waitingResponse.status(), await waitingResponse.text()).toBe(200)
  await expect(t.getByTestId('substate-current')).toHaveText('รออะไหล่')
  await expect(t.getByTestId('wt-team-total')).toHaveText('14 ชม. (ปกติ 8 ชม. / ล่วงเวลา 6 ชม.)')

  // 12. Actions, actual parts and evidence; a lost response is re-sent without a duplicate (25).
  let dropped = false
  await t.route(`**/api/v1/repairs/${repairId}/actions`, async (route) => {
    if (dropped) return route.continue()
    dropped = true
    await route.fetch() // the server records the action...
    await route.abort('connectionreset') // ...but the response is lost
  })
  await t.getByLabel('เพิ่มการดำเนินการ').fill('ถอดชุดปั๊มไฮดรอลิก')
  await t.locator('#action-photo').setInputFiles({ name: 'evidence.png', mimeType: 'image/png', buffer: TINY_PNG })
  await expect(t.getByText('แนบแล้ว 1 รูป')).toBeVisible()
  await t.getByRole('button', { name: 'บันทึกการดำเนินการ' }).click()
  await expect(t.getByText(/ไม่ทราบผลการบันทึก/)).toBeVisible()
  await t.getByRole('button', { name: 'บันทึกการดำเนินการ' }).click()
  await expect(t.getByText('ถอดชุดปั๊มไฮดรอลิก')).toBeVisible()
  const afterRetry = await (await t.request.get(`/api/v1/repairs/${repairId}`)).json()
  expect(afterRetry.actions.filter((a: { action_text: string }) => a.action_text === 'ถอดชุดปั๊มไฮดรอลิก')).toHaveLength(1)
  await t.getByText('ไม่พบอะไหล่ในระบบ — ระบุชื่อเอง (สำหรับอะไหล่ที่ยังไม่ได้ลงทะเบียน)').click()
  await t.getByLabel('ชื่ออะไหล่ (ระบุเอง — อะไหล่ยังไม่ได้ลงทะเบียนใน Part Master)').fill('ซีลปั๊มไฮดรอลิก')
  await t.getByText('+ เพิ่มอะไหล่').click()
  await expect(t.getByText('ซีลปั๊มไฮดรอลิก')).toBeVisible()
  await expectResponsive(t)

  // 3. Repair handover (setup through the V2 route): 912 becomes PRIMARY; 911 stays a former member.
  const handover = await m.request.post(`/api/v1/repairs/${repairId}/technician-assignments`, {
    data: { primary_technician_id: T912.technician, collaborator_technician_ids: [], expected_current: { primary_technician_id: T911.technician, collaborator_technician_ids: [T912.technician] } },
    headers: { 'X-Request-Id': randomUUID() },
  })
  expect(handover.ok(), await handover.text()).toBe(true)

  // 1–5 (PM): open, assign, START, then reassign while IN_PROGRESS (OD-1).
  await m.goto(`/vehicle/${REPAIR_VEHICLE}`)
  await m.getByRole('link', { name: 'PM', exact: true }).click()
  await m.getByRole('button', { name: 'เริ่มทำ PM' }).first().click()
  await expect(m).toHaveURL(/\/pm\/work-orders\/PMWO-/)
  const pmId = jobIdFrom(m, /\/pm\/work-orders\/([^/?#]+)/)
  await m.getByLabel(/ช่างหลัก \(PRIMARY\)/).selectOption(T912.technician)
  await m.getByRole('button', { name: 'บันทึกการมอบหมายช่าง' }).click()
  await expect(m.getByTestId('v2-assignment-message-success')).toBeVisible()
  await m.getByRole('button', { name: 'เริ่มงาน' }).click()
  await expect(m.getByText('กำลังดำเนินการ').first()).toBeVisible()
  await expect(m.getByRole('button', { name: 'ถอนการมอบหมายช่างทั้งหมด' })).toBeVisible() // controls still offered
  const reassigned = await m.request.post(`/api/v1/pm/work-orders/${pmId}/technician-assignments`, {
    data: { primary_technician_id: T911.technician, collaborator_technician_ids: [T912.technician], expected_current: { primary_technician_id: T912.technician, collaborator_technician_ids: [] } },
    headers: { 'X-Request-Id': randomUUID() },
  })
  expect(reassigned.ok(), await reassigned.text()).toBe(true)
  await m.reload()
  await expect(m.getByTestId('v2-current-set')).toContainText(T911.technician)

  // 10. The same technician cannot record overlapping work on another Work Order.
  await t.goto(`/pm/work-orders/${pmId}`)
  await recordEntry(t, `${D}T16:00`, `${D}T18:00`, { text: 'PM ทับเวลา' })
  await expect(t.getByRole('dialog').getByRole('alert')).toContainText('มีเวลาทำงานที่บันทึกไว้ในช่วงเวลาเดียวกันแล้ว')
  await t.getByRole('dialog').getByRole('button', { name: 'ยกเลิก' }).click()
  await recordEntry(t, `${D2}T08:00`, `${D2}T10:00`, { text: 'ตรวจเช็ค PM' })
  await expect(t.getByTestId('wt-entry')).toHaveCount(1)

  // 13. Submit: items saved (setup), then the new PRIMARY submits in the UI; a team change is now refused.
  const detail = await (await t.request.get(`/api/v1/pm/work-orders/${pmId}`)).json()
  for (const task of detail.work_order.scope_task_ids as string[]) {
    const saved = await t.request.post(`/api/v1/pm/work-orders/${pmId}/items/${task}/outcome`, {
      data: { disposition: 'PERFORMED', performed_actions: ['ตรวจเช็ค'] },
    })
    expect(saved.ok(), await saved.text()).toBe(true)
  }
  await t.reload()
  await t.getByRole('button', { name: 'ส่งตรวจสอบ' }).click()
  await expect(t.getByText('รอตรวจสอบ').first()).toBeVisible()
  const lateChange = await m.request.post(`/api/v1/pm/work-orders/${pmId}/technician-assignments`, {
    data: { primary_technician_id: T912.technician, collaborator_technician_ids: [], expected_current: { primary_technician_id: T911.technician, collaborator_technician_ids: [T912.technician] } },
    headers: { 'X-Request-Id': randomUUID() },
  })
  expect(lateChange.status()).toBe(409)
  expect((await lateChange.json()).error.code).toBe('TECHNICIAN_ASSIGNMENT_JOB_CLOSED')

  // 14. CLOSE is refused while recorded time is unconfirmed (PM).
  await m.goto(`/pm/work-orders/${pmId}`)
  await m.getByRole('button', { name: 'อนุมัติและปิดงาน' }).click()
  await expect(m.getByText(/กรุณายืนยันเวลาทำงานทุกรายการก่อนปิดงาน PM/)).toBeVisible()

  // 15. Self-confirmation refused: a manager who is also TEC-TEST-911 cannot confirm 911's time.
  const selfManager = await actor(browser, baseURL!, 'MAINTENANCE', T911.user)
  const pmView = await (await selfManager.page.request.get(`/api/v1/pm/work-orders/${pmId}/work-time`)).json()
  const own = pmView.entries[0].entry
  const selfConfirm = await selfManager.page.request.post(`/api/v1/pm/work-orders/${pmId}/work-time/confirmations`, {
    data: { entries: [{ entry_id: own.entry_id, revision: own.revision }] },
    headers: { 'X-Request-Id': randomUUID() },
  })
  expect(selfConfirm.status()).toBe(403)
  expect((await selfConfirm.json()).error.code).toBe('WORK_TIME_SELF_CONFIRMATION_REFUSED')
  await selfManager.page.goto(`/pm/work-orders/${pmId}`)
  await expect(selfManager.page.getByTestId('wt-entry')).toHaveCount(1)
  await expect(selfManager.page.getByRole('button', { name: 'ยืนยันเวลานี้' })).toHaveCount(0)
  await selfManager.context.close()

  // 15–16. An independent manager confirms; PM and Repair close.
  await m.reload()
  await m.getByRole('button', { name: 'ยืนยันเวลานี้' }).click()
  await expect(m.getByTestId('wt-unconfirmed')).toHaveCount(0)
  await m.getByRole('button', { name: 'อนุมัติและปิดงาน' }).click()
  await expect(m.getByText('ปิดงานแล้ว').first()).toBeVisible()

  await m.goto(`/repairs/${repairId}`)
  await m.getByRole('button', { name: 'ปิดใบแจ้งซ่อม' }).click()
  await expect(m.getByText(/กรุณายืนยันเวลาทำงานทุกรายการก่อนปิดใบแจ้งซ่อม/)).toBeVisible()
  await m.getByRole('button', { name: /ยืนยันทุกรายการที่รอ \(3\)/ }).click()
  await expect(m.getByTestId('wt-unconfirmed')).toHaveCount(0)
  await m.getByRole('button', { name: 'ปิดใบแจ้งซ่อม' }).click()
  await expect(m.getByText('ปิดงานเมื่อ')).toBeVisible()

  // 17–18. Post-close correction by the manager (reason) keeps the Work Order CLOSED; the same manager re-confirms (AMB-2).
  await m.getByTestId('wt-entry').filter({ hasText: 'งานกลางคืน' }).getByRole('button', { name: 'แก้ไข' }).click()
  const correction = m.getByRole('dialog')
  await correction.getByLabel('สิ้นสุด').fill(`${D2}T01:00`)
  await correction.getByLabel('เหตุผลการแก้ไข').fill('ตรวจพบเลิกงานจริง 01:00')
  await correction.getByRole('button', { name: 'บันทึก' }).click()
  await expect(m.getByTestId('wt-unconfirmed')).toContainText('แก้ไขหลังปิดงาน — ใบงานยังคงปิดอยู่')
  await expect(m.getByText('ปิดงานเมื่อ')).toBeVisible()
  await m.getByRole('button', { name: 'ยืนยันเวลานี้' }).click()
  await expect(m.getByTestId('wt-unconfirmed')).toHaveCount(0)
  const closedRepair = await (await m.request.get(`/api/v1/repairs/${repairId}`)).json()
  expect(closedRepair.repair.status).toBe('CLOSED')

  // 19. Labor totals, actual workdays and elapsed time; the technician page across Work Orders.
  await expect(m.getByTestId('wt-team-total')).toHaveText('13 ชม. (ปกติ 8 ชม. / ล่วงเวลา 5 ชม.)')
  await m.goto(`/work-time/assignees/${T911.technician}`)
  await m.getByLabel('ตั้งแต่วันที่').fill(D)
  await m.getByLabel('ถึงวันที่').fill(D2)
  await expect(m.getByTestId('twt-total')).toHaveText('15 ชม.') // 13 h Repair + 2 h PM
  await expect(m.getByTestId('twt-overtime')).toHaveText('5 ชม.')
  await expect(m.getByTestId('twt-workdays')).toHaveText('3 วัน')
  await expectResponsive(m)

  for (const a of [manager, tech911, tech912]) await a.context.close()
})

test('R5 vehicle status: AMB-1 authorization, effective-dated events, time correction and downtime without double counting', async ({ browser, baseURL }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'one shared TEST-scoped vehicle: run once')
  test.setTimeout(480_000)

  // 23. DRIVER and TECHNICIAN: no status control, and the server refuses a direct write (zero writes).
  for (const role of ['DRIVER', 'TECHNICIAN']) {
    const a = await actor(browser, baseURL!, role, `USR-E2E-R5-${role}`)
    await a.page.goto(`/vehicle/${STATUS_VEHICLE}`)
    await expect(a.page.getByText('ประวัติการเปลี่ยนสถานะ')).toBeVisible()
    await expect(a.page.getByRole('button', { name: 'เปลี่ยนสถานะ' })).toHaveCount(0)
    const before = await (await a.page.request.get(`/api/v1/vehicles/${STATUS_VEHICLE}/status-history`)).json()
    const refused = await a.page.request.patch(`/api/v1/vehicles/${STATUS_VEHICLE}/status`, { data: { status: 'MAINTENANCE' } })
    expect(refused.status()).toBe(403)
    const after = await (await a.page.request.get(`/api/v1/vehicles/${STATUS_VEHICLE}/status-history`)).json()
    expect(after.length).toBe(before.length)
    await a.context.close()
  }

  const manager = await actor(browser, baseURL!, 'MAINTENANCE_MANAGER', 'USR-E2E-R5-VMGR')
  const m = manager.page

  // 24. A REAL-scoped vehicle cannot be written from the TEST context.
  const real = await m.request.patch(`/api/v1/vehicles/${REPAIR_VEHICLE}/status`, { data: { status: 'MAINTENANCE' } })
  expect(real.status()).toBe(422)
  expect((await real.json()).error.code).toBe('VEHICLE_SCOPE_UNPROVEN')

  // 20. An authorized, in-scope manager changes the current status through the dialog (MAINTENANCE, then WORKING).
  // Other specs change this shared vehicle concurrently; our pair is retried until it is adjacent with a gap of
  // more than a minute, so the minute-precision correction below lands strictly between its neighbours.
  await m.goto(`/vehicle/${STATUS_VEHICLE}`)
  type Ev = { history_id: string; status: string; changed_by: string; effective_at: string }
  let mine: Ev | undefined
  let target = new Date(0)
  for (let attempt = 1; attempt <= 3 && !mine; attempt += 1) {
    for (const label of ['MAINTENANCE', 'WORKING']) {
      await m.getByRole('button', { name: 'เปลี่ยนสถานะ' }).click()
      const dialog = m.getByRole('alertdialog')
      await dialog.getByLabel('สถานะใหม่').selectOption(label)
      await dialog.getByRole('button', { name: 'ยืนยันเปลี่ยนสถานะ' }).click()
      await expect(dialog).toBeHidden()
      if (label === 'MAINTENANCE') await m.waitForTimeout(65_000)
    }
    const ordered: Ev[] = [...(await (await m.request.get(`/api/v1/vehicles/${STATUS_VEHICLE}/status-events`)).json())].reverse()
    const position = ordered.map((e) => e.status === 'MAINTENANCE' && e.changed_by === 'USR-E2E-R5-VMGR').lastIndexOf(true)
    const next = ordered[position + 1]
    const candidate = new Date(Date.parse(ordered[position].effective_at) + 60_000)
    candidate.setUTCSeconds(0, 0)
    if (next && next.changed_by === 'USR-E2E-R5-VMGR' && next.status === 'WORKING' && candidate.getTime() < Date.parse(next.effective_at)) {
      mine = ordered[position]
      target = candidate
    }
  }
  expect(mine, 'our MAINTENANCE / WORKING pair stayed adjacent in one of three attempts').toBeTruthy()

  // An effective time before the latest event is refused with a clear message (no write).
  await m.getByRole('button', { name: 'เปลี่ยนสถานะ' }).click()
  const late = m.getByRole('alertdialog')
  await late.getByLabel('สถานะใหม่').selectOption('OUT_OF_SERVICE')
  await late.getByLabel('เวลาที่มีผลจริง (ไม่บังคับ — เว้นว่าง = ตอนนี้)').fill('2026-01-01T08:00')
  await late.getByRole('button', { name: 'ยืนยันเปลี่ยนสถานะ' }).click()
  await expect(late.getByRole('alert')).toContainText('เวลาที่มีผลต้องอยู่หลังสถานะล่าสุด')
  await late.getByRole('button', { name: 'ยกเลิก' }).click()

  // 21. Correct our MAINTENANCE event's effective time (strictly between its neighbours) with an audit reason.
  const local = new Date(target.getTime() + 7 * 3600_000).toISOString().slice(0, 16)
  await m.getByRole('button', { name: 'แสดงเวลาที่มีผลและช่วงรถหยุดใช้งาน' }).click()
  const myEvent = m.locator(`[data-testid="vehicle-status-event"][data-history-id="${mine!.history_id}"]`)
  await myEvent.getByRole('button', { name: 'แก้เวลาที่มีผล' }).click()
  const fix = m.getByRole('dialog')
  await fix.getByLabel('เวลาที่มีผลใหม่ (เวลาประเทศไทย)').fill(local)
  await fix.getByLabel('เหตุผลการแก้ไข').fill('เข้าซ่อมจริงตามใบรับรถ')
  await fix.getByRole('button', { name: 'บันทึกการแก้ไข' }).click()
  await expect(fix).toBeHidden()
  await expect(myEvent).toContainText('แก้เวลาแล้ว 1 ครั้ง')
  await expect(m.getByTestId('vehicle-downtime-interval').first()).toBeVisible() // evidence-based span shown in the UI

  // 22. Downtime over a fixed past window is identical after two simultaneous Repair Work Orders open.
  const end = new Date(Date.now() - 5000)
  end.setUTCMilliseconds(0)
  const windowEnd = end.toISOString() // a whole second in the past: identical for both reads
  const windowStart = new Date(target.getTime() - 3600_000).toISOString()
  const query = `from=${encodeURIComponent(windowStart)}&to=${encodeURIComponent(windowEnd)}`
  const before = await (await m.request.get(`/api/v1/vehicles/${STATUS_VEHICLE}/downtime?${query}`)).json()
  expect(before.total_seconds).toBeGreaterThan(0)
  expect(before.intervals.some((i: { started_at: string }) => Date.parse(i.started_at) === target.getTime())).toBe(true)
  for (let n = 0; n < 2; n += 1) {
    const created = await m.request.post('/api/v1/repairs', { data: { asset_type: 'VEHICLE', asset_id: STATUS_VEHICLE, source_type: 'MANUAL', symptom: `R5 downtime ${n}` } })
    expect(created.ok(), await created.text()).toBe(true)
  }
  const after = await (await m.request.get(`/api/v1/vehicles/${STATUS_VEHICLE}/downtime?${query}`)).json()
  expect(after.total_seconds).toBe(before.total_seconds)
  expect(after.intervals).toEqual(before.intervals)
  await expectResponsive(m)
  await manager.context.close()
})
