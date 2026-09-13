import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PartDetailPage } from './PartDetailPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const instanceTrackedPart = {
  part_id: 'PART-0005',
  part_code: 'HYD-PUMP-INST',
  name: 'ปั๊มไฮดรอลิกหลัก แบบติดตามรายชิ้น (ข้อมูลตัวอย่างสำหรับพัฒนา/ทดสอบระบบ)',
  specification: null,
  manufacturer: null,
  part_number: null,
  tracking_mode: 'INSTANCE_TRACKED',
  category: 'HYDRAULIC',
  is_active: true,
  metadata: {},
  created_at: '2026-01-15T08:00:00Z',
  updated_at: '2026-01-15T08:00:00Z',
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/parts/PART-0005']}>
      <Routes>
        <Route path="/parts/:partId" element={<PartDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('PartDetailPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows the tracking mode and an instance-registration action for INSTANCE_TRACKED parts', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(instanceTrackedPart)))

    renderPage()

    await waitFor(() =>
      expect(screen.getByText('ติดตามรายชิ้น (มีรหัสชิ้นงานเฉพาะ)')).toBeInTheDocument(),
    )
    expect(screen.getByText('+ ลงทะเบียนชิ้นงานใหม่')).toBeInTheDocument()
  })
})
