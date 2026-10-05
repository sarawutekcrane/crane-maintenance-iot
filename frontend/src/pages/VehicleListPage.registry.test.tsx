import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BrowserRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { VehicleListPage } from './VehicleListPage'

// Phase 7 Batch 7O2a — registry column, reference resolution and the exact
// branch filter on the vehicle list (contract Final Rev2 §7.1-§7.3, §10.5).
// Imports only the page, so this file also runs against the baseline page
// (where it fails on behaviour). Synthetic data only.

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function apiError(code: string, status: number) {
  return json({ error: { code, message: code, details: null, request_id: `req-${code}` } }, status)
}

type Field = { state: string; value: string | null }
const rec = (value: string): Field => ({ state: 'RECORDED', value })
const blank: Field = { state: 'NOT_RECORDED', value: null }
const absent: Field = { state: 'NOT_IN_SCHEMA', value: null }

function vehicle(n: number, reg: [Field, Field, Field] = [rec(`00${n}`), rec('TH-21'), rec('BR-SYN-A')]) {
  const id = String(n).padStart(3, '0')
  return {
    vehicle_id: `SYN-VEH-${id}`, machine_no: `SYN-${id}`, model_id: 'SYN-MODEL-001', serial_number: null,
    operational_status: 'WORKING', created_at: '2026-01-15T08:00:00Z', updated_at: '2026-01-15T08:00:00Z',
    registry: { registration_no: reg[0], registration_province: reg[1], responsible_branch: reg[2] },
  }
}

const BRANCHES = {
  items: [
    { branch_id: 'BR-SYN-A', branch_name: 'สาขาเอ', is_active: true },
    { branch_id: 'BR-SYN-B', branch_name: 'สาขาบี', is_active: false },
  ],
}
const PROVINCES = { items: [{ province_code: 'TH-21', province_name_th: 'ระยอง', is_active: true }] }

interface Options {
  vehicles?: ReturnType<typeof vehicle>[]
  branches?: () => Response | Promise<Response>
  provinces?: () => Response | Promise<Response>
  vehiclesHandler?: (url: URL) => Response | Promise<Response>
}

function installApi(options: Options = {}) {
  const vehicles = options.vehicles ?? [vehicle(1)]
  const calls: URL[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost')
      calls.push(url)
      const path = url.pathname
      if (path === '/api/v1/vehicles') {
        if (options.vehiclesHandler) return options.vehiclesHandler(url)
        const branch = url.searchParams.get('branch_id')
        const status = url.searchParams.get('status')
        const filtered = vehicles.filter(
          (v) =>
            (!branch || (v.registry.responsible_branch.state === 'RECORDED' && v.registry.responsible_branch.value === branch)) &&
            (!status || v.operational_status === status),
        )
        const page = Number(url.searchParams.get('page') ?? '1')
        const size = Number(url.searchParams.get('page_size') ?? '20')
        return json({ items: filtered.slice((page - 1) * size, page * size), page, page_size: size, total_items: filtered.length })
      }
      if (path === '/api/v1/branches') return options.branches ? options.branches() : json(BRANCHES)
      if (path === '/api/v1/provinces') return options.provinces ? options.provinces() : json(PROVINCES)
      if (path === '/api/v1/models') return json({ items: [], page: 1, page_size: 200, total_items: 0 })
      if (path === '/api/v1/repairs' || path === '/api/v1/pm/work-orders') {
        return json({ items: [], page: 1, page_size: 200, total_items: 0 })
      }
      if (path === '/api/v1/findings') return json([])
      throw new Error(`Unexpected fetch: ${url.toString()}`)
    }),
  )
  const vehicleCalls = () => calls.filter((c) => c.pathname === '/api/v1/vehicles')
  return { calls, vehicleCalls }
}

function renderPage() {
  return render(
    <BrowserRouter>
      <VehicleListPage />
    </BrowserRouter>,
  )
}

const branchSelect = () => screen.getByLabelText('สาขาที่รับผิดชอบ') as HTMLSelectElement

describe('VehicleListPage — 7O2a registry column', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows exact registration text with resolved province and branch, one reference call each', async () => {
    const api = installApi({
      vehicles: [
        vehicle(1),
        vehicle(2, [rec(' กข-1234 '), rec('TH-99'), rec('BR-SYN-B')]),
        vehicle(3, [blank, blank, absent]),
      ],
    })
    renderPage()
    expect(await screen.findByText('ทะเบียน: 001 · ระยอง')).toBeInTheDocument()
    expect(screen.getByText('สาขา: สาขาเอ')).toBeInTheDocument()
    expect(screen.getByText((_, el) => el?.textContent === 'ทะเบียน:  กข-1234  · รหัสไม่อยู่ในทะเบียน (TH-99)')).toBeInTheDocument()
    expect(screen.getByText('สาขา: สาขาบี (ไม่ใช้งาน)')).toBeInTheDocument()
    expect(screen.getByText('ทะเบียน: ยังไม่ได้บันทึก')).toBeInTheDocument()
    expect(screen.getByText('สาขา: แหล่งข้อมูลยังไม่มีช่องนี้')).toBeInTheDocument()
    expect(api.calls.filter((c) => c.pathname === '/api/v1/branches')).toHaveLength(1)
    expect(api.calls.filter((c) => c.pathname === '/api/v1/provinces')).toHaveLength(1)
  })

  it('a reference outage shows raw codes as unavailable, never as unknown', async () => {
    installApi({ branches: () => apiError('BRANCH_MASTER_READ_FAILED', 503) })
    renderPage()
    expect(await screen.findByText('สาขา: BR-SYN-A (ไม่สามารถโหลดชื่อได้)')).toBeInTheDocument()
    expect(screen.queryByText(/รหัสไม่อยู่ในทะเบียน \(BR-SYN-A\)/)).not.toBeInTheDocument()
    // A non-blocking note (role=status), not an alert that would compete with list errors.
    expect(screen.getByText(/โหลดรายชื่อสาขา\/จังหวัดไม่สำเร็จ/)).toHaveAttribute('role', 'status')
  })
})

describe('VehicleListPage — 7O2a reference list shape', () => {
  afterEach(() => vi.unstubAllGlobals())

  const malformed: [string, unknown][] = [
    ['item missing branch_name', { items: [{ branch_id: 'BR-SYN-A', is_active: true }] }],
    ['is_active as text', { items: [{ branch_id: 'BR-SYN-A', branch_name: 'สาขาเอ', is_active: 'TRUE' }] }],
    ['numeric branch_id', { items: [{ branch_id: 7, branch_name: 'สาขาเอ', is_active: true }] }],
    ['null item', { items: [null] }],
  ]
  for (const [label, body] of malformed) {
    it(`a 200 /branches body with ${label} is treated as unavailable, never as names`, async () => {
      installApi({ branches: () => json(body) })
      renderPage()
      expect(await screen.findByText('สาขา: BR-SYN-A (ไม่สามารถโหลดชื่อได้)')).toBeInTheDocument()
      expect(screen.queryByText('สาขา: สาขาเอ')).not.toBeInTheDocument()
      expect(screen.queryByText(/รหัสไม่อยู่ในทะเบียน \(BR-SYN-A\)/)).not.toBeInTheDocument()
      expect(branchSelect().options.length).toBe(1)
    })
  }

  it('a malformed 200 /provinces body is unavailable too; valid branches still resolve', async () => {
    installApi({ provinces: () => json({ items: [{ province_code: 'TH-21', is_active: true }] }) })
    renderPage()
    expect(await screen.findByText('ทะเบียน: 001 · TH-21 (ไม่สามารถโหลดชื่อได้)')).toBeInTheDocument()
    expect(screen.getByText('สาขา: สาขาเอ')).toBeInTheDocument()
  })
})

describe('VehicleListPage — 7O2a branch filter', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('applies the exact branch id on change, resets to page 1 and shows it in the summary', async () => {
    const vehicles = Array.from({ length: 60 }, (_, i) => vehicle(i + 1, [rec('x'), rec('TH-21'), rec(i < 55 ? 'BR-SYN-A' : 'BR-SYN-B')]))
    const api = installApi({ vehicles })
    renderPage()
    const user = userEvent.setup()
    await screen.findByText('แสดงรายการที่ 1–50 จาก 60 คันที่ตรงกับเงื่อนไข')
    await user.click(screen.getByRole('button', { name: 'ถัดไป' }))
    await screen.findByText('แสดงรายการที่ 51–60 จาก 60 คันที่ตรงกับเงื่อนไข')
    await waitFor(() => expect(branchSelect().options.length).toBe(3))
    await user.selectOptions(branchSelect(), 'BR-SYN-B')
    await screen.findByText('แสดงรายการที่ 1–5 จาก 5 คันที่ตรงกับเงื่อนไข')
    const last = api.vehicleCalls().at(-1)!.searchParams
    expect(last.get('branch_id')).toBe('BR-SYN-B')
    expect(last.get('page')).toBe('1')
    expect(screen.getByText(/เงื่อนไขที่ใช้: สาขา สาขาบี \(ไม่ใช้งาน\)/)).toBeInTheDocument()
  })

  it('ANDs with status and clears with the other filters', async () => {
    const api = installApi()
    renderPage()
    const user = userEvent.setup()
    await screen.findByText('ทะเบียน: 001 · ระยอง')
    await waitFor(() => expect(branchSelect().options.length).toBe(3))
    await user.selectOptions(screen.getByLabelText('สถานะ'), 'WORKING')
    await user.selectOptions(branchSelect(), 'BR-SYN-A')
    await waitFor(() => {
      const last = api.vehicleCalls().at(-1)!.searchParams
      expect([last.get('status'), last.get('branch_id')]).toEqual(['WORKING', 'BR-SYN-A'])
    })
    await user.click(screen.getByRole('button', { name: 'ล้างตัวกรอง' }))
    await waitFor(() => expect(api.vehicleCalls().at(-1)!.searchParams.has('branch_id')).toBe(false))
    expect(branchSelect().value).toBe('')
  })

  it('a reference retry keeps the applied branch filter and does not reload vehicles', async () => {
    let provincesUp = false
    const api = installApi({ provinces: () => (provincesUp ? json(PROVINCES) : apiError('PROVINCE_MASTER_READ_FAILED', 503)) })
    renderPage()
    const user = userEvent.setup()
    await screen.findByText('สาขา: สาขาเอ')
    await user.selectOptions(branchSelect(), 'BR-SYN-A')
    await waitFor(() => expect(api.vehicleCalls().at(-1)!.searchParams.get('branch_id')).toBe('BR-SYN-A'))
    const before = api.vehicleCalls().length
    provincesUp = true
    await user.click(screen.getByRole('button', { name: 'ลองโหลดรายชื่อสาขา/จังหวัดอีกครั้ง' }))
    expect(await screen.findByText('ทะเบียน: 001 · ระยอง')).toBeInTheDocument()
    expect(api.vehicleCalls()).toHaveLength(before)
    expect(branchSelect().value).toBe('BR-SYN-A')
    expect(screen.getByText(/เงื่อนไขที่ใช้: สาขา สาขาเอ/)).toBeInTheDocument()
  })

  it('a branch list failure never blocks or changes the vehicle list', async () => {
    const api = installApi({ branches: () => apiError('BRANCH_MASTER_SCHEMA_INVALID', 500) })
    renderPage()
    await screen.findByText(/โหลดรายชื่อสาขา\/จังหวัดไม่สำเร็จ/)
    expect(await screen.findByText('ทะเบียน: 001 · ระยอง')).toBeInTheDocument()
    expect(branchSelect().options.length).toBe(1) // only "all branches"
    expect(api.vehicleCalls()).toHaveLength(1)
    expect(api.vehicleCalls()[0].searchParams.has('branch_id')).toBe(false)
  })

  it('a missing branch column is explained and the applied filter stays until cleared', async () => {
    installApi({
      vehiclesHandler: (url) =>
        url.searchParams.has('branch_id')
          ? apiError('VEHICLE_BRANCH_FILTER_UNAVAILABLE', 409)
          : json({ items: [vehicle(1)], page: 1, page_size: 50, total_items: 1 }),
    })
    renderPage()
    const user = userEvent.setup()
    await screen.findByText('ทะเบียน: 001 · ระยอง')
    await user.selectOptions(branchSelect(), 'BR-SYN-A')
    expect(await screen.findByText('กรองตามสาขาไม่ได้')).toBeInTheDocument()
    expect(screen.getByText(/ยังไม่มีช่องสาขาที่รับผิดชอบ/)).toBeInTheDocument()
    expect(branchSelect().value).toBe('BR-SYN-A')
    await user.click(screen.getByRole('button', { name: 'ล้างตัวกรอง' }))
    expect(await screen.findByText('ทะเบียน: 001 · ระยอง')).toBeInTheDocument()
  })

  it('a slow response for the previous branch never replaces the newer result', async () => {
    let releaseSlow!: (r: Response) => void
    installApi({
      vehiclesHandler: (url) => {
        const branch = url.searchParams.get('branch_id')
        if (branch === 'BR-SYN-A') return new Promise<Response>((res) => (releaseSlow = res))
        const items = branch === 'BR-SYN-B' ? [vehicle(2, [rec('บี'), rec('TH-21'), rec('BR-SYN-B')])] : [vehicle(1)]
        return json({ items, page: 1, page_size: 50, total_items: items.length })
      },
    })
    renderPage()
    const user = userEvent.setup()
    await screen.findByText('ทะเบียน: 001 · ระยอง')
    await user.selectOptions(branchSelect(), 'BR-SYN-A')
    await user.selectOptions(branchSelect(), 'BR-SYN-B')
    expect(await screen.findByText('ทะเบียน: บี · ระยอง')).toBeInTheDocument()
    await act(async () => releaseSlow(json({ items: [vehicle(1)], page: 1, page_size: 50, total_items: 1 })))
    expect(screen.getByText('ทะเบียน: บี · ระยอง')).toBeInTheDocument()
    expect(screen.queryByText('ทะเบียน: 001 · ระยอง')).not.toBeInTheDocument()
  })
})
