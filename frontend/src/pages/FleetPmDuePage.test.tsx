import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import type { PmDueSet, VehiclePmDue } from '../lib/types'
import { FleetPmDuePage, VehiclePmDuePage } from './FleetPmDuePage'

// R4 / TASK-010 Fleet PM Due B1 — synthetic payloads only (SYN-* ids). The page shows
// the backend read model as-is; these tests prove it never recalculates or overrides it.

const DUE_PATH = '/api/v1/pm/due/vehicles'

function set(overrides: Partial<PmDueSet> = {}): PmDueSet {
  return {
    plan_code: 'SYN PM Plan1',
    revision_number: 1,
    set_key: 'SYN-M1|CRANE|A',
    model_variant: 'SYN-M1',
    section: 'CRANE',
    set_code: 'A',
    meter_type: 'ENGINE_HOUR',
    interval_value: 600,
    interval_unit: 'HOUR',
    driving_component_role: 'CRANE_ENGINE',
    component_id: 'SYN-CMP-CRANE',
    status: 'NOT_DUE',
    explanation: 'ยังไม่ถึงกำหนด PM',
    diagnostic_code: null,
    next_due: 1250,
    last_completed_meter: 650,
    last_completed_at: '2026-11-01T02:15:00Z',
    last_completed_pm_work_order_id: 'SYN-PMWO-1',
    current_meter: 1249,
    current_observed_at: '2026-11-08T02:15:00Z',
    planned_team_minutes: null,
    ...overrides,
  }
}

function vehicle(id: string, overrides: Partial<VehiclePmDue> = {}): VehiclePmDue {
  return {
    vehicle_id: id,
    machine_no: `TC-${id}`,
    model_id: 'SYN-MODEL',
    state: 'AVAILABLE',
    explanation: 'แสดงกำหนด PM ตามแผนหลักที่กำหนดให้รถคันนี้',
    assignments: [
      { assembly: '', source: 'EXPLICIT_ASSIGNED', plan_code: 'SYN PM Plan1' },
      { assembly: 'CARRIER', source: 'EXPLICIT_ASSIGNED', plan_code: 'SYN PM Plan1' },
      { assembly: 'CRANE', source: 'EXPLICIT_NONE', plan_code: null },
    ],
    plans: [
      {
        plan_code: 'SYN PM Plan1',
        state: 'RESOLVED',
        revision_number: 1,
        model_variant: 'SYN-M1',
        explanation: 'ชุดงานตามแผนฉบับปัจจุบัน',
      },
    ],
    sets: [set()],
    ...overrides,
  }
}

const NOT_ACTIVE: Partial<VehiclePmDue> = {
  state: 'MASTER_NOT_ACTIVE',
  explanation: 'ระบบแผน PM หลัก (PM Master) ยังไม่เปิดใช้งาน จึงยังคำนวณกำหนด PM ไม่ได้ (ไม่ได้หมายความว่าไม่มี PM ถึงกำหนด)',
  assignments: [],
  plans: [],
  sets: [],
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function page(items: VehiclePmDue[], total = items.length, pageNumber = 1) {
  return json({ items, page: pageNumber, page_size: 20, total_items: total })
}

interface Call {
  path: string
  params: Record<string, string>
}

function stub(capabilities: string[], queue: Array<Response | Error>) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost')
      if (url.pathname.endsWith('/me')) {
        return json({ user_id: 'SYN-VIEWER', roles: [], capabilities, data_context: 'TEST' })
      }
      calls.push({ path: url.pathname, params: Object.fromEntries(url.searchParams) })
      const next = queue.shift()
      if (next === undefined) throw new Error(`Unexpected fetch: ${url.toString()}`)
      if (next instanceof Error) throw next
      return next
    }),
  )
  return calls
}

function renderAt(path: string) {
  return render(
    <CapabilitiesProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/pm/due" element={<FleetPmDuePage />} />
          <Route path="/vehicle/:vehicleId/pm/due" element={<VehiclePmDuePage />} />
          <Route path="/vehicle/:vehicleId/pm" element={<p>vehicle pm page</p>} />
          <Route path="/pm/work-orders/:workOrderId" element={<p>work order detail</p>} />
        </Routes>
      </MemoryRouter>
    </CapabilitiesProvider>,
  )
}

describe('FleetPmDuePage (R4 / TASK-010 Fleet PM Due B1)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows loading, then the server values exactly (no recalculation)', async () => {
    stub(['can_view'], [page([vehicle('SYN-VEH-1')])])
    renderAt('/pm/due')
    expect(await screen.findByText('กำลังโหลดกำหนด PM...')).toBeInTheDocument()
    const status = await screen.findByTestId('pm-due-status')
    expect(status).toHaveAttribute('data-status', 'NOT_DUE')
    expect(within(status).getByText('ยังไม่ถึงกำหนด')).toBeInTheDocument()
    expect(screen.getByText('1,250 HOUR')).toBeInTheDocument() // the backend next Due
    expect(screen.getByText('1,249 HOUR')).toBeInTheDocument()
    expect(screen.getByTestId('pm-due-last')).toHaveTextContent('650 HOUR')
    expect(screen.getByRole('link', { name: 'SYN-PMWO-1' })).toHaveAttribute('href', '/pm/work-orders/SYN-PMWO-1')
    expect(screen.getByText(/ส่วนเครน \(CRANE\): กำหนดว่าไม่มีแผน/)).toBeInTheDocument()
    expect(screen.getByTestId('fleet-pm-due-total')).toHaveTextContent('รถทั้งหมด 1 คันตามเงื่อนไข')
  })

  it('keeps UNKNOWN as UNKNOWN even when a current reading and a proven completion exist', async () => {
    const unknown = set({
      status: 'UNKNOWN',
      explanation: 'ไม่มีค่ามิเตอร์ปัจจุบันจาก IoT ที่ยืนยันได้',
      diagnostic_code: 'CURRENT_METER_UNVERIFIED',
      next_due: null,
      current_meter: 5000, // far beyond last + interval: still never shown as DUE
    })
    stub(['can_view'], [page([vehicle('SYN-VEH-1', { sets: [unknown] })])])
    renderAt('/pm/due')
    const status = await screen.findByTestId('pm-due-status')
    expect(status).toHaveAttribute('data-status', 'UNKNOWN')
    expect(within(status).getByText('ยังยืนยันไม่ได้ (UNKNOWN)')).toBeInTheDocument()
    expect(within(status).getByText(/ไม่มีค่ามิเตอร์ปัจจุบันจาก IoT ที่ยืนยันได้/)).toBeInTheDocument()
    expect(screen.queryByText('ถึงกำหนด PM')).toBeNull()
    expect(screen.queryByText('CURRENT_METER_UNVERIFIED')).toBeNull() // diagnostics are not UI text
    expect(screen.getByTestId('pm-due-last')).toHaveTextContent('650 HOUR')
  })

  it('shows MASTER_NOT_ACTIVE per vehicle, never as an empty "nothing due" fleet', async () => {
    stub(['can_view'], [page([vehicle('SYN-VEH-1', NOT_ACTIVE), vehicle('SYN-VEH-2', NOT_ACTIVE)])])
    renderAt('/pm/due')
    const vehicles = await screen.findAllByTestId('pm-due-vehicle')
    expect(vehicles.map((v) => v.getAttribute('data-state'))).toEqual(['MASTER_NOT_ACTIVE', 'MASTER_NOT_ACTIVE'])
    expect(screen.getAllByText('แผน PM หลักยังไม่เปิดใช้งาน')).toHaveLength(2)
    expect(screen.getAllByText(/ไม่ได้หมายความว่าไม่มี PM ถึงกำหนด/)).toHaveLength(2)
    expect(screen.queryByTestId('fleet-pm-due-empty')).toBeNull()
    expect(screen.queryByTestId('pm-due-status')).toBeNull()
  })

  it('applies the vehicle filters and pages through the URL', async () => {
    const user = userEvent.setup()
    const calls = stub(
      ['can_view'],
      [page([vehicle('SYN-VEH-1')], 45), page([vehicle('SYN-VEH-2')], 45, 1), page([vehicle('SYN-VEH-3')], 45, 2)],
    )
    renderAt('/pm/due')
    await screen.findByText('TC-SYN-VEH-1')
    expect(calls[0]).toEqual({ path: DUE_PATH, params: { page: '1', page_size: '20' } })
    await user.type(screen.getByLabelText('ค้นหา (เลขรถ / รหัส / รุ่น)'), ' TC-13 ')
    await user.selectOptions(screen.getByLabelText('สถานะรถ'), 'MAINTENANCE')
    await user.type(screen.getByLabelText('รหัสรุ่นรถ'), 'SYN-MODEL')
    await user.click(screen.getByRole('button', { name: 'ค้นหา' }))
    await screen.findByText('TC-SYN-VEH-2')
    expect(calls[1].params).toEqual({ page: '1', page_size: '20', q: 'TC-13', status: 'MAINTENANCE', model_id: 'SYN-MODEL' })
    expect(screen.getByText('หน้า 1 / 3')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'ถัดไป' }))
    await screen.findByText('TC-SYN-VEH-3')
    expect(calls[2].params).toEqual({ page: '2', page_size: '20', q: 'TC-13', status: 'MAINTENANCE', model_id: 'SYN-MODEL' })
  })

  it('says so for no matching vehicle and for a page beyond the last', async () => {
    stub(['can_view'], [page([], 0)])
    renderAt('/pm/due')
    expect(await screen.findByTestId('fleet-pm-due-empty')).toHaveTextContent('ไม่มีรถตามเงื่อนไขที่เลือก')
    vi.unstubAllGlobals()
    stub(['can_view'], [page([], 3, 9)])
    renderAt('/pm/due?page=9')
    expect(await screen.findByTestId('fleet-pm-due-out-of-range')).toHaveTextContent('มีทั้งหมด 1 หน้า')
  })

  it('shows a failed request with retry and an access-denied state', async () => {
    const user = userEvent.setup()
    stub(['can_view'], [json({ error: { code: 'PM_E01_TRANSITION_INCOMPLETE', message: 'x', request_id: 'SYN-REQ' } }, 409),
      page([vehicle('SYN-VEH-1')])])
    renderAt('/pm/due')
    expect(await screen.findByText('โหลดกำหนด PM ไม่สำเร็จ')).toBeInTheDocument()
    expect(screen.queryByTestId('pm-due-vehicle')).toBeNull() // never stale or partial rows
    await user.click(screen.getByRole('button', { name: /ลองใหม่/ }))
    expect(await screen.findByTestId('pm-due-vehicle')).toBeInTheDocument()
  })

  it('is denied without can_view (no Due read) and on a backend 403', async () => {
    const calls = stub(['can_report_repair'], [])
    renderAt('/pm/due')
    expect(await screen.findByText('ไม่มีสิทธิ์เข้าถึง')).toBeInTheDocument()
    expect(calls).toEqual([])
    vi.unstubAllGlobals()
    stub(['can_view'], [json({ error: { code: 'FORBIDDEN', message: 'x', request_id: null } }, 403)])
    renderAt('/pm/due')
    expect(await screen.findByText('ไม่มีสิทธิ์เข้าถึง')).toBeInTheDocument()
  })

  it('renders the Sets through the shared responsive table (stacked-card labels)', async () => {
    stub(['can_view'], [page([vehicle('SYN-VEH-1')])])
    const { container } = renderAt('/pm/due')
    await screen.findByTestId('pm-due-status')
    expect(container.querySelector('.responsive-table')).not.toBeNull()
    expect(container.querySelector('td[data-label="ครบกำหนดที่"]')).not.toBeNull()
  })
})

describe('VehiclePmDuePage (R4 / TASK-010 Fleet PM Due B1)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('reads the same backend model for one vehicle and links back to the vehicle PM page', async () => {
    const calls = stub(['can_view'], [json(vehicle('SYN-VEH-1', { sets: [set({ status: 'DUE', explanation: 'ถึงกำหนด PM แล้ว' })] }))])
    renderAt('/vehicle/SYN-VEH-1/pm/due')
    const status = await screen.findByTestId('pm-due-status')
    expect(status).toHaveAttribute('data-status', 'DUE')
    expect(calls[0].path).toBe(`${DUE_PATH}/SYN-VEH-1`)
    expect(screen.getByRole('link', { name: 'กลับไปหน้า PM ของรถ' })).toHaveAttribute('href', '/vehicle/SYN-VEH-1/pm')
  })

  it('shows NO_ASSIGNED_PLAN truthfully with no Set table', async () => {
    stub(['can_view'], [json(vehicle('SYN-VEH-1', {
      state: 'NO_ASSIGNED_PLAN',
      explanation: 'รถคันนี้ยังไม่ได้รับการกำหนดแผน PM หลักอย่างชัดเจน จึงยังคำนวณกำหนด PM ไม่ได้',
      assignments: [{ assembly: '', source: 'ABSENT', plan_code: null }],
      plans: [],
      sets: [],
    }))])
    renderAt('/vehicle/SYN-VEH-1/pm/due')
    expect(await screen.findByText('ยังไม่ได้กำหนดแผน PM หลัก')).toBeInTheDocument()
    expect(screen.getByText(/ทั้งคัน: ยังไม่ได้กำหนด/)).toBeInTheDocument()
    expect(screen.queryByTestId('pm-due-status')).toBeNull()
  })
})

/** Browser Back / Forward stand-in: moves the router history without touching the form. */
function HistoryButtons() {
  const navigate = useNavigate()
  return (
    <>
      <button type="button" onClick={() => navigate(-1)}>
        SYN-BACK
      </button>
      <button type="button" onClick={() => navigate(1)}>
        SYN-FORWARD
      </button>
    </>
  )
}

describe('FleetPmDuePage — R2 URL / filter consistency', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function renderHistory(entries: string[], index: number) {
    return render(
      <CapabilitiesProvider>
        <MemoryRouter initialEntries={entries} initialIndex={index}>
          <HistoryButtons />
          <Routes>
            <Route path="/pm/due" element={<FleetPmDuePage />} />
          </Routes>
        </MemoryRouter>
      </CapabilitiesProvider>,
    )
  }

  it('shows the filters of the URL it requested after Back and Forward', async () => {
    const user = userEvent.setup()
    const calls = stub(
      ['can_view'],
      [page([vehicle('SYN-VEH-NEW')], 45, 2), page([vehicle('SYN-VEH-OLD')], 45), page([vehicle('SYN-VEH-NEW')], 45, 2)],
    )
    renderHistory(['/pm/due?q=OLD&status=READY&model_id=M-OLD', '/pm/due?q=NEW&model_id=M-NEW&page=2'], 1)
    await screen.findByText('TC-SYN-VEH-NEW')
    expect(screen.getByLabelText('ค้นหา (เลขรถ / รหัส / รุ่น)')).toHaveValue('NEW')
    expect(screen.getByLabelText('รหัสรุ่นรถ')).toHaveValue('M-NEW')

    await user.click(screen.getByRole('button', { name: 'SYN-BACK' }))
    await screen.findByText('TC-SYN-VEH-OLD')
    expect(calls[1].params).toEqual({ page: '1', page_size: '20', q: 'OLD', status: 'READY', model_id: 'M-OLD' })
    expect(screen.getByLabelText('ค้นหา (เลขรถ / รหัส / รุ่น)')).toHaveValue('OLD')
    expect(screen.getByLabelText('สถานะรถ')).toHaveValue('READY')
    expect(screen.getByLabelText('รหัสรุ่นรถ')).toHaveValue('M-OLD')
    expect(screen.queryByText('TC-SYN-VEH-NEW')).toBeNull()

    await user.click(screen.getByRole('button', { name: 'SYN-FORWARD' }))
    await screen.findByText('TC-SYN-VEH-NEW')
    expect(calls[2].params).toEqual({ page: '2', page_size: '20', q: 'NEW', model_id: 'M-NEW' })
    expect(screen.getByLabelText('ค้นหา (เลขรถ / รหัส / รุ่น)')).toHaveValue('NEW')
    expect(screen.getByLabelText('สถานะรถ')).toHaveValue('')
  })

  it('keeps unsubmitted edits while the active URL is unchanged (refresh, paging stays on the URL)', async () => {
    const user = userEvent.setup()
    const calls = stub(['can_view'], [page([vehicle('SYN-VEH-1')], 45), page([vehicle('SYN-VEH-1')], 45)])
    renderHistory(['/pm/due?q=KEEP'], 0)
    await screen.findByText('TC-SYN-VEH-1')
    const search = screen.getByLabelText('ค้นหา (เลขรถ / รหัส / รุ่น)')
    await user.clear(search)
    await user.type(search, 'UNSUBMITTED')
    await user.click(screen.getByRole('button', { name: 'รีเฟรช' }))
    await screen.findByText('TC-SYN-VEH-1')
    expect(calls[1].params).toEqual({ page: '1', page_size: '20', q: 'KEEP' }) // the active URL, not the draft
    expect(search).toHaveValue('UNSUBMITTED')
  })
})

// R4 final consolidated batch — RT4-C planned TEAM elapsed duration shown per Set. The value is
// the backend's (`planned_team_minutes`); the UI only formats ONE Set's minutes and never sums,
// multiplies, infers or treats a missing value as zero.
describe('PM Due — planned team duration (R4 RT4-C frontend)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  async function plannedCells(sets: PmDueSet[], path = '/pm/due') {
    stub(['can_view'], [path === '/pm/due' ? page([vehicle('SYN-VEH-1', { sets })]) : json(vehicle('SYN-VEH-1', { sets }))])
    renderAt(path)
    await screen.findAllByTestId('pm-due-status')
    return screen.getAllByTestId('pm-due-planned')
  }

  it.each([
    [150, '2 ชม. 30 นาที (150 นาที)'],
    [45, '45 นาที'],
    [180, '3 ชม. (180 นาที)'],
    [60, '1 ชม. (60 นาที)'],
    [61, '1 ชม. 1 นาที (61 นาที)'],
  ])('formats %i minutes as "%s" (hours and minutes of the server value, no decimal hours)', async (minutes, text) => {
    const [cell] = await plannedCells([set({ planned_team_minutes: minutes })])
    expect(cell).toHaveTextContent(text)
    expect(cell).toHaveAttribute('data-minutes', String(minutes))
    expect(cell).toHaveTextContent('เวลาที่ทีมใช้ทำงานตามแผน ไม่ใช่ชั่วโมงคน')
    expect(cell.textContent).not.toMatch(/\d+\.\d+/) // never 2.5 hours
  })

  it('shows no-data text for null, never zero', async () => {
    const [cell] = await plannedCells([set({ planned_team_minutes: null })])
    expect(cell).toHaveTextContent('ไม่มีข้อมูลเวลาตามแผน')
    expect(cell).not.toHaveAttribute('data-minutes')
    expect(cell.textContent).not.toMatch(/(^|\D)0 นาที|0 ชม/)
  })

  it('handles a response that omits the field (older backend) without crashing', async () => {
    const older: Partial<PmDueSet> = { ...set() }
    delete older.planned_team_minutes
    const [cell] = await plannedCells([older as PmDueSet])
    expect(cell).toHaveTextContent('ไม่มีข้อมูลเวลาตามแผน')
    expect(cell).not.toHaveAttribute('data-minutes')
  })

  it.each([[0], [-30], [12.5], [Number.NaN], ['150'], [true]])(
    'treats an unexpected runtime value %p as no data (no rounding, no coercion)',
    async (value) => {
      const [cell] = await plannedCells([set({ planned_team_minutes: value as unknown as number })])
      expect(cell).toHaveTextContent('ไม่มีข้อมูลเวลาตามแผน')
      expect(cell).not.toHaveAttribute('data-minutes')
    },
  )

  it('keeps each Set its own duration and never shows a combined total', async () => {
    const cells = await plannedCells([
      set({ set_key: 'SYN-M1|CARRIER|A', set_code: 'A', section: 'CARRIER', planned_team_minutes: 150 }),
      set({ set_key: 'SYN-M1|CRANE|B', set_code: 'B', section: 'CRANE', planned_team_minutes: 90 }),
    ])
    expect(cells.map((c) => c.getAttribute('data-minutes'))).toEqual(['150', '90'])
    expect(cells[0]).toHaveTextContent('2 ชม. 30 นาที (150 นาที)')
    expect(cells[1]).toHaveTextContent('1 ชม. 30 นาที (90 นาที)')
    expect(document.body.textContent).not.toMatch(/240|4 ชม\./) // no sum anywhere
  })

  it('shows the same duration contract on the Fleet and the Vehicle Due screens', async () => {
    const fleet = (await plannedCells([set({ planned_team_minutes: 150 })], '/pm/due')).map((c) => c.textContent)
    vi.unstubAllGlobals()
    document.body.innerHTML = ''
    const single = (await plannedCells([set({ planned_team_minutes: 150 })], '/vehicle/SYN-VEH-1/pm/due')).map(
      (c) => c.textContent,
    )
    expect(single).toEqual(fleet)
    expect(fleet[0]).toContain('2 ชม. 30 นาที (150 นาที)')
  })

  it('never changes the server status badge or explanation', async () => {
    const sets = [
      set({ set_key: 'K1', status: 'DUE', explanation: 'ถึงกำหนด PM แล้ว', planned_team_minutes: 150 }),
      set({ set_key: 'K2', status: 'UNKNOWN', explanation: 'ไม่มีค่ามิเตอร์ปัจจุบันจาก IoT ที่ยืนยันได้', next_due: null,
            planned_team_minutes: 45 }),
      set({ set_key: 'K3', status: 'NOT_DUE', explanation: 'ยังไม่ถึงกำหนด PM', planned_team_minutes: null }),
    ]
    await plannedCells(sets)
    const statuses = screen.getAllByTestId('pm-due-status')
    expect(statuses.map((s) => s.getAttribute('data-status'))).toEqual(['DUE', 'UNKNOWN', 'NOT_DUE'])
    expect(within(statuses[0]).getByText(/ถึงกำหนด PM แล้ว/)).toBeInTheDocument()
    expect(within(statuses[1]).getByText(/ไม่มีค่ามิเตอร์ปัจจุบันจาก IoT ที่ยืนยันได้/)).toBeInTheDocument()
  })

  it('reveals no duration when the PM Master is not active (no Set table)', async () => {
    stub(['can_view'], [page([vehicle('SYN-VEH-1', NOT_ACTIVE)])])
    renderAt('/pm/due')
    await screen.findByTestId('pm-due-vehicle')
    expect(screen.queryByTestId('pm-due-planned')).toBeNull()
    expect(screen.queryByText(/เวลาทีมตามแผน|ไม่มีข้อมูลเวลาตามแผน/)).toBeNull()
  })

  it('adds one responsive column right after the interval column', async () => {
    stub(['can_view'], [page([vehicle('SYN-VEH-1', { sets: [set({ planned_team_minutes: 150 })] })])])
    const { container } = renderAt('/pm/due')
    await screen.findByTestId('pm-due-status')
    const headers = [...container.querySelectorAll('th')].map((th) => th.textContent)
    expect(headers.indexOf('เวลาทีมตามแผน')).toBe(headers.indexOf('รอบ') + 1)
    expect(container.querySelector('td[data-label="เวลาทีมตามแผน"]')).not.toBeNull()
  })
})
