import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { VehicleDetailPage } from './VehicleDetailPage'

// Phase 7 Batch 7O2a — registry display, read-only history panels, keyed
// view and stale-read guards on Vehicle Detail (contract Final Rev2 §7.1,
// §7.2, §7.4, §4.5, §10.1, §10.2, §10.6). Imports only the page, so this file
// also runs against the baseline page (where it fails on behaviour).
// Synthetic data only.

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function apiError(code: string, status: number, requestId = `req-${code}`) {
  return json({ error: { code, message: code, details: null, request_id: requestId } }, status)
}

const TS = '2026-01-15T08:00:00Z'

function registry(no: string | null, province: string | null, branch: string | null, state = 'RECORDED') {
  const field = (value: string | null) =>
    value === null ? { state: state === 'RECORDED' ? 'NOT_RECORDED' : state, value: null } : { state: 'RECORDED', value }
  return { registration_no: field(no), registration_province: field(province), responsible_branch: field(branch) }
}

function detail(id: string, machine: string, reg = registry('0012', 'TH-99', 'BR-SYN-A')) {
  return {
    vehicle: {
      vehicle_id: id, machine_no: machine, model_id: 'SYN-MODEL', serial_number: null,
      operational_status: 'WORKING', created_at: TS, updated_at: TS, registry: reg,
    },
    model: null,
    components: [],
  }
}

const BRANCHES = { items: [{ branch_id: 'BR-SYN-A', branch_name: 'สาขาทดสอบเอ', is_active: true }] }
const PROVINCES = { items: [{ province_code: 'TH-21', province_name_th: 'ระยอง', is_active: true }] }

function branchHistory(id: string, records = 1) {
  const recs = Array.from({ length: records }, (_, i) => ({
    record_id: `ABH-${id}-${i}`, record_kind: 'ASSIGNMENT', entry_operation: 'TRANSFER', event_id: `ABH-${id}-${i}`,
    revision_no: 1, supersedes_record_id: null, branch_id: 'BR-SYN-A', effective_at: '2026-08-31T17:00:00+00:00',
    recorded_from_branch_id: null, recorded_from_source: 'NONE', recorded_at: '2026-09-01T03:00:00+00:00',
    recorded_by: 'SYN-USER', request_id: `req-${id}-${i}`, related_request_id: null, reason_th: null,
    reconciled_old_master_branch_id: null,
  }))
  return {
    asset_type: 'VEHICLE', asset_id: id, timeline_status: 'VALID',
    current: records ? { branch_id: 'BR-SYN-A', source: 'EVENT' } : { branch_id: 'BR-SYN-A', source: 'IMPORTED_MASTER' },
    master: { state: 'RECORDED', value: 'BR-SYN-A' }, consistency: records ? 'CONSISTENT' : 'NO_HISTORY',
    history_revision: 'BHR1-00000000000000000000', baseline: records ? { branch_id: null, source: 'NONE' } : null,
    events: recs.map((r) => ({
      event_id: r.event_id, in_force: true, head_record_id: r.record_id, revision_no: 1, to_branch_id: 'BR-SYN-A',
      effective_at: r.effective_at, effective_precision: 'DATE', derived_from_branch_id: null,
      original_entry_from_branch_id: null, original_entry_from_source: 'NONE', head_entry_from_branch_id: null,
      head_entry_from_source: 'NONE', derived_end_at: null, notes: [],
    })),
    records: recs, excluded_test_rows: 0, issues: {},
  }
}

function registrationHistory(id: string, newNo: string | null = 'กข 1234') {
  return {
    vehicle_id: id,
    current: { registration_no: { state: 'RECORDED', value: newNo }, registration_province: { state: 'RECORDED', value: 'TH-21' } },
    consistency: newNo ? 'CONSISTENT' : 'NO_HISTORY', history_revision: 'RHR1-00000000000000000000',
    items: newNo
      ? [{
          change_id: `VRH-${id}`, change_kind: 'CHANGE', old_registration_no: null, old_registration_province_code: null,
          new_registration_no: newNo, new_registration_province_code: 'TH-21', recorded_at: '2026-09-02T03:00:00+00:00',
          recorded_by: 'SYN-USER', request_id: `rreq-${id}`, related_request_id: null, accepted_exceptions: [], note_th: null,
        }]
      : [],
    excluded_test_rows: 0, issues: {},
  }
}

type Handler = () => Response | Promise<Response>

/** Routes by exact path; unknown paths fail the test loudly. */
function installApi(routes: Record<string, Handler>) {
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://localhost')
      const path = url.pathname.replace('/api/v1', '')
      calls.push(`${(init?.method ?? 'GET').toUpperCase()} ${path}`)
      const handler = routes[path]
      if (!handler) throw new Error(`Unexpected fetch: ${path}`)
      return handler()
    }),
  )
  return calls
}

function vehicleRoutes(id: string, machine: string, overrides: Record<string, Handler> = {}): Record<string, Handler> {
  return {
    [`/vehicles/${id}`]: () => json(detail(id, machine)),
    [`/vehicles/${id}/status-history`]: () => json([]),
    [`/vehicles/${id}/latest-location`]: () => json(null),
    [`/vehicles/${id}/branch-history`]: () => json(branchHistory(id)),
    [`/vehicles/${id}/registration-history`]: () => json(registrationHistory(id)),
    ...overrides,
  }
}

function deferred() {
  let resolve!: (r: Response) => void
  const promise = new Promise<Response>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function renderAt(path: string, withLinks = false) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="/vehicle/:vehicleId"
          element={
            <>
              {withLinks && <Link to="/vehicle/SYN-V2">ไปคันที่สอง</Link>}
              <VehicleDetailPage />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  )
}

const refs = { '/branches': () => json(BRANCHES), '/provinces': () => json(PROVINCES) }

describe('VehicleDetailPage — 7O2a registry display', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows exact registration text, unknown province and resolved branch', async () => {
    installApi({ ...refs, ...vehicleRoutes('SYN-V1', 'SYN-M1') })
    renderAt('/vehicle/SYN-V1')
    expect(await screen.findByText('0012')).toBeInTheDocument()
    expect(await screen.findByText('รหัสไม่อยู่ในทะเบียน (TH-99)')).toBeInTheDocument()
    expect(screen.getAllByText('สาขาทดสอบเอ').length).toBeGreaterThan(0)
  })

  it('a reference outage shows the raw code, never "unknown code", and retries', async () => {
    let branchesUp = false
    installApi({
      ...refs,
      '/branches': () => (branchesUp ? json(BRANCHES) : apiError('BRANCH_MASTER_READ_FAILED', 503)),
      ...vehicleRoutes('SYN-V1', 'SYN-M1'),
    })
    renderAt('/vehicle/SYN-V1')
    expect((await screen.findAllByText('BR-SYN-A (ไม่สามารถโหลดชื่อได้)')).length).toBeGreaterThan(0)
    expect(screen.queryByText('รหัสไม่อยู่ในทะเบียน (BR-SYN-A)')).not.toBeInTheDocument()
    branchesUp = true
    await userEvent.setup().click(screen.getByRole('button', { name: 'ลองโหลดชื่อสาขา/จังหวัดอีกครั้ง' }))
    expect((await screen.findAllByText('สาขาทดสอบเอ')).length).toBeGreaterThan(0)
  })

  it('distinguishes a column missing from the source from a blank value', async () => {
    const reg = {
      registration_no: { state: 'NOT_IN_SCHEMA', value: null },
      registration_province: { state: 'NOT_IN_SCHEMA', value: null },
      responsible_branch: { state: 'NOT_RECORDED', value: null },
    }
    installApi({ ...refs, ...vehicleRoutes('SYN-V1', 'SYN-M1', { '/vehicles/SYN-V1': () => json(detail('SYN-V1', 'SYN-M1', reg)) }) })
    renderAt('/vehicle/SYN-V1')
    expect(await screen.findAllByText('แหล่งข้อมูลยังไม่มีช่องนี้')).toHaveLength(2)
    expect(screen.getByText('ยังไม่ได้บันทึก')).toBeInTheDocument()
  })
})

describe('VehicleDetailPage — 7O2a history panels', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('a failed history read is an error with retry, never an empty history; panels are independent', async () => {
    let branchUp = false
    installApi({
      ...refs,
      ...vehicleRoutes('SYN-V1', 'SYN-M1', {
        '/vehicles/SYN-V1/branch-history': () =>
          branchUp ? json(branchHistory('SYN-V1', 0)) : apiError('BRANCH_HISTORY_READ_FAILED', 503, 'req-bh'),
      }),
    })
    renderAt('/vehicle/SYN-V1')
    const branchPanel = await screen.findByTestId('branch-history-panel')
    expect(await within(branchPanel).findByText('ไม่สามารถอ่านประวัติสาขาที่รับผิดชอบได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง')).toBeInTheDocument()
    expect(within(branchPanel).getByText(/req-bh/)).toBeInTheDocument()
    expect(within(branchPanel).queryByText('ยังไม่มีประวัติ')).not.toBeInTheDocument()
    // The other panel and the detail are unaffected.
    const registrationPanel = screen.getByTestId('registration-history-panel')
    expect(await within(registrationPanel).findByText(/กข 1234/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'SYN-M1' })).toBeInTheDocument()
    // Retry; a successful response with no rows is the only "no history".
    branchUp = true
    await userEvent.setup().click(within(branchPanel).getByRole('button', { name: 'ลองโหลดประวัติสาขาอีกครั้ง' }))
    expect(await within(branchPanel).findByText('ยังไม่มีประวัติ')).toBeInTheDocument()
  })

  it('a response of the wrong shape is an error, not an empty history', async () => {
    installApi({
      ...refs,
      ...vehicleRoutes('SYN-V1', 'SYN-M1', { '/vehicles/SYN-V1/registration-history': () => json([]) }),
    })
    renderAt('/vehicle/SYN-V1')
    const panel = await screen.findByTestId('registration-history-panel')
    expect(await within(panel).findByText(/รูปแบบไม่ถูกต้อง/)).toBeInTheDocument()
    expect(within(panel).queryByText('ยังไม่มีประวัติ')).not.toBeInTheDocument()
  })

  it('history panels are read-only: no edit, transfer, correction or reconciliation control', async () => {
    installApi({ ...refs, ...vehicleRoutes('SYN-V1', 'SYN-M1') })
    renderAt('/vehicle/SYN-V1')
    const branchPanel = await screen.findByTestId('branch-history-panel')
    await within(branchPanel).findByText('ตามประวัติการย้ายสาขา', { exact: false })
    const registrationPanel = screen.getByTestId('registration-history-panel')
    await within(registrationPanel).findByText(/กข 1234/)
    expect(within(branchPanel).queryAllByRole('button')).toHaveLength(0)
    expect(within(registrationPanel).queryAllByRole('button')).toHaveLength(0)
    expect(screen.queryByRole('button', { name: /ย้ายสาขา|แก้ไขทะเบียน|ยกเลิกการย้าย|ปรับข้อมูล/ })).not.toBeInTheDocument()
  })

  it('the legacy status-history empty fallback is unchanged', async () => {
    installApi({
      ...refs,
      ...vehicleRoutes('SYN-V1', 'SYN-M1', {
        '/vehicles/SYN-V1/status-history': () => apiError('VEHICLE_STATUS_HISTORY_READ_FAILED', 503),
      }),
    })
    renderAt('/vehicle/SYN-V1')
    // Status history keeps its documented `[]` fallback (Rev2 §10.6) ...
    expect(await screen.findByText('ยังไม่มีการเปลี่ยนสถานะสำหรับยานพาหนะนี้')).toBeInTheDocument()
  })
})

describe('VehicleDetailPage — 7O2a keyed view and stale-read guards', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('navigating to another vehicle resets an open machine-number editor (Rev2 §10.6)', async () => {
    installApi({ ...refs, ...vehicleRoutes('SYN-V1', 'SYN-M1'), ...vehicleRoutes('SYN-V2', 'SYN-M2') })
    renderAt('/vehicle/SYN-V1', true)
    const user = userEvent.setup()
    await screen.findByRole('heading', { name: 'SYN-M1' })
    await user.click(screen.getByRole('button', { name: 'แก้ไข' }))
    await user.clear(screen.getByLabelText('เลขเครื่องจักรใหม่'))
    await user.type(screen.getByLabelText('เลขเครื่องจักรใหม่'), 'ค่าที่พิมพ์ค้างไว้')
    await user.click(screen.getByRole('link', { name: 'ไปคันที่สอง' }))
    expect(await screen.findByRole('heading', { name: 'SYN-M2' })).toBeInTheDocument()
    expect(screen.queryByLabelText('เลขเครื่องจักรใหม่')).not.toBeInTheDocument()
    expect(screen.queryByDisplayValue('ค่าที่พิมพ์ค้างไว้')).not.toBeInTheDocument()
  })

  it('a delayed detail for the previous vehicle never replaces the current one', async () => {
    const slow = deferred()
    installApi({
      ...refs,
      ...vehicleRoutes('SYN-V1', 'SYN-M1', { '/vehicles/SYN-V1': () => slow.promise }),
      ...vehicleRoutes('SYN-V2', 'SYN-M2'),
    })
    renderAt('/vehicle/SYN-V1', true)
    await userEvent.setup().click(screen.getByRole('link', { name: 'ไปคันที่สอง' }))
    expect(await screen.findByRole('heading', { name: 'SYN-M2' })).toBeInTheDocument()
    await act(async () => slow.resolve(json(detail('SYN-V1', 'SYN-M1'))))
    expect(screen.getByRole('heading', { name: 'SYN-M2' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'SYN-M1' })).not.toBeInTheDocument()
  })

  it('a delayed history response for the previous vehicle never appears on the next', async () => {
    const slowBranch = deferred()
    const slowRegistration = deferred()
    installApi({
      ...refs,
      ...vehicleRoutes('SYN-V1', 'SYN-M1', {
        '/vehicles/SYN-V1/branch-history': () => slowBranch.promise,
        '/vehicles/SYN-V1/registration-history': () => slowRegistration.promise,
      }),
      ...vehicleRoutes('SYN-V2', 'SYN-M2', {
        '/vehicles/SYN-V2/registration-history': () => json(registrationHistory('SYN-V2', null)),
      }),
    })
    renderAt('/vehicle/SYN-V1', true)
    await screen.findByRole('heading', { name: 'SYN-M1' })
    await userEvent.setup().click(screen.getByRole('link', { name: 'ไปคันที่สอง' }))
    await screen.findByRole('heading', { name: 'SYN-M2' })
    const registrationPanel = screen.getByTestId('registration-history-panel')
    expect(await within(registrationPanel).findByText('ยังไม่มีประวัติ')).toBeInTheDocument()
    await act(async () => {
      slowBranch.resolve(apiError('BRANCH_HISTORY_READ_FAILED', 503))
      slowRegistration.resolve(json(registrationHistory('SYN-V1', 'ทะเบียนคันแรก')))
    })
    expect(screen.queryByText(/ทะเบียนคันแรก/)).not.toBeInTheDocument()
    expect(within(registrationPanel).getByText('ยังไม่มีประวัติ')).toBeInTheDocument()
    expect(screen.queryByText('ไม่สามารถอ่านประวัติสาขาที่รับผิดชอบได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง')).not.toBeInTheDocument()
  })

  it('a late machine-number result from the previous vehicle does not reload or touch the next', async () => {
    const slowPatch = deferred()
    const calls = installApi({ ...refs, ...vehicleRoutes('SYN-V1', 'SYN-M1'), ...vehicleRoutes('SYN-V2', 'SYN-M2') })
    renderAt('/vehicle/SYN-V1', true)
    const user = userEvent.setup()
    await screen.findByRole('heading', { name: 'SYN-M1' })
    const original = vi.mocked(fetch).getMockImplementation()!
    vi.mocked(fetch).mockImplementation(async (input, init) =>
      (init?.method ?? 'GET').toUpperCase() === 'PATCH' ? slowPatch.promise : original(input, init),
    )
    await user.click(screen.getByRole('button', { name: 'แก้ไข' }))
    await user.click(screen.getByRole('button', { name: 'บันทึก' }))
    await user.click(screen.getByRole('link', { name: 'ไปคันที่สอง' }))
    await screen.findByRole('heading', { name: 'SYN-M2' })
    const before = calls.length
    await act(async () => slowPatch.resolve(json(detail('SYN-V1', 'SYN-M1').vehicle)))
    await waitFor(() => expect(screen.getByRole('heading', { name: 'SYN-M2' })).toBeInTheDocument())
    expect(calls.slice(before).filter((c) => c.includes('SYN-V1'))).toEqual([])
  })

  it('history requests encode the vehicle id', async () => {
    // ':' stays raw in a URL path but encodeURIComponent turns it into %3A.
    const id = 'SYN-V:1'
    const enc = encodeURIComponent(id)
    const calls = installApi({
      ...refs,
      [`/vehicles/${id}`]: () => json(detail(id, 'SYN-M1')),
      [`/vehicles/${id}/status-history`]: () => json([]),
      [`/vehicles/${id}/latest-location`]: () => json(null),
      [`/vehicles/${enc}/branch-history`]: () => json(branchHistory(id)),
      [`/vehicles/${enc}/registration-history`]: () => json(registrationHistory(id)),
    })
    renderAt(`/vehicle/${enc}`)
    await screen.findByRole('heading', { name: 'SYN-M1' })
    await waitFor(() => expect(calls).toContain(`GET /vehicles/${enc}/branch-history`))
    expect(calls).toContain(`GET /vehicles/${enc}/registration-history`)
  })
})
