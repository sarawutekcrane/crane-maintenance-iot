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

const ZERO_TEXT = 'ไม่พบงานซ่อม/ใบงาน PM ที่เปิด หรือข้อบกพร่องที่บันทึกไว้'

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

    await user.type(screen.getByLabelText('ค้นหา (เลขเครื่องจักร รหัสยานพาหนะ หรือรุ่น)'), 'SYN-0')
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
    expect(screen.getByLabelText('ค้นหา (เลขเครื่องจักร รหัสยานพาหนะ หรือรุ่น)')).toHaveValue('')
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
    expect(screen.getByText('ไม่พบข้อบกพร่องที่บันทึกไว้')).toBeInTheDocument()
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

    await screen.findByText('ข้อบกพร่องที่บันทึกไว้: โหลดข้อมูลไม่สำเร็จ')
    expect(screen.getAllByText(/^ยังไม่ทราบจำนวน: ข้อบกพร่องที่บันทึกไว้$/)).toHaveLength(2)
    expect(screen.queryByText(ZERO_TEXT)).not.toBeInTheDocument()
    expect(screen.queryByText(/ไม่พบ.*ข้อบกพร่องที่บันทึกไว้/)).not.toBeInTheDocument()
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
    expect(screen.queryByText('ข้อบกพร่องที่บันทึกไว้: โหลดข้อมูลไม่สำเร็จ')).not.toBeInTheDocument()
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

    const input = screen.getByLabelText('ค้นหา (เลขเครื่องจักร รหัสยานพาหนะ หรือรุ่น)')
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

  // Web/API Phase 7 Batch 7G2 — list-specific wording for the validated
  // vehicle list's error codes (DEC-4); shared labels.ts wording unchanged.
  const DATA_INVALID_MESSAGE =
    'ข้อมูลทะเบียนรถบางรายการไม่ครบหรือไม่ถูกต้อง (เช่น ไม่ได้ระบุสถานะ สถานะไม่ถูกต้อง หรือรหัสรถซ้ำ) ระบบจึงไม่แสดงรายการ เพื่อไม่ให้ผลการค้นหาคลาดเคลื่อน กรุณาแจ้งผู้ดูแลข้อมูลให้ตรวจสอบทะเบียนรถ'
  const SCHEMA_INVALID_MESSAGE =
    'โครงสร้างตารางทะเบียนรถไม่ตรงกับที่ระบบรองรับ ระบบจึงไม่แสดงรายการ กรุณาติดต่อผู้ดูแลระบบ'
  const READ_FAILED_MESSAGE = 'ไม่สามารถอ่านข้อมูลทะเบียนรถได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง'

  function vehicleMasterError(code: string, status: number, details: unknown = null) {
    return jsonResponse({ error: { code, message: 'x', details, request_id: `req-${code}` } }, status)
  }

  const listErrorCases = [
    {
      code: 'VEHICLE_MASTER_DATA_INVALID',
      status: 500,
      details: { issue_counts: { BLANK_STATUS: 1 } },
      title: 'ไม่แสดงรายการยานพาหนะ',
      message: DATA_INVALID_MESSAGE,
    },
    {
      code: 'VEHICLE_MASTER_SCHEMA_INVALID',
      status: 500,
      details: { tab: 'vehicle_master', problem: 'MISSING_HEADERS', headers: ['operational_status'] },
      title: 'ไม่แสดงรายการยานพาหนะ',
      message: SCHEMA_INVALID_MESSAGE,
    },
    {
      code: 'VEHICLE_MASTER_READ_FAILED',
      status: 503,
      details: null,
      title: 'โหลดรายการยานพาหนะไม่สำเร็จ',
      message: READ_FAILED_MESSAGE,
    },
  ]

  for (const c of listErrorCases) {
    it(`shows list wording for ${c.code} and retries the applied request`, async () => {
      let fail = true
      const api = installApi({
        vehiclesHandler: (url) =>
          fail
            ? vehicleMasterError(c.code, c.status, c.details)
            : jsonResponse(paginate([syntheticVehicle(7, { machine_no: 'SYN-OK' })], url)),
      })
      const user = userEvent.setup()
      renderPage()
      await screen.findByText(c.title)

      // Apply a filter so the retry must repeat exactly the applied request.
      await user.type(screen.getByLabelText('ค้นหา (เลขเครื่องจักร รหัสยานพาหนะ หรือรุ่น)'), 'SYN')
      await user.selectOptions(screen.getByLabelText('สถานะ'), 'READY')
      const alert = await screen.findByRole('alert')
      expect(within(alert).getByText(c.title)).toBeInTheDocument()
      expect(within(alert).getByText(c.message)).toBeInTheDocument()
      expect(within(alert).getByText(`รหัสอ้างอิง: req-${c.code}`)).toBeInTheDocument()
      // Dashboard wording ("ไม่แสดงตัวเลข") never appears on the list page.
      expect(screen.queryByText(/ไม่แสดงตัวเลข/)).not.toBeInTheDocument()
      expect(screen.queryByText(/แสดงรายการที่/)).not.toBeInTheDocument()
      expect(screen.queryByText('ไม่พบยานพาหนะ')).not.toBeInTheDocument()
      expect(screen.queryByText(/สรุปงานนับเฉพาะงานซ่อม/)).not.toBeInTheDocument()
      if (c.title === 'ไม่แสดงรายการยานพาหนะ') {
        expect(screen.queryByText('โหลดรายการยานพาหนะไม่สำเร็จ')).not.toBeInTheDocument()
      }

      const before = api.callsTo('/api/v1/vehicles')
      const applied = before[before.length - 1].url.search
      fail = false
      await user.click(screen.getByRole('button', { name: 'ลองใหม่อีกครั้ง' }))
      await screen.findByText('SYN-OK')
      const after = api.callsTo('/api/v1/vehicles')
      expect(after).toHaveLength(before.length + 1)
      expect(after[after.length - 1].url.search).toBe(applied)
      expect(new URLSearchParams(applied).get('q')).toBe('SYN')
      expect(new URLSearchParams(applied).get('status')).toBe('READY')
      expect(screen.queryByText(c.title)).not.toBeInTheDocument()
      expect(api.calls.every((call) => call.method === 'GET')).toBe(true)
    })
  }

  it('keeps the generic title and message for other vehicle-list failures', async () => {
    installApi({ vehiclesHandler: () => errorResponse() })
    renderPage()
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByText('โหลดรายการยานพาหนะไม่สำเร็จ')).toBeInTheDocument()
    expect(screen.queryByText('ไม่แสดงรายการยานพาหนะ')).not.toBeInTheDocument()
  })

  it('ignores a slow obsolete data-quality error after a newer successful search', async () => {
    const slow = deferred<Response>()
    installApi({
      vehiclesHandler: (url) => {
        const q = url.searchParams.get('q')
        if (q === 'OLD') return slow.promise
        return jsonResponse(paginate([syntheticVehicle(3, { machine_no: q ? `SYN-${q}` : 'SYN-003' })], url))
      },
    })
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('SYN-003')
    const input = screen.getByLabelText('ค้นหา (เลขเครื่องจักร รหัสยานพาหนะ หรือรุ่น)')
    await user.type(input, 'OLD')
    await user.click(screen.getByRole('button', { name: 'ค้นหา' }))
    await user.clear(input)
    await user.type(input, 'NEW')
    await user.click(screen.getByRole('button', { name: 'ค้นหา' }))
    await screen.findByText('SYN-NEW')
    await act(async () => {
      slow.resolve(vehicleMasterError('VEHICLE_MASTER_DATA_INVALID', 500, { issue_counts: { BLANK_STATUS: 1 } }))
      await slow.promise
    })
    expect(screen.getByText('SYN-NEW')).toBeInTheDocument()
    expect(screen.queryByText('ไม่แสดงรายการยานพาหนะ')).not.toBeInTheDocument()
  })
})

// Phase 7 Batch 7M1 — vehicle-list link safety (reusing the unchanged 7D2
// isLinkableVehicleId rule) and recorded-findings wording. Synthetic ids only.
describe('VehicleListPage link safety and recorded-findings wording (7M1)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const SAFE_IDS = ['VEH-1046', '0012', 'a.b_c~d', '...', '.a']
  const UNSAFE_IDS = [
    'VEH/1', 'VEH?1', 'VEH#1', 'VEH%201', '%2E%2E', '.', '..', 'VEH 1', ' VEH-2', 'VEH-3\t', 'รถ-1', 'Café', '',
  ]
  const NO_LINK_NOTE = '(ไม่มีลิงก์: ใช้รหัสนี้เปิดหน้าข้อมูลรถไม่ได้ เพราะมีอักขระที่ยังรองรับไม่ได้)'
  const vehiclesFor = (ids: string[]) =>
    ids.map((id, i) => syntheticVehicle(i + 1, { vehicle_id: id, machine_no: `SYN-M-${i + 1}` }))

  function idTextCell(container: HTMLElement, id: string) {
    return Array.from(container.querySelectorAll('.vehicle-list__id-text')).find((el) => el.textContent === id)
  }

  it('links ids accepted by the shared rule verbatim, including leading zeros and dots', async () => {
    installApi({
      vehicles: vehiclesFor(SAFE_IDS),
      repairsHandler: () =>
        jsonResponse({ items: [repairItem('0012', 1)], page: 1, page_size: 200, total_items: 1 }),
      pmHandler: () =>
        jsonResponse({
          items: [{ pm_work_order_id: 'SYN-PM-1', asset_type: 'VEHICLE', asset_id: 'a.b_c~d' }],
          page: 1,
          page_size: 200,
          total_items: 1,
        }),
      findingsHandler: () => jsonResponse([{ finding_id: 'SYN-F-1', asset_type: 'VEHICLE', asset_id: '...' }]),
    })
    renderPage()
    await screen.findByRole('link', { name: 'ซ่อม 1' })
    for (const id of SAFE_IDS) {
      expect(screen.getByRole('link', { name: id })).toHaveAttribute('href', `/vehicle/${id}`)
    }
    expect(screen.getByRole('link', { name: 'ซ่อม 1' })).toHaveAttribute('href', '/vehicle/0012/repairs')
    expect(screen.getByRole('link', { name: 'ใบงาน PM 1' })).toHaveAttribute('href', '/vehicle/a.b_c~d/pm')
    expect(screen.getByRole('link', { name: 'ข้อบกพร่อง 1' })).toHaveAttribute('href', '/vehicle/.../inspections')
    expect(screen.queryByText(NO_LINK_NOTE)).not.toBeInTheDocument()
  })

  it('shows rejected ids exactly as stored, with a no-link note and no vehicle links of any kind', async () => {
    installApi({
      vehicles: vehiclesFor([...UNSAFE_IDS, 'VEH-OK']),
      repairsHandler: () =>
        jsonResponse({
          items: [repairItem('VEH/1', 1), repairItem('VEH/1', 2), repairItem('VEH-OK', 3)],
          page: 1,
          page_size: 200,
          total_items: 3,
        }),
      pmHandler: () =>
        jsonResponse({
          items: [{ pm_work_order_id: 'SYN-PM-1', asset_type: 'VEHICLE', asset_id: 'VEH%201' }],
          page: 1,
          page_size: 200,
          total_items: 1,
        }),
      findingsHandler: () => jsonResponse([{ finding_id: 'SYN-F-1', asset_type: 'VEHICLE', asset_id: 'รถ-1' }]),
    })
    const { container } = renderPage()
    await screen.findByRole('link', { name: 'VEH-OK' })
    await screen.findByText('ซ่อม 2')

    for (const id of UNSAFE_IDS) {
      const cell = idTextCell(container, id)
      expect(cell, `stored text for ${JSON.stringify(id)}`).toBeDefined()
      expect(cell!.closest('a')).toBeNull()
    }
    expect(screen.getAllByText(NO_LINK_NOTE)).toHaveLength(UNSAFE_IDS.length)

    // Indicator information is kept, but rendered without links.
    for (const text of ['ซ่อม 2', 'ใบงาน PM 1', 'ข้อบกพร่อง 1']) {
      const badge = screen.getByText(text)
      expect(badge.closest('a')).toBeNull()
      expect(badge).toHaveClass('vehicle-indicators__badge')
    }
    // The accepted id in the same list keeps its links.
    expect(screen.getByRole('link', { name: 'VEH-OK' })).toHaveAttribute('href', '/vehicle/VEH-OK')
    expect(screen.getByRole('link', { name: 'ซ่อม 1' })).toHaveAttribute('href', '/vehicle/VEH-OK/repairs')
    const vehicleHrefs = Array.from(container.querySelectorAll('a'))
      .map((a) => a.getAttribute('href') ?? '')
      .filter((href) => href.startsWith('/vehicle/'))
    expect(vehicleHrefs.sort()).toEqual(['/vehicle/VEH-OK', '/vehicle/VEH-OK/repairs'])
  })

  it('describes findings as recorded findings in counts, zero, failed and note text', async () => {
    let failFindings = false
    const api = installApi({
      vehicles: [syntheticVehicle(1), syntheticVehicle(2)],
      findingsHandler: () =>
        failFindings
          ? errorResponse()
          : jsonResponse([{ finding_id: 'SYN-F-1', asset_type: 'VEHICLE', asset_id: 'SYN-VEH-002' }]),
    })
    const user = userEvent.setup()
    const { container } = renderPage()
    expect(await screen.findByRole('link', { name: 'ข้อบกพร่อง 1' })).toHaveAttribute(
      'href',
      '/vehicle/SYN-VEH-002/inspections',
    )
    expect(screen.getByText('ไม่พบงานซ่อม/ใบงาน PM ที่เปิด หรือข้อบกพร่องที่บันทึกไว้')).toBeInTheDocument()
    expect(screen.getByText(/ข้อบกพร่องที่บันทึกไว้ไม่ได้บอกว่าแก้ไขแล้วหรือยัง/)).toBeInTheDocument()
    expect(screen.getByText(/การไม่พบรายการไม่ได้ยืนยันว่าไม่มีข้อบกพร่อง/)).toBeInTheDocument()
    expect(container.textContent).not.toContain('ข้อบกพร่องที่ค้าง')
    expect(api.callsTo('/api/v1/findings').map((c) => c.url.search)).toEqual(['?asset_type=VEHICLE&status=OPEN'])

    failFindings = true
    // A failed findings read stays unknown under the new wording, never zero.
    vi.unstubAllGlobals()
    installApi({
      vehicles: [syntheticVehicle(1), syntheticVehicle(2)],
      findingsHandler: () => errorResponse(),
    })
    await user.click(screen.getByRole('button', { name: 'ค้นหา' }))
    await screen.findByText('ข้อบกพร่องที่บันทึกไว้: โหลดข้อมูลไม่สำเร็จ')
    expect(screen.getAllByText(/^ยังไม่ทราบจำนวน: ข้อบกพร่องที่บันทึกไว้$/)).toHaveLength(2)
    // Zero claims start with "ไม่พบ"; the explanatory note does not.
    expect(screen.queryByText(/^ไม่พบ.*ข้อบกพร่อง/)).not.toBeInTheDocument()
    expect(container.textContent).not.toContain('ข้อบกพร่องที่ค้าง')
  })
})
