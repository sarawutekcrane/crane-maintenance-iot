import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { VehicleWorkHistoryPage } from './VehicleWorkHistoryPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function baseEvent(overrides: Record<string, unknown> = {}) {
  return {
    event_id: 'EVT-0001',
    vehicle_id: 'VEH-1046',
    device_id: 'DEV-0001',
    component_id: 'CMP-0001',
    event_type: 'ENGINE_START',
    event_time: '2026-02-01T08:00:00Z',
    fuel_level_value: null,
    fuel_level_unit: null,
    latitude: null,
    longitude: null,
    gps_valid: null,
    received_at: '2026-02-01T08:00:05Z',
    note_th: null,
    device_event_id: 'DEVEVT-0001',
    sequence: 1,
    created_offline: false,
    time_quality: 'TIME_SYNCED',
    ...overrides,
  }
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/vehicle/VEH-1046/work-history']}>
      <Routes>
        <Route path="/vehicle/:vehicleId/work-history" element={<VehicleWorkHistoryPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('VehicleWorkHistoryPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('calls GET /vehicles/{vehicleId}/events and never issues a write request', async () => {
    const calls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        calls.push(`${init?.method ?? 'GET'} ${url}`)
        if (url.includes('/vehicles/VEH-1046/events')) return jsonResponse([baseEvent()])
        throw new Error(`Unexpected fetch: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() =>
      expect(calls.some((c) => c === 'GET /api/v1/vehicles/VEH-1046/events')).toBe(true),
    )
    // No POST/PUT/PATCH/DELETE was ever made — this page is strictly read-only.
    expect(calls.every((c) => c.startsWith('GET'))).toBe(true)
  })

  it('shows a loading state before the response resolves', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(() => {})),
    )

    renderPage()

    expect(screen.getByText('กำลังโหลดประวัติการทำงาน...')).toBeInTheDocument()
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
        return jsonResponse([baseEvent()])
      }),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ไม่พบข้อมูลยานพาหนะนี้')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'ลองใหม่อีกครั้ง' }))

    await waitFor(() => expect(callCount).toBe(2))
    await waitFor(() => expect(screen.getByText('เริ่มเดินเครื่อง')).toBeInTheDocument())
  })

  it('shows an empty state when the backend returns no events', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse([])),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ไม่มีประวัติการทำงาน')).toBeInTheDocument())
  })

  it('renders Thai labels for all six frozen event types', async () => {
    const events = [
      baseEvent({ event_id: 'EVT-1', event_type: 'ENGINE_START', device_event_id: 'DE-1', sequence: 1 }),
      baseEvent({ event_id: 'EVT-2', event_type: 'ENGINE_STOP', device_event_id: 'DE-2', sequence: 2 }),
      baseEvent({ event_id: 'EVT-3', event_type: 'PTO_ON', device_event_id: 'DE-3', sequence: 3 }),
      baseEvent({ event_id: 'EVT-4', event_type: 'PTO_OFF', device_event_id: 'DE-4', sequence: 4 }),
      baseEvent({ event_id: 'EVT-5', event_type: 'DEVICE_ONLINE', device_event_id: 'DE-5', sequence: 5 }),
      baseEvent({ event_id: 'EVT-6', event_type: 'DEVICE_OFFLINE', device_event_id: 'DE-6', sequence: 6 }),
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(events)),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('เริ่มเดินเครื่อง')).toBeInTheDocument())
    expect(screen.getByText('หยุดเครื่อง')).toBeInTheDocument()
    expect(screen.getByText('เปิด PTO')).toBeInTheDocument()
    expect(screen.getByText('ปิด PTO')).toBeInTheDocument()
    expect(screen.getByText('อุปกรณ์ออนไลน์')).toBeInTheDocument()
    expect(screen.getByText('อุปกรณ์ออฟไลน์')).toBeInTheDocument()
  })

  it('displays event_time and received_at as separate values, and shows the Thai unknown text when event_time is null', async () => {
    const events = [
      baseEvent({
        event_id: 'EVT-1',
        event_time: '2026-02-01T08:00:00Z',
        received_at: '2026-02-03T10:00:00Z',
      }),
      baseEvent({
        event_id: 'EVT-2',
        device_event_id: 'DE-2',
        sequence: 2,
        event_time: null,
        time_quality: 'TIME_NOT_SYNCED',
        received_at: '2026-02-04T00:00:00Z',
      }),
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(events)),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ไม่ทราบเวลาที่เกิดเหตุการณ์')).toBeInTheDocument())

    const eventTimeText = new Intl.DateTimeFormat('th-TH', {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date('2026-02-01T08:00:00Z'))
    const receivedAtText = new Intl.DateTimeFormat('th-TH', {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date('2026-02-03T10:00:00Z'))

    // Distinct instants must never collapse into the same displayed value.
    expect(eventTimeText).not.toBe(receivedAtText)
    expect(screen.getByText(eventTimeText)).toBeInTheDocument()
    expect(screen.getByText(receivedAtText)).toBeInTheDocument()
  })

  it('renders Thai labels for all three frozen time_quality values', async () => {
    const events = [
      baseEvent({ event_id: 'EVT-1', time_quality: 'TIME_SYNCED' }),
      baseEvent({
        event_id: 'EVT-2',
        device_event_id: 'DE-2',
        sequence: 2,
        time_quality: 'TIME_ESTIMATED',
      }),
      baseEvent({
        event_id: 'EVT-3',
        device_event_id: 'DE-3',
        sequence: 3,
        event_time: null,
        time_quality: 'TIME_NOT_SYNCED',
      }),
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(events)),
    )

    renderPage()

    await waitFor(() =>
      expect(screen.getByText('เวลาจากอุปกรณ์ถูกซิงก์แล้ว')).toBeInTheDocument(),
    )
    expect(screen.getByText('เวลาจากอุปกรณ์เป็นค่าประมาณ')).toBeInTheDocument()
    expect(screen.getByText('เวลาอุปกรณ์ยังไม่ซิงก์')).toBeInTheDocument()
  })

  it('displays created_offline as ใช่/ไม่ใช่ correctly', async () => {
    const events = [
      baseEvent({ event_id: 'EVT-1', created_offline: true }),
      baseEvent({ event_id: 'EVT-2', device_event_id: 'DE-2', sequence: 2, created_offline: false }),
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(events)),
    )

    renderPage()

    await waitFor(() => expect(screen.getAllByText('ใช่').length).toBeGreaterThan(0))
    expect(screen.getAllByText('ไม่ใช่').length).toBeGreaterThan(0)
  })

  it('preserves the exact backend array order, even when it differs from received_at chronology', async () => {
    // Event A is returned FIRST by the backend, but its received_at is
    // LATER than Event B's. The UI must keep the backend order (A before
    // B) and must never re-sort by received_at.
    const eventA = baseEvent({
      event_id: 'EVT-A',
      device_event_id: 'DE-A',
      sequence: 10,
      note_th: 'เหตุการณ์ A',
      received_at: '2026-02-05T12:00:00Z',
    })
    const eventB = baseEvent({
      event_id: 'EVT-B',
      device_event_id: 'DE-B',
      sequence: 1,
      note_th: 'เหตุการณ์ B',
      received_at: '2026-02-01T00:00:00Z',
    })
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse([eventA, eventB])),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('เหตุการณ์ A')).toBeInTheDocument())

    const table = screen.getByRole('table')
    const bodyRows = within(table).getAllByRole('row').slice(1)
    expect(bodyRows).toHaveLength(2)
    expect(within(bodyRows[0]).getByText('เหตุการณ์ A')).toBeInTheDocument()
    expect(within(bodyRows[1]).getByText('เหตุการณ์ B')).toBeInTheDocument()
  })

  it('shows note_th when present', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse([baseEvent({ note_th: 'หมายเหตุทดสอบ' })])),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('หมายเหตุทดสอบ')).toBeInTheDocument())
  })

  it('registers the /vehicle/:vehicleId/work-history route in the app router', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/vehicles/VEH-1046/events')) return jsonResponse([baseEvent()])
        throw new Error(`Unexpected fetch: ${url}`)
      }),
    )

    render(
      <MemoryRouter initialEntries={['/vehicle/VEH-1046/work-history']}>
        <App />
      </MemoryRouter>,
    )

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'ประวัติการทำงาน' })).toBeInTheDocument(),
    )
  })
})
