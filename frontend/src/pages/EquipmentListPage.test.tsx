import { render, screen, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { EquipmentListPage } from './EquipmentListPage'

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('EquipmentListPage', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          items: [
            {
              equipment_id: 'EQP-0001',
              equipment_code: 'LATHE-01',
              name: 'เครื่องกลึงเบอร์ 1',
              category: 'LATHE',
              serial_number: 'LT-2019-0021',
              location: 'โรงซ่อมกลาง',
              operational_status: 'IN_USE',
              created_at: '2026-01-15T08:00:00Z',
              updated_at: '2026-01-15T08:00:00Z',
            },
          ],
          page: 1,
          page_size: 50,
          total_items: 1,
        }),
      ),
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders equipment separately from vehicles with a link to its detail page', async () => {
    render(
      <BrowserRouter>
        <EquipmentListPage />
      </BrowserRouter>,
    )

    await waitFor(() =>
      expect(screen.getByText('เครื่องกลึงเบอร์ 1')).toBeInTheDocument(),
    )
    expect(screen.getAllByText('เครื่องกลึง').length).toBeGreaterThan(0)
    expect(screen.getByRole('link', { name: 'EQP-0001' })).toHaveAttribute(
      'href',
      '/equipment/EQP-0001',
    )
  })
})
