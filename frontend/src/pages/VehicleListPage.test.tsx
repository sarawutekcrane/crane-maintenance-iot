import { render, screen, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { VehicleListPage } from './VehicleListPage'

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('VehicleListPage', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/api/v1/vehicles')) {
          return jsonResponse({
            items: [
              {
                vehicle_id: 'VEH-1046',
                machine_no: 'TC-12',
                model_id: 'MODEL-0001',
                serial_number: 'ZL-2021-0456',
                operational_status: 'WORKING',
                created_at: '2026-01-15T08:00:00Z',
                updated_at: '2026-01-15T08:00:00Z',
              },
            ],
            page: 1,
            page_size: 50,
            total_items: 1,
          })
        }
        if (url.includes('/api/v1/models')) {
          return jsonResponse({
            items: [
              {
                model_id: 'MODEL-0001',
                model_code: 'QY50',
                model_name: 'Zoomlion QY50',
                brand: 'Zoomlion',
                description: null,
                component_roles: ['CARRIER_ENGINE', 'PTO'],
                created_at: '2026-01-15T08:00:00Z',
                updated_at: '2026-01-15T08:00:00Z',
              },
            ],
            page: 1,
            page_size: 200,
            total_items: 1,
          })
        }
        throw new Error(`Unexpected fetch: ${url}`)
      }),
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders the vehicle list with Thai labels and a link to the detail page', async () => {
    render(
      <BrowserRouter>
        <VehicleListPage />
      </BrowserRouter>,
    )

    await waitFor(() => expect(screen.getByText('TC-12')).toBeInTheDocument())
    expect(screen.getByText('Zoomlion QY50')).toBeInTheDocument()
    expect(screen.getAllByText('ใช้งานอยู่').length).toBeGreaterThan(0)
    expect(screen.getByRole('link', { name: 'VEH-1046' })).toHaveAttribute(
      'href',
      '/vehicle/VEH-1046',
    )
  })
})
