import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BrowserRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { VehicleListPage } from './VehicleListPage'

// All fixtures below are synthetic test data (SYN-* identifiers), not
// company fleet data.

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function errorResponse() {
  return jsonResponse(
    { error: { code: 'INTERNAL_ERROR', message: 'boom', request_id: 'req-test' } },
    500,
  )
}

interface SyntheticVehicle {
  vehicle_id: string
  machine_no: string
  model_id: string
  serial_number: string | null
  operational_status: string
  created_at: string
  updated_at: string
}

function syntheticVehicle(n: number, overrides: Partial<SyntheticVehicle> = {}): SyntheticVehicle {
  const id = String(n).padStart(3, '0')
  return {
    vehicle_id: `SYN-VEH-${id}`,
    machine_no: `SYN-${id}`,
    model_id: 'SYN-MODEL-001',
    serial_number: null,
    operational_status: 'WORKING',
    created_at: '2026-01-15T08:00:00Z',
    updated_at: '2026-01-15T08:00:00Z',
    ...overrides,
  }
}

function syntheticModel(n: number) {
  const id = String(n).padStart(3, '0')
  return {
    model_id: `SYN-MODEL-${id}`,
    model_code: `SYN${id}`,
    model_name: `รุ่นทดสอบ ${id}`,
    brand: 'Synthetic',
    description: null,
    component_roles: ['CARRIER_ENGINE'],
    created_at: '2026-01-15T08:00:00Z',
    updated_at: '2026-01-15T08:00:00Z',
  }
}

function paginate<T>(items: T[], url: URL, defaultSize = 20) {
  const page = Number(url.searchParams.get('page') ?? '1')
  const pageSize = Number(url.searchParams.get('page_size') ?? String(defaultSize))
  const start = (page - 1) * pageSize
  return { items: items.slice(start, start + pageSize), page, page_size: pageSize, total_items: items.length }
}

type Handler = (url: URL) => Response | Promise<Response>

interface ApiOptions {
  vehicles?: SyntheticVehicle[]
  models?: ReturnType<typeof syntheticModel>[]
  vehiclesHandler?: Handler
  modelsHandler?: Handler
  repairsHandler?: Handler
  pmHandler?: Handler
  findingsHandler?: Handler
}

function installApi(options: ApiOptions = {}) {
  const vehicles = options.vehicles ?? [syntheticVehicle(1)]
  const models = options.models ?? [syntheticModel(1)]
  const calls: { url: URL; method: string }[] = []

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost')
    calls.push({ url, method: (init?.method ?? 'GET').toUpperCase() })
    const path = url.pathname

    if (path === '/api/v1/vehicles') {
      if (options.vehiclesHandler) return options.vehiclesHandler(url)
      const q = (url.searchParams.get('q') ?? '').toLowerCase()
      const status = url.searchParams.get('status')
      const modelId = url.searchParams.get('model_id')
      const filtered = vehicles.filter(
        (v) =>
          (!q || v.machine_no.toLowerCase().includes(q) || v.vehicle_id.toLowerCase().includes(q)) &&
          (!status || v.operational_status === status) &&
          (!modelId || v.model_id === modelId),
      )
      return jsonResponse(paginate(filtered, url))
    }
    if (path === '/api/v1/models') {
      if (options.modelsHandler) return options.modelsHandler(url)
      return jsonResponse(paginate(models, url))
    }
    if (path === '/api/v1/repairs') {
      if (options.repairsHandler) return options.repairsHandler(url)
      return jsonResponse({ items: [], page: 1, page_size: 200, total_items: 0 })
    }
    if (path === '/api/v1/pm/work-orders') {
      if (options.pmHandler) return options.pmHandler(url)
      return jsonResponse({ items: [], page: 1, page_size: 200, total_items: 0 })
    }
    if (path === '/api/v1/findings') {
      if (options.findingsHandler) return options.findingsHandler(url)
      return jsonResponse([])
    }
    throw new Error(`Unexpected fetch: ${url.toString()}`)
  })
  vi.stubGlobal('fetch', fetchMock)

  const callsTo = (path: string) => calls.filter((c) => c.url.pathname === path)
  return { calls, callsTo }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function renderPage() {
  return render(
    <BrowserRouter>
      <VehicleListPage />
    </BrowserRouter>,
  )
}

const ZERO_TEXT = 'ไม่พบงานซ่อม/ใบงาน PM ที่เปิด หรือข้อบกพร่องที่ค้าง'

function repairItem(assetId: string, n: number) {
  return { repair_id: `SYN-REP-${n}`, asset_type: 'VEHICLE', asset_id: assetId, status: 'OPEN' }
}

describe('VehicleListPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders the vehicle list with Thai labels and a link to the detail page', async () => {
    installApi({
      vehicles: [
        syntheticVehicle(1, { vehicle_id: 'VEH-1046', machine_no: 'TC-12', model_id: 'MODEL-0001' }),
      ],
      models: [{ ...syntheticModel(1), model_id: 'MODEL-0001', model_name: 'Zoomlion QY50' }],
    })
    renderPage()

    await waitFor(() => expect(screen.getByText('TC-12')).toBeInTheDocument())
    expect(screen.getAllByText('Zoomlion QY50').length).toBeGreaterThan(0)
    expect(screen.getAllByText('ใช้งานอยู่').length).toBeGreaterThan(0)
    expect(screen.getByRole('link', { name: 'VEH-1046' })).toHaveAttribute(
      'href',
      '/vehicle/VEH-1046',
    )
    // Changed expectation (Phase 7 Batch 7A): the old global "ไม่มีงานค้าง"
    // over-claimed — these three reads do not establish PM due, lifetime,
    // certificate expiry or offline status. When all three categories
    // load completely with zero rows, the zero text names exactly those
    // queried categories.
    await waitFor(() => expect(screen.getByText(ZERO_TEXT)).toBeInTheDocument())
    expect(screen.queryByText('ไม่มีงานค้าง')).not.toBeInTheDocument()
    expect(screen.getByText(/ไม่ได้บอกกำหนด PM/)).toBeInTheDocument()
  })

  it('composes search, status and model filters and resets to page 1', async () => {
    const vehicles = Array.from({ length: 120 }, (_, i) =>
      syntheticVehicle(i + 1, {
        operational_status: i % 2 === 0 ? 'WORKING' : 'READY',
        model_id: i % 3 === 0 ? 'SYN-MODEL-002' : 'SYN-MODEL-001',
      }),
    )
    const api = installApi({ vehicles, models: [syntheticModel(1), syntheticModel(2)] })
    const user = userEvent.setup()
    renderPage()

    await screen.findByText('แสดงรายการที่ 1–50 จาก 120 คันที่ตรงกับเงื่อนไข')
    await user.click(screen.getByRole('button', { name: 'ถัดไป' }))
    await screen.findByText('แสดงรายการที่ 51–100 จาก 120 คันที่ตรงกับเงื่อนไข')

    await user.type(screen.getByLabelText('ค้นหา (เลขเครื่องจักร หรือ รหัสยานพาหนะ)'), 'SYN-0')
    await user.click(screen.getByRole('button', { name: 'ค้นหา' }))
    await user.selectOptions(screen.getByLabelText('สถานะ'), 'WORKING')
    await user.selectOptions(screen.getByLabelText('รุ่น'), 'SYN-MODEL-002')

    await waitFor(() => {
      const last = api.callsTo('/api/v1/vehicles').at(-1)!.url.searchParams
      expect(last.get('q')).toBe('SYN-0')
      expect(last.get('status')).toBe('WORKING')
      expect(last.get('model_id')).toBe('SYN-MODEL-002')
      expect(last.get('page')).toBe('1')
      expect(last.get('page_size')).toBe('50')
    })
    // SYN-001..SYN-099 with i%2==0 and i%3==0 -> i%6==0 among i=0..98 -> 17 vehicles.
    await screen.findByText('แสดงรายการที่ 1–17 จาก 17 คันที่ตรงกับเงื่อนไข')
    expect(
      screen.getByText('เงื่อนไขที่ใช้: คำค้น “SYN-0” · สถานะ ใช้งานอยู่ · รุ่น รุ่นทดสอบ 002'),
    ).toBeInTheDocument()

    // Clearing produces a defined, unfiltered state on page 1.
    await user.click(screen.getByRole('button', { name: 'ล้างตัวกรอง' }))
    await screen.findByText('แสดงรายการที่ 1–50 จาก 120 คันที่ตรงกับเงื่อนไข')
    expect(
      screen.getByText('เงื่อนไขที่ใช้: ไม่มีตัวกรอง (แสดงรถทุกคันในรายการ)'),
    ).toBeInTheDocument()
    expect(screen.getByLabelText('ค้นหา (เลขเครื่องจักร หรือ รหัสยานพาหนะ)')).toHaveValue('')
    const last = api.callsTo('/api/v1/vehicles').at(-1)!.url.searchParams
    expect(last.has('q') || last.has('status') || last.has('model_id')).toBe(false)
    expect(api.calls.every((c) => c.method === 'GET')).toBe(true)
  })

  it('paginates more than 50 vehicles while preserving filters and stable links', async () => {
    const vehicles = Array.from({ length: 120 }, (_, i) =>
      syntheticVehicle(i + 1, { operational_status: i < 110 ? 'WORKING' : 'READY' }),
    )
    const api = installApi({ vehicles })
    const user = userEvent.setup()
    renderPage()

    await user.selectOptions(await screen.findByLabelText('สถานะ'), 'WORKING')
    await screen.findByText('แสดงรายการที่ 1–50 จาก 110 คันที่ตรงกับเงื่อนไข')
    expect(screen.getByRole('button', { name: 'ก่อนหน้า' })).toBeDisabled()
    expect(screen.getByText('หน้า 1 จาก 3')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'ถัดไป' }))
    await screen.findByText('แสดงรายการที่ 51–100 จาก 110 คันที่ตรงกับเงื่อนไข')
    expect(screen.getByRole('link', { name: 'SYN-VEH-051' })).toHaveAttribute(
      'href',
      '/vehicle/SYN-VEH-051',
    )
    const page2 = api.callsTo('/api/v1/vehicles').at(-1)!.url.searchParams
    expect(page2.get('page')).toBe('2')
    expect(page2.get('status')).toBe('WORKING')

    await user.click(screen.getByRole('button', { name: 'ถัดไป' }))
    await screen.findByText('แสดงรายการที่ 101–110 จาก 110 คันที่ตรงกับเงื่อนไข')
    expect(screen.getByRole('button', { name: 'ถัดไป' })).toBeDisabled()
    expect(screen.getByText('หน้า 3 จาก 3')).toBeInTheDocument()
    // Never labelled as the total fleet.
    expect(screen.queryByText(/ทั้งหมดในกองรถ|รถทั้งหมด \d/)).not.toBeInTheDocument()
  })

  it('reaches model options beyond the first page and keeps the selected model', async () => {
    const models = Array.from({ length: 250 }, (_, i) => syntheticModel(i + 1))
    const vehicles = [
      syntheticVehicle(1, { model_id: 'SYN-MODEL-240' }),
      syntheticVehicle(2, { model_id: 'SYN-MODEL-001' }),
    ]
    const api = installApi({ vehicles, models })
    const user = userEvent.setup()
    renderPage()

    await screen.findByText('โหลดรายการรุ่นแล้ว 200 จาก 250 รุ่น')
    const modelSelect = screen.getByLabelText('รุ่น')
    expect(within(modelSelect).queryByRole('option', { name: 'รุ่นทดสอบ 240' })).toBeNull()
    // Before the page containing it is loaded, the row falls back to the stable ID.
    expect(screen.getByText('SYN-MODEL-240')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'โหลดรายการรุ่นเพิ่ม' }))
    await screen.findByText('โหลดรายการรุ่นแล้ว 250 จาก 250 รุ่น')
    expect(screen.queryByRole('button', { name: 'โหลดรายการรุ่นเพิ่ม' })).not.toBeInTheDocument()
    expect(api.callsTo('/api/v1/models').map((c) => c.url.searchParams.get('page'))).toEqual([
      '1',
      '2',
    ])

    await user.selectOptions(modelSelect, 'SYN-MODEL-240')
    await waitFor(() =>
      expect(api.callsTo('/api/v1/vehicles').at(-1)!.url.searchParams.get('model_id')).toBe(
        'SYN-MODEL-240',
      ),
    )
    await screen.findByText('แสดงรายการที่ 1–1 จาก 1 คันที่ตรงกับเงื่อนไข')
    expect(modelSelect).toHaveValue('SYN-MODEL-240')
    expect(screen.getAllByText('รุ่นทดสอบ 240').length).toBeGreaterThan(0)
  })

  it('shows a retryable model-list failure without blocking vehicle results', async () => {
    let failModels = true
    installApi({
      modelsHandler: (url) =>
        failModels ? errorResponse() : jsonResponse(paginate([syntheticModel(1)], url)),
    })
    const user = userEvent.setup()
    renderPage()

    await screen.findByText('โหลดรายการรุ่นไม่สำเร็จ ยังค้นหาด้วยเงื่อนไขอื่นได้')
    expect(await screen.findByRole('link', { name: 'SYN-VEH-001' })).toBeInTheDocument()
    // Model name unavailable -> stable model ID fallback.
    expect(screen.getByText('SYN-MODEL-001')).toBeInTheDocument()

    failModels = false
    await user.click(screen.getByRole('button', { name: 'ลองโหลดรายการรุ่นอีกครั้ง' }))
    await screen.findByText('โหลดรายการรุ่นแล้ว 1 จาก 1 รุ่น')
    expect(screen.getAllByText('รุ่นทดสอบ 001').length).toBeGreaterThan(0)
  })

  it('distinguishes a vehicle load failure from a genuinely empty result', async () => {
    let failVehicles = true
    installApi({
      vehicles: [],
      vehiclesHandler: (url) =>
        failVehicles ? errorResponse() : jsonResponse(paginate([] as SyntheticVehicle[], url)),
    })
    const user = userEvent.setup()
    renderPage()

    await screen.findByText('โหลดรายการยานพาหนะไม่สำเร็จ')
    expect(screen.queryByText('ไม่พบยานพาหนะ')).not.toBeInTheDocument()
    expect(screen.queryByText(ZERO_TEXT)).not.toBeInTheDocument()

    failVehicles = false
    await user.click(screen.getByRole('button', { name: 'ลองใหม่อีกครั้ง' }))
    await screen.findByText('ไม่พบยานพาหนะ')
    expect(screen.queryByText('โหลดรายการยานพาหนะไม่สำเร็จ')).not.toBeInTheDocument()
  })

  it('never turns a failed indicator category into zero, and retry recovers', async () => {
    let failRepairs = true
    const api = installApi({
      repairsHandler: () =>
        failRepairs
          ? errorResponse()
          : jsonResponse({ items: [repairItem('SYN-VEH-001', 1)], page: 1, page_size: 200, total_items: 1 }),
      findingsHandler: () =>
        jsonResponse([{ finding_id: 'SYN-F-1', asset_type: 'VEHICLE', asset_id: 'SYN-VEH-001' }]),
    })
    const user = userEvent.setup()
    renderPage()

    await screen.findByText('ยังไม่ทราบจำนวน: งานซ่อมที่เปิด')
    expect(screen.getByText('งานซ่อมที่เปิด: โหลดข้อมูลไม่สำเร็จ')).toBeInTheDocument()
    expect(screen.queryByText(ZERO_TEXT)).not.toBeInTheDocument()
    expect(screen.queryByText('ไม่มีงานค้าง')).not.toBeInTheDocument()
    // The complete categories stay useful.
    expect(screen.getByRole('link', { name: 'ข้อบกพร่อง 1' })).toHaveAttribute(
      'href',
      '/vehicle/SYN-VEH-001/inspections',
    )
    expect(screen.getByText('ไม่พบใบงาน PM ที่เปิด')).toBeInTheDocument()

    failRepairs = false
    const vehicleCallsBefore = api.callsTo('/api/v1/vehicles').length
    await user.click(screen.getByRole('button', { name: 'ลองโหลดสรุปงานอีกครั้ง' }))
    expect(await screen.findByRole('link', { name: 'ซ่อม 1' })).toHaveAttribute(
      'href',
      '/vehicle/SYN-VEH-001/repairs',
    )
    expect(screen.queryByText(/ยังไม่ทราบจำนวน/)).not.toBeInTheDocument()
    // Retrying indicators keeps the vehicle results; it does not refetch them.
    expect(api.callsTo('/api/v1/vehicles').length).toBe(vehicleCallsBefore)
    expect(api.calls.every((c) => c.method === 'GET')).toBe(true)
  })

  it('does not show a falsely complete repair count when more than 200 open repairs exist', async () => {
    const truncatedRepairs = Array.from({ length: 200 }, (_, i) => repairItem('SYN-VEH-001', i))
    installApi({
      repairsHandler: () =>
        jsonResponse({ items: truncatedRepairs, page: 1, page_size: 200, total_items: 250 }),
      pmHandler: () =>
        jsonResponse({
          items: [{ pm_work_order_id: 'SYN-PM-1', asset_type: 'VEHICLE', asset_id: 'SYN-VEH-001' }],
          page: 1,
          page_size: 200,
          total_items: 1,
        }),
    })
    renderPage()

    await screen.findByText('ยังไม่ทราบจำนวน: งานซ่อมที่เปิด')
    expect(screen.queryByText(/^ซ่อม \d+$/)).not.toBeInTheDocument()
    expect(screen.getByText(/งานซ่อมที่เปิด: ข้อมูลยังไม่ครบ/)).toBeInTheDocument()
    // Truncation is not a failure, so no pointless retry is offered.
    expect(screen.queryByRole('button', { name: 'ลองโหลดสรุปงานอีกครั้ง' })).not.toBeInTheDocument()
    // Open PM work orders are shown as work orders, never as PM due/overdue.
    expect(screen.getByRole('link', { name: 'ใบงาน PM 1' })).toHaveAttribute(
      'href',
      '/vehicle/SYN-VEH-001/pm',
    )
    expect(screen.queryByText(/ถึงกำหนด|เกินกำหนด/)).not.toBeInTheDocument()
    expect(screen.queryByText(ZERO_TEXT)).not.toBeInTheDocument()
  })

  it('does not show a falsely complete PM count when more than 200 open PM work orders exist', async () => {
    const truncatedPm = Array.from({ length: 200 }, (_, i) => ({
      pm_work_order_id: `SYN-PM-${i}`,
      asset_type: 'VEHICLE',
      asset_id: 'SYN-VEH-001',
    }))
    installApi({
      vehicles: [syntheticVehicle(1), syntheticVehicle(2)],
      repairsHandler: () =>
        jsonResponse({ items: [repairItem('SYN-VEH-001', 1)], page: 1, page_size: 200, total_items: 1 }),
      pmHandler: () => jsonResponse({ items: truncatedPm, page: 1, page_size: 200, total_items: 250 }),
      findingsHandler: () =>
        jsonResponse([{ finding_id: 'SYN-F-1', asset_type: 'VEHICLE', asset_id: 'SYN-VEH-002' }]),
    })
    renderPage()

    await screen.findByText('ใบงาน PM ที่เปิด: ข้อมูลยังไม่ครบ (มีรายการมากกว่าที่โหลดได้ในครั้งเดียว) จึงไม่แสดงจำนวน')
    // Both rows mark PM as unknown; no exact PM badge or count is shown.
    expect(screen.getAllByText(/^ยังไม่ทราบจำนวน: ใบงาน PM ที่เปิด$/)).toHaveLength(2)
    expect(screen.queryByText(/^ใบงาน PM \d+$/)).not.toBeInTheDocument()
    expect(screen.queryByText(ZERO_TEXT)).not.toBeInTheDocument()
    expect(screen.queryByText(/ไม่พบ.*ใบงาน PM ที่เปิด/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'ลองโหลดสรุปงานอีกครั้ง' })).not.toBeInTheDocument()
    // The complete categories stay useful, including their complete zeros.
    expect(screen.getByRole('link', { name: 'ซ่อม 1' })).toHaveAttribute(
      'href',
      '/vehicle/SYN-VEH-001/repairs',
    )
    expect(screen.getByRole('link', { name: 'ข้อบกพร่อง 1' })).toHaveAttribute(
      'href',
      '/vehicle/SYN-VEH-002/inspections',
    )
    expect(screen.getByText('ไม่พบข้อบกพร่องที่ค้าง')).toBeInTheDocument()
    expect(screen.getByText('ไม่พบงานซ่อมที่เปิด')).toBeInTheDocument()
  })

  it('never turns a failed findings request into zero, and retry recovers findings', async () => {
    let failFindings = true
    const api = installApi({
      vehicles: [syntheticVehicle(1), syntheticVehicle(2)],
      repairsHandler: () =>
        jsonResponse({ items: [repairItem('SYN-VEH-001', 1)], page: 1, page_size: 200, total_items: 1 }),
      pmHandler: () =>
        jsonResponse({
          items: [{ pm_work_order_id: 'SYN-PM-1', asset_type: 'VEHICLE', asset_id: 'SYN-VEH-002' }],
          page: 1,
          page_size: 200,
          total_items: 1,
        }),
      findingsHandler: () =>
        failFindings
          ? errorResponse()
          : jsonResponse([{ finding_id: 'SYN-F-1', asset_type: 'VEHICLE', asset_id: 'SYN-VEH-002' }]),
    })
    const user = userEvent.setup()
    renderPage()

    await screen.findByText('ข้อบกพร่องที่ค้าง: โหลดข้อมูลไม่สำเร็จ')
    expect(screen.getAllByText(/^ยังไม่ทราบจำนวน: ข้อบกพร่องที่ค้าง$/)).toHaveLength(2)
    expect(screen.queryByText(ZERO_TEXT)).not.toBeInTheDocument()
    expect(screen.queryByText(/ไม่พบ.*ข้อบกพร่องที่ค้าง/)).not.toBeInTheDocument()
    expect(screen.queryByText(/^ข้อบกพร่อง \d+$/)).not.toBeInTheDocument()
    // Repair and PM loaded completely and stay useful.
    expect(screen.getByRole('link', { name: 'ซ่อม 1' })).toHaveAttribute(
      'href',
      '/vehicle/SYN-VEH-001/repairs',
    )
    expect(screen.getByRole('link', { name: 'ใบงาน PM 1' })).toHaveAttribute(
      'href',
      '/vehicle/SYN-VEH-002/pm',
    )

    failFindings = false
    const vehicleCallsBefore = api.callsTo('/api/v1/vehicles').length
    await user.click(screen.getByRole('button', { name: 'ลองโหลดสรุปงานอีกครั้ง' }))
    expect(await screen.findByRole('link', { name: 'ข้อบกพร่อง 1' })).toHaveAttribute(
      'href',
      '/vehicle/SYN-VEH-002/inspections',
    )
    expect(screen.queryByText(/ยังไม่ทราบจำนวน/)).not.toBeInTheDocument()
    expect(screen.queryByText('ข้อบกพร่องที่ค้าง: โหลดข้อมูลไม่สำเร็จ')).not.toBeInTheDocument()
    expect(api.callsTo('/api/v1/vehicles').length).toBe(vehicleCallsBefore)
    expect(api.calls.every((c) => c.method === 'GET')).toBe(true)
  })

  it('ignores a slow obsolete vehicle response that arrives after a newer search', async () => {
    const slow = deferred<Response>()
    const api = installApi({
      vehiclesHandler: (url) => {
        const q = url.searchParams.get('q')
        if (q === 'OLD') return slow.promise
        if (q === 'NEW') {
          return jsonResponse({
            items: [syntheticVehicle(2, { machine_no: 'SYN-NEW' })],
            page: 1,
            page_size: 50,
            total_items: 1,
          })
        }
        return jsonResponse(paginate([syntheticVehicle(1)], url))
      },
    })
    const user = userEvent.setup()
    renderPage()
    await screen.findByRole('link', { name: 'SYN-VEH-001' })

    const input = screen.getByLabelText('ค้นหา (เลขเครื่องจักร หรือ รหัสยานพาหนะ)')
    await user.type(input, 'OLD')
    await user.click(screen.getByRole('button', { name: 'ค้นหา' }))
    await user.clear(input)
    await user.type(input, 'NEW')
    await user.click(screen.getByRole('button', { name: 'ค้นหา' }))
    await screen.findByText('SYN-NEW')

    await act(async () => {
      slow.resolve(errorResponse())
      await slow.promise
    })
    // Neither the stale error nor stale page metadata replaces the newer result.
    expect(screen.getByText('SYN-NEW')).toBeInTheDocument()
    expect(screen.queryByText('โหลดรายการยานพาหนะไม่สำเร็จ')).not.toBeInTheDocument()
    expect(screen.getByText('แสดงรายการที่ 1–1 จาก 1 คันที่ตรงกับเงื่อนไข')).toBeInTheDocument()
    expect(screen.getByText('เงื่อนไขที่ใช้: คำค้น “NEW”')).toBeInTheDocument()
    expect(api.calls.every((c) => c.method === 'GET')).toBe(true)
  })

  it('ignores a slow obsolete indicator response that arrives after a newer one', async () => {
    const slow = deferred<Response>()
    let repairCall = 0
    installApi({
      repairsHandler: () => {
        repairCall += 1
        if (repairCall === 1) return slow.promise
        return jsonResponse({ items: [repairItem('SYN-VEH-001', 1)], page: 1, page_size: 200, total_items: 1 })
      },
    })
    const user = userEvent.setup()
    renderPage()
    await screen.findByRole('link', { name: 'SYN-VEH-001' })

    await user.click(screen.getByRole('button', { name: 'ค้นหา' }))
    expect(await screen.findByRole('link', { name: 'ซ่อม 1' })).toBeInTheDocument()

    await act(async () => {
      slow.resolve(errorResponse())
      await slow.promise
    })
    expect(screen.getByRole('link', { name: 'ซ่อม 1' })).toBeInTheDocument()
    expect(screen.queryByText(/งานซ่อมที่เปิด: โหลดข้อมูลไม่สำเร็จ/)).not.toBeInTheDocument()
  })

  it('handles an out-of-range page without an impossible range or automatic retry', async () => {
    const api = installApi({
      vehiclesHandler: (url) => {
        const page = Number(url.searchParams.get('page'))
        if (page === 1) {
          return jsonResponse({
            items: Array.from({ length: 50 }, (_, i) => syntheticVehicle(i + 1)),
            page: 1,
            page_size: 50,
            total_items: 60,
          })
        }
        // Data shrank between requests: page 2 is now past the end.
        return jsonResponse({ items: [], page, page_size: 50, total_items: 40 })
      },
    })
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: 'ถัดไป' }))
    await screen.findByText('หน้านี้ไม่มีรายการแล้ว')
    expect(screen.queryByText(/แสดงรายการที่/)).not.toBeInTheDocument()
    const callsAfter = api.callsTo('/api/v1/vehicles').length
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(api.callsTo('/api/v1/vehicles').length).toBe(callsAfter)

    await user.click(screen.getByRole('button', { name: 'กลับไปหน้าแรก' }))
    await screen.findByText('แสดงรายการที่ 1–50 จาก 60 คันที่ตรงกับเงื่อนไข')
  })

  it('keeps the request count independent of the number of visible vehicles', async () => {
    const vehicles = Array.from({ length: 50 }, (_, i) => syntheticVehicle(i + 1))
    const api = installApi({ vehicles })
    renderPage()

    await screen.findByRole('link', { name: 'SYN-VEH-050' })
    await waitFor(() => expect(screen.getAllByText(ZERO_TEXT)).toHaveLength(50))
    // StrictMode is not used here, so exactly one call per endpoint.
    expect(api.calls.map((c) => c.url.pathname).sort()).toEqual([
      '/api/v1/findings',
      '/api/v1/models',
      '/api/v1/pm/work-orders',
      '/api/v1/repairs',
      '/api/v1/vehicles',
    ])
    expect(api.calls.some((c) => /\/vehicles\/SYN-VEH/.test(c.url.pathname))).toBe(false)
  })
})
