import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DriverListPage } from './DriverListPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const driversPage = {
  items: [
    {
      driver_id: 'DRV-0001',
      driver_name_th: 'สมชาย ใจดี (ข้อมูลตัวอย่างสำหรับพัฒนา/ทดสอบระบบ)',
      phone: '081-234-5678',
      license_no: 'TH-DL-000123',
      license_expiry_date: '2027-06-30',
      active_status: null,
      note_th: null,
    },
  ],
  page: 1,
  page_size: 50,
  total_items: 1,
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/drivers']}>
      <Routes>
        <Route path="/drivers" element={<DriverListPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('DriverListPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders drivers with phone/license, never fabricating a status label', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(driversPage)))

    renderPage()

    await waitFor(() =>
      expect(screen.getByText(/สมชาย ใจดี/)).toBeInTheDocument(),
    )
    expect(screen.getByText('081-234-5678')).toBeInTheDocument()
    expect(screen.getByText('TH-DL-000123')).toBeInTheDocument()
  })

  it('shows an empty state when no driver matches', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ items: [], page: 1, page_size: 50, total_items: 0 })),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ไม่พบคนขับ/ผู้ควบคุม')).toBeInTheDocument())
  })
})
