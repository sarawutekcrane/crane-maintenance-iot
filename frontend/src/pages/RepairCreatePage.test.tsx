import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import { RepairCreatePage } from './RepairCreatePage'

const meBody = {
  user_id: 'dev-user',
  roles: ['ADMIN'],
  capabilities: [
    'can_view',
    'can_manage_pm',
    'can_report_repair',
    'can_manage_repair',
    'can_close_repair',
    'can_record_inspection',
  ],
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const vehicleDetailBody = {
  vehicle: {
    vehicle_id: 'VEH-1046',
    machine_no: 'TC-12',
    model_id: 'MODEL-0001',
    serial_number: 'ZL-2021-0456',
    operational_status: 'WORKING',
    created_at: '2026-01-15T08:00:00Z',
    updated_at: '2026-01-15T08:00:00Z',
  },
  model: null,
  components: [],
}

const currentMachineStateBody = {
  asset_type: 'VEHICLE',
  asset_id: 'VEH-1046',
  readings: [],
  latitude: null,
  longitude: null,
  gps_observed_at: null,
  note: 'แสดงค่าล่าสุดที่ระบบทราบเท่านั้น (อ่านอย่างเดียว)',
}

const repairDetailBody = {
  repair: {
    repair_id: 'RPR-0001',
    asset_type: 'VEHICLE',
    asset_id: 'VEH-1046',
    source_type: 'MANUAL',
    source_id: null,
    category: null,
    symptom: 'มีเสียงดังผิดปกติ',
    meter_snapshot_id: null,
    status: 'OPEN',
    opened_at: '2026-02-01T00:00:00Z',
    opened_by: 'dev-user',
    closed_at: null,
    closed_by: null,
    close_note: null,
  },
  actions: [],
  parts: [],
}

function renderPage(initialPath: string) {
  return render(
    <CapabilitiesProvider>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/vehicle/:vehicleId/repairs/new" element={<RepairCreatePage />} />
        </Routes>
      </MemoryRouter>
    </CapabilitiesProvider>,
  )
}

describe('RepairCreatePage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('defaults to a MANUAL source and submits the report', async () => {
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
        if (url.includes('/me')) return jsonResponse(meBody)
        if (url.includes('/machine-state/current')) return jsonResponse(currentMachineStateBody)
        if (url.includes('/vehicles/VEH-1046')) return jsonResponse(vehicleDetailBody)
        if (method === 'POST' && url.includes('/repairs')) return jsonResponse(repairDetailBody)
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    renderPage('/vehicle/VEH-1046/repairs/new')

    await waitFor(() => expect(screen.getByText('แจ้งซ่อมด้วยตนเอง')).toBeInTheDocument())

    await user.type(screen.getByLabelText('อาการ/ปัญหาที่พบ'), 'มีเสียงดังผิดปกติ')
    await user.click(screen.getByText('ส่งแจ้งซ่อม'))

    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.url.includes('/repairs'))).toBe(true),
    )
    const createCall = calls.find((c) => c.method === 'POST' && c.url.includes('/repairs'))
    expect(createCall?.body).toMatchObject({
      asset_type: 'VEHICLE',
      asset_id: 'VEH-1046',
      source_type: 'MANUAL',
      source_id: null,
      symptom: 'มีเสียงดังผิดปกติ',
    })
  })

  it('shows and locks the source when reached from a Finding', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/me')) return jsonResponse(meBody)
        if (url.includes('/machine-state/current')) return jsonResponse(currentMachineStateBody)
        return jsonResponse(vehicleDetailBody)
      }),
    )

    renderPage('/vehicle/VEH-1046/repairs/new?source_type=FINDING&source_id=FND-0001')

    await waitFor(() =>
      expect(screen.getByText('ข้อบกพร่องจากการตรวจเช็ค')).toBeInTheDocument(),
    )
    expect(
      screen.getByText('รายการนี้เชื่อมโยงมาจาก ข้อบกพร่องจากการตรวจเช็ค รหัส FND-0001'),
    ).toBeInTheDocument()
  })
})
