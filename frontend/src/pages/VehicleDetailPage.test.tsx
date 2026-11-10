import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import { VehicleDetailPage } from './VehicleDetailPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const detailBody = {
  vehicle: {
    vehicle_id: 'VEH-1046',
    machine_no: 'TC-12',
    model_id: 'MODEL-0001',
    serial_number: 'ZL-2021-0456',
    operational_status: 'WORKING',
    created_at: '2026-01-15T08:00:00Z',
    updated_at: '2026-01-15T08:00:00Z',
  },
  model: {
    model_id: 'MODEL-0001',
    model_code: 'QY50',
    model_name: 'Zoomlion QY50',
    brand: 'Zoomlion',
    description: null,
    component_roles: ['CARRIER_ENGINE', 'PTO'],
    created_at: '2026-01-15T08:00:00Z',
    updated_at: '2026-01-15T08:00:00Z',
  },
  components: [
    {
      component_id: 'CMP-0001',
      vehicle_id: 'VEH-1046',
      component_role: 'CARRIER_ENGINE',
      label: 'เครื่องยนต์ Carrier / เครื่องยนต์ช่วงล่าง',
    },
  ],
}

const historyBody = [
  {
    history_id: 'STH-0001',
    vehicle_id: 'VEH-1046',
    status: 'WORKING',
    changed_at: '2026-01-15T08:00:00Z',
    changed_by: null,
    note: 'สถานะเริ่มต้นจากการนำเข้าข้อมูล',
  },
]

function renderPage(withCapabilities = false) {
  const page = (
    <MemoryRouter initialEntries={['/vehicle/VEH-1046']}>
      <Routes>
        <Route path="/vehicle/:vehicleId" element={<VehicleDetailPage />} />
      </Routes>
    </MemoryRouter>
  )
  return render(withCapabilities ? <CapabilitiesProvider>{page}</CapabilitiesProvider> : page)
}

/** R5 AMB-1: the status controls follow the server capabilities from /me. */
function meResponse(capabilities: string[]) {
  return jsonResponse({ user_id: 'u-r5', roles: ['SYN'], capabilities, is_dev_auth: true })
}

describe('VehicleDetailPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders vehicle identity, model, components, and status history in Thai', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/latest-location')) return jsonResponse(null)
        if (url.includes('/status-history')) return jsonResponse(historyBody)
        if (url.includes('/vehicles/VEH-1046')) return jsonResponse(detailBody)
        throw new Error(`Unexpected fetch: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => expect(screen.getByRole('heading', { name: 'TC-12' })).toBeInTheDocument())
    expect(screen.getByText(/Zoomlion QY50/)).toBeInTheDocument()
    expect(screen.getByText('ZL-2021-0456')).toBeInTheDocument()
    expect(screen.getByText('เครื่องยนต์ Carrier / เครื่องยนต์ช่วงล่าง')).toBeInTheDocument()
    expect(screen.getByText('สถานะเริ่มต้นจากการนำเข้าข้อมูล')).toBeInTheDocument()
    // R2 Batch R2-C3 (A2-8.4, D4): the legacy Phase 6 driver/operator link is retired; the
    // permanent responsible driver and the E2 day / shift assignment are panels on this page.
    expect(screen.queryByRole('link', { name: 'คนขับ/ผู้ควบคุม' })).not.toBeInTheDocument()
    expect(document.querySelector('a[href="/vehicle/VEH-1046/drivers"]')).toBeNull()
    // Web/API Phase 6 Batch 2A: Vehicle Certificate integration link is present.
    // Wording deliberately says "ใบรับรองยานพาหนะ" (Vehicle Certificates),
    // never "เอกสาร"/documents — Batch 2A implements only certificates.
    expect(screen.getByRole('link', { name: 'ใบรับรองยานพาหนะ' })).toHaveAttribute(
      'href',
      '/vehicle/VEH-1046/certificates',
    )
    // Web/API Phase 6 Batch 3A: Model Document integration link is present,
    // pointing at the vehicle's model_id (model-scoped, not vehicle-scoped
    // data — every vehicle sharing this model sees the same documents).
    expect(screen.getByRole('link', { name: 'เอกสารประจำรุ่นเครื่องจักร' })).toHaveAttribute(
      'href',
      '/models/MODEL-0001/documents',
    )
    // Web/API Phase 6 Batch 6A: Vehicle Work History integration link is present.
    expect(screen.getByRole('link', { name: 'ประวัติการทำงาน' })).toHaveAttribute(
      'href',
      '/vehicle/VEH-1046/work-history',
    )
    // Web/API Phase 6 Batch 6B: Vehicle Daily Summary integration link is present.
    expect(screen.getByRole('link', { name: 'สรุปการทำงานรายวัน' })).toHaveAttribute(
      'href',
      '/vehicle/VEH-1046/daily-summary',
    )
    // Web/API Phase 6 Batch 6C: Vehicle Alerts integration link is present.
    expect(screen.getByRole('link', { name: 'การแจ้งเตือน' })).toHaveAttribute(
      'href',
      '/vehicle/VEH-1046/alerts',
    )
    // Web/API Phase 6 Batch 6D: the GPS card is integrated directly into
    // Vehicle Detail (no separate GPS route/page).
    expect(screen.getByRole('heading', { name: 'ตำแหน่ง GPS ล่าสุด' })).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByText('ยังไม่มีข้อมูลตำแหน่ง GPS')).toBeInTheDocument(),
    )
  })

  it('a GPS-card fetch failure does not hide or fail the rest of Vehicle Detail', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/latest-location')) {
          return jsonResponse(
            {
              error: {
                code: 'INTERNAL_ERROR',
                message: 'boom',
                details: null,
                request_id: 'req-gps-1',
              },
            },
            500,
          )
        }
        if (url.includes('/status-history')) return jsonResponse(historyBody)
        // R2 Batch R2-C2a: the permanent responsible-driver panel's own read (valid, empty).
        if (url.includes('/vehicles/VEH-1046/responsible-drivers')) {
          return jsonResponse({ vehicle_id: 'VEH-1046', timeline_status: 'VALID', current_status: 'NONE',
            current_driver_id: null, current_since: null, events: [] })
        }
        // R2 Batch R2-C2b: the E2 panel's own reads (valid, empty).
        if (url.includes('/vehicles/VEH-1046/operational-driver-assignments')) {
          return jsonResponse({ vehicle_id: 'VEH-1046', timeline_status: 'VALID', current_status: 'NONE', current: null,
            intervals: [], unknown: [], conflicts: [], warnings: [] })
        }
        if (url.includes('/vehicles/VEH-1046/operational-driver-assignment-history')) {
          return jsonResponse({ vehicle_id: 'VEH-1046', events: [], records: [] })
        }
        if (url.includes('/vehicles/VEH-1046')) return jsonResponse(detailBody)
        throw new Error(`Unexpected fetch: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => expect(screen.getByRole('heading', { name: 'TC-12' })).toBeInTheDocument())
    // The rest of the page still renders normally.
    expect(screen.getByText(/Zoomlion QY50/)).toBeInTheDocument()
    // The GPS card shows its own error + retry, scoped to itself.
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'ลองใหม่อีกครั้ง' })).toBeInTheDocument(),
    )
  })

  it('shows a controlled Thai 404 message for a missing vehicle', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          {
            error: {
              code: 'VEHICLE_NOT_FOUND',
              message: "Vehicle 'VEH-1046' was not found",
              details: null,
              request_id: 'req-1',
            },
          },
          404,
        ),
      ),
    )

    renderPage()

    await waitFor(() =>
      expect(screen.getByText('ไม่พบข้อมูลยานพาหนะนี้')).toBeInTheDocument(),
    )
  })

  it('opens the status change dialog and submits a PATCH request', async () => {
    const user = userEvent.setup()
    const calls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        calls.push(`${init?.method ?? 'GET'} ${url}`)
        if (init?.method === 'PATCH' && url.includes('/status')) {
          return jsonResponse({
            vehicle: { ...detailBody.vehicle, operational_status: 'MAINTENANCE' },
            history_entry: {
              history_id: 'STH-0002',
              vehicle_id: 'VEH-1046',
              status: 'MAINTENANCE',
              changed_at: '2026-02-01T00:00:00Z',
              changed_by: 'dev-user',
              note: null,
            },
          })
        }
        if (url.endsWith('/me')) return meResponse(['can_view', 'can_manage_repair'])
        if (url.includes('/latest-location')) return jsonResponse(null)
        if (url.includes('/status-history')) return jsonResponse(historyBody)
        if (url.includes('/vehicles/VEH-1046')) return jsonResponse(detailBody)
        throw new Error(`Unexpected fetch: ${url}`)
      }),
    )

    // R5 AMB-1 (deliberate migration): the status control needs can_manage_repair from /me.
    renderPage(true)

    await waitFor(() => expect(screen.getByRole('heading', { name: 'TC-12' })).toBeInTheDocument())

    await user.click(await screen.findByRole('button', { name: 'เปลี่ยนสถานะ' }))
    expect(screen.getByRole('alertdialog')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'ยืนยันเปลี่ยนสถานะ' }))

    await waitFor(() =>
      expect(calls.some((c) => c.startsWith('PATCH') && c.includes('/status'))).toBe(true),
    )
  })

  // ---------------------------------------------------------------- R5 (AMB-1, OD-3)

  function installR5(capabilities: string[], extra: (url: string, init?: RequestInit) => Response | null = () => null) {
    const calls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        calls.push(`${init?.method ?? 'GET'} ${url}`)
        const custom = extra(url, init)
        if (custom) return custom
        if (url.endsWith('/me')) return meResponse(capabilities)
        if (url.includes('/latest-location')) return jsonResponse(null)
        if (url.includes('/status-history')) return jsonResponse(historyBody)
        if (url.includes('/vehicles/VEH-1046')) return jsonResponse(detailBody)
        throw new Error(`Unexpected fetch: ${url}`)
      }),
    )
    return calls
  }

  it.each([
    ['DRIVER', ['can_view', 'can_report_repair', 'can_record_inspection']],
    ['TECHNICIAN', ['can_view', 'can_report_repair', 'can_record_inspection']],
  ])('R5 AMB-1: a %s capability set gets no status-write control', async (_role, capabilities) => {
    installR5(capabilities)
    renderPage(true)
    await waitFor(() => expect(screen.getByRole('heading', { name: 'TC-12' })).toBeInTheDocument())
    await waitFor(() => expect(screen.queryByRole('button', { name: 'เปลี่ยนสถานะ' })).toBeNull())
    expect(screen.getByText('ประวัติการเปลี่ยนสถานะ')).toBeInTheDocument() // the history stays readable
  })

  it('R5 AMB-1: a server refusal is shown in the dialog and nothing is reported as saved', async () => {
    const user = userEvent.setup()
    const calls = installR5(['can_view', 'can_manage_repair'], (_url, init) =>
      init?.method === 'PATCH'
        ? jsonResponse({ error: { code: 'VEHICLE_SCOPE_UNPROVEN', message: 'x', details: null, request_id: 'r' } }, 422)
        : null,
    )
    renderPage(true)
    await user.click(await screen.findByRole('button', { name: 'เปลี่ยนสถานะ' }))
    await user.click(screen.getByRole('button', { name: 'ยืนยันเปลี่ยนสถานะ' }))
    expect(await within(screen.getByRole('alertdialog')).findByRole('alert')).toHaveTextContent('รถคันนี้ไม่อยู่ในขอบเขตข้อมูลปัจจุบันของระบบ')
    expect(screen.getByRole('alertdialog')).toBeInTheDocument()
    expect(calls.filter((c) => c.startsWith('PATCH'))).toHaveLength(1)
  })

  it('R5 AMB-1: a 403 from the server is explained, never shown as success', async () => {
    const user = userEvent.setup()
    installR5(['can_view', 'can_manage_repair'], (_url, init) =>
      init?.method === 'PATCH'
        ? jsonResponse({ error: { code: 'HTTP_ERROR', message: 'forbidden', details: null, request_id: 'r' } }, 403)
        : null,
    )
    renderPage(true)
    await user.click(await screen.findByRole('button', { name: 'เปลี่ยนสถานะ' }))
    await user.click(screen.getByRole('button', { name: 'ยืนยันเปลี่ยนสถานะ' }))
    expect(await within(screen.getByRole('alertdialog')).findByRole('alert')).toHaveTextContent('คุณไม่มีสิทธิ์เปลี่ยนสถานะรถ')
  })

  it('R5 OD-3: an effective-dated change posts a status event with a request id kept for the resend', async () => {
    const user = userEvent.setup()
    const ids: string[] = []
    let attempt = 0
    installR5(['can_view', 'can_manage_repair'], (url, init) => {
      if (init?.method === 'POST' && url.endsWith('/status-events')) {
        ids.push(new Headers(init.headers).get('X-Request-Id') ?? '')
        attempt += 1
        if (attempt === 1) throw new TypeError('network down')
        return jsonResponse({ vehicle: detailBody.vehicle, history_entry: historyBody[0], replayed: false })
      }
      return null
    })
    renderPage(true)
    await user.click(await screen.findByRole('button', { name: 'เปลี่ยนสถานะ' }))
    await user.type(screen.getByLabelText('เวลาที่มีผลจริง (ไม่บังคับ — เว้นว่าง = ตอนนี้)'), '2026-11-02T08:30')
    await user.click(screen.getByRole('button', { name: 'ยืนยันเปลี่ยนสถานะ' }))
    expect(await within(screen.getByRole('alertdialog')).findByRole('alert')).toHaveTextContent('ไม่ทราบผลการบันทึก')
    await user.click(screen.getByRole('button', { name: 'ยืนยันเปลี่ยนสถานะ' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
    expect(ids).toHaveLength(2)
    expect(ids[0]).toMatch(/^[0-9a-f-]{36}$/)
    expect(ids[1]).toBe(ids[0])
  })

  it('R5 OD-3: the history card shows effective times and evidence-based downtime on demand', async () => {
    const user = userEvent.setup()
    installR5(['can_view', 'can_manage_repair'], (url) => {
      if (url.includes('/status-events'))
        return jsonResponse([
          {
            history_id: 'STH-0002', status: 'MAINTENANCE', effective_at: '2026-11-01T01:00:00Z', effective_source: 'EXPLICIT',
            recorded_at: '2026-11-03T01:00:00Z', changed_by: 'm', note: null,
            corrections: [{ correction_id: 'C', vehicle_id: 'VEH-1046', history_id: 'STH-0002', previous_effective_at: '2026-11-01T02:00:00Z',
              new_effective_at: '2026-11-01T01:00:00Z', reason: 'เวลาจริง', corrected_by: 'm', recorded_at: '2026-11-03T02:00:00Z' }],
          },
        ])
      if (url.includes('/downtime'))
        return jsonResponse({
          vehicle_id: 'VEH-1046', from: '2026-10-05T00:00:00Z', to: '2026-11-04T00:00:00Z', unavailable_statuses: ['MAINTENANCE', 'OUT_OF_SERVICE'],
          intervals: [{ started_at: '2026-11-01T01:00:00Z', ended_at: '2026-11-02T01:00:00Z' }], total_seconds: 86400,
          unknown: [{ started_at: '2026-10-05T00:00:00Z', ended_at: '2026-10-10T00:00:00Z' }], flags: [],
        })
      return null
    })
    renderPage(true)
    await user.click(await screen.findByRole('button', { name: 'แสดงเวลาที่มีผลและช่วงรถหยุดใช้งาน' }))
    expect(await screen.findByTestId('vehicle-downtime-total')).toHaveTextContent('1 วัน 0 ชม. 0 นาที')
    expect(screen.getAllByTestId('vehicle-downtime-interval')).toHaveLength(1)
    expect(screen.getByTestId('vehicle-downtime-unknown')).toHaveTextContent('ไม่มีหลักฐานสถานะ')
    expect(screen.getByTestId('vehicle-status-event')).toHaveTextContent('แก้เวลาแล้ว 1 ครั้ง')
    expect(screen.getByRole('button', { name: 'แก้เวลาที่มีผล' })).toBeInTheDocument()
  })
})
