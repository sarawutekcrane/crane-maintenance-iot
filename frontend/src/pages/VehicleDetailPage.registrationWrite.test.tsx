import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import { registryPendingStore, storageKey } from '../lib/registryPending'
import { VehicleDetailPage } from './VehicleDetailPage'

// R8 (Owner source approval 2026-11-18): the reads R8 added to this page (vehicle overview,
// crew panel, branch reference lists) are answered here, OUTSIDE the test's own routes and
// call log, so every pre-R8 assertion of this file stays exactly as it was.
function r8Answer(input: RequestInfo | URL | string): Response | null {
  const url = new URL(String(input), 'http://localhost')
  const path = url.pathname.replace(/^\/api\/v1/, '')
  const ok = (body: unknown) =>
    new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
  const vehicle = /^\/vehicles\/([^/]+)\/(machine-state|part-lifetime|alerts|crew-assignments)$/.exec(path)
  if (vehicle) {
    const id = decodeURIComponent(vehicle[1])
    if (vehicle[2] === 'machine-state') return ok({ vehicle_id: id, readings: [], note: '' })
    if (vehicle[2] === 'part-lifetime')
      return ok({ asset_type: 'VEHICLE', asset_id: id, policy_context: 'TEST', instances: [], positions: [] })
    if (vehicle[2] === 'alerts') return ok([])
    return ok({ vehicle_id: id, intervals: [] })
  }
  if (/^\/pm\/due\/vehicles\/[^/]+$/.test(path))
    return ok({ vehicle_id: '', machine_no: '', model_id: '', state: 'UNKNOWN', explanation: '', assignments: [], plans: [], sets: [] })
  if (path === '/repairs' && url.searchParams.get('asset_id') !== null && url.searchParams.get('page_size') === '1')
    return ok({ items: [], page: 1, page_size: 1, total_items: 0 })
  if (path === '/findings/follow-up' && url.searchParams.get('asset_id') !== null) return ok([])
  return null
}

// Phase 7 Batch 7O2b — the registration editor on Vehicle Detail: capability
// gating, history-driven settlement (I-OC-01 at unit level), late responses
// after navigation (W-13) and settlement at load (W-11). Synthetic data only.

const TS = '2026-01-15T08:00:00Z'
const UNKNOWN = 'ยังไม่ทราบผลการบันทึก — ระบบจะตรวจสอบจากประวัติ'

function json(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } })
}

function detail(id: string, no: string | null) {
  const field = (value: string | null) => (value === null ? { state: 'NOT_RECORDED', value: null } : { state: 'RECORDED', value })
  return {
    vehicle: {
      vehicle_id: id, machine_no: `M-${id}`, model_id: 'SYN-MODEL', serial_number: null, operational_status: 'WORKING',
      created_at: TS, updated_at: TS,
      registry: { registration_no: field(no), registration_province: field(null), responsible_branch: field(null) },
    },
    model: null,
    components: [],
  }
}

function regHistory(id: string, requestIds: string[], consistency = 'CONSISTENT') {
  return {
    vehicle_id: id,
    current: { registration_no: { state: 'NOT_RECORDED', value: null }, registration_province: { state: 'NOT_RECORDED', value: null } },
    consistency: requestIds.length ? consistency : 'NO_HISTORY', history_revision: 'RHR1-0', excluded_test_rows: 0, issues: {},
    items: requestIds.map((rid, n) => ({
      change_id: `VRH-${n}`, change_kind: 'CHANGE', old_registration_no: null, old_registration_province_code: null,
      new_registration_no: 'ใหม่', new_registration_province_code: null, recorded_at: '2026-10-05T00:00:00+00:00',
      recorded_by: 'u1', request_id: rid, related_request_id: null, accepted_exceptions: [], note_th: null,
    })),
  }
}

const BRANCH_HISTORY = (id: string) => ({
  asset_type: 'VEHICLE', asset_id: id, timeline_status: 'VALID', current: { branch_id: null, source: 'NONE' },
  master: { state: 'NOT_RECORDED', value: null }, consistency: 'NO_HISTORY', history_revision: 'BHR1-0', baseline: null,
  events: [], records: [], excluded_test_rows: 0, issues: {},
})

type Handler = (init: RequestInit, rid: string) => Response | Promise<Response>

function installApi(capabilities: string[], extra: Record<string, Handler>) {
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = new URL(String(input), 'http://localhost')
      const r8 = r8Answer(url)
      if (r8) return r8
      const method = (init.method ?? 'GET').toUpperCase()
      const key = `${method} ${url.pathname.replace('/api/v1', '')}`
      calls.push(key)
      const rid = new Headers(init.headers).get('X-Request-Id') ?? ''
      if (extra[key]) return extra[key](init, rid)
      if (key === 'GET /me') return json({ user_id: 'u1', roles: ['MAINTENANCE_MANAGER'], capabilities, is_dev_auth: true })
      if (key === 'GET /branches') return json({ items: [] })
      if (key === 'GET /provinces') return json({ items: [] })
      const match = /^GET \/vehicles\/([^/]+)(\/status-history|\/branch-history|\/latest-location)?$/.exec(key)
      if (match) {
        const id = decodeURIComponent(match[1])
        if (match[2] === '/status-history') return json([])
        if (match[2] === '/branch-history') return json(BRANCH_HISTORY(id))
        if (match[2] === '/latest-location') return json({ error: { code: 'NOT_FOUND', message: 'x', details: null, request_id: 'x' } }, 404)
        return json(detail(id, null))
      }
      throw new Error(`unexpected request ${key}`)
    }),
  )
  return calls
}

function renderPage(path: string) {
  return render(
    <CapabilitiesProvider>
      <MemoryRouter initialEntries={[path]}>
        <Link to="/vehicle/SYN-OTHER">ไปอีกคัน</Link>
        <Routes>
          <Route path="/vehicle/:vehicleId" element={<VehicleDetailPage />} />
        </Routes>
      </MemoryRouter>
    </CapabilitiesProvider>,
  )
}

beforeEach(() => window.localStorage.clear())
afterEach(() => vi.unstubAllGlobals())

describe('capability gating', () => {
  it('only holders of can_edit_vehicle_registration see the editor; the history panel stays read-only', async () => {
    installApi(['can_view', 'can_edit_vehicle_registration'], {
      'GET /vehicles/SYN-G1/registration-history': () => json(regHistory('SYN-G1', [])),
    })
    const holder = renderPage('/vehicle/SYN-G1')
    expect(await screen.findByRole('button', { name: 'เปลี่ยนทะเบียน' })).toBeInTheDocument()
    const panel = await screen.findByTestId('registration-history-panel')
    await within(panel).findByText('ยังไม่มีประวัติ')
    expect(within(panel).queryAllByRole('button')).toHaveLength(0)
    holder.unmount()
    vi.unstubAllGlobals()
    installApi(['can_view'], { 'GET /vehicles/SYN-G1/registration-history': () => json(regHistory('SYN-G1', [])) })
    renderPage('/vehicle/SYN-G1')
    await screen.findByRole('heading', { name: 'ทะเบียนและสาขาที่รับผิดชอบ' })
    await screen.findByTestId('registration-history-panel')
    expect(screen.queryByRole('button', { name: 'เปลี่ยนทะเบียน' })).toBeNull()
  })
})

describe('history-driven settlement', () => {
  it('I-OC-01 (unit): a 500 after a real write shows the uncertainty banner; the next history read settles it', async () => {
    let recorded = false
    let sentId = ''
    installApi(['can_view', 'can_edit_vehicle_registration'], {
      'PATCH /vehicles/SYN-S1/registration': (_init, rid) => {
        sentId = rid
        return json({ error: { code: 'INTERNAL_ERROR', message: 'x', details: null, request_id: rid } }, 500)
      },
      'GET /vehicles/SYN-S1/registration-history': () => json(regHistory('SYN-S1', recorded ? [sentId] : [])),
    })
    const user = userEvent.setup()
    renderPage('/vehicle/SYN-S1')
    await user.click(await screen.findByRole('button', { name: 'เปลี่ยนทะเบียน' }))
    await user.type(screen.getByLabelText('ทะเบียนรถ'), 'ใหม่')
    await user.click(screen.getByRole('button', { name: 'บันทึกทะเบียน' }))
    const banner = await screen.findByTestId('registration-intent-banner')
    expect(within(banner).getByText(UNKNOWN)).toBeInTheDocument()
    // the automatic re-read does not contain the record yet: still uncertain
    await waitFor(() => expect(within(banner).getByText(/ยังไม่พบคำขอนี้ในประวัติ/)).toBeInTheDocument())
    expect(registryPendingStore.list('u1', 'SYN-S1')[0].state).toBe('UNCONFIRMED')
    recorded = true // the write had in fact happened
    await user.click(within(banner).getByRole('button', { name: 'ตรวจสอบผลจากประวัติอีกครั้ง' }))
    await waitFor(() => expect(screen.queryByTestId('registration-intent-banner')).toBeNull())
    expect(screen.getByTestId('registration-settlement-notice')).toHaveTextContent('ตรวจสอบจากประวัติแล้ว')
    expect(registryPendingStore.list('u1', 'SYN-S1')).toEqual([])
  })

  it('an intent left by an earlier page is settled at the next history read on load', async () => {
    const rid = '33333333-2222-4333-8444-555555555555'
    window.localStorage.setItem(
      storageKey('u1', 'SYN-L1'),
      JSON.stringify([{
        request_id: rid, operation: 'registration', vehicle_id: 'SYN-L1', body: { registration_no: 'ใหม่' },
        submitted_at: new Date().toISOString(), state: 'SUBMITTING', page_instance: 'old', route_epoch: 0, prior_uncertain: false,
      }]),
    )
    installApi(['can_view', 'can_edit_vehicle_registration'], {
      'GET /vehicles/SYN-L1/registration-history': () => json(regHistory('SYN-L1', [rid], 'MISMATCH')),
    })
    renderPage('/vehicle/SYN-L1')
    const banner = await screen.findByTestId('registration-intent-banner')
    await waitFor(() => expect(within(banner).getByText(/บันทึกในประวัติแล้ว แต่ทะเบียนในข้อมูลทะเบียนรถยังไม่ตรงกับประวัติ/)).toBeInTheDocument())
    expect(registryPendingStore.list('u1', 'SYN-L1')[0].state).toBe('RECORDED_PROJECTION_PENDING')
  })
})

describe('late responses after navigation (W-13)', () => {
  it('a success delivered after moving to another vehicle updates bookkeeping only', async () => {
    let release!: (r: Response) => void
    let sentId = ''
    installApi(['can_view', 'can_edit_vehicle_registration'], {
      'PATCH /vehicles/SYN-N1/registration': (_init, rid) => {
        sentId = rid
        return new Promise<Response>((resolve) => {
          release = resolve
        })
      },
      'GET /vehicles/SYN-N1/registration-history': () => json(regHistory('SYN-N1', [])),
      'GET /vehicles/SYN-OTHER/registration-history': () => json(regHistory('SYN-OTHER', [])),
    })
    const user = userEvent.setup()
    renderPage('/vehicle/SYN-N1')
    await user.click(await screen.findByRole('button', { name: 'เปลี่ยนทะเบียน' }))
    await user.type(screen.getByLabelText('ทะเบียนรถ'), 'ใหม่')
    await user.click(screen.getByRole('button', { name: 'บันทึกทะเบียน' }))
    await waitFor(() => expect(sentId).not.toBe(''))
    expect(registryPendingStore.list('u1', 'SYN-N1')).toHaveLength(1)
    await user.click(screen.getByRole('link', { name: 'ไปอีกคัน' }))
    await screen.findByText('รหัสยานพาหนะ: SYN-OTHER')
    await act(async () => {
      release(json({ request_id: sentId, changed: false, warnings: [] }, 200, { 'X-Request-Id': sentId }))
    })
    await waitFor(() => expect(registryPendingStore.list('u1', 'SYN-N1')).toEqual([]))
    expect(screen.queryByTestId('registration-editor-message')).toBeNull()
    expect(screen.queryByTestId('registration-intent-banner')).toBeNull()
    expect(screen.getByText('รหัสยานพาหนะ: SYN-OTHER')).toBeInTheDocument()
  })
})
