import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { VehicleAlertsPage } from './VehicleAlertsPage'
import { VehicleDetailPage } from './VehicleDetailPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function baseAlert(overrides: Record<string, unknown> = {}) {
  return {
    alert_id: 'ALT-0001',
    vehicle_id: 'VEH-1046',
    alert_type: 'PM_DUE',
    source_type: 'PM_WORK_ORDER',
    source_id: 'PMWO-0001',
    severity: 'WARNING',
    created_at: '2026-02-01T08:00:00Z',
    alert_status: 'ACTIVE',
    muted_until: null,
    acknowledged_by_user_id: null,
    acknowledged_at: null,
    resolved_at: null,
    message_th: 'ถึงกำหนดตรวจสอบ PM',
    ...overrides,
  }
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
  model: null,
  components: [],
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/vehicle/VEH-1046/alerts']}>
      <Routes>
        <Route path="/vehicle/:vehicleId/alerts" element={<VehicleAlertsPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('VehicleAlertsPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('calls GET /vehicles/{vehicleId}/alerts and never issues a write request', async () => {
    const calls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        calls.push(`${init?.method ?? 'GET'} ${url}`)
        if (url.includes('/vehicles/VEH-1046/alerts')) return jsonResponse([baseAlert()])
        throw new Error(`Unexpected fetch: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() =>
      expect(calls.some((c) => c === 'GET /api/v1/vehicles/VEH-1046/alerts')).toBe(true),
    )
    // No POST/PUT/PATCH/DELETE was ever made — this page is strictly read-only.
    expect(calls.every((c) => c.startsWith('GET'))).toBe(true)
    expect(calls.some((c) => /^(POST|PUT|PATCH|DELETE)/.test(c))).toBe(false)
  })

  it('shows a loading state before the response resolves', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(() => {})),
    )

    renderPage()

    expect(screen.getByText('กำลังโหลดการแจ้งเตือน...')).toBeInTheDocument()
  })

  it('shows an error state with retry, and retry re-fetches', async () => {
    const user = userEvent.setup()
    let callCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        callCount += 1
        if (callCount === 1) {
          return jsonResponse(
            {
              error: {
                code: 'VEHICLE_NOT_FOUND',
                message: "Vehicle 'VEH-1046' was not found",
                details: null,
                request_id: 'req-1',
              },
            },
            404,
          )
        }
        return jsonResponse([baseAlert()])
      }),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ไม่พบข้อมูลยานพาหนะนี้')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'ลองใหม่อีกครั้ง' }))

    await waitFor(() => expect(callCount).toBe(2))
    await waitFor(() => expect(screen.getByText('ถึงกำหนดตรวจสอบ PM')).toBeInTheDocument())
  })

  it('shows an empty state when the backend returns no alerts', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse([])),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ไม่มีการแจ้งเตือน')).toBeInTheDocument())
  })

  it('renders Thai labels for all three frozen severity values', async () => {
    const alerts = [
      baseAlert({ alert_id: 'ALT-1', severity: 'INFO' }),
      baseAlert({ alert_id: 'ALT-2', severity: 'WARNING' }),
      baseAlert({ alert_id: 'ALT-3', severity: 'CRITICAL' }),
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(alerts)),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ข้อมูล')).toBeInTheDocument())
    expect(screen.getByText('คำเตือน')).toBeInTheDocument()
    expect(screen.getByText('วิกฤต')).toBeInTheDocument()
  })

  it('renders Thai labels for all four frozen alert_status values, keeping MUTED and RESOLVED visibly distinct', async () => {
    const alerts = [
      baseAlert({ alert_id: 'ALT-1', alert_status: 'ACTIVE' }),
      baseAlert({ alert_id: 'ALT-2', alert_status: 'ACKNOWLEDGED' }),
      baseAlert({ alert_id: 'ALT-3', alert_status: 'MUTED', muted_until: '2026-03-01T00:00:00Z' }),
      baseAlert({ alert_id: 'ALT-4', alert_status: 'RESOLVED', resolved_at: '2026-02-05T00:00:00Z' }),
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(alerts)),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('กำลังแจ้งเตือน')).toBeInTheDocument())
    expect(screen.getByText('รับทราบแล้ว')).toBeInTheDocument()
    expect(screen.getByText('ระงับการแจ้งเตือนชั่วคราว')).toBeInTheDocument()
    expect(screen.getByText('สิ้นสุดแล้ว')).toBeInTheDocument()

    // MUTED and RESOLVED must never collapse into the same displayed label.
    expect(screen.queryByText('ระงับการแจ้งเตือนชั่วคราว')).not.toEqual(
      screen.queryByText('สิ้นสุดแล้ว'),
    )
  })

  it('formats created_at with the Thai date-time formatter', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse([baseAlert({ created_at: '2026-02-01T08:00:00Z' })])),
    )

    renderPage()

    const expected = new Intl.DateTimeFormat('th-TH', {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date('2026-02-01T08:00:00Z'))

    await waitFor(() => expect(screen.getByText(expected)).toBeInTheDocument())
  })

  it('displays message_th exactly when present, and the Thai fallback when null', async () => {
    const alerts = [
      baseAlert({ alert_id: 'ALT-1', message_th: 'ข้อความแจ้งเตือนตัวอย่าง' }),
      baseAlert({ alert_id: 'ALT-2', message_th: null }),
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(alerts)),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ข้อความแจ้งเตือนตัวอย่าง')).toBeInTheDocument())
    expect(screen.getByText('ไม่มีข้อความแจ้งเตือน')).toBeInTheDocument()
  })

  it('displays alert_type as the exact stored opaque value when present, and the Thai fallback when null', async () => {
    const alerts = [
      baseAlert({ alert_id: 'ALT-1', alert_type: 'CERT_EXPIRY' }),
      baseAlert({ alert_id: 'ALT-2', alert_type: null }),
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(alerts)),
    )

    renderPage()

    // Exact passthrough — never normalized/aliased (e.g. never rewritten
    // to CERTIFICATE_EXPIRY).
    await waitFor(() => expect(screen.getByText('CERT_EXPIRY')).toBeInTheDocument())
    expect(screen.getByText('ไม่ระบุประเภท')).toBeInTheDocument()
  })

  it('shows the Thai unknown label (not INFO) when severity is null', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse([baseAlert({ severity: null })])),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ไม่มีข้อมูล')).toBeInTheDocument())
    expect(screen.queryByText('ข้อมูล')).not.toBeInTheDocument()
  })

  it('shows the Thai unknown label (not ACTIVE) when alert_status is null', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse([baseAlert({ alert_status: null })])),
    )

    renderPage()

    await waitFor(() => expect(screen.getAllByText('ไม่มีข้อมูล').length).toBeGreaterThan(0))
    expect(screen.queryByText('กำลังแจ้งเตือน')).not.toBeInTheDocument()
  })

  it('displays source_type/source_id as opaque unchanged values, and the Thai fallback when both are null', async () => {
    const alerts = [
      baseAlert({ alert_id: 'ALT-1', source_type: 'PM_WORK_ORDER', source_id: 'PMWO-0007' }),
      baseAlert({ alert_id: 'ALT-2', source_type: null, source_id: null }),
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(alerts)),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('PM_WORK_ORDER / PMWO-0007')).toBeInTheDocument())
    expect(screen.getByText('ไม่มีข้อมูลแหล่งที่มา')).toBeInTheDocument()
  })

  it('formats muted_until with the Thai date-time formatter when present, and shows - when null', async () => {
    const alerts = [
      baseAlert({ alert_id: 'ALT-1', muted_until: '2026-03-15T10:00:00Z' }),
      baseAlert({ alert_id: 'ALT-2', muted_until: null }),
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(alerts)),
    )

    renderPage()

    const expected = new Intl.DateTimeFormat('th-TH', {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date('2026-03-15T10:00:00Z'))

    await waitFor(() => expect(screen.getByText(expected)).toBeInTheDocument())
    expect(screen.getAllByText('-').length).toBeGreaterThan(0)
  })

  it('preserves the exact backend array order, even when it conflicts with created_at chronology', async () => {
    // Alert A is returned FIRST by the backend, but its created_at is
    // EARLIER than Alert B's. The UI must keep the backend order (A
    // before B) and must never sort/re-sort by created_at.
    const alertA = baseAlert({
      alert_id: 'ALT-A',
      message_th: 'การแจ้งเตือน A',
      created_at: '2026-01-01T00:00:00Z',
    })
    const alertB = baseAlert({
      alert_id: 'ALT-B',
      message_th: 'การแจ้งเตือน B',
      created_at: '2026-02-01T00:00:00Z',
    })
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse([alertA, alertB])),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('การแจ้งเตือน A')).toBeInTheDocument())

    const table = screen.getByRole('table')
    const bodyRows = within(table).getAllByRole('row').slice(1)
    expect(bodyRows).toHaveLength(2)
    expect(within(bodyRows[0]).getByText('การแจ้งเตือน A')).toBeInTheDocument()
    expect(within(bodyRows[1]).getByText('การแจ้งเตือน B')).toBeInTheDocument()
  })

  it('shows the Vehicle Alerts navigation link on Vehicle Detail', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/status-history')) return jsonResponse([])
        if (url.includes('/vehicles/VEH-1046')) return jsonResponse(detailBody)
        throw new Error(`Unexpected fetch: ${url}`)
      }),
    )

    render(
      <MemoryRouter initialEntries={['/vehicle/VEH-1046']}>
        <Routes>
          <Route path="/vehicle/:vehicleId" element={<VehicleDetailPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByRole('heading', { name: 'TC-12' })).toBeInTheDocument())
    expect(screen.getByRole('link', { name: 'การแจ้งเตือน' })).toHaveAttribute(
      'href',
      '/vehicle/VEH-1046/alerts',
    )
  })

  it('registers the /vehicle/:vehicleId/alerts route in the app router', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/vehicles/VEH-1046/alerts')) return jsonResponse([baseAlert()])
        throw new Error(`Unexpected fetch: ${url}`)
      }),
    )

    render(
      <MemoryRouter initialEntries={['/vehicle/VEH-1046/alerts']}>
        <App />
      </MemoryRouter>,
    )

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'การแจ้งเตือน' })).toBeInTheDocument(),
    )
  })

  it('renders no alert lifecycle mutation controls (no acknowledge/mute/resolve/reopen buttons)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse([baseAlert()])),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ถึงกำหนดตรวจสอบ PM')).toBeInTheDocument())

    // Read-only page: no buttons of any kind exist (no acknowledge, mute,
    // resolve, or reopen control).
    expect(screen.queryAllByRole('button')).toHaveLength(0)
  })
})
