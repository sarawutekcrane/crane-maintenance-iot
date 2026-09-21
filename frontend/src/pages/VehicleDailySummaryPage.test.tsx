import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { VehicleDailySummaryPage } from './VehicleDailySummaryPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function baseSummary(overrides: Record<string, unknown> = {}) {
  return {
    daily_summary_id: 'DSUM-0001',
    summary_date: '2026-02-01',
    vehicle_id: 'VEH-1046',
    component_id: 'CMP-0001',
    metric_type: 'ENGINE_RUN_DURATION',
    value: 3600,
    unit: 's',
    data_status: 'COMPLETE',
    created_at: '2026-02-02T00:00:00Z',
    ...overrides,
  }
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/vehicle/VEH-1046/daily-summary']}>
      <Routes>
        <Route path="/vehicle/:vehicleId/daily-summary" element={<VehicleDailySummaryPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('VehicleDailySummaryPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('calls GET /vehicles/{vehicleId}/daily-summaries and never issues a write request', async () => {
    const calls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        calls.push(`${init?.method ?? 'GET'} ${url}`)
        if (url.includes('/vehicles/VEH-1046/daily-summaries')) return jsonResponse([baseSummary()])
        throw new Error(`Unexpected fetch: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() =>
      expect(calls.some((c) => c === 'GET /api/v1/vehicles/VEH-1046/daily-summaries')).toBe(true),
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

    expect(screen.getByText('กำลังโหลดสรุปการทำงานรายวัน...')).toBeInTheDocument()
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
        return jsonResponse([baseSummary()])
      }),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ไม่พบข้อมูลยานพาหนะนี้')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'ลองใหม่อีกครั้ง' }))

    await waitFor(() => expect(callCount).toBe(2))
    await waitFor(() => expect(screen.getByText('ระยะเวลาเดินเครื่อง')).toBeInTheDocument())
  })

  it('shows an empty state when the backend returns no summaries', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse([])),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ไม่มีข้อมูลสรุปการทำงานรายวัน')).toBeInTheDocument())
  })

  it('renders Thai labels for both frozen metric types', async () => {
    const summaries = [
      baseSummary({ daily_summary_id: 'DSUM-1', metric_type: 'ENGINE_RUN_DURATION' }),
      baseSummary({ daily_summary_id: 'DSUM-2', metric_type: 'PTO_RUN_DURATION' }),
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(summaries)),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ระยะเวลาเดินเครื่อง')).toBeInTheDocument())
    expect(screen.getByText('ระยะเวลาใช้งาน PTO')).toBeInTheDocument()
  })

  it('renders Thai labels for both frozen data_status values', async () => {
    const summaries = [
      baseSummary({ daily_summary_id: 'DSUM-1', data_status: 'COMPLETE' }),
      baseSummary({ daily_summary_id: 'DSUM-2', data_status: 'PARTIAL', value: null }),
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(summaries)),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ข้อมูลครบถ้วน')).toBeInTheDocument())
    expect(screen.getByText('ข้อมูลไม่ครบถ้วน')).toBeInTheDocument()
  })

  it('formats summary_date using the existing Thai date formatter', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse([baseSummary({ summary_date: '2026-02-01' })])),
    )

    renderPage()

    const expected = new Intl.DateTimeFormat('th-TH', { dateStyle: 'medium' }).format(
      new Date('2026-02-01'),
    )
    await waitFor(() => expect(screen.getByText(expected)).toBeInTheDocument())
  })

  it('formats created_at using the existing Thai date-time formatter, including time (not date-only)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse([baseSummary({ created_at: '2026-02-02T14:30:00Z' })])),
    )

    renderPage()

    const expectedDateTime = new Intl.DateTimeFormat('th-TH', {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date('2026-02-02T14:30:00Z'))
    const expectedDateOnly = new Intl.DateTimeFormat('th-TH', { dateStyle: 'medium' }).format(
      new Date('2026-02-02T14:30:00Z'),
    )

    // The date-time and date-only formats of the same instant must differ
    // (the date-time format includes the time), otherwise this test would
    // not actually distinguish the two formatters.
    expect(expectedDateTime).not.toBe(expectedDateOnly)
    await waitFor(() => expect(screen.getByText(expectedDateTime)).toBeInTheDocument())
    // The date-only rendering of created_at must not appear on its own
    // (it would if created_at were still formatted with formatThaiDate).
    expect(screen.queryByText(expectedDateOnly)).not.toBeInTheDocument()
  })

  it('displays a non-null value as seconds', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse([baseSummary({ value: 3600 })])),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('3600 วินาที')).toBeInTheDocument())
  })

  it('displays component_id', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse([baseSummary({ component_id: 'CMP-9999' })])),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('CMP-9999')).toBeInTheDocument())
  })

  it('never displays a null value as 0, and displays a genuine 0 value as 0 วินาที (frozen null-vs-zero distinction)', async () => {
    // Row A: no provable duration at all (PARTIAL, value: null).
    const rowA = baseSummary({
      daily_summary_id: 'DSUM-A',
      component_id: 'CMP-A',
      metric_type: 'ENGINE_RUN_DURATION',
      value: null,
      data_status: 'PARTIAL',
    })
    // Row B: a genuine, proven zero-duration interval (COMPLETE, value: 0).
    const rowB = baseSummary({
      daily_summary_id: 'DSUM-B',
      component_id: 'CMP-B',
      metric_type: 'PTO_RUN_DURATION',
      value: 0,
      data_status: 'COMPLETE',
    })
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse([rowA, rowB])),
    )

    renderPage()

    await waitFor(() =>
      expect(screen.getByText('ไม่สามารถคำนวณระยะเวลาได้จากข้อมูลที่มี')).toBeInTheDocument(),
    )
    expect(screen.getByText('0 วินาที')).toBeInTheDocument()
    // The unprovable text must never be confused with "0 วินาที".
    expect(screen.queryByText('null วินาที')).not.toBeInTheDocument()
  })

  it('preserves the exact backend array order, even when it differs from summary_date/component_id ordering', async () => {
    // The backend already applies its own deterministic ordering
    // (summary_date desc, component_id asc, metric_type asc,
    // daily_summary_id tie-break) — the UI must render exactly what it
    // receives and must never re-sort it independently.
    const rowA = baseSummary({
      daily_summary_id: 'DSUM-A',
      component_id: 'CMP-ZZZZ',
      summary_date: '2026-01-10',
    })
    const rowB = baseSummary({
      daily_summary_id: 'DSUM-B',
      component_id: 'CMP-AAAA',
      summary_date: '2026-02-20',
    })
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse([rowA, rowB])),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('CMP-ZZZZ')).toBeInTheDocument())

    const table = screen.getByRole('table')
    const bodyRows = within(table).getAllByRole('row').slice(1)
    expect(bodyRows).toHaveLength(2)
    expect(within(bodyRows[0]).getByText('CMP-ZZZZ')).toBeInTheDocument()
    expect(within(bodyRows[1]).getByText('CMP-AAAA')).toBeInTheDocument()
  })

  it('registers the /vehicle/:vehicleId/daily-summary route in the app router', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/vehicles/VEH-1046/daily-summaries')) return jsonResponse([baseSummary()])
        throw new Error(`Unexpected fetch: ${url}`)
      }),
    )

    render(
      <MemoryRouter initialEntries={['/vehicle/VEH-1046/daily-summary']}>
        <App />
      </MemoryRouter>,
    )

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'สรุปการทำงานรายวัน' })).toBeInTheDocument(),
    )
  })
})
