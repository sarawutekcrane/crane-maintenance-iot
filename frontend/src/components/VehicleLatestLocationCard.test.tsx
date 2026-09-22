import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { LatestLocation } from '../lib/types'
import { VehicleLatestLocationCard } from './VehicleLatestLocationCard'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function fullLocation(overrides: Partial<LatestLocation> = {}): LatestLocation {
  return {
    vehicle_id: 'VEH-1046',
    latitude: 13.75,
    longitude: 100.5,
    gps_time: '2026-09-16T09:50:00+00:00',
    received_at: '2026-09-16T09:55:30+00:00',
    source_device_id: 'DEV-A',
    source_component_id: 'CMP-0001',
    ...overrides,
  }
}

describe('VehicleLatestLocationCard', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('calls GET /vehicles/{vehicleId}/latest-location and never a write method', async () => {
    const calls: { method: string; url: string }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ method: init?.method ?? 'GET', url: String(input) })
        return jsonResponse(fullLocation())
      }),
    )

    render(<VehicleLatestLocationCard vehicleId="VEH-1046" />)

    await waitFor(() => expect(screen.getByText('ละติจูด')).toBeInTheDocument())

    expect(calls).toHaveLength(1)
    expect(calls[0].method).toBe('GET')
    expect(calls[0].url).toContain('/api/v1/vehicles/VEH-1046/latest-location')
    expect(calls.every((c) => ['GET'].includes(c.method))).toBe(true)
    expect(calls.some((c) => ['POST', 'PATCH', 'PUT', 'DELETE'].includes(c.method))).toBe(false)
  })

  it('shows a loading state before the response resolves', async () => {
    let resolveFetch: (value: Response) => void = () => {}
    vi.stubGlobal(
      'fetch',
      vi.fn(
        () =>
          new Promise<Response>((resolve) => {
            resolveFetch = resolve
          }),
      ),
    )

    render(<VehicleLatestLocationCard vehicleId="VEH-1046" />)

    expect(screen.getByText('กำลังโหลดตำแหน่ง GPS...')).toBeInTheDocument()

    resolveFetch(jsonResponse(null))
    await waitFor(() =>
      expect(screen.getByText('ยังไม่มีข้อมูลตำแหน่ง GPS')).toBeInTheDocument(),
    )
  })

  it('shows an error state with retry on failure, and retry re-fetches', async () => {
    let attempt = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        attempt += 1
        if (attempt === 1) {
          return jsonResponse(
            {
              error: {
                code: 'INTERNAL_ERROR',
                message: 'boom',
                details: null,
                request_id: 'req-1',
              },
            },
            500,
          )
        }
        return jsonResponse(fullLocation())
      }),
    )

    const user = userEvent.setup()
    render(<VehicleLatestLocationCard vehicleId="VEH-1046" />)

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'ลองใหม่อีกครั้ง' })).toBeInTheDocument(),
    )

    await user.click(screen.getByRole('button', { name: 'ลองใหม่อีกครั้ง' }))

    await waitFor(() => expect(screen.getByText('ละติจูด')).toBeInTheDocument())
    expect(attempt).toBe(2)
  })

  it('shows the Thai no-location message for JSON null', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(null)))

    render(<VehicleLatestLocationCard vehicleId="VEH-1046" />)

    await waitFor(() =>
      expect(screen.getByText('ยังไม่มีข้อมูลตำแหน่ง GPS')).toBeInTheDocument(),
    )
    expect(screen.queryByText('ละติจูด')).not.toBeInTheDocument()
  })

  it('displays both coordinates, including a genuine 0 value (not treated as missing)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(fullLocation({ latitude: 0, longitude: 0 }))),
    )

    render(<VehicleLatestLocationCard vehicleId="VEH-1046" />)

    await waitFor(() => expect(screen.getByText('ละติจูด')).toBeInTheDocument())
    expect(screen.getByText('ลองจิจูด')).toBeInTheDocument()
    // Both coordinate values render as literal "0", not blank/omitted.
    const rows = screen.getAllByText('0')
    expect(rows.length).toBeGreaterThanOrEqual(2)
  })

  it('formats gps_time separately from received_at, never falling back', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          fullLocation({
            gps_time: '2026-09-16T09:50:00+00:00',
            received_at: '2026-09-16T09:55:30+00:00',
          }),
        ),
      ),
    )

    render(<VehicleLatestLocationCard vehicleId="VEH-1046" />)

    await waitFor(() => expect(screen.getByText('เวลา GPS')).toBeInTheDocument())
    expect(screen.getByText('เวลาที่ระบบได้รับ')).toBeInTheDocument()
    // Two distinct formatted timestamps must be shown (not the same value
    // rendered twice via a fallback).
    const gpsRow = screen.getByText('เวลา GPS').parentElement
    const receivedRow = screen.getByText('เวลาที่ระบบได้รับ').parentElement
    expect(gpsRow?.textContent).not.toBe(receivedRow?.textContent)
  })

  it('shows "ไม่ทราบเวลา GPS" when gps_time is null, without falling back to received_at', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          fullLocation({ gps_time: null, received_at: '2026-09-16T09:55:30+00:00' }),
        ),
      ),
    )

    render(<VehicleLatestLocationCard vehicleId="VEH-1046" />)

    await waitFor(() => expect(screen.getByText('ไม่ทราบเวลา GPS')).toBeInTheDocument())
  })

  it('shows "ไม่ทราบเวลาที่ระบบได้รับ" when received_at is null', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          fullLocation({ gps_time: '2026-09-16T09:50:00+00:00', received_at: null }),
        ),
      ),
    )

    render(<VehicleLatestLocationCard vehicleId="VEH-1046" />)

    await waitFor(() =>
      expect(screen.getByText('ไม่ทราบเวลาที่ระบบได้รับ')).toBeInTheDocument(),
    )
  })

  it('passes source_device_id / source_component_id through exactly', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          fullLocation({ source_device_id: 'DEV-XYZ', source_component_id: 'CMP-XYZ' }),
        ),
      ),
    )

    render(<VehicleLatestLocationCard vehicleId="VEH-1046" />)

    await waitFor(() => expect(screen.getByText('DEV-XYZ')).toBeInTheDocument())
    expect(screen.getByText('CMP-XYZ')).toBeInTheDocument()
  })

  it('preserves a numeric-looking source_device_id ("000009") as a string', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(fullLocation({ source_device_id: '000009', source_component_id: '000001' })),
      ),
    )

    render(<VehicleLatestLocationCard vehicleId="VEH-1046" />)

    await waitFor(() => expect(screen.getByText('000009')).toBeInTheDocument())
    expect(screen.getByText('000001')).toBeInTheDocument()
  })

  it('shows "-" for null source_device_id/source_component_id', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(fullLocation({ source_device_id: null, source_component_id: null })),
      ),
    )

    render(<VehicleLatestLocationCard vehicleId="VEH-1046" />)

    await waitFor(() => expect(screen.getByText('อุปกรณ์ IoT ต้นทาง')).toBeInTheDocument())
    const dashes = screen.getAllByText('-')
    expect(dashes.length).toBeGreaterThanOrEqual(2)
  })

  it('does not render a partial coordinate pair as a valid position', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(fullLocation({ latitude: 13.75, longitude: null }))),
    )

    render(<VehicleLatestLocationCard vehicleId="VEH-1046" />)

    await waitFor(() =>
      expect(screen.getByText('ข้อมูลตำแหน่ง GPS ไม่สมบูรณ์')).toBeInTheDocument(),
    )
    expect(screen.queryByText('ละติจูด')).not.toBeInTheDocument()
    expect(screen.queryByText('ลองจิจูด')).not.toBeInTheDocument()
    expect(screen.queryByText('13.75')).not.toBeInTheDocument()
  })

  it('never renders a map, external link, or iframe', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(fullLocation())))

    const { container } = render(<VehicleLatestLocationCard vehicleId="VEH-1046" />)

    await waitFor(() => expect(screen.getByText('ละติจูด')).toBeInTheDocument())
    expect(container.querySelector('iframe')).toBeNull()
    expect(container.querySelector('a')).toBeNull()
    expect(container.textContent).not.toMatch(/maps\.google|google\.com\/maps/i)
  })
})
