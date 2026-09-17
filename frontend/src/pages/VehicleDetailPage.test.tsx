import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { VehicleDetailPage } from './VehicleDetailPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const detailBody = {
  vehicle: {
    vehicle_id: 'VEH-1046',
    machine_no: 'TC-12',
    model_id: 'MODEL-0001',
    serial_number: 'ZL-2021-0456',
    operational_status: 'WORKING',
    created_at: '2026-01-15T08:00:00Z',
    updated_at: '2026-01-15T08:00:00Z',
  },
  model: {
    model_id: 'MODEL-0001',
    model_code: 'QY50',
    model_name: 'Zoomlion QY50',
    brand: 'Zoomlion',
    description: null,
    component_roles: ['CARRIER_ENGINE', 'PTO'],
    created_at: '2026-01-15T08:00:00Z',
    updated_at: '2026-01-15T08:00:00Z',
  },
  components: [
    {
      component_id: 'CMP-0001',
      vehicle_id: 'VEH-1046',
      component_role: 'CARRIER_ENGINE',
      label: 'เครื่องยนต์ Carrier / เครื่องยนต์ช่วงล่าง',
    },
  ],
}

const historyBody = [
  {
    history_id: 'STH-0001',
    vehicle_id: 'VEH-1046',
    status: 'WORKING',
    changed_at: '2026-01-15T08:00:00Z',
    changed_by: null,
    note: 'สถานะเริ่มต้นจากการนำเข้าข้อมูล',
  },
]

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/vehicle/VEH-1046']}>
      <Routes>
        <Route path="/vehicle/:vehicleId" element={<VehicleDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('VehicleDetailPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders vehicle identity, model, components, and status history in Thai', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/status-history')) return jsonResponse(historyBody)
        if (url.includes('/vehicles/VEH-1046')) return jsonResponse(detailBody)
        throw new Error(`Unexpected fetch: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => expect(screen.getByRole('heading', { name: 'TC-12' })).toBeInTheDocument())
    expect(screen.getByText(/Zoomlion QY50/)).toBeInTheDocument()
    expect(screen.getByText('ZL-2021-0456')).toBeInTheDocument()
    expect(screen.getByText('เครื่องยนต์ Carrier / เครื่องยนต์ช่วงล่าง')).toBeInTheDocument()
    expect(screen.getByText('สถานะเริ่มต้นจากการนำเข้าข้อมูล')).toBeInTheDocument()
    // Web/API Phase 6 Batch 1: Driver/Operator integration link is present.
    expect(screen.getByRole('link', { name: 'คนขับ/ผู้ควบคุม' })).toHaveAttribute(
      'href',
      '/vehicle/VEH-1046/drivers',
    )
  })

  it('shows a controlled Thai 404 message for a missing vehicle', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          {
            error: {
              code: 'VEHICLE_NOT_FOUND',
              message: "Vehicle 'VEH-1046' was not found",
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
      expect(screen.getByText('ไม่พบข้อมูลยานพาหนะนี้')).toBeInTheDocument(),
    )
  })

  it('opens the status change dialog and submits a PATCH request', async () => {
    const user = userEvent.setup()
    const calls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        calls.push(`${init?.method ?? 'GET'} ${url}`)
        if (init?.method === 'PATCH' && url.includes('/status')) {
          return jsonResponse({
            vehicle: { ...detailBody.vehicle, operational_status: 'MAINTENANCE' },
            history_entry: {
              history_id: 'STH-0002',
              vehicle_id: 'VEH-1046',
              status: 'MAINTENANCE',
              changed_at: '2026-02-01T00:00:00Z',
              changed_by: 'dev-user',
              note: null,
            },
          })
        }
        if (url.includes('/status-history')) return jsonResponse(historyBody)
        if (url.includes('/vehicles/VEH-1046')) return jsonResponse(detailBody)
        throw new Error(`Unexpected fetch: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => expect(screen.getByRole('heading', { name: 'TC-12' })).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'เปลี่ยนสถานะ' }))
    expect(screen.getByRole('alertdialog')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'ยืนยันเปลี่ยนสถานะ' }))

    await waitFor(() =>
      expect(calls.some((c) => c.startsWith('PATCH') && c.includes('/status'))).toBe(true),
    )
  })
})
