import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import { DriverVehiclesPanel } from './DriverVehiclesPanel'

/** R2 Batch R2-C2a — Driver → vehicles under PERMANENT responsibility (R2f-f, current only). */

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

function stub(vehicles: () => Response) {
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/me')) return json({ user_id: 'dev-user', roles: [], capabilities: ['can_view'], data_context: 'TEST' })
    if (url.endsWith('/drivers/DRV-TEST-901/vehicles')) return vehicles()
    throw new Error(`Unexpected fetch: ${url}`)
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

const renderPanel = () => render(
  <CapabilitiesProvider><MemoryRouter><DriverVehiclesPanel driverId="DRV-TEST-901" /></MemoryRouter></CapabilitiesProvider>,
)

describe('DriverVehiclesPanel', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists every vehicle (one driver, many vehicles) with a link to its vehicle page and the not-driving note', async () => {
    const fn = stub(() => json({ driver_id: 'DRV-TEST-901', items: [
      { vehicle_id: 'VEH-1048', since: '2026-01-04T17:00:00+00:00', event_id: 'CDR-1' },
      { vehicle_id: 'VEH-TEST-901', since: '2026-02-01T00:00:00+00:00', event_id: 'CDR-2' },
    ] }))
    renderPanel()
    expect(screen.getByRole('heading', { name: 'รถที่รับผิดชอบประจำ' })).toBeInTheDocument()
    expect(screen.getByTestId('responsible-driver-note')).toHaveTextContent('ผู้รับผิดชอบรถประจำ ไม่ได้ยืนยันว่าเป็นผู้ขับรถจริงในแต่ละวัน')
    const list = await screen.findByTestId('driver-vehicles')
    expect(within(list).getByRole('link', { name: 'VEH-1048' })).toHaveAttribute('href', '/vehicle/VEH-1048')
    expect(within(list).getByRole('link', { name: 'VEH-TEST-901' })).toBeInTheDocument()
    // Only the R2f-f read: no E2 day / shift data is read.
    expect(fn.mock.calls.map(([u]) => String(u)).some((u) => u.includes('operational-driver'))).toBe(false)
  })

  it('no current responsibility is an empty state (history lives on each vehicle page)', async () => {
    stub(() => json({ driver_id: 'DRV-TEST-901', items: [] }))
    renderPanel()
    expect(await screen.findByText('ไม่มีรถที่รับผิดชอบประจำในปัจจุบัน')).toBeInTheDocument()
  })

  it('a driver outside the server data scope gets the scope explanation', async () => {
    stub(() => json({ error: { code: 'DRIVER_SCOPE_UNPROVEN', message: 'x', details: null, request_id: 'r-1' } }, 422))
    renderPanel()
    expect(await screen.findByTestId('r2-scope-unproven')).toBeInTheDocument()
  })

  it('an ambiguous timeline is a controlled error, never an empty list', async () => {
    stub(() => json({ error: { code: 'DRIVER_RESPONSIBILITY_TIMELINE_AMBIGUOUS', message: 'x', details: null, request_id: 'r-2' } }, 409))
    renderPanel()
    expect(await screen.findByText('โหลดรถที่รับผิดชอบประจำไม่สำเร็จ')).toBeInTheDocument()
    expect(screen.queryByText('ไม่มีรถที่รับผิดชอบประจำในปัจจุบัน')).not.toBeInTheDocument()
  })
})
