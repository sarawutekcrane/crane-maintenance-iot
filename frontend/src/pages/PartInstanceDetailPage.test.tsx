import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PartInstanceDetailPage } from './PartInstanceDetailPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function detailWith(overrides: Partial<{ status: string; segments: unknown[]; priorValue: number | null }>) {
  return {
    instance: {
      part_instance_id: 'PINST-0001',
      part_id: 'PART-0005',
      serial_number: null,
      status: overrides.status ?? 'READY_FOR_INSTALL',
      prior_usage: { quality: 'UNKNOWN', value: overrides.priorValue ?? null, note: null },
      current_lifecycle_id: 'PLC-0001',
      note: null,
      created_at: '2026-02-01T00:00:00Z',
      updated_at: '2026-02-01T00:00:00Z',
    },
    lifecycles: [
      {
        lifecycle_id: 'PLC-0001',
        part_instance_id: 'PINST-0001',
        cycle_number: 1,
        start_reason: 'ENROLLMENT',
        started_at: '2026-02-01T00:00:00Z',
        started_by: 'dev-user',
        started_note: null,
        ended_at: null,
      },
    ],
    segments: overrides.segments ?? [],
  }
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/part-instances/PINST-0001']}>
      <Routes>
        <Route path="/part-instances/:instanceId" element={<PartInstanceDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('PartInstanceDetailPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('never displays an UNKNOWN prior-usage value as 0', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(detailWith({}))))

    renderPage()

    await waitFor(() => expect(screen.getAllByText('ไม่ทราบค่า').length).toBeGreaterThan(0))
    expect(screen.queryByText('0')).not.toBeInTheDocument()
  })

  it('installs the instance onto a vehicle', async () => {
    const user = userEvent.setup()
    const calls: { method: string; url: string; body?: unknown }[] = []
    let installed = false

    const installedDetail = detailWith({
      status: 'INSTALLED',
      segments: [
        {
          segment_id: 'SEG-0001',
          part_instance_id: 'PINST-0001',
          lifecycle_id: 'PLC-0001',
          asset_type: 'VEHICLE',
          asset_id: 'VEH-1046',
          position_code: null,
          status: 'ACTIVE',
          installed_at: '2026-02-01T01:00:00Z',
          installed_by: 'dev-user',
          baseline_meter_snapshot_id: null,
          install_note: null,
          removed_at: null,
          removed_by: null,
          removal_meter_snapshot_id: null,
          removal_reason: null,
        },
      ],
    })

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
        if (method === 'GET' && url.includes('/vehicles')) {
          return jsonResponse({
            items: [
              {
                vehicle_id: 'VEH-1046',
                machine_no: 'TC-12',
                model_id: 'MODEL-0001',
                serial_number: null,
                operational_status: 'WORKING',
                created_at: '2026-01-15T08:00:00Z',
                updated_at: '2026-01-15T08:00:00Z',
              },
            ],
            page: 1,
            page_size: 10,
            total_items: 1,
          })
        }
        if (method === 'GET' && url.includes('/part-instances'))
          return jsonResponse(installed ? installedDetail : detailWith({}))
        if (method === 'POST' && url.includes('/install')) {
          installed = true
          return jsonResponse(installedDetail)
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ติดตั้ง')).toBeInTheDocument())
    await user.click(screen.getByText('ติดตั้ง'))
    await user.type(screen.getByLabelText('ค้นหายานพาหนะ/อุปกรณ์'), 'VEH-1046')
    await waitFor(() => expect(screen.getByText('VEH-1046 — TC-12')).toBeInTheDocument())
    await user.click(screen.getByText('VEH-1046 — TC-12'))
    await user.click(screen.getByText('ยืนยันการติดตั้ง'))

    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.url.includes('/install'))).toBe(true),
    )
    const installCall = calls.find((c) => c.method === 'POST' && c.url.includes('/install'))
    expect(installCall?.body).toMatchObject({ asset_type: 'VEHICLE', asset_id: 'VEH-1046' })
    await waitFor(() => expect(screen.getAllByText('ติดตั้งใช้งานอยู่').length).toBeGreaterThan(0))
  })

  it('shows lifecycle and installation history', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          detailWith({
            status: 'IN_REPAIR',
            segments: [
              {
                segment_id: 'SEG-0001',
                part_instance_id: 'PINST-0001',
                lifecycle_id: 'PLC-0001',
                asset_type: 'VEHICLE',
                asset_id: 'VEH-1046',
                position_code: 'MAIN-PUMP',
                status: 'CLOSED',
                installed_at: '2026-02-01T01:00:00Z',
                installed_by: 'dev-user',
                baseline_meter_snapshot_id: null,
                install_note: null,
                removed_at: '2026-02-05T01:00:00Z',
                removed_by: 'dev-user',
                removal_meter_snapshot_id: null,
                removal_reason: 'ตรวจสภาพ',
              },
            ],
          }),
        ),
      ),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText(/VEH-1046/)).toBeInTheDocument())
    expect(screen.getByText('สิ้นสุดการติดตั้งแล้ว')).toBeInTheDocument()
    expect(screen.getByText('เหตุผล: ตรวจสภาพ')).toBeInTheDocument()
    expect(screen.getByText(/รอบที่ 1/)).toBeInTheDocument()
  })
})
