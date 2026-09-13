import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AssetPartsPage } from './AssetPartsPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/vehicle/VEH-1046/parts']}>
      <Routes>
        <Route path="/vehicle/:vehicleId/parts" element={<AssetPartsPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('AssetPartsPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows an empty state and never displays an UNKNOWN prior-usage value as 0', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse([
          {
            position_lifetime_id: 'POSLT-0001',
            asset_type: 'VEHICLE',
            asset_id: 'VEH-1046',
            position_code: 'BOOM-CYL-1',
            part_id: 'PART-0004',
            lifetime_rule_id: null,
            baseline_meter_snapshot_id: null,
            prior_usage: { quality: 'UNKNOWN', value: null, note: null },
            started_at: '2026-02-01T00:00:00Z',
            started_by: 'dev-user',
            note: null,
          },
        ]),
      ),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ตำแหน่ง: BOOM-CYL-1')).toBeInTheDocument())
    expect(screen.getAllByText('ไม่ทราบค่า').length).toBeGreaterThan(0)
    expect(screen.queryByText('0')).not.toBeInTheDocument()
  })

  it('creates a new position-lifetime enrollment', async () => {
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
        if (method === 'POST' && url.includes('/position-lifetime')) {
          return jsonResponse({
            position_lifetime_id: 'POSLT-0002',
            asset_type: 'VEHICLE',
            asset_id: 'VEH-1046',
            position_code: 'BOOM-CYL-2',
            part_id: null,
            lifetime_rule_id: null,
            baseline_meter_snapshot_id: null,
            prior_usage: { quality: 'UNKNOWN', value: null, note: null },
            started_at: '2026-02-01T00:00:00Z',
            started_by: 'dev-user',
            note: null,
          })
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    renderPage()

    await waitFor(() =>
      expect(screen.getByText('+ ลงทะเบียนอายุการใช้งานตามตำแหน่ง')).toBeInTheDocument(),
    )
    await user.click(screen.getByText('+ ลงทะเบียนอายุการใช้งานตามตำแหน่ง'))
    await user.type(screen.getByLabelText('ตำแหน่ง (position code)'), 'BOOM-CYL-2')
    await user.click(screen.getByText('บันทึก'))

    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.url.includes('/position-lifetime'))).toBe(
        true,
      ),
    )
    const createCall = calls.find((c) => c.method === 'POST' && c.url.includes('/position-lifetime'))
    expect(createCall?.body).toMatchObject({
      asset_type: 'VEHICLE',
      asset_id: 'VEH-1046',
      position_code: 'BOOM-CYL-2',
    })
  })
})
