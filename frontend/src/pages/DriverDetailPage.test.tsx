import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DriverDetailPage } from './DriverDetailPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const driver = {
  driver_id: 'DRV-0001',
  driver_name_th: 'สมชาย ใจดี',
  phone: '081-234-5678',
  license_no: 'TH-DL-000123',
  license_expiry_date: '2027-06-30',
  active_status: null,
  note_th: null,
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/drivers/DRV-0001']}>
      <Routes>
        <Route path="/drivers/:driverId" element={<DriverDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('DriverDetailPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders driver identity/contact/license fields, never fabricating active_status', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(driver)))

    renderPage()

    await waitFor(() => expect(screen.getByRole('heading', { name: 'สมชาย ใจดี' })).toBeInTheDocument())
    expect(screen.getByText('081-234-5678')).toBeInTheDocument()
    expect(screen.getByText('TH-DL-000123')).toBeInTheDocument()
    // active_status/note_th are None (no approved vocabulary) — shown honestly.
    expect(screen.getAllByText('ไม่มีข้อมูล').length).toBeGreaterThanOrEqual(2)
  })

  it('shows a controlled Thai 404 message for a missing driver', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          {
            error: {
              code: 'DRIVER_NOT_FOUND',
              message: "Driver 'DRV-0001' was not found",
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
      expect(screen.getByText('ไม่พบข้อมูลพนักงานขับ/ผู้ควบคุมนี้')).toBeInTheDocument(),
    )
  })

  it('edits and submits an update via PATCH, preserving the driver_id', async () => {
    const user = userEvent.setup()
    const calls: { method: string; url: string; body?: unknown }[] = []

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'
        calls.push({
          method,
          url,
          body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined,
        })
        if (method === 'GET') return jsonResponse(driver)
        if (method === 'PATCH') {
          return jsonResponse({ ...driver, driver_name_th: 'สมชาย (แก้ไข)' })
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => expect(screen.getByRole('heading', { name: 'สมชาย ใจดี' })).toBeInTheDocument())
    await user.click(screen.getByText('แก้ไขข้อมูล'))
    await user.clear(screen.getByLabelText('ชื่อ'))
    await user.type(screen.getByLabelText('ชื่อ'), 'สมชาย (แก้ไข)')
    await user.click(screen.getByText('บันทึก'))

    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    const patchCall = calls.find((c) => c.method === 'PATCH')
    expect(patchCall?.url).toContain('/drivers/DRV-0001')
    expect(patchCall?.body).toMatchObject({ driver_name_th: 'สมชาย (แก้ไข)' })
  })
})
