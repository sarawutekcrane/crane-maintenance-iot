import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AssetPartsPage } from './AssetPartsPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/vehicle/VEH-1046/parts']}>
      <Routes>
        <Route path="/vehicle/:vehicleId/parts" element={<AssetPartsPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('AssetPartsPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows an empty state and never displays an UNKNOWN prior-usage value as 0', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse([
          {
            position_lifetime_id: 'POSLT-0001',
            asset_type: 'VEHICLE',
            asset_id: 'VEH-1046',
            position_code: 'BOOM-CYL-1',
            part_id: 'PART-0004',
            lifetime_rule_id: null,
            baseline_meter_snapshot_id: null,
            prior_usage: { quality: 'UNKNOWN', value: null, note: null },
            started_at: '2026-02-01T00:00:00Z',
            started_by: 'dev-user',
            note: null,
          },
        ]),
      ),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ตำแหน่ง: BOOM-CYL-1')).toBeInTheDocument())
    expect(screen.getAllByText('ไม่ทราบค่า').length).toBeGreaterThan(0)
    expect(screen.queryByText('0')).not.toBeInTheDocument()
  })

  it('creates a new position-lifetime enrollment', async () => {
    const user = userEvent.setup()
    const calls: { method: string; url: string; body?: unknown }[] = []

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'
        calls.push({
          method,
          url,
          body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined,
        })
        if (method === 'GET') return jsonResponse([])
        if (method === 'POST' && url.includes('/position-lifetime')) {
          return jsonResponse({
            position_lifetime_id: 'POSLT-0002',
            asset_type: 'VEHICLE',
            asset_id: 'VEH-1046',
            position_code: 'BOOM-CYL-2',
            part_id: null,
            lifetime_rule_id: null,
            baseline_meter_snapshot_id: null,
            prior_usage: { quality: 'UNKNOWN', value: null, note: null },
            started_at: '2026-02-01T00:00:00Z',
            started_by: 'dev-user',
            note: null,
          })
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    renderPage()

    await waitFor(() =>
      expect(screen.getByText('+ ลงทะเบียนอายุการใช้งานตามตำแหน่ง')).toBeInTheDocument(),
    )
    await user.click(screen.getByText('+ ลงทะเบียนอายุการใช้งานตามตำแหน่ง'))
    await user.type(screen.getByLabelText('ตำแหน่ง (position code)'), 'BOOM-CYL-2')
    await user.click(screen.getByText('บันทึก'))

    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.url.includes('/position-lifetime'))).toBe(
        true,
      ),
    )
    const createCall = calls.find((c) => c.method === 'POST' && c.url.includes('/position-lifetime'))
    expect(createCall?.body).toMatchObject({
      asset_type: 'VEHICLE',
      asset_id: 'VEH-1046',
      position_code: 'BOOM-CYL-2',
    })
  })

  it('R6: lists installed instances with nested hosted seals from the single summary endpoint', async () => {
    const q = (value: number | null) => ({ value, quality: value === null ? 'UNKNOWN' : 'KNOWN', policy_state: null,
      reasons: value === null ? ['METER_EVIDENCE_MISSING'] : [] })
    const counters = (value: number | null) => [{ basis: { counter_type: 'ENGINE_HOUR', component_role: 'CARRIER_ENGINE' },
      verified_lifetime_total: q(value), verified_current_cycle: q(value), tracked_since_enrollment: q(value),
      tracked_in_current_cycle: q(value) }]
    const view = (id: string, extra: object) => ({ target_type: 'PART_INSTANCE', target_id: id, part_id: 'PART-0005',
      status: 'INSTALLED', policy_context: 'TEST', evaluated_at: '2026-11-10T00:00:00Z',
      host: { asset_type: 'VEHICLE', asset_id: 'VEH-1046', position_code: 'BOOM-1', model_id: 'MODEL-0001', installed: true },
      lifecycle: { lifecycle_id: 'L', cycle_number: 1, start_reason: 'ENROLLMENT', start_trigger_event_id: null },
      approval: null, declarations: { prior_usage: null, prior_cycle_usage: null }, counters: counters(null),
      rules: [], inactive_rules: [], ...extra })
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/part-lifetime')) {
        return jsonResponse({ asset_type: 'VEHICLE', asset_id: 'VEH-1046', policy_context: 'TEST', positions: [],
          instances: [view('PINST-0007', { hosted_positions: [view('POSLT-0009', {
            target_type: 'POSITION_LIFETIME', part_id: 'PART-0004',
            host: { asset_type: 'VEHICLE', asset_id: 'VEH-1046', position_code: 'ROD-SEAL', model_id: 'MODEL-0001',
              installed: true, host_part_instance_id: 'PINST-0007' }, counters: counters(80) })] })] })
      }
      return jsonResponse([])
    }))
    renderPage()
    await waitFor(() => expect(screen.getByTestId('installed-instance')).toBeInTheDocument())
    expect(screen.getByRole('link', { name: 'PINST-0007' })).toBeInTheDocument()
    expect(screen.getByTestId('hosted-position')).toHaveTextContent('ROD-SEAL')
    expect(screen.getByTestId('hosted-position')).toHaveTextContent('80')
    // The instance itself has no verified reading: shown as unknown, never 0.
    expect(screen.getAllByTestId('asset-status-summary')[0]).toHaveTextContent('ไม่ทราบ')
  })

  it('R6: a summary load failure is shown as such, not as "nothing installed"', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => String(input).includes('/part-lifetime')
      ? jsonResponse({ error: { code: 'VEHICLE_NOT_FOUND', message: 'x' } }, 404)
      : jsonResponse([])))
    renderPage()
    await waitFor(() => expect(screen.getByText(/โหลดสถานะชิ้นงานที่ติดตั้งไม่สำเร็จ/)).toBeInTheDocument())
    expect(screen.queryByText('ไม่มีชิ้นงานรายชิ้นติดตั้งอยู่บนสินทรัพย์นี้')).not.toBeInTheDocument()
  })
})
