import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RepairHistoryPage } from './RepairHistoryPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/equipment/EQP-0001/repairs']}>
      <Routes>
        <Route path="/equipment/:equipmentId/repairs" element={<RepairHistoryPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('RepairHistoryPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('lists repairs with Thai source and status labels, and links to a new repair', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          items: [
            {
              repair_id: 'RPR-0001',
              asset_type: 'EQUIPMENT',
              asset_id: 'EQP-0001',
              source_type: 'MANUAL',
              source_id: null,
              status: 'OPEN',
              opened_at: '2026-02-01T00:00:00Z',
              closed_at: null,
              action_count: 0,
            },
          ],
          page: 1,
          page_size: 50,
          total_items: 1,
        }),
      ),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('แจ้งซ่อมด้วยตนเอง')).toBeInTheDocument())
    expect(screen.getByText('กำลังดำเนินการ')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'แจ้งซ่อมใหม่' })).toHaveAttribute(
      'href',
      '/equipment/EQP-0001/repairs/new',
    )
  })
})
