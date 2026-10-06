import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import { VehicleDetailPage } from './VehicleDetailPage'

// Phase 7 Batch 7O2d — I-04: the Final Rev2 §10.6 keyed vehicle-detail
// remount (`<VehicleDetailView key={vehicleId} />`), reviewed as one named
// expectation. Moving from vehicle A to vehicle B in-app (no reload):
//   - A's open machine-number editor is gone (also pinned in 7O2a);
//   - A's open status dialog is gone;
//   - A's open registration editor and branch dialog / management area are
//     not carried into B;
//   - a late status-change result from A does not change B's view or trigger
//     any read for A.
// Synthetic data only.

const TS = '2026-01-15T08:00:00Z'
const CAPS = ['can_view', 'can_edit_vehicle_registration', 'can_transfer_vehicle_branch', 'can_correct_branch_history']

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function detail(id: string, machine: string, status = 'WORKING') {
  return {
    vehicle: {
      vehicle_id: id, machine_no: machine, model_id: 'SYN-MODEL', serial_number: null, operational_status: status,
      created_at: TS, updated_at: TS,
      registry: {
        registration_no: { state: 'RECORDED', value: `REG-${id}` },
        registration_province: { state: 'NOT_RECORDED', value: null },
        responsible_branch: { state: 'RECORDED', value: 'BR-SYN-A' },
      },
    },
    model: null,
    components: [],
  }
}

function branchHistory(id: string) {
  return {
    asset_type: 'VEHICLE', asset_id: id, timeline_status: 'VALID', current: { branch_id: 'BR-SYN-A', source: 'IMPORTED_MASTER' },
    master: { state: 'RECORDED', value: 'BR-SYN-A' }, consistency: 'NO_HISTORY', history_revision: 'BHR1-0', baseline: null,
    events: [], records: [], excluded_test_rows: 0, issues: {},
  }
}

function registrationHistory(id: string) {
  return {
    vehicle_id: id,
    current: { registration_no: { state: 'NOT_RECORDED', value: null }, registration_province: { state: 'NOT_RECORDED', value: null } },
    consistency: 'NO_HISTORY', history_revision: 'RHR1-0', excluded_test_rows: 0, issues: {}, items: [],
  }
}

function deferred() {
  let resolve!: (r: Response) => void
  const promise = new Promise<Response>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

type Handler = () => Response | Promise<Response>

function installApi(extra: Record<string, Handler> = {}) {
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = new URL(String(input), 'http://localhost')
      const key = `${(init.method ?? 'GET').toUpperCase()} ${url.pathname.replace('/api/v1', '')}`
      calls.push(key)
      if (extra[key]) return extra[key]()
      if (key === 'GET /me') return json({ user_id: 'u1', roles: ['MAINTENANCE_MANAGER'], capabilities: CAPS, is_dev_auth: true })
      if (key === 'GET /branches') return json({ items: [{ branch_id: 'BR-SYN-A', branch_name: 'สาขาเอ', is_active: true }] })
      if (key === 'GET /provinces') return json({ items: [] })
      const match = /^GET \/vehicles\/([^/]+)(\/status-history|\/branch-history|\/registration-history|\/latest-location)?$/.exec(key)
      if (match) {
        const id = decodeURIComponent(match[1])
        if (match[2] === '/status-history') return json([])
        if (match[2] === '/branch-history') return json(branchHistory(id))
        if (match[2] === '/registration-history') return json(registrationHistory(id))
        if (match[2] === '/latest-location') return json(null)
        return json(detail(id, `M-${id}`))
      }
      throw new Error(`unexpected request ${key}`)
    }),
  )
  return calls
}

function renderAt(path: string) {
  return render(
    <CapabilitiesProvider>
      <MemoryRouter initialEntries={[path]}>
        <Link to="/vehicle/SYN-B">ไปคัน B</Link>
        <Routes>
          <Route path="/vehicle/:vehicleId" element={<VehicleDetailPage />} />
        </Routes>
      </MemoryRouter>
    </CapabilitiesProvider>,
  )
}

beforeEach(() => window.localStorage.clear())
afterEach(() => vi.unstubAllGlobals())

describe('I-04 — keyed vehicle-detail remount (Final Rev2 §10.6)', () => {
  it('an open status dialog from vehicle A is gone on vehicle B', async () => {
    installApi()
    const user = userEvent.setup()
    renderAt('/vehicle/SYN-A')
    await screen.findByRole('heading', { name: 'M-SYN-A' })
    await user.click(screen.getByRole('button', { name: 'เปลี่ยนสถานะ' }))
    const dialog = screen.getByRole('alertdialog', { name: 'เปลี่ยนสถานะการใช้งาน' })
    await user.type(within(dialog).getByLabelText('หมายเหตุ (ไม่บังคับ)'), 'หมายเหตุของคัน A')
    await user.click(screen.getByRole('link', { name: 'ไปคัน B' }))
    expect(await screen.findByRole('heading', { name: 'M-SYN-B' })).toBeInTheDocument()
    expect(screen.queryByRole('alertdialog', { name: 'เปลี่ยนสถานะการใช้งาน' })).toBeNull()
    expect(screen.queryByDisplayValue('หมายเหตุของคัน A')).toBeNull()
  })

  it('open registration and branch editors from vehicle A are not carried into vehicle B', async () => {
    installApi()
    const user = userEvent.setup()
    renderAt('/vehicle/SYN-A')
    await user.click(await screen.findByRole('button', { name: 'เปลี่ยนทะเบียน' }))
    const input = screen.getByLabelText('ทะเบียนรถ')
    await user.clear(input)
    await user.type(input, 'ค้างจากคัน A')
    const toggle = screen.getByRole('button', { name: 'จัดการประวัติสาขา' })
    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    await user.click(screen.getByRole('button', { name: 'ย้ายสาขา' }))
    expect(screen.getByTestId('branch-change-dialog')).toBeInTheDocument()
    await user.click(screen.getByRole('link', { name: 'ไปคัน B' }))
    expect(await screen.findByRole('heading', { name: 'M-SYN-B' })).toBeInTheDocument()
    expect(screen.queryByTestId('branch-change-dialog')).toBeNull()
    expect(screen.queryByLabelText('ทะเบียนรถ')).toBeNull()
    expect(screen.queryByDisplayValue('ค้างจากคัน A')).toBeNull()
    expect(await screen.findByRole('button', { name: 'จัดการประวัติสาขา' })).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByTestId('branch-history-actions')).toBeNull()
    expect(screen.getByText('REG-SYN-B')).toBeInTheDocument()
  })

  it('a late status-change result from vehicle A does not change vehicle B or reload A', async () => {
    const slow = deferred()
    const calls = installApi({ 'PATCH /vehicles/SYN-A/status': () => slow.promise })
    const user = userEvent.setup()
    renderAt('/vehicle/SYN-A')
    await screen.findByRole('heading', { name: 'M-SYN-A' })
    await user.click(screen.getByRole('button', { name: 'เปลี่ยนสถานะ' }))
    const dialog = screen.getByRole('alertdialog', { name: 'เปลี่ยนสถานะการใช้งาน' })
    await user.selectOptions(within(dialog).getByLabelText('สถานะใหม่'), 'MAINTENANCE')
    await user.click(within(dialog).getByRole('button', { name: 'ยืนยันเปลี่ยนสถานะ' }))
    await waitFor(() => expect(calls).toContain('PATCH /vehicles/SYN-A/status'))
    await user.click(screen.getByRole('link', { name: 'ไปคัน B' }))
    await screen.findByRole('heading', { name: 'M-SYN-B' })
    const before = calls.length
    await act(async () => {
      slow.resolve(json({ vehicle: detail('SYN-A', 'M-SYN-A', 'MAINTENANCE').vehicle, history_entry: null }))
    })
    expect(screen.getByRole('heading', { name: 'M-SYN-B' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'M-SYN-A' })).toBeNull()
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(calls.slice(before).filter((c) => c.includes('SYN-A'))).toEqual([])
  })
})
