import { expect, test, type Page, type Route } from '@playwright/test'

// Phase 7 Batch 7G2 — vehicle search validation and asset picker hardening.
//
// Tests marked [mocked] are SYNTHETIC browser tests: every /api/v1 call is
// intercepted with page.route() and answered with controlled SYN-* data,
// because vehicle-master data-quality failures and out-of-order responses
// cannot be produced from the shared mock seed without editing it. They
// exercise the real pages/CSS in every configured viewport, not the
// backend. The picker tests use the real containing page (part instance
// detail) and never submit an install or transfer. The final [real mock
// backend] test is unmocked and runs against the mock backend started by
// playwright.config.ts.

const SEARCH_LABEL = 'ค้นหา (เลขเครื่องจักร หรือ รหัสยานพาหนะ)'
const PICKER_LABEL = 'ค้นหายานพาหนะ/อุปกรณ์'
const TS = '2026-01-15T08:00:00Z'

function syntheticVehicle(id: string, machineNo: string, status = 'READY') {
  return {
    vehicle_id: id,
    machine_no: machineNo,
    model_id: 'SYN-MODEL-001',
    serial_number: null,
    operational_status: status,
    created_at: TS,
    updated_at: TS,
  }
}

function pageOf<T>(items: T[], pageSize = 10) {
  return { items, page: 1, page_size: pageSize, total_items: items.length }
}

function errorBody(code: string, details: unknown = null) {
  return { error: { code, message: 'synthetic failure', details, request_id: `req-${code}` } }
}

const fulfill = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })

interface Recorded {
  method: string
  path: string
  search: string
}

/** Records every /api request; anything not routed explicitly gets 404. */
async function recordApi(page: Page) {
  const requests: Recorded[] = []
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (url.pathname.startsWith('/api/')) {
      requests.push({ method: request.method(), path: url.pathname, search: url.search })
    }
  })
  await page.route(/\/api\/v1\//, (route) => fulfill(route, errorBody('NOT_FOUND'), 404))
  return requests
}

async function expectNoHorizontalOverflow(page: Page) {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1)
}

// ---------------------------------------------------------------------------
// Vehicle list: list-specific wording for the validated list's errors
// ---------------------------------------------------------------------------

async function mockListSupport(page: Page) {
  await page.route(/\/api\/v1\/models(\?|$)/, (route) => fulfill(route, pageOf([], 200)))
  await page.route(/\/api\/v1\/repairs(\?|$)/, (route) => fulfill(route, pageOf([], 200)))
  await page.route(/\/api\/v1\/pm\/work-orders(\?|$)/, (route) => fulfill(route, pageOf([], 200)))
  await page.route(/\/api\/v1\/findings(\?|$)/, (route) => fulfill(route, []))
}

const LIST_ERROR_CASES = [
  {
    code: 'VEHICLE_MASTER_DATA_INVALID',
    status: 500,
    details: { issue_counts: { BLANK_STATUS: 1 } },
    title: 'ไม่แสดงรายการยานพาหนะ',
    message: /ระบบจึงไม่แสดงรายการ เพื่อไม่ให้ผลการค้นหาคลาดเคลื่อน/,
  },
  {
    code: 'VEHICLE_MASTER_SCHEMA_INVALID',
    status: 500,
    details: { tab: 'vehicle_master', problem: 'MISSING_HEADERS', headers: ['operational_status'] },
    title: 'ไม่แสดงรายการยานพาหนะ',
    message: /โครงสร้างตารางทะเบียนรถไม่ตรงกับที่ระบบรองรับ ระบบจึงไม่แสดงรายการ/,
  },
  {
    code: 'VEHICLE_MASTER_READ_FAILED',
    status: 503,
    details: null,
    title: 'โหลดรายการยานพาหนะไม่สำเร็จ',
    message: /ไม่สามารถอ่านข้อมูลทะเบียนรถได้ในขณะนี้/,
  },
]

for (const c of LIST_ERROR_CASES) {
  test(`[mocked] vehicle list shows list wording for ${c.code} and recovers on retry`, async ({ page }) => {
    const requests = await recordApi(page)
    await mockListSupport(page)
    let fail = true
    await page.route(/\/api\/v1\/vehicles(\?|$)/, (route) =>
      fail
        ? fulfill(route, errorBody(c.code, c.details), c.status)
        : fulfill(route, pageOf([syntheticVehicle('SYN-VEH-001', 'SYN-OK')], 50)),
    )
    await page.goto('/vehicles')
    await expect(page.getByText(c.title)).toBeVisible()

    await page.getByLabel(SEARCH_LABEL).fill('SYN')
    await page.getByRole('button', { name: 'ค้นหา', exact: true }).click()
    const alert = page.getByRole('alert')
    await expect(alert).toContainText(c.title)
    await expect(alert).toContainText(c.message)
    await expect(alert).toContainText(`รหัสอ้างอิง: req-${c.code}`)
    await expect(page.getByText(/ไม่แสดงตัวเลข/)).toHaveCount(0)
    await expect(page.getByText(/แสดงรายการที่/)).toHaveCount(0)
    await expectNoHorizontalOverflow(page)

    const listCalls = () => requests.filter((r) => r.path === '/api/v1/vehicles')
    const applied = listCalls().at(-1)?.search
    expect(new URLSearchParams(applied).get('q')).toBe('SYN')
    fail = false
    await page.getByRole('button', { name: 'ลองใหม่อีกครั้ง' }).click()
    await expect(page.getByText('SYN-OK')).toBeVisible()
    expect(listCalls().at(-1)?.search).toBe(applied)
    await expect(page.getByText(c.title)).toHaveCount(0)
    expect(requests.every((r) => r.method === 'GET')).toBe(true)
  })
}

// ---------------------------------------------------------------------------
// Asset picker on the part instance detail page (never submitted)
// ---------------------------------------------------------------------------

function instanceDetail(installed: boolean) {
  return {
    instance: {
      part_instance_id: 'SYN-PINST-1',
      part_id: 'SYN-PART-1',
      serial_number: null,
      status: installed ? 'INSTALLED' : 'READY_FOR_INSTALL',
      prior_usage: { quality: 'UNKNOWN', value: null, note: null },
      current_lifecycle_id: 'SYN-PLC-1',
      note: null,
      created_at: TS,
      updated_at: TS,
    },
    lifecycles: [
      {
        lifecycle_id: 'SYN-PLC-1',
        part_instance_id: 'SYN-PINST-1',
        cycle_number: 1,
        start_reason: 'ENROLLMENT',
        started_at: TS,
        started_by: 'dev-user',
        started_note: null,
        ended_at: null,
      },
    ],
    segments: installed
      ? [
          {
            segment_id: 'SYN-SEG-1',
            part_instance_id: 'SYN-PINST-1',
            lifecycle_id: 'SYN-PLC-1',
            asset_type: 'VEHICLE',
            asset_id: 'SYN-VEH-HOST',
            position_code: null,
            status: 'ACTIVE',
            installed_at: TS,
            installed_by: 'dev-user',
            baseline_meter_snapshot_id: null,
            install_note: null,
            removed_at: null,
            removed_by: null,
            removal_meter_snapshot_id: null,
            removal_reason: null,
          },
        ]
      : [],
  }
}

async function openPicker(page: Page, installed: boolean) {
  await page.route(/\/api\/v1\/part-instances\/SYN-PINST-1$/, (route) =>
    route.request().method() === 'GET'
      ? fulfill(route, instanceDetail(installed))
      : fulfill(route, errorBody('UNEXPECTED_WRITE'), 500),
  )
  await page.goto('/part-instances/SYN-PINST-1')
  if (installed) {
    await page.getByRole('button', { name: 'โยกย้ายไปยานพาหนะ/อุปกรณ์อื่น' }).click()
  } else {
    await page.getByRole('button', { name: 'ติดตั้ง', exact: true }).click()
  }
}

const optionButtons = (page: Page) => page.getByRole('button', { name: / — / })

test('[mocked] picker: a failed vehicle search hides earlier options, shows an error, and retry recovers', async ({
  page,
}) => {
  const requests = await recordApi(page)
  let failSearch = true
  await page.route(/\/api\/v1\/vehicles(\?|$)/, (route) => {
    const q = new URL(route.request().url()).searchParams.get('q')
    if (q === 'SYN-FAIL' && failSearch) {
      return fulfill(route, errorBody('VEHICLE_MASTER_DATA_INVALID', { issue_counts: { BLANK_STATUS: 1 } }), 500)
    }
    if (q === 'SYN-FAIL') return fulfill(route, pageOf([syntheticVehicle('SYN-VEH-009', 'SYN-RECOVERED')]))
    return fulfill(route, pageOf([syntheticVehicle('SYN-VEH-001', 'SYN-001'), syntheticVehicle('SYN-VEH-002', 'SYN-002')]))
  })
  await openPicker(page, false)
  await expect(page.getByRole('button', { name: 'SYN-VEH-001 — SYN-001' })).toBeVisible()

  await page.getByLabel(PICKER_LABEL).fill('SYN-FAIL')
  // Hidden at once — before the 300 ms debounce, let alone the response.
  await expect(optionButtons(page)).toHaveCount(0, { timeout: 250 })
  await expect(page.getByText('ค้นหายานพาหนะไม่สำเร็จ จึงไม่แสดงรายการให้เลือก')).toBeVisible()
  await expect(optionButtons(page)).toHaveCount(0)
  await expectNoHorizontalOverflow(page)

  failSearch = false
  const failedQueries = () => requests.filter((r) => r.path === '/api/v1/vehicles' && r.search.includes('q=SYN-FAIL'))
  expect(failedQueries()).toHaveLength(1)
  await page.getByRole('button', { name: 'ลองค้นหาอีกครั้ง' }).click()
  await expect(page.getByRole('button', { name: 'SYN-VEH-009 — SYN-RECOVERED' })).toBeVisible()
  await page.waitForTimeout(600)
  expect(failedQueries()).toHaveLength(2) // exactly one retry request, no automatic retry

  // Selecting keeps the original id; nothing is submitted.
  await page.getByRole('button', { name: 'SYN-VEH-009 — SYN-RECOVERED' }).click()
  await expect(page.getByText('เลือกแล้ว: SYN-VEH-009')).toBeVisible()
  expect(requests.every((r) => r.method === 'GET')).toBe(true)
  expect(requests.some((r) => /install|transfer/.test(r.path))).toBe(false)
})

test('[mocked] picker: a slow older response never replaces the newer result', async ({ page }) => {
  const requests = await recordApi(page)
  await page.route(/\/api\/v1\/vehicles(\?|$)/, async (route) => {
    const q = new URL(route.request().url()).searchParams.get('q')
    if (q === 'SYN-SLOW') {
      await new Promise((resolve) => setTimeout(resolve, 1500))
      return fulfill(route, pageOf([syntheticVehicle('SYN-VEH-OLD', 'SYN-SLOW-RESULT')]))
    }
    if (q === 'SYN-FAST') return fulfill(route, pageOf([syntheticVehicle('SYN-VEH-NEW', 'SYN-FAST-RESULT')]))
    return fulfill(route, pageOf([]))
  })
  await openPicker(page, false)
  await expect(page.getByText('ไม่พบยานพาหนะที่ตรงกับคำค้น')).toBeVisible()

  const slowResponse = page.waitForResponse((r) => r.url().includes('q=SYN-SLOW'))
  await page.getByLabel(PICKER_LABEL).fill('SYN-SLOW')
  await page.waitForRequest((r) => r.url().includes('q=SYN-SLOW'))
  await page.getByLabel(PICKER_LABEL).fill('SYN-FAST')
  await expect(page.getByRole('button', { name: 'SYN-VEH-NEW — SYN-FAST-RESULT' })).toBeVisible()
  await slowResponse
  await page.waitForTimeout(100)
  await expect(page.getByRole('button', { name: 'SYN-VEH-OLD — SYN-SLOW-RESULT' })).toHaveCount(0)
  await expect(optionButtons(page)).toHaveCount(1)
  expect(requests.every((r) => r.method === 'GET')).toBe(true)
})

test('[mocked] picker (transfer, equipment): type switch hides vehicle options; equipment failure and retry', async ({
  page,
}) => {
  const requests = await recordApi(page)
  let failEquipment = true
  await page.route(/\/api\/v1\/vehicles(\?|$)/, (route) =>
    fulfill(route, pageOf([syntheticVehicle('SYN-VEH-001', 'SYN-001')])),
  )
  await page.route(/\/api\/v1\/equipment(\?|$)/, (route) =>
    failEquipment
      ? fulfill(route, errorBody('INTERNAL_ERROR'), 500)
      : fulfill(route, pageOf([{ equipment_id: 'SYN-EQP-001', name: 'Sling' }])),
  )
  await openPicker(page, true)
  await expect(page.getByRole('button', { name: 'SYN-VEH-001 — SYN-001' })).toBeVisible()

  await page.getByLabel('ประเภทสินทรัพย์ปลายทาง').selectOption('EQUIPMENT')
  await expect(page.getByRole('button', { name: 'SYN-VEH-001 — SYN-001' })).toHaveCount(0, { timeout: 250 })
  await expect(page.getByText('ค้นหาเครื่องมือ/อุปกรณ์ไม่สำเร็จ จึงไม่แสดงรายการให้เลือก')).toBeVisible()
  await expect(optionButtons(page)).toHaveCount(0)

  failEquipment = false
  await page.getByRole('button', { name: 'ลองค้นหาอีกครั้ง' }).click()
  await expect(page.getByRole('button', { name: 'SYN-EQP-001 — Sling' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'SYN-VEH-001 — SYN-001' })).toHaveCount(0)
  await expectNoHorizontalOverflow(page)
  expect(requests.every((r) => r.method === 'GET')).toBe(true)
  expect(requests.filter((r) => r.path === '/api/v1/equipment')).toHaveLength(2)
})

test('[mocked] picker: returning to an earlier query does not revive its old options', async ({ page }) => {
  const requests = await recordApi(page)
  let served = 0
  await page.route(/\/api\/v1\/vehicles(\?|$)/, (route) => {
    served += 1
    const q = new URL(route.request().url()).searchParams.get('q') ?? ''
    // Every response is labelled with its request number, so an old
    // result can be told apart from a fresh one for the same query.
    return fulfill(route, pageOf([syntheticVehicle(`SYN-VEH-${q || 'ALL'}`, `R${served}`)]))
  })
  await openPicker(page, false)
  const picker = page.getByLabel(PICKER_LABEL)
  await picker.fill('SYN-A')
  await expect(page.getByRole('button', { name: /^SYN-VEH-SYN-A — R\d+$/ })).toBeVisible()
  const oldLabel = (await page.getByRole('button', { name: /^SYN-VEH-SYN-A — / }).textContent()) ?? ''
  const before = served

  await picker.fill('SYN-B')
  await picker.fill('SYN-A') // back before the 300 ms debounce fires
  await expect(page.getByRole('button', { name: oldLabel, exact: true })).toHaveCount(0, { timeout: 250 })
  await expect(optionButtons(page)).toHaveCount(0, { timeout: 250 })
  const fresh = page.getByRole('button', { name: /^SYN-VEH-SYN-A — R\d+$/ })
  await expect(fresh).toBeVisible()
  expect(await fresh.textContent()).not.toBe(oldLabel)
  expect(served).toBe(before + 1) // exactly one fresh request for SYN-A
  await expect(optionButtons(page)).toHaveCount(1)
  expect(requests.every((r) => r.method === 'GET')).toBe(true)
})

// ---------------------------------------------------------------------------
// Unmocked smoke against the real mock backend
// ---------------------------------------------------------------------------

test('[real mock backend] vehicle search still lists and filters the seed vehicles', async ({ page }) => {
  await page.goto('/vehicles')
  for (const id of ['VEH-1046', 'VEH-1047', 'VEH-1048']) {
    await expect(page.getByRole('link', { name: id })).toBeVisible()
  }
  await page.getByLabel(SEARCH_LABEL).fill('TC-12')
  await page.getByRole('button', { name: 'ค้นหา', exact: true }).click()
  await expect(page.getByRole('link', { name: 'VEH-1046' })).toBeVisible()
  await expect(page.getByText('แสดงรายการที่ 1–1 จาก 1 คันที่ตรงกับเงื่อนไข')).toBeVisible()
  await expect(page.getByText('ไม่แสดงรายการยานพาหนะ')).toHaveCount(0)
})
