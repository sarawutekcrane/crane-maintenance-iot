import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import { MyWorkPage } from './MyWorkPage'
import { PmStatusPage } from './PmStatusPage'
import { RepairCreatePage } from './RepairCreatePage'
import { RepairDetailPage } from './RepairDetailPage'
import { RepairRequestQueuePage } from './RepairRequestQueuePage'
import { WaitingAssignmentQueuePage } from './WaitingAssignmentQueuePage'

type Handler = (url: string, init: RequestInit) => Response | Promise<Response> | undefined

interface Call {
  url: string
  method: string
  body: unknown
  headers: Record<string, string>
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const errorBody = (code: string, requestId = 'REQ-SYN-1', details: Record<string, unknown> = {}) => ({
  error: { code, message: 'x', details, request_id: requestId },
})

const ALL_CAPS = ['can_view', 'can_manage_repair', 'can_manage_pm']

function me(overrides: Record<string, unknown> = {}) {
  return {
    user_id: 'SYN-USER',
    roles: ['ADMIN'],
    capabilities: ALL_CAPS,
    technician_assignment_v2_enabled: true,
    data_context: 'TEST',
    ...overrides,
  }
}

function setup(handler: Handler, meBody: unknown = me(), meStatus = 200) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET'
      calls.push({
        url: input,
        method,
        body: init.body ? JSON.parse(String(init.body)) : undefined,
        headers: (init.headers ?? {}) as Record<string, string>,
      })
      if (input === '/api/v1/me') return jsonResponse(meBody, meStatus)
      if (input.startsWith('/api/v1/machine-state/current')) return jsonResponse(errorBody('NOT_FOUND'), 404)
      if (input.startsWith('/api/v1/attachments/by-source/')) return jsonResponse([])
      if (input.startsWith('/api/v1/repair-requests/mine')) return jsonResponse({ items: [], page: 1, page_size: 50, total_items: 0 })
      const response = await handler(input, init)
      if (response) return response
      throw new Error(`unexpected request ${method} ${input}`)
    }),
  )
  return calls
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <CapabilitiesProvider>
        <Routes>
          <Route path="/vehicle/:vehicleId/repairs/new" element={<RepairCreatePage />} />
          <Route path="/equipment/:equipmentId/repairs/new" element={<RepairCreatePage />} />
          <Route path="/vehicle/:vehicleId/pm" element={<PmStatusPage />} />
          <Route path="/repairs/:repairId" element={<RepairDetailPage />} />
          <Route path="/my-work" element={<MyWorkPage />} />
          <Route path="/waiting-assignment" element={<WaitingAssignmentQueuePage />} />
          <Route path="/repair-request-queue" element={<RepairRequestQueuePage />} />
        </Routes>
      </CapabilitiesProvider>
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

const writes = (calls: Call[]) => calls.filter((c) => c.method !== 'GET')

describe('V2 creation gate (cutover OFF / /me failure → blocked, no create request)', () => {
  it.each([
    ['flag false', me({ technician_assignment_v2_enabled: false }), 200],
    ['flag missing', me({ technician_assignment_v2_enabled: undefined }), 200],
    ['flag "true" string', me({ technician_assignment_v2_enabled: 'true' }), 200],
  ])('Repair (vehicle, Maintenance): %s → blocked, no form, no request but /me', async (_name, meBody, status) => {
    const calls = setup(() => undefined, meBody, status)
    renderAt('/vehicle/VEH-SYN-1/repairs/new')
    expect(await screen.findByTestId('v2-creation-disabled')).toHaveTextContent('การมอบหมายช่างยังไม่เปิดใช้งาน')
    expect(screen.queryByRole('button', { name: 'ส่งแจ้งซ่อม' })).toBeNull()
    expect(screen.queryByLabelText('อาการ/ปัญหาที่พบ')).toBeNull()
    expect(screen.queryByLabelText(/ช่างผู้รับผิดชอบหลัก/)).toBeNull() // never the legacy create
    expect(writes(calls)).toEqual([])
    expect([...new Set(calls.map((c) => c.url))]).toEqual(['/api/v1/me'])
  })

  it.each([
    ['flag false', me({ technician_assignment_v2_enabled: false }), 200],
    ['/me fails', errorBody('INTERNAL_ERROR'), 500],
  ])('Repair (equipment, always the direct create): %s → blocked, no request but /me', async (_name, meBody, status) => {
    const calls = setup(() => undefined, meBody, status)
    renderAt('/equipment/EQ-SYN-1/repairs/new')
    expect(await screen.findByTestId('v2-creation-disabled')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'ส่งแจ้งซ่อม' })).toBeNull()
    expect(writes(calls)).toEqual([])
    expect([...new Set(calls.map((c) => c.url))]).toEqual(['/api/v1/me'])
  })

  it('Repair (vehicle) when /me fails: no direct-create form (only the unchanged problem report, which creates no job)', async () => {
    const calls = setup(() => undefined, errorBody('INTERNAL_ERROR'), 500)
    renderAt('/vehicle/VEH-SYN-1/repairs/new')
    expect(await screen.findByRole('heading', { name: 'แจ้งปัญหา/แจ้งซ่อม' })).toBeInTheDocument()
    expect(screen.queryByLabelText('หมวดหมู่ (ถ้ามี)')).toBeNull()
    expect(screen.queryByLabelText(/ช่างผู้รับผิดชอบหลัก/)).toBeNull()
    expect(calls.some((c) => c.url === '/api/v1/repairs')).toBe(false)
  })

  const PLANS = [{ plan: { pm_plan_id: 'PMP-SYN', plan_code: 'P', name: 'แผนทดสอบ' }, active_revision: { revision_number: 1 }, last_completed_at: null, due_status_note: 'note' }]

  it('PM: flag false keeps the plan status (a read) but offers no start and sends no create', async () => {
    const calls = setup(
      (url) => (url.startsWith('/api/v1/pm/plans/status') ? jsonResponse(PLANS) : undefined),
      me({ technician_assignment_v2_enabled: false }),
    )
    renderAt('/vehicle/VEH-SYN-1/pm')
    expect(await screen.findByTestId('v2-creation-disabled')).toHaveTextContent('การมอบหมายช่างยังไม่เปิดใช้งาน')
    expect(screen.getByText('แผนทดสอบ')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'เริ่มทำ PM' })).toBeNull()
    expect(writes(calls)).toEqual([])
  })

  it('flag ON, vehicle, without can_manage_repair: the unchanged problem report only (no direct create)', async () => {
    const calls = setup(() => undefined, me({ capabilities: ['can_view', 'can_report_repair'] }))
    renderAt('/vehicle/VEH-SYN-1/repairs/new')
    expect(await screen.findByRole('heading', { name: 'แจ้งปัญหา/แจ้งซ่อม' })).toBeInTheDocument()
    expect(screen.queryByLabelText('หมวดหมู่ (ถ้ามี)')).toBeNull()
    expect(writes(calls)).toEqual([])
  })

  it('Repair Request convert: flag OFF → no convert control, no request; flag ON → convert sends no technician', async () => {
    const pending = { items: [{ repair_request_id: 'RRQ-SYN-1', vehicle_id: 'VEH-SYN-1', reported_at: '2026-01-01T00:00:00Z', symptom_th: 'x', request_status: 'PENDING' }], page: 1, page_size: 100, total_items: 1 }
    let calls = setup((url) => (url.startsWith('/api/v1/repair-requests/pending') ? jsonResponse(pending) : undefined), me({ technician_assignment_v2_enabled: false }))
    const { unmount } = renderAt('/repair-request-queue')
    expect(await screen.findByTestId('v2-creation-disabled')).toHaveTextContent('การมอบหมายช่างยังไม่เปิดใช้งาน')
    expect(screen.queryByRole('button', { name: 'เปิดใบงานซ่อม' })).toBeNull()
    expect(writes(calls)).toEqual([])
    unmount()
    vi.unstubAllGlobals()
    calls = setup((url, init) => {
      if (url.startsWith('/api/v1/repair-requests/pending')) return jsonResponse(pending)
      if (url === '/api/v1/repair-requests/RRQ-SYN-1/convert' && init.method === 'POST') return jsonResponse({ repair: { repair_id: 'RPR-SYN-9' } })
      return undefined
    })
    const user = userEvent.setup()
    renderAt('/repair-request-queue')
    const convert = await screen.findByRole('button', { name: 'เปิดใบงานซ่อม' })
    await user.click(convert)
    await waitFor(() => expect(writes(calls)).toHaveLength(1))
    expect(writes(calls)[0].body).toEqual({})
  })

  it('flag ON: POST /repairs carries no technician field, once, even on a double click', async () => {
    let release: () => void = () => {}
    const calls = setup((url, init) => {
      if (url === '/api/v1/repairs' && init.method === 'POST') {
        return new Promise<Response>((resolve) => {
          release = () => resolve(jsonResponse({ repair: { repair_id: 'RPR-SYN-1' } }))
        })
      }
      if (url === '/api/v1/repairs/RPR-SYN-1') return jsonResponse(errorBody('REPAIR_NOT_FOUND'), 404)
      return undefined
    })
    const user = userEvent.setup()
    renderAt('/vehicle/VEH-SYN-1/repairs/new')
    await user.type(await screen.findByLabelText('อาการ/ปัญหาที่พบ'), 'ไฮดรอลิกรั่ว')
    const submit = screen.getByRole('button', { name: 'ส่งแจ้งซ่อม' })
    await user.click(submit)
    await user.click(submit)
    act(() => release())
    await waitFor(() => expect(calls.some((c) => c.url === '/api/v1/repairs/RPR-SYN-1')).toBe(true))
    const posts = writes(calls)
    expect(posts).toHaveLength(1)
    expect(posts[0].body).toEqual({
      asset_type: 'VEHICLE',
      asset_id: 'VEH-SYN-1',
      source_type: 'MANUAL',
      source_id: null,
      category: null,
      symptom: 'ไฮดรอลิกรั่ว',
    })
    expect(posts[0].body).not.toHaveProperty('primary_technician')
    expect(posts[0].body).not.toHaveProperty('collaborators')
  })

  it('flag ON: PM start posts the plan with no technician field', async () => {
    const calls = setup((url, init) => {
      if (url.startsWith('/api/v1/pm/plans/status')) {
        return jsonResponse([
          { plan: { pm_plan_id: 'PMP-SYN', plan_code: 'P', name: 'แผนทดสอบ' }, active_revision: { revision_number: 1 } },
        ])
      }
      if (url === '/api/v1/pm/work-orders' && init.method === 'POST') {
        return jsonResponse({ work_order: { pm_work_order_id: 'PMWO-SYN-1' } })
      }
      if (url === '/api/v1/pm/work-orders/PMWO-SYN-1') return jsonResponse(errorBody('PM_WORK_ORDER_NOT_FOUND'), 404)
      return undefined
    })
    const user = userEvent.setup()
    renderAt('/vehicle/VEH-SYN-1/pm')
    await user.click(await screen.findByRole('button', { name: 'เริ่มทำ PM' }))
    await waitFor(() => expect(writes(calls)).toHaveLength(1))
    expect(writes(calls)[0].body).toEqual({ asset_type: 'VEHICLE', asset_id: 'VEH-SYN-1', pm_plan_id: 'PMP-SYN' })
  })
})

describe('V2 context labelling', () => {
  it.each([
    ['TEST', 'TEST — ข้อมูลทดสอบ'],
    ['REAL', 'REAL — ข้อมูลจริง'],
    ['UNCONFIGURED', 'ยังไม่ได้กำหนดขอบเขตข้อมูล'],
    ['real', 'ไม่ทราบขอบเขตข้อมูล'],
    [undefined, 'ไม่ทราบขอบเขตข้อมูล'],
  ])('data_context %s', async (value, label) => {
    setup(() => undefined, me({ data_context: value, technician_assignment_v2_enabled: false }))
    renderAt('/vehicle/VEH-SYN-1/repairs/new')
    const banner = await screen.findByTestId('v2-data-context')
    expect(banner).toHaveTextContent(label)
    if (value !== 'REAL') expect(banner).not.toHaveTextContent('REAL')
  })
})

const TECHS = {
  items: [
    { technician_id: 'TEC-SYN-1', first_name: 'ช่างหนึ่ง', last_name: 'ทดสอบ', active_status: 'ACTIVE' },
    { technician_id: 'TEC-SYN-2', first_name: 'ช่างสอง', last_name: 'ทดสอบ', active_status: 'ACTIVE' },
    { technician_id: 'TEC-SYN-3', first_name: null, last_name: null, active_status: 'INACTIVE' },
  ],
  page: 1,
  page_size: 200,
  total_items: 3,
}

const repairJob = (overrides: Record<string, unknown> = {}) => ({
  repair: {
    repair_id: 'RPR-SYN-1',
    asset_type: 'VEHICLE',
    asset_id: 'VEH-SYN-1',
    source_type: 'MANUAL',
    source_id: null,
    category: null,
    meter_snapshot_id: null,
    closed_at: null,
    close_note: null,
    closed_snapshot_id: null,
    status: 'OPEN',
    opened_at: '2026-01-01T00:00:00Z',
    symptom: 'ทดสอบ',
    primary_technician: null,
    collaborators: [],
    assignment_model: 'TECHNICIAN_V2',
    ...overrides,
  },
  actions: [],
  parts: [],
})

const SET = {
  assignment_set_id: 'SET-1',
  assigned_at: '2026-01-02T00:00:00Z',
  assigned_by_user_id: 'SYN-USER',
  primary_technician_id: 'TEC-SYN-1',
  collaborator_technician_ids: ['TEC-GONE'],
  reason_th: null,
  record_ids: ['R1', 'R2'],
}

function jobHandler(job: unknown, assignments: unknown, post?: Handler): Handler {
  return (url, init) => {
    if (url === '/api/v1/repairs/RPR-SYN-1') return jsonResponse(job)
    if (url === '/api/v1/repairs/RPR-SYN-1/technician-assignments' && (init.method ?? 'GET') === 'GET') {
      return jsonResponse(assignments)
    }
    if (url.startsWith('/api/v1/technicians?')) return jsonResponse(TECHS)
    if (url === '/api/v1/repairs/RPR-SYN-1/technician-assignments' && init.method === 'POST') return post?.(url, init)
    return undefined
  }
}

describe('V2 job detail branches on the persisted assignment_model', () => {
  it('LEGACY: read-only LEGACY_USER_ID, no V2 read, no control', async () => {
    const calls = setup(jobHandler(repairJob({ assignment_model: 'LEGACY', primary_technician: 'legacy-user-7' }), null))
    renderAt('/repairs/RPR-SYN-1')
    expect(await screen.findByTestId('legacy-assignment-readonly')).toBeInTheDocument()
    expect(screen.getByText('legacy-user-7')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'บันทึกการมอบหมายช่าง' })).toBeNull()
    expect(calls.some((c) => c.url.includes('technician-assignments'))).toBe(false)
  })

  it.each(['INVALID', 'technician_v2', ''])('%s: explicit error, no control', async (model) => {
    const calls = setup(jobHandler(repairJob({ assignment_model: model }), null))
    renderAt('/repairs/RPR-SYN-1')
    expect(await screen.findByText('รูปแบบการมอบหมายของงานนี้ไม่ถูกต้อง')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'บันทึกการมอบหมายช่าง' })).toBeNull()
    expect(calls.some((c) => c.url.includes('technician-assignments'))).toBe(false)
  })

  it('TECHNICIAN_V2: current set with id + name, unresolved id explicit, history separate', async () => {
    setup(jobHandler(repairJob(), { job_id: 'RPR-SYN-1', assignment_model: 'TECHNICIAN_V2', status: 'VALID', current: SET, sets: [SET] }))
    renderAt('/repairs/RPR-SYN-1')
    const current = await screen.findByTestId('v2-current-set')
    expect(within(current).getByText('TEC-SYN-1')).toBeInTheDocument()
    expect(within(current).getByText(/ช่างหนึ่ง ทดสอบ/)).toBeInTheDocument()
    expect(within(current).getByText('TEC-GONE')).toBeInTheDocument()
    expect(within(current).getByText(/ไม่พบรหัสช่างนี้ในขอบเขตข้อมูลปัจจุบัน/)).toBeInTheDocument()
    expect(within(screen.getByTestId('v2-assignment-history')).getAllByText('TEC-SYN-1').length).toBeGreaterThan(0)
  })

  it('AMBIGUOUS: explained, no form', async () => {
    setup(jobHandler(repairJob(), { job_id: 'RPR-SYN-1', assignment_model: 'TECHNICIAN_V2', status: 'AMBIGUOUS', current: null, sets: [SET, SET] }))
    renderAt('/repairs/RPR-SYN-1')
    expect(await screen.findByText(/ระบุทีมช่างปัจจุบันไม่ได้/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'บันทึกการมอบหมายช่าง' })).toBeNull()
  })

  it('CLOSED: no assignment form', async () => {
    setup(jobHandler(repairJob({ status: 'CLOSED' }), { job_id: 'RPR-SYN-1', assignment_model: 'TECHNICIAN_V2', status: 'NONE', current: null, sets: [] }))
    renderAt('/repairs/RPR-SYN-1')
    expect(await screen.findByTestId('v2-assignment-closed')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'บันทึกการมอบหมายช่าง' })).toBeNull()
  })

  it('read failure: ErrorState with code and request id, no control', async () => {
    setup((url) => {
      if (url === '/api/v1/repairs/RPR-SYN-1') return jsonResponse(repairJob())
      if (url.includes('technician-assignments')) return jsonResponse(errorBody('TECHNICIAN_ASSIGNMENT_DATA_INVALID', 'REQ-DI'), 500)
      if (url.startsWith('/api/v1/technicians?')) return jsonResponse(TECHS)
      return undefined
    })
    renderAt('/repairs/RPR-SYN-1')
    expect(await screen.findByText('รหัสข้อผิดพลาด: TECHNICIAN_ASSIGNMENT_DATA_INVALID')).toBeInTheDocument()
    expect(screen.getByText('รหัสอ้างอิง: REQ-DI')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'บันทึกการมอบหมายช่าง' })).toBeNull()
  })

  it('picker read failure: no form (never free text)', async () => {
    setup((url) => {
      if (url === '/api/v1/repairs/RPR-SYN-1') return jsonResponse(repairJob())
      if (url.includes('technician-assignments')) {
        return jsonResponse({ job_id: 'RPR-SYN-1', assignment_model: 'TECHNICIAN_V2', status: 'NONE', current: null, sets: [] })
      }
      if (url.startsWith('/api/v1/technicians?')) return jsonResponse(errorBody('REGISTRY_DATA_CONTEXT_NOT_CONFIGURED', 'REQ-T'), 503)
      return undefined
    })
    renderAt('/repairs/RPR-SYN-1')
    expect(await screen.findByText('โหลดรายชื่อช่างไม่สำเร็จ')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'บันทึกการมอบหมายช่าง' })).toBeNull()
    expect(screen.queryByRole('textbox', { name: /ช่างหลัก/ })).toBeNull()
  })

  it('empty picker: explicit empty state, no form', async () => {
    setup((url) => {
      if (url === '/api/v1/repairs/RPR-SYN-1') return jsonResponse(repairJob())
      if (url.includes('technician-assignments')) {
        return jsonResponse({ job_id: 'RPR-SYN-1', assignment_model: 'TECHNICIAN_V2', status: 'NONE', current: null, sets: [] })
      }
      if (url.startsWith('/api/v1/technicians?')) return jsonResponse({ items: [], page: 1, page_size: 200, total_items: 0 })
      return undefined
    })
    renderAt('/repairs/RPR-SYN-1')
    expect(await screen.findByText('ไม่มีช่างในขอบเขตข้อมูลนี้')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'บันทึกการมอบหมายช่าง' })).toBeNull()
  })
})

describe('V2 assignment save', () => {
  const none = { job_id: 'RPR-SYN-1', assignment_model: 'TECHNICIAN_V2', status: 'NONE', current: null, sets: [] }

  async function choose(user: ReturnType<typeof userEvent.setup>) {
    await user.selectOptions(await screen.findByLabelText(/ช่างหลัก \(PRIMARY\)/), 'TEC-SYN-1')
    await user.click(screen.getByLabelText(/TEC-SYN-2/))
  }

  it('sends PRIMARY + COLLABORATOR with expected_current null, once, and the PRIMARY is never offered as COLLABORATOR', async () => {
    let release: () => void = () => {}
    const calls = setup(
      jobHandler(repairJob(), none, () =>
        new Promise<Response>((resolve) => {
          release = () => resolve(jsonResponse({ request_id: 'x', changed: true, record_ids: [], current: SET }))
        }),
      ),
    )
    const user = userEvent.setup()
    renderAt('/repairs/RPR-SYN-1')
    await choose(user)
    const picker = screen.getByTestId('technician-v2-picker')
    expect(within(picker).queryByRole('checkbox', { name: /TEC-SYN-1/ })).toBeNull()
    const submit = screen.getByRole('button', { name: 'บันทึกการมอบหมายช่าง' })
    await user.click(submit)
    await user.click(screen.getByRole('button', { name: 'กำลังบันทึก...' }))
    act(() => release())
    expect(await screen.findByText('บันทึกการมอบหมายช่างเรียบร้อยแล้ว')).toBeInTheDocument()
    const posts = writes(calls)
    expect(posts).toHaveLength(1)
    expect(posts[0].body).toEqual({
      primary_technician_id: 'TEC-SYN-1',
      collaborator_technician_ids: ['TEC-SYN-2'],
      expected_current: null,
    })
    expect(posts[0].headers['X-Request-Id']).toBeTruthy()
  })

  it('sends the exact current set as expected_current', async () => {
    const current = { ...SET, collaborator_technician_ids: ['TEC-SYN-2'] }
    const calls = setup(
      jobHandler(repairJob(), { ...none, status: 'VALID', current, sets: [current] }, () =>
        jsonResponse({ request_id: 'x', changed: true, record_ids: [], current }),
      ),
    )
    const user = userEvent.setup()
    renderAt('/repairs/RPR-SYN-1')
    await user.selectOptions(await screen.findByLabelText(/ช่างหลัก \(PRIMARY\)/), 'TEC-SYN-2')
    await user.click(screen.getByRole('button', { name: 'บันทึกการมอบหมายช่าง' }))
    await waitFor(() => expect(writes(calls)).toHaveLength(1))
    expect(writes(calls)[0].body).toEqual({
      primary_technician_id: 'TEC-SYN-2',
      collaborator_technician_ids: [],
      expected_current: { primary_technician_id: 'TEC-SYN-1', collaborator_technician_ids: ['TEC-SYN-2'] },
    })
  })

  it('no PRIMARY: refused locally, no request (no empty-set unassignment)', async () => {
    const calls = setup(jobHandler(repairJob(), none))
    const user = userEvent.setup()
    renderAt('/repairs/RPR-SYN-1')
    await user.click(await screen.findByRole('button', { name: 'บันทึกการมอบหมายช่าง' }))
    expect(await screen.findByText('กรุณาเลือกช่างหลัก (PRIMARY) 1 คน')).toBeInTheDocument()
    expect(writes(calls)).toEqual([])
  })

  it('stale: explicit conflict, form locked until reload, no automatic resend, selection kept for reconfirmation', async () => {
    const calls = setup(jobHandler(repairJob(), none, () => jsonResponse(errorBody('TECHNICIAN_ASSIGNMENT_STALE'), 409)))
    const user = userEvent.setup()
    renderAt('/repairs/RPR-SYN-1')
    await choose(user)
    await user.click(screen.getByRole('button', { name: 'บันทึกการมอบหมายช่าง' }))
    expect(await screen.findByTestId('v2-assignment-message-stale')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'บันทึกการมอบหมายช่าง' })).toBeDisabled()
    expect(writes(calls)).toHaveLength(1)
    const readsBefore = calls.filter((c) => c.url.endsWith('/technician-assignments') && c.method === 'GET').length
    await user.click(screen.getByRole('button', { name: 'โหลดข้อมูลล่าสุด' }))
    await waitFor(() =>
      expect(calls.filter((c) => c.url.endsWith('/technician-assignments') && c.method === 'GET').length).toBe(readsBefore + 1),
    )
    expect(await screen.findByRole('button', { name: 'บันทึกการมอบหมายช่าง' })).toBeEnabled()
    expect(screen.getByLabelText(/ช่างหลัก \(PRIMARY\)/)).toHaveValue('TEC-SYN-1')
    expect(writes(calls)).toHaveLength(1)
  })

  it('refusal: code and request id shown, intent cleared', async () => {
    setup(jobHandler(repairJob(), none, () => jsonResponse(errorBody('TECHNICIAN_NOT_ACTIVE', 'REQ-NA'), 422)))
    const user = userEvent.setup()
    renderAt('/repairs/RPR-SYN-1')
    await choose(user)
    await user.click(screen.getByRole('button', { name: 'บันทึกการมอบหมายช่าง' }))
    expect(await screen.findByText('รหัสข้อผิดพลาด: TECHNICIAN_NOT_ACTIVE')).toBeInTheDocument()
    expect(screen.queryByTestId('v2-assignment-pending')).toBeNull()
  })

  it('transport failure: UNKNOWN (never success), pending intent kept, resend uses the same request id', async () => {
    let fail = true
    const calls = setup(
      jobHandler(repairJob(), none, () => {
        if (fail) return Promise.reject(new TypeError('network down'))
        return jsonResponse({ request_id: 'x', replayed: true, record_ids: [] })
      }),
    )
    const user = userEvent.setup()
    renderAt('/repairs/RPR-SYN-1')
    await choose(user)
    await user.click(screen.getByRole('button', { name: 'บันทึกการมอบหมายช่าง' }))
    expect(await screen.findByTestId('v2-assignment-message-unknown')).toBeInTheDocument()
    expect(screen.queryByText('บันทึกการมอบหมายช่างเรียบร้อยแล้ว')).toBeNull()
    expect(screen.getByTestId('v2-assignment-pending')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'บันทึกการมอบหมายช่าง' })).toBeNull()
    fail = false
    await user.click(screen.getByRole('button', { name: 'ส่งคำขอเดิมอีกครั้ง' }))
    await waitFor(() => expect(writes(calls)).toHaveLength(2))
    const [first, second] = writes(calls)
    expect(second.headers['X-Request-Id']).toBe(first.headers['X-Request-Id'])
    expect(second.body).toEqual(first.body)
    expect(await screen.findByText('บันทึกการมอบหมายช่างเรียบร้อยแล้ว')).toBeInTheDocument()
  })

  it('without the management capability the panel is read-only', async () => {
    setup(jobHandler(repairJob(), none), me({ capabilities: ['can_view'] }))
    renderAt('/repairs/RPR-SYN-1')
    expect(await screen.findByTestId('v2-current-set')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'บันทึกการมอบหมายช่าง' })).toBeNull()
  })
})

describe('V2 My Work', () => {
  it('splits PRIMARY and COLLABORATOR and links to the V2 detail', async () => {
    const calls = setup((url) =>
      url === '/api/v1/my-work'
        ? jsonResponse({
            resolution: 'RESOLVED',
            technician_id: 'TEC-SYN-1',
            items: [
              { work_type: 'REPAIR', job_id: 'RPR-SYN-1', asset_type: 'VEHICLE', asset_id: 'VEH-SYN-1', status: 'OPEN', opened_at: '2026-01-01T00:00:00Z', assignment_role: 'PRIMARY', assignment_set_id: 'S1', assigned_at: '2026-01-01T00:00:00Z' },
              { work_type: 'PM', job_id: 'PMWO-SYN-1', asset_type: 'VEHICLE', asset_id: 'VEH-SYN-1', status: 'OPEN', opened_at: '2026-01-01T00:00:00Z', assignment_role: 'COLLABORATOR', assignment_set_id: 'S2', assigned_at: '2026-01-01T00:00:00Z' },
            ],
          })
        : undefined,
    )
    renderAt('/my-work')
    const primary = await screen.findByTestId('v2-my-work-primary')
    expect(within(primary).getByRole('link', { name: /RPR-SYN-1/ })).toHaveAttribute('href', '/repairs/RPR-SYN-1')
    expect(within(screen.getByTestId('v2-my-work-collaborator')).getByRole('link', { name: /PMWO-SYN-1/ })).toHaveAttribute(
      'href',
      '/pm/work-orders/PMWO-SYN-1',
    )
    expect(calls.some((c) => c.url.includes('/repairs/my-work') || c.url.includes('/pm/work-orders/my-work'))).toBe(false)
  })

  it.each(['PERSONNEL_UNLINKED', 'TECHNICIAN_SCOPE_UNPROVEN', 'SOMETHING_NEW'])('unresolved %s is explicit, never an empty list', async (resolution) => {
    setup((url) => (url === '/api/v1/my-work' ? jsonResponse({ resolution, technician_id: null, items: null }) : undefined))
    renderAt('/my-work')
    expect(await screen.findByTestId('v2-my-work-unresolved')).toHaveTextContent(resolution)
    expect(screen.queryByText('ยังไม่มีงานที่มอบหมายให้คุณ')).toBeNull()
  })

  it('failure: ErrorState with code; no legacy fallback request', async () => {
    const calls = setup((url) => (url === '/api/v1/my-work' ? jsonResponse(errorBody('TECHNICIAN_MASTER_DATA_INVALID', 'REQ-MW'), 500) : undefined))
    renderAt('/my-work')
    expect(await screen.findByText('รหัสข้อผิดพลาด: TECHNICIAN_MASTER_DATA_INVALID')).toBeInTheDocument()
    expect([...new Set(calls.map((c) => c.url))].sort()).toEqual(['/api/v1/me', '/api/v1/my-work', '/api/v1/repair-requests/mine?page_size=50'])
  })
})

describe('V2 U1 waiting queues', () => {
  const queue = (items: unknown[]) => ({ data_context: 'TEST', items, page: 1, page_size: 50, total_items: items.length })
  const item = (job_id: string, assignment_status: string, issues: Record<string, number> = {}) => ({
    work_type: 'REPAIR', job_id, asset_type: 'VEHICLE', asset_id: 'VEH-SYN-1', status: 'OPEN', opened_at: '2026-01-01T00:00:00Z', assignment_status, issues,
  })

  it('shows NONE / AMBIGUOUS / DATA_INVALID distinctly with issue codes, each linking to the detail', async () => {
    setup((url) => {
      if (url.startsWith('/api/v1/repairs/v2-waiting-assignment')) {
        return jsonResponse(queue([item('RPR-A', 'NONE'), item('RPR-B', 'AMBIGUOUS'), item('RPR-C', 'DATA_INVALID', { SET_INCOMPLETE: 1 })]))
      }
      if (url.startsWith('/api/v1/pm/work-orders/v2-waiting-assignment')) return jsonResponse(queue([]))
      return undefined
    })
    renderAt('/waiting-assignment')
    const repairs = await screen.findByTestId('v2-waiting-REPAIR')
    await within(repairs).findByRole('link', { name: 'RPR-A' })
    const statuses = within(repairs).getAllByTestId('v2-waiting-status').map((el) => el.getAttribute('data-status'))
    expect(statuses).toEqual(['NONE', 'AMBIGUOUS', 'DATA_INVALID'])
    expect(within(repairs).getByText(/SET_INCOMPLETE × 1/)).toBeInTheDocument()
    expect(within(repairs).getByRole('link', { name: 'RPR-C' })).toHaveAttribute('href', '/repairs/RPR-C')
    expect(await within(screen.getByTestId('v2-waiting-PM')).findByText('ไม่มีงานที่รอมอบหมายช่าง')).toBeInTheDocument()
  })

  it('per-capability visibility; neither → permission denied; no legacy waiting route', async () => {
    const calls = setup((url) => (url.startsWith('/api/v1/pm/work-orders/v2-waiting-assignment') ? jsonResponse(queue([])) : undefined), me({ capabilities: ['can_view', 'can_manage_pm'] }))
    renderAt('/waiting-assignment')
    expect(await screen.findByTestId('v2-waiting-PM')).toBeInTheDocument()
    expect(screen.queryByTestId('v2-waiting-REPAIR')).toBeNull()
    expect(calls.some((c) => c.url.includes('/repairs/waiting-assignment'))).toBe(false)
    expect(calls.some((c) => c.url.includes('/repairs/v2-waiting-assignment'))).toBe(false)
  })

  it('no capability: permission denied, no queue request', async () => {
    const calls = setup(() => undefined, me({ capabilities: ['can_view'] }))
    renderAt('/waiting-assignment')
    expect(await screen.findByText('ไม่มีสิทธิ์เข้าถึง')).toBeInTheDocument()
    expect(calls.map((c) => c.url)).toEqual(['/api/v1/me'])
  })

  it('a failed refresh replaces the rows with ErrorState (never a stale queue)', async () => {
    let fail = false
    setup((url) => {
      if (url.startsWith('/api/v1/repairs/v2-waiting-assignment')) {
        return fail ? jsonResponse(errorBody('TECHNICIAN_ASSIGNMENT_JOB_DATA_INVALID', 'REQ-Q', { issues: { JOB_STATUS_INVALID: 1 } }), 500) : jsonResponse(queue([item('RPR-A', 'NONE')]))
      }
      return undefined
    }, me({ capabilities: ['can_view', 'can_manage_repair'] }))
    const user = userEvent.setup()
    renderAt('/waiting-assignment')
    const repairs = await screen.findByTestId('v2-waiting-REPAIR')
    expect(await within(repairs).findByRole('link', { name: 'RPR-A' })).toBeInTheDocument()
    fail = true
    await user.click(within(repairs).getByRole('button', { name: 'รีเฟรช' }))
    expect(await within(repairs).findByText('รหัสข้อผิดพลาด: TECHNICIAN_ASSIGNMENT_JOB_DATA_INVALID')).toBeInTheDocument()
    expect(within(repairs).getByText('รหัสอ้างอิง: REQ-Q')).toBeInTheDocument()
    expect(within(repairs).queryByRole('link', { name: 'RPR-A' })).toBeNull()
  })
})

describe('B5 navigation cutover', () => {
  const noneSet = { job_id: 'RPR-SYN-1', assignment_model: 'TECHNICIAN_V2', status: 'NONE', current: null, sets: [] }

  it('the Repair detail keeps its non-assignment workflow and has no legacy free-text assignment', async () => {
    const calls = setup(jobHandler(repairJob(), noneSet), me({ capabilities: [...ALL_CAPS, 'can_close_repair'] }))
    renderAt('/repairs/RPR-SYN-1')
    expect(await screen.findByTestId('v2-current-set')).toBeInTheDocument()
    expect(screen.getByLabelText('เพิ่มการดำเนินการ')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'บันทึกการดำเนินการ' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '+ เพิ่มอะไหล่' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'ปิดใบแจ้งซ่อม' })).toBeInTheDocument()
    expect(screen.queryByLabelText('ช่างผู้รับผิดชอบหลัก')).toBeNull()
    expect(screen.queryByLabelText('ผู้ร่วมงาน (คั่นด้วยจุลภาค)')).toBeNull()
    expect(screen.queryByRole('button', { name: 'บันทึกการมอบหมาย' })).toBeNull()
    expect(calls.some((c) => c.url.endsWith('/assign') || c.url.includes('assignment-history'))).toBe(false)
  })

  it('a LEGACY Repair keeps its actions / parts / close, with the stored legacy ids read-only', async () => {
    setup(jobHandler(repairJob({ assignment_model: 'LEGACY', primary_technician: 'legacy-user-7', collaborators: ['legacy-user-8'] }), null))
    renderAt('/repairs/RPR-SYN-1')
    expect(await screen.findByTestId('legacy-assignment-readonly')).toBeInTheDocument()
    expect(screen.getByText('legacy-user-8')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'บันทึกการดำเนินการ' })).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: /LEGACY_USER_ID/ })).toBeNull()
  })

  it('My Work keeps the caller’s own Repair Requests (UAT-F2) next to the V2 work', async () => {
    const calls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: string) => {
        calls.push(input)
        if (input === '/api/v1/me') return jsonResponse(me())
        if (input === '/api/v1/my-work') return jsonResponse({ resolution: 'RESOLVED', technician_id: 'TEC-SYN-1', items: [] })
        if (input.startsWith('/api/v1/repair-requests/mine')) {
          return jsonResponse({ items: [{ repair_request_id: 'RRQ-SYN-2', vehicle_id: 'VEH-SYN-1', reported_at: '2026-01-01T00:00:00Z', symptom_th: 'เสียงดัง', request_status: 'PENDING' }], page: 1, page_size: 50, total_items: 1 })
        }
        throw new Error(`unexpected ${input}`)
      }),
    )
    renderAt('/my-work')
    expect(await screen.findByText('ยังไม่มีงานที่มอบหมายให้คุณ')).toBeInTheDocument()
    expect(await screen.findByText('เสียงดัง')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'คำขอแจ้งซ่อมของฉัน' })).toBeInTheDocument()
    expect(calls.some((u) => u.includes('/repairs/my-work') || u.includes('/pm/work-orders/my-work'))).toBe(false)
  })

  it('queue and My Work items link to the canonical job detail pages', async () => {
    setup((url) =>
      url === '/api/v1/my-work'
        ? jsonResponse({
            resolution: 'RESOLVED',
            technician_id: 'TEC-SYN-1',
            items: [{ work_type: 'PM', job_id: 'PMWO-SYN-7', asset_type: 'VEHICLE', asset_id: 'VEH-SYN-1', status: 'OPEN', opened_at: '2026-01-01T00:00:00Z', assignment_role: 'PRIMARY', assignment_set_id: 'S', assigned_at: '2026-01-01T00:00:00Z' }],
          })
        : undefined,
    )
    renderAt('/my-work')
    expect(await screen.findByRole('link', { name: /PMWO-SYN-7/ })).toHaveAttribute('href', '/pm/work-orders/PMWO-SYN-7')
  })
})

describe('B5 creation pages wait for the server signal', () => {
  it('no create form (or legacy form) is offered while GET /me is still pending', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => {})))
    renderAt('/vehicle/VEH-SYN-1/repairs/new')
    expect(await screen.findByText('กำลังตรวจสอบสถานะของระบบ...')).toBeInTheDocument()
    expect(screen.queryByLabelText('อาการ/ปัญหาที่พบ')).toBeNull()
    expect(screen.queryByRole('button', { name: 'ส่งแจ้งซ่อม' })).toBeNull()
  })
})
