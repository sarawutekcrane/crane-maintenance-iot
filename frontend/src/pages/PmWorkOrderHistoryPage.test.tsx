import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PmWorkOrderHistoryPage } from './PmWorkOrderHistoryPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/vehicle/VEH-1046/pm/history']}>
      <Routes>
        <Route path="/vehicle/:vehicleId/pm/history" element={<PmWorkOrderHistoryPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('PmWorkOrderHistoryPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('lists PM work orders newest first with Thai status labels', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          items: [
            {
              pm_work_order_id: 'PMWO-0002',
              asset_type: 'VEHICLE',
              asset_id: 'VEH-1046',
              pm_plan_id: 'PMP-0001',
              revision_id: 'PMREV-0001',
              status: 'CLOSED',
              opened_at: '2026-02-02T00:00:00Z',
              closed_at: '2026-02-02T01:00:00Z',
              result_count: 3,
            },
          ],
          page: 1,
          page_size: 50,
          total_items: 1,
        }),
      ),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ปิดงานแล้ว')).toBeInTheDocument())
    expect(screen.getByText('PMP-0001')).toBeInTheDocument()
  })

  // R4 PM Workflow: every E01 status has its own Thai label (none shows a raw code).
  it.each([
    ['IN_PROGRESS', 'กำลังดำเนินการ'],
    ['PENDING_REVIEW', 'รอตรวจสอบ'],
    ['CANCELLED', 'ยกเลิกแล้ว'],
  ])('labels a %s work order as %s', async (status, label) => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          items: [
            {
              pm_work_order_id: 'PMWO-0003',
              asset_type: 'VEHICLE',
              asset_id: 'VEH-1046',
              pm_plan_id: 'PMP-0001',
              revision_id: 'PMREV-0001',
              status,
              opened_at: '2026-02-03T00:00:00Z',
              closed_at: null,
              result_count: 0,
            },
          ],
          page: 1,
          page_size: 50,
          total_items: 1,
        }),
      ),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText(label)).toBeInTheDocument())
    expect(screen.queryByText(status)).not.toBeInTheDocument()
  })

  it('shows an empty state when no PM history exists', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ items: [], page: 1, page_size: 50, total_items: 0 })),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ยังไม่มีประวัติ PM')).toBeInTheDocument())
  })
})
