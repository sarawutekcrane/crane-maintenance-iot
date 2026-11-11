import { randomUUID } from 'node:crypto'
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

// R6 combined browser acceptance (FINAL plan §15) — Owner decision A-4 ON, TEST ONLY.
//
// Every meter value below is an explicitly FAKE verified reading recorded through the TEST-only
// hook `/test-support/part-meter-observations` (refused outside the Mock/TEST backend), and the
// 5,000-hour REPLACE rule is a synthetic TEST rule — never a real threshold or real meter history.
//
// The fake readings are per vehicle, so this spec runs ONLY in the desktop project and in serial
// (the shared backend serves every viewport project in parallel). VEH-1048 is the mock's single
// TEST-scoped vehicle (MODEL-0003, one CARRIER_ENGINE + PTO); a vehicle-to-vehicle transfer needs a
// second TEST-scoped vehicle the mock seed does not have, so the numeric transfer case is proven by
// the backend suite (test_r6_part_usage_counters) and the browser proves transfer-without-reset on
// workshop equipment (no counter model there: the verified counters honestly become UNKNOWN).

test.describe.configure({ mode: 'serial' })
test.skip(() => test.info().project.name !== 'desktop', 'fake readings are per vehicle: desktop project only')

const V = 'VEH-1048'

async function carrierComponent(request: APIRequestContext): Promise<string> {
  const r = await request.get(`/api/v1/machine-state/current?asset_type=VEHICLE&asset_id=${V}`)
  expect(r.ok(), await r.text()).toBe(true)
  const readings = (await r.json()).readings as { component_id: string | null; counter_type: string }[]
  const engines = readings.filter((x) => x.counter_type === 'ENGINE_HOUR' && x.component_id)
  expect(engines.length).toBe(1) // single physical engine (CARRIER_ENGINE); PTO is PTO_HOUR
  return engines[0].component_id as string
}

async function meter(request: APIRequestContext, component: string, value: number): Promise<void> {
  const r = await request.post('/api/v1/test-support/part-meter-observations', {
    data: { vehicle_id: V, component_id: component, counter_type: 'ENGINE_HOUR', value },
    headers: { 'X-Request-Id': randomUUID() },
  })
  expect(r.ok(), await r.text()).toBe(true)
  expect((await r.json()).test_only).toBe(true)
}

async function repairId(request: APIRequestContext): Promise<string> {
  const r = await request.post('/api/v1/repairs', {
    data: { asset_type: 'VEHICLE', asset_id: V, source_type: 'MANUAL', symptom: 'ไดชาร์จเสีย (ทดสอบ)' },
  })
  expect(r.ok(), await r.text()).toBe(true)
  return (await r.json()).repair.repair_id as string
}

async function counterValue(page: Page, row: string): Promise<string> {
  return (await page.getByTestId(`counter-value-${row}`).first().innerText()).trim()
}

async function expectCounters(page: Page, lifetime: string, cycle: string): Promise<void> {
  await expect(page.getByTestId('counter-value-verified_lifetime_total').first()).toHaveText(lifetime)
  await expect(page.getByTestId('counter-value-verified_current_cycle').first()).toHaveText(cycle)
}

async function registerBrandNew(page: Page, request: APIRequestContext): Promise<string> {
  const evidence = await repairId(request)
  await page.goto('/parts/PART-0005/instances/new')
  await page.getByLabel('ป้ายระบุชิ้น (ถ้ามี)').fill(`R6-E2E-${randomUUID()}`)
  await page.getByLabel('ประวัติการใช้งานก่อนเริ่มติดตาม').selectOption('KNOWN')
  await page.getByLabel('ค่าที่ทราบ (เช่น ชั่วโมงใช้งานเดิม)').fill('0')
  await page.getByLabel('ประเภทหลักฐาน').selectOption('NEW_PART')
  await page.getByLabel('ค่า ณ วันที่').fill('2026-01-01')
  await page.getByLabel('เลขอ้างอิงหลักฐาน').fill(evidence)
  await page.getByRole('button', { name: 'ลงทะเบียนชิ้นงาน' }).click()
  await expect(page).toHaveURL(/\/part-instances\/PINST-/)
  return new URL(page.url()).pathname.split('/').pop() as string
}

async function installOnVehicle(page: Page, position: string): Promise<void> {
  await page.getByRole('button', { name: 'ติดตั้ง', exact: true }).click()
  const picker = page.getByLabel('ค้นหายานพาหนะ/อุปกรณ์')
  if (await picker.count()) {
    await picker.fill(V)
    await page.getByRole('button', { name: new RegExp(V) }).first().click()
  }
  await page.getByLabel('ตำแหน่งติดตั้ง (ถ้ามี)').fill(position)
  await page.getByRole('button', { name: 'ยืนยันการติดตั้ง' }).click()
  await expect(page.getByText('ติดตั้งใช้งานอยู่').first()).toBeVisible()
}

test('principal example: 3,200 h, approved repair, new cycle at install, then 8,200 / 5,000 DUE', async ({
  page,
  request,
}) => {
  const component = await carrierComponent(request)
  // A synthetic TEST REPLACE rule for this part on MODEL-0003 (not a real threshold).
  const rule = await request.post('/api/v1/lifetime-rules', {
    data: { part_id: 'PART-0005', scope: 'MODEL', model_id: 'MODEL-0003', trigger_type: 'ENGINE_HOUR',
      component_role: 'CARRIER_ENGINE', interval_value: 5000, interval_unit: 'HOUR', due_action: 'REPLACE',
      note: 'SYNTHETIC TEST RULE (R6 e2e) — not a real threshold' },
  })
  expect(rule.ok(), await rule.text()).toBe(true)

  const instanceId = await registerBrandNew(page, request)
  await meter(request, component, 10000)
  await installOnVehicle(page, `ALT-${randomUUID()}`)

  // 3,200 verified hours before the repair.
  await meter(request, component, 13200)
  await page.getByRole('button', { name: 'ถอดออก', exact: true }).click()
  await page.getByLabel('สถานะหลังถอดออก').selectOption('IN_REPAIR')
  await page.getByRole('button', { name: 'ยืนยันการถอดออก' }).click()
  await expect(page.getByText('อยู่ระหว่างซ่อม').first()).toBeVisible()
  await expectCounters(page, '3,200', '3,200')

  // While removed the vehicle keeps running: the part accrues nothing.
  await meter(request, component, 15000)
  await page.reload()
  await expectCounters(page, '3,200', '3,200')

  // A-2(i): no direct install from IN_REPAIR; the legacy new-cycle control is gone (A-2(ii)).
  await expect(page.getByRole('button', { name: 'ติดตั้ง', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /เริ่มรอบใหม่|Overhaul/ })).toHaveCount(0)

  // Qualifying approved return (TEST-labelled reason; PG-2 is not Owner-approved).
  await page.getByRole('button', { name: 'รับกลับจากซ่อม' }).click()
  await page.getByLabel('เลขที่ใบงานซ่อม (ถ้ามี)').fill(await repairId(request))
  await page.getByLabel(/อนุมัติให้เริ่มรอบการใช้งานใหม่เมื่อติดตั้ง/).check()
  await page.getByLabel(/รหัสเหตุผลการอนุมัติ/).fill('TEST-QUALIFYING-REPAIR')
  await page.getByRole('button', { name: 'ยืนยันรับกลับจากซ่อม' }).click()
  await expect(page.getByTestId('approval-state')).toHaveText(/รอเริ่มรอบใหม่เมื่อติดตั้ง/)
  // The approval alone opens nothing: still cycle 1.
  await expect(page.getByText(/รอบที่ \d/)).toHaveCount(1)

  // A successful install opens exactly one new cycle: lifetime stays 3,200, cycle starts at 0.
  await meter(request, component, 20000)
  await installOnVehicle(page, `ALT-${randomUUID()}`)
  await expect(page.getByText(/รอบที่ \d/)).toHaveCount(2)
  await expectCounters(page, '3,200', '0')

  // A further 5,000 verified hours: 8,200 / 5,000 and the synthetic REPLACE rule is DUE.
  await meter(request, component, 25000)
  await page.reload()
  await expectCounters(page, '8,200', '5,000')
  await expect(page.getByTestId('due-rule').filter({ hasText: 'เปลี่ยน' }).filter({ hasText: 'ถึงกำหนด' }).first())
    .toBeVisible()
  await expect(page.getByText(/ค่าทดสอบตามข้อเสนอ/).first()).toBeVisible()

  // The vehicle page shows the same engine's verdict for this instance.
  await page.goto(`/vehicle/${V}/parts`)
  const row = page.getByTestId('installed-instance').filter({ hasText: instanceId })
  await expect(row).toBeVisible()
  await expect(row.getByTestId('asset-status-summary').first()).toContainText('5,000')

  // Transfer without repair (to the mock's TEST-scoped workshop equipment EQP-0002 — R6 CG-1): no new cycle,
  // history kept.
  await page.goto(`/part-instances/${instanceId}`)
  await page.getByRole('button', { name: 'โยกย้ายไปยานพาหนะ/อุปกรณ์อื่น' }).click()
  await page.getByLabel('ประเภทสินทรัพย์ปลายทาง').selectOption('EQUIPMENT')
  await page.getByLabel('ค้นหายานพาหนะ/อุปกรณ์').fill('EQP-0002')
  await page.getByRole('button', { name: /EQP-0002/ }).first().click()
  await page.getByRole('button', { name: 'ยืนยันการโยกย้าย' }).click()
  await expect(page.getByText('สิ้นสุดการติดตั้งแล้ว').first()).toBeVisible()
  await expect(page.getByText(/รอบที่ \d/)).toHaveCount(2)
  // Equipment has no counter model: the vehicle-hour basis stays listed, but the verified counters
  // honestly become non-decisive (never a number, never 0, never reset).
  for (const key of ['verified_lifetime_total', 'verified_current_cycle']) {
    await expect(page.getByTestId(`counter-value-${key}`).first()).not.toHaveText(/^[\d,.]+$/)
  }
})

test('a used part with UNKNOWN prior usage shows tracked hours only, never a verified total', async ({
  page,
  request,
}) => {
  const component = await carrierComponent(request)
  await page.goto('/parts/PART-0005/instances/new')
  await page.getByLabel('ป้ายระบุชิ้น (ถ้ามี)').fill(`R6-E2E-USED-${randomUUID()}`)
  await page.getByLabel('ประวัติการใช้งานก่อนเริ่มติดตาม').selectOption('UNKNOWN')
  await page.getByRole('button', { name: 'ลงทะเบียนชิ้นงาน' }).click()
  await expect(page).toHaveURL(/\/part-instances\/PINST-/)
  await meter(request, component, 40000)
  await installOnVehicle(page, `USED-${randomUUID()}`)
  await meter(request, component, 41000)
  await page.reload()
  expect(await counterValue(page, 'tracked_since_enrollment')).toBe('1,000')
  expect(await counterValue(page, 'verified_lifetime_total')).toBe('ไม่ทราบ')
  expect(await counterValue(page, 'verified_current_cycle')).toBe('ไม่ทราบ')
})

test('a seal hosted in a cylinder follows the cylinder; replacing the seal never resets the cylinder', async ({
  page,
  request,
}) => {
  const component = await carrierComponent(request)
  const cylinder = await request.post('/api/v1/part-instances', {
    data: { part_id: 'PART-0005', tag_label: `R6-CYL-${randomUUID()}`, prior_usage: { quality: 'UNKNOWN' } },
    headers: { 'X-Request-Id': randomUUID() },
  })
  expect(cylinder.ok(), await cylinder.text()).toBe(true)
  const cylinderId = (await cylinder.json()).instance.part_instance_id as string
  await meter(request, component, 50000)
  const position = `BOOM-${randomUUID()}`
  const installed = await request.post(`/api/v1/part-instances/${cylinderId}/install`, {
    data: { asset_type: 'VEHICLE', asset_id: V, position_code: position },
    headers: { 'X-Request-Id': randomUUID() },
  })
  expect(installed.ok(), await installed.text()).toBe(true)
  const seal = await request.post('/api/v1/position-lifetime', {
    data: { host_part_instance_id: cylinderId, position_code: 'ROD-SEAL', part_id: 'PART-0004',
      prior_usage: { quality: 'UNKNOWN' } },
    headers: { 'X-Request-Id': randomUUID() },
  })
  expect(seal.ok(), await seal.text()).toBe(true)
  await meter(request, component, 50040)

  await page.goto(`/vehicle/${V}/parts`)
  const row = page.getByTestId('installed-instance').filter({ hasText: cylinderId })
  await expect(row.getByTestId('hosted-position')).toContainText('ROD-SEAL')

  const replaced = await request.post(`/api/v1/position-lifetime/${(await seal.json()).position_lifetime_id}/replace`, {
    data: { reason: 'ซีลรั่ว (ทดสอบ)', prior_usage: { quality: 'UNKNOWN' } },
    headers: { 'X-Request-Id': randomUUID() },
  })
  expect(replaced.ok(), await replaced.text()).toBe(true)
  await page.reload()
  await expect(page.getByTestId('installed-instance').filter({ hasText: cylinderId }).getByTestId('hosted-position'))
    .toHaveCount(1)
  await page.goto(`/part-instances/${cylinderId}`)
  await expect(page.getByText(/รอบที่ \d/)).toHaveCount(1)
  expect(await counterValue(page, 'tracked_since_enrollment')).toBe('40')
})
