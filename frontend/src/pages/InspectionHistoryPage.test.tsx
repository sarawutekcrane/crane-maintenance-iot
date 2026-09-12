import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { InspectionHistoryPage } from './InspectionHistoryPage'

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/vehicle/VEH-1046/inspections']}>
      <Routes>
        <Route path="/vehicle/:vehicleId/inspections" element={<InspectionHistoryPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('InspectionHistoryPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders inspection history rows with Thai pass/fail summaries', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          items: [
            {
              inspection_id: 'INS-0001',
              asset_type: 'VEHICLE',
              asset_id: 'VEH-1046',
              checklist_id: 'CHK-0001',
              revision_number: 1,
              submitted_at: '2026-02-01T00:00:00Z',
              inspector_user_id: 'dev-user',
              pass_count: 4,
              fail_count: 1,
              na_count: 0,
              has_fail: true,
            },
          ],
          page: 1,
          page_size: 50,
          total_items: 1,
        }),
      ),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ไม่ผ่าน 1 รายการ')).toBeInTheDocument())
    expect(screen.getByRole('link')).toHaveAttribute('href', '/inspections/INS-0001')
  })

  it('shows a Thai empty state when there is no inspection history yet', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({ items: [], page: 1, page_size: 50, total_items: 0 }),
      ),
    )

    renderPage()

    await waitFor(() =>
      expect(screen.getByText('ยังไม่มีประวัติการตรวจเช็ค')).toBeInTheDocument(),
    )
  })
})
