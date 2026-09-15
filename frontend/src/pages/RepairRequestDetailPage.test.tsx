import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RepairRequestDetailPage } from './RepairRequestDetailPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderPage(initialPath: string) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route
          path="/repair-requests/:repairRequestId"
          element={<RepairRequestDetailPage />}
        />
      </Routes>
    </MemoryRouter>,
  )
}

describe('RepairRequestDetailPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows a pending Repair Request via the existing GET /repair-requests/{id} endpoint (Web UAT Defect Fix UAT-F2)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/repair-requests/RRQ-0001')) {
          return jsonResponse({
            repair_request_id: 'RRQ-0001',
            vehicle_id: 'VEH-1046',
            reported_at: '2026-02-01T00:00:00Z',
            reported_by_user_id: 'driver-1',
            reporter_type: null,
            reporter_driver_id: null,
            reporter_name_snapshot_th: null,
            report_channel: null,
            symptom_th: 'เบรกมีเสียงดังผิดปกติ',
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
          })
        }
        throw new Error(`Unexpected fetch: ${url}`)
      }),
    )

    renderPage('/repair-requests/RRQ-0001')

    await waitFor(() => expect(screen.getByText('รหัสคำขอ: RRQ-0001')).toBeInTheDocument())
    expect(screen.getByText('VEH-1046')).toBeInTheDocument()
    expect(screen.getByText(/เบรกมีเสียงดังผิดปกติ/)).toBeInTheDocument()
    expect(screen.getByText('รอตรวจรับ')).toBeInTheDocument()
    expect(
      screen.getByText('คำขอนี้อยู่ระหว่างรอทีมซ่อมบำรุงตรวจสอบและเปิดใบงานซ่อม'),
    ).toBeInTheDocument()
  })

  it('links to the converted Repair once Maintenance has accepted the request', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/repair-requests/RRQ-0002')) {
          return jsonResponse({
            repair_request_id: 'RRQ-0002',
            vehicle_id: 'VEH-1046',
            reported_at: '2026-02-01T00:00:00Z',
            reported_by_user_id: 'driver-1',
            reporter_type: null,
            reporter_driver_id: null,
            reporter_name_snapshot_th: null,
            report_channel: null,
            symptom_th: 'เบรกมีเสียงดังผิดปกติ',
            priority: null,
            request_status: 'CONVERTED',
            reviewed_by_user_id: 'maint-1',
            reviewed_at: '2026-02-01T01:00:00Z',
            repair_id: 'RPR-0002',
            converted_at: '2026-02-01T01:00:00Z',
            note_th: null,
            meter_snapshot_id: null,
            source_type: null,
            source_id: null,
          })
        }
        throw new Error(`Unexpected fetch: ${url}`)
      }),
    )

    renderPage('/repair-requests/RRQ-0002')

    await waitFor(() => expect(screen.getByText('เปิดใบงานซ่อมแล้ว')).toBeInTheDocument())
    expect(screen.getByRole('link', { name: /RPR-0002/ })).toHaveAttribute(
      'href',
      '/repairs/RPR-0002',
    )
  })
})
