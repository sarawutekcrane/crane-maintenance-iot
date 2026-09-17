import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { VehicleDriverAssignmentsPage } from './VehicleDriverAssignmentsPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const historyBody = [
  {
    assignment_id: 'VDRV-0002',
    vehicle_id: 'VEH-1046',
    driver_id: 'DRV-0001',
    start_at: '2026-01-01T08:00:00Z',
    end_at: null,
    is_primary: true,
    assignment_status: null,
    changed_by_user_id: null,
    note_th: null,
  },
  {
    assignment_id: 'VDRV-0001',
    vehicle_id: 'VEH-1046',
    driver_id: 'DRV-0002',
    start_at: '2025-06-01T08:00:00Z',
    end_at: '2026-01-01T08:00:00Z',
    is_primary: true,
    assignment_status: null,
    changed_by_user_id: null,
    note_th: null,
  },
]

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/vehicle/VEH-1046/drivers']}>
      <Routes>
        <Route path="/vehicle/:vehicleId/drivers" element={<VehicleDriverAssignmentsPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('VehicleDriverAssignmentsPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows both the active and the ended assignment period — history is never hidden', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(historyBody)))

    renderPage()

    await waitFor(() => expect(screen.getAllByText('DRV-0001').length).toBeGreaterThan(0))
    expect(screen.getAllByText('DRV-0002').length).toBeGreaterThan(0)
    expect(screen.getByText('ยังคงมอบหมายอยู่')).toBeInTheDocument()
    // Exactly one active row exposes the "สิ้นสุดการมอบหมาย" action.
    expect(screen.getAllByText('สิ้นสุดการมอบหมาย').length).toBe(1)
  })

  it('assigns a new driver via POST', async () => {
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
        if (method === 'GET') return jsonResponse([])
        if (method === 'POST' && url.includes('/driver-assignments')) {
          return jsonResponse({
            assignment_id: 'VDRV-0003',
            vehicle_id: 'VEH-1046',
            driver_id: 'DRV-0003',
            start_at: '2026-03-01T08:00:00Z',
            end_at: null,
            is_primary: true,
            assignment_status: null,
            changed_by_user_id: 'dev-user',
            note_th: null,
          })
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('+ มอบหมายคนขับ/ผู้ควบคุม')).toBeInTheDocument())
    await user.click(screen.getByText('+ มอบหมายคนขับ/ผู้ควบคุม'))
    await user.type(screen.getByLabelText('รหัสคนขับ/ผู้ควบคุม (driver_id)'), 'DRV-0003')
    await user.click(screen.getByText('บันทึก'))

    await waitFor(() =>
      expect(
        calls.some((c) => c.method === 'POST' && c.url.includes('/vehicles/VEH-1046/driver-assignments')),
      ).toBe(true),
    )
    const createCall = calls.find((c) => c.method === 'POST')
    expect(createCall?.body).toMatchObject({ driver_id: 'DRV-0003', is_primary: true })
  })

  it('ends an active assignment via POST to the end endpoint', async () => {
    const user = userEvent.setup()
    const calls: { method: string; url: string }[] = []

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'
        calls.push({ method, url })
        if (method === 'GET') return jsonResponse(historyBody)
        if (method === 'POST' && url.includes('/end')) {
          return jsonResponse({ ...historyBody[0], end_at: '2026-03-01T00:00:00Z' })
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('สิ้นสุดการมอบหมาย')).toBeInTheDocument())
    await user.click(screen.getByText('สิ้นสุดการมอบหมาย'))

    await waitFor(() =>
      expect(
        calls.some((c) => c.method === 'POST' && c.url.includes('/vehicle-driver-assignments/VDRV-0002/end')),
      ).toBe(true),
    )
  })
})
