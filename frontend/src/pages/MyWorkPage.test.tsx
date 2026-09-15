import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi, afterEach } from 'vitest'
import { MyWorkPage } from './MyWorkPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/my-work']}>
      <Routes>
        <Route path="/my-work" element={<MyWorkPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('MyWorkPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows both my open repairs and my open PM work orders (REV06 section 18)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/repairs/my-work')) {
          return jsonResponse({
            items: [
              {
                repair_id: 'RPR-0001',
                asset_type: 'VEHICLE',
                asset_id: 'VEH-1046',
                source_type: 'MANUAL',
                source_id: null,
                status: 'OPEN',
                opened_at: '2026-02-01T00:00:00Z',
                closed_at: null,
                action_count: 0,
                primary_technician: 'dev-user',
                collaborators: [],
                symptom: 'มีเสียงดังผิดปกติ',
              },
            ],
            page: 1,
            page_size: 50,
            total_items: 1,
          })
        }
        if (url.includes('/pm/work-orders/my-work')) {
          return jsonResponse({
            items: [
              {
                pm_work_order_id: 'PMWO-0001',
                asset_type: 'VEHICLE',
                asset_id: 'VEH-1047',
                pm_plan_id: 'PMP-0001',
                revision_id: 'PMREV-0001',
                status: 'OPEN',
                opened_at: '2026-02-01T00:00:00Z',
                closed_at: null,
                result_count: 1,
                primary_technician: 'dev-user',
                collaborators: [],
              },
            ],
            page: 1,
            page_size: 50,
            total_items: 1,
          })
        }
        // Web UAT Defect Fix UAT-F2.
        if (url.includes('/repair-requests/mine')) {
          return jsonResponse({
            items: [
              {
                repair_request_id: 'RRQ-0001',
                vehicle_id: 'VEH-1048',
                reported_at: '2026-02-01T00:00:00Z',
                reported_by_user_id: 'dev-user',
                reporter_type: null,
                reporter_driver_id: null,
                reporter_name_snapshot_th: null,
                report_channel: null,
                symptom_th: 'เบรกมีเสียงดัง',
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
            ],
            page: 1,
            page_size: 50,
            total_items: 1,
          })
        }
        throw new Error(`Unexpected fetch: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('มีเสียงดังผิดปกติ')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByText('ยานพาหนะ VEH-1047')).toBeInTheDocument())
    expect(screen.getByText('ใบแจ้งซ่อม')).toBeInTheDocument()
    expect(screen.getByText('ใบสั่งงาน PM')).toBeInTheDocument()

    // Web UAT Defect Fix UAT-F2: reporter's own submitted requests, any
    // status, discoverable from the same existing My Work page.
    expect(screen.getByText('คำขอแจ้งซ่อมของฉัน')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('เบรกมีเสียงดัง')).toBeInTheDocument())
    expect(
      screen
        .getAllByRole('link')
        .some((link) => link.getAttribute('href') === '/repair-requests/RRQ-0001'),
    ).toBe(true)
  })
})
