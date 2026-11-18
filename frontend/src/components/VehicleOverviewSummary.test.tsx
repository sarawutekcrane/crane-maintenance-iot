import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { VehicleOverviewSummary } from './VehicleOverviewSummary'

// R8 (R8-03 / R8-04): the summary composed from the guarded owner reads. Synthetic data.
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const error = (code: string, status: number) => json({ error: { code, message: 'x', details: null, request_id: 'r' } }, status)

type Handler = () => Response
function installApi(overrides: Record<string, Handler> = {}) {
  const calls: string[] = []
  const routes: Record<string, Handler> = {
    '/vehicles/VEH-1/machine-state': () =>
      json({ vehicle_id: 'VEH-1', note: '', readings: [
        { component_id: 'CMP-1', counter_type: 'ENGINE_HOUR', value: 1234, observed_at: '2026-11-18T01:00:00+00:00' },
        { component_id: 'CMP-2', counter_type: 'PTO_HOUR', value: null, observed_at: null },
      ] }),
    '/pm/due/vehicles/VEH-1': () => json({ vehicle_id: 'VEH-1', machine_no: 'TC-1', model_id: 'M', state: 'UNKNOWN',
      explanation: '', assignments: [], plans: [], sets: [] }),
    '/repairs': () => json({ items: [], page: 1, page_size: 1, total_items: 2 }),
    '/findings/follow-up': () => json([{}, {}, {}]),
    '/vehicles/VEH-1/part-lifetime': () => json({ asset_type: 'VEHICLE', asset_id: 'VEH-1', policy_context: 'TEST',
      instances: [{ target_id: 'I1', rules: [{ status: 'DUE' }], hosted_positions: [{ target_id: 'H1', rules: [{ status: 'NOT_DUE' }] }] }],
      positions: [{ target_id: 'P1', rules: [] }] }),
    '/vehicles/VEH-1/alerts': () => json([{ alert_status: 'ACTIVE' }, { alert_status: 'RESOLVED' }, { alert_status: 'MUTED' }]),
    ...overrides,
  }
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://localhost')
    const path = url.pathname.replace('/api/v1', '')
    calls.push(`${path}${url.search}`)
    const handler = routes[path]
    if (!handler) throw new Error(`Unexpected fetch: ${path}`)
    return handler()
  }))
  return calls
}

function renderSummary() {
  return render(
    <MemoryRouter>
      <VehicleOverviewSummary vehicleId="VEH-1" />
    </MemoryRouter>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('VehicleOverviewSummary', () => {
  it('shows each owner value with its link; an unknown meter value is "ไม่ทราบ", never 0', async () => {
    const calls = installApi()
    renderSummary()
    expect(await screen.findByText('2 งาน')).toBeInTheDocument()
    expect(screen.getByText('1,234')).toBeInTheDocument()
    expect(screen.getAllByText('ไม่ทราบ').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('ไม่ทราบเวลาอัปเดต')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '3 รายการ' })).toHaveAttribute('href', '/vehicle/VEH-1/inspections')
    expect(screen.getByRole('link', { name: '3 รายการ · ถึงกำหนด 1 รายการ' })).toHaveAttribute('href', '/vehicle/VEH-1/parts')
    expect(screen.getByRole('link', { name: '2 รายการ' })).toHaveAttribute('href', '/vehicle/VEH-1/alerts')
    expect(screen.getByRole('link', { name: '2 งาน' })).toHaveAttribute('href', '/vehicle/VEH-1/repairs')
    expect(calls).toContain('/repairs?asset_type=VEHICLE&asset_id=VEH-1&status=OPEN&page_size=1')
  })

  it('never requests the certificate list (write-on-read, A-5) and never the ungated machine-state route', async () => {
    const calls = installApi()
    renderSummary()
    await screen.findByText('2 งาน')
    expect(calls.some((c) => c.includes('/certificates'))).toBe(false)
    expect(calls.some((c) => c.includes('/machine-state/current'))).toBe(false)
    expect(screen.getByRole('link', { name: 'ดูใบรับรอง' })).toHaveAttribute('href', '/vehicle/VEH-1/certificates')
  })

  it('a failed, refused or malformed section is unknown with a retry and does not block the others', async () => {
    installApi({
      '/repairs': () => error('INTERNAL_ERROR', 500),
      '/findings/follow-up': () => error('HTTP_ERROR', 403),
      '/vehicles/VEH-1/alerts': () => json({ not: 'a list' }),
    })
    renderSummary()
    expect(await screen.findByText('1,234')).toBeInTheDocument()
    const grid = document.querySelector('.vehicle-overview__grid') as HTMLElement
    expect(await within(grid).findAllByText('ไม่ทราบ (โหลดไม่สำเร็จ)')).toHaveLength(2)
    expect(within(grid).getByText('ไม่มีสิทธิ์ดูข้อมูลส่วนนี้')).toBeInTheDocument()
    expect(within(grid).queryByText('0 งาน')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'ลองโหลดสรุปข้อมูลอีกครั้ง' })).toBeInTheDocument()
  })

  it('states that the device status is a Phase 8 placeholder, not online/offline', async () => {
    installApi()
    renderSummary()
    expect(await screen.findByText(/รอเชื่อมต่ออุปกรณ์ \(Phase 8\)/)).toBeInTheDocument()
    expect(screen.queryByText('ออนไลน์')).not.toBeInTheDocument()
  })
})
