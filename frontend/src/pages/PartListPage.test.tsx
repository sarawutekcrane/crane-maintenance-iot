import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PartListPage } from './PartListPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const partsPage = {
  items: [
    {
      part_id: 'PART-0002',
      part_code: 'OIL-FILTER-A',
      name: 'ไส้กรองน้ำมันเครื่อง (ข้อมูลตัวอย่างสำหรับพัฒนา/ทดสอบระบบ)',
      specification: 'ขนาด A',
      manufacturer: null,
      part_number: null,
      tracking_mode: 'CONSUMABLE',
      category: 'FILTER',
      is_active: true,
      metadata: {},
      created_at: '2026-01-15T08:00:00Z',
      updated_at: '2026-01-15T08:00:00Z',
    },
  ],
  page: 1,
  page_size: 50,
  total_items: 1,
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/parts']}>
      <Routes>
        <Route path="/parts" element={<PartListPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('PartListPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders parts with their Thai tracking-mode label', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(partsPage)))

    renderPage()

    await waitFor(() => expect(screen.getByText('OIL-FILTER-A')).toBeInTheDocument())
    expect(screen.getAllByText('วัสดุสิ้นเปลือง (บันทึกการใช้งานจริง)').length).toBeGreaterThan(0)
    expect(screen.getByText('ขนาด A')).toBeInTheDocument()
  })

  it('shows an empty state when no part matches', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ items: [], page: 1, page_size: 50, total_items: 0 })),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ไม่พบอะไหล่')).toBeInTheDocument())
  })
})
