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

// Web UAT Defect Fix — a TECHNICIAN/DRIVER-shaped actor (no
// can_manage_repair), so submitting on this page goes through the
// Repair-Request flow (POST /repair-requests) rather than a direct
// Repair, exactly like the real UAT-F1 failure scenario.
const technicianMeBody = {
  user_id: 'tech-1',
  roles: ['TECHNICIAN'],
  capabilities: ['can_view', 'can_report_repair', 'can_record_inspection'],
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

  // -------------------------------------------------------------------
  // Web UAT Defect Fix UAT-F1 (HIGH): a non-Maintenance reporter (no
  // can_manage_repair) following a Finding link previously had
  // source_type/source_id silently dropped when submitting via the
  // Repair-Request flow. These tests pin the fixed behavior.
  // -------------------------------------------------------------------

  it('forwards the Finding source when a non-Maintenance reporter submits a Repair Request from a Finding link', async () => {
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
        if (url.includes('/me')) return jsonResponse(technicianMeBody)
        if (url.includes('/machine-state/current')) return jsonResponse(currentMachineStateBody)
        if (url.includes('/vehicles/VEH-1046')) return jsonResponse(vehicleDetailBody)
        // UAT-F3: "already reported" check — none exists yet for this test.
        if (url.includes('/repair-requests/by-source/FINDING/FND-0001')) return jsonResponse([])
        if (method === 'POST' && url.includes('/repair-requests')) {
          return jsonResponse({
            request: {
              repair_request_id: 'RRQ-0001',
              vehicle_id: 'VEH-1046',
              reported_at: '2026-02-01T00:00:00Z',
              reported_by_user_id: 'tech-1',
              reporter_type: null,
              reporter_driver_id: null,
              reporter_name_snapshot_th: null,
              report_channel: null,
              symptom_th: 'พบข้อบกพร่องระหว่างตรวจเช็ค',
              priority: null,
              request_status: 'PENDING',
              reviewed_by_user_id: null,
              reviewed_at: null,
              repair_id: null,
              converted_at: null,
              note_th: null,
              meter_snapshot_id: null,
              source_type: 'FINDING',
              source_id: 'FND-0001',
            },
            meter_snapshot_id: null,
          })
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    renderPage('/vehicle/VEH-1046/repairs/new?source_type=FINDING&source_id=FND-0001')

    await waitFor(() => expect(screen.getByText('แจ้งปัญหา/แจ้งซ่อม')).toBeInTheDocument())
    await user.type(screen.getByLabelText('อาการ/ปัญหาที่พบ'), 'พบข้อบกพร่องระหว่างตรวจเช็ค')
    await user.click(screen.getByText('ส่งแจ้งซ่อม'))

    await waitFor(() =>
      expect(
        calls.some((c) => c.method === 'POST' && c.url.includes('/repair-requests')),
      ).toBe(true),
    )
    const submitCall = calls.find(
      (c) => c.method === 'POST' && c.url.includes('/repair-requests'),
    )
    // This is the exact UAT-F1 regression assertion: the Repair-Request
    // flow must forward the Finding source, not silently drop it.
    expect(submitCall?.body).toMatchObject({
      vehicle_id: 'VEH-1046',
      symptom_th: 'พบข้อบกพร่องระหว่างตรวจเช็ค',
      source_type: 'FINDING',
      source_id: 'FND-0001',
    })

    await waitFor(() =>
      expect(screen.getByText(/บันทึกการแจ้งปัญหาแล้ว \(รหัส RRQ-0001\)/)).toBeInTheDocument(),
    )
    expect(screen.getByRole('link', { name: 'ดูรายละเอียดคำขอ' })).toHaveAttribute(
      'href',
      '/repair-requests/RRQ-0001',
    )
  })

  it('does not send a Finding/PM source on an ordinary manual report (no query params)', async () => {
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
        if (url.includes('/me')) return jsonResponse(technicianMeBody)
        if (url.includes('/machine-state/current')) return jsonResponse(currentMachineStateBody)
        if (url.includes('/vehicles/VEH-1046')) return jsonResponse(vehicleDetailBody)
        if (method === 'POST' && url.includes('/repair-requests')) {
          return jsonResponse({
            request: {
              repair_request_id: 'RRQ-0002',
              vehicle_id: 'VEH-1046',
              reported_at: '2026-02-01T00:00:00Z',
              reported_by_user_id: 'tech-1',
              reporter_type: null,
              reporter_driver_id: null,
              reporter_name_snapshot_th: null,
              report_channel: null,
              symptom_th: 'อาการทั่วไป',
              priority: null,
              request_status: 'PENDING',
              reviewed_by_user_id: null,
              reviewed_at: null,
              repair_id: null,
              converted_at: null,
              note_th: null,
              meter_snapshot_id: null,
              source_type: null,
              source_id: null,
            },
            meter_snapshot_id: null,
          })
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    // No source_type/source_id query params at all — this must never be
    // treated as (or accidentally forward) a Finding/PM source.
    renderPage('/vehicle/VEH-1046/repairs/new')

    await waitFor(() => expect(screen.getByText('แจ้งปัญหา/แจ้งซ่อม')).toBeInTheDocument())
    await user.type(screen.getByLabelText('อาการ/ปัญหาที่พบ'), 'อาการทั่วไป')
    await user.click(screen.getByText('ส่งแจ้งซ่อม'))

    await waitFor(() =>
      expect(
        calls.some((c) => c.method === 'POST' && c.url.includes('/repair-requests')),
      ).toBe(true),
    )
    const submitCall = calls.find(
      (c) => c.method === 'POST' && c.url.includes('/repair-requests'),
    )
    expect(submitCall?.body).toMatchObject({
      vehicle_id: 'VEH-1046',
      symptom_th: 'อาการทั่วไป',
      source_type: null,
      source_id: null,
    })
  })

  it('shows an "already reported" state instead of the form when a Repair Request already exists for this Finding (UAT-F3, persisted across reload)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/me')) return jsonResponse(technicianMeBody)
        if (url.includes('/machine-state/current')) return jsonResponse(currentMachineStateBody)
        if (url.includes('/vehicles/VEH-1046')) return jsonResponse(vehicleDetailBody)
        if (url.includes('/repair-requests/by-source/FINDING/FND-0002')) {
          return jsonResponse([
            {
              repair_request_id: 'RRQ-0003',
              vehicle_id: 'VEH-1046',
              reported_at: '2026-02-01T00:00:00Z',
              reported_by_user_id: 'tech-1',
              reporter_type: null,
              reporter_driver_id: null,
              reporter_name_snapshot_th: null,
              report_channel: null,
              symptom_th: 'พบข้อบกพร่อง',
              priority: null,
              request_status: 'PENDING',
              reviewed_by_user_id: null,
              reviewed_at: null,
              repair_id: null,
              converted_at: null,
              note_th: null,
              meter_snapshot_id: null,
              source_type: 'FINDING',
              source_id: 'FND-0002',
            },
          ])
        }
        throw new Error(`Unexpected fetch: ${String(input)}`)
      }),
    )

    renderPage('/vehicle/VEH-1046/repairs/new?source_type=FINDING&source_id=FND-0002')

    await waitFor(() =>
      expect(screen.getByText(/ถูกแจ้งซ่อมไปแล้ว/)).toBeInTheDocument(),
    )
    expect(screen.getByRole('link', { name: /RRQ-0003/ })).toHaveAttribute(
      'href',
      '/repair-requests/RRQ-0003',
    )
    // The submission form itself must not be offered again.
    expect(screen.queryByText('ส่งแจ้งซ่อม')).not.toBeInTheDocument()
  })
})
