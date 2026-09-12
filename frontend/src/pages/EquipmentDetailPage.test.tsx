import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { EquipmentDetailPage } from './EquipmentDetailPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/equipment/EQP-0001']}>
      <Routes>
        <Route path="/equipment/:equipmentId" element={<EquipmentDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('EquipmentDetailPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders equipment identity fields in Thai', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          equipment_id: 'EQP-0001',
          equipment_code: 'LATHE-01',
          name: 'เครื่องกลึงเบอร์ 1',
          category: 'LATHE',
          serial_number: 'LT-2019-0021',
          location: 'โรงซ่อมกลาง',
          operational_status: 'IN_USE',
          created_at: '2026-01-15T08:00:00Z',
          updated_at: '2026-01-15T08:00:00Z',
        }),
      ),
    )

    renderPage()

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'เครื่องกลึงเบอร์ 1' })).toBeInTheDocument(),
    )
    expect(screen.getByText('เครื่องกลึง')).toBeInTheDocument()
    expect(screen.getByText('โรงซ่อมกลาง')).toBeInTheDocument()
    // Equipment status renders via the equipment-specific label map
    // (decision C02), not the vehicle status label map.
    expect(screen.getByText('กำลังใช้งาน')).toBeInTheDocument()
  })

  it('shows a controlled Thai 404 message for missing equipment', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          {
            error: {
              code: 'EQUIPMENT_NOT_FOUND',
              message: "Equipment 'EQP-0001' was not found",
              details: null,
              request_id: 'req-1',
            },
          },
          404,
        ),
      ),
    )

    renderPage()

    await waitFor(() =>
      expect(screen.getByText('ไม่พบข้อมูลเครื่องมือ/อุปกรณ์นี้')).toBeInTheDocument(),
    )
  })
})
