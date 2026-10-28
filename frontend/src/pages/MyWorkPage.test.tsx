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

  // R2 Batch R2f-h4 B5 (deliberate test migration): My Work now reads Technician V2
  // `GET /my-work` (one list of REPAIR and PM items with the caller's role) instead
  // of the legacy `/repairs/my-work` + `/pm/work-orders/my-work`. The invariant this
  // test protects is unchanged: the caller's open repairs AND open PM work orders
  // both appear, each linking to its job, next to the caller's own Repair Requests.
  it('shows both my open repairs and my open PM work orders (REV06 section 18)', async () => {
    const urls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        urls.push(url)
        if (url.endsWith('/api/v1/my-work')) {
          return jsonResponse({
            resolution: 'RESOLVED',
            technician_id: 'TEC-SYN-1',
            items: [
              { work_type: 'REPAIR', job_id: 'RPR-0001', asset_type: 'VEHICLE', asset_id: 'VEH-1046', status: 'OPEN', opened_at: '2026-02-01T00:00:00Z', assignment_role: 'PRIMARY', assignment_set_id: 'S1', assigned_at: '2026-02-01T00:00:00Z' },
              { work_type: 'PM', job_id: 'PMWO-0001', asset_type: 'VEHICLE', asset_id: 'VEH-1047', status: 'PENDING_REVIEW', opened_at: '2026-02-01T00:00:00Z', assignment_role: 'COLLABORATOR', assignment_set_id: 'S2', assigned_at: '2026-02-01T00:00:00Z' },
            ],
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

    expect(await screen.findByRole('link', { name: /RPR-0001/ })).toHaveAttribute('href', '/repairs/RPR-0001')
    expect(screen.getByRole('link', { name: /PMWO-0001/ })).toHaveAttribute('href', '/pm/work-orders/PMWO-0001')
    expect(screen.getByText('VEHICLE VEH-1047')).toBeInTheDocument()
    // R4 PM Workflow: a PM job awaiting review shows its E01 status label (was: raw status only).
    expect(screen.getAllByText('รอตรวจสอบ').length).toBeGreaterThan(0)
    expect(urls.some((u) => u.includes('/repairs/my-work') || u.includes('/pm/work-orders/my-work'))).toBe(false)

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
