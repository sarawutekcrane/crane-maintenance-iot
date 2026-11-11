import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
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

// ---------------------------------------------------------------------------
// R6 (FINAL plan §9): matrix-driven actions, approved return, retry identity
// ---------------------------------------------------------------------------

describe('PartInstanceDetailPage — R6 lifecycle', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function headerOf(init: RequestInit | undefined, name: string): string | null {
    const headers = (init?.headers ?? {}) as Record<string, string>
    return headers[name] ?? null
  }

  function renderWithCapabilities() {
    return render(
      <CapabilitiesProvider>
        <MemoryRouter initialEntries={['/part-instances/PINST-0001']}>
          <Routes>
            <Route path="/part-instances/:instanceId" element={<PartInstanceDetailPage />} />
          </Routes>
        </MemoryRouter>
      </CapabilitiesProvider>,
    )
  }

  it('an IN_REPAIR part offers return-from-repair, never a direct install or a legacy new-cycle control', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(detailWith({ status: 'IN_REPAIR' }))))
    renderPage()
    await waitFor(() => expect(screen.getByText('รับกลับจากซ่อม')).toBeInTheDocument())
    expect(screen.queryByText('ติดตั้ง')).not.toBeInTheDocument()
    expect(screen.queryByText(/เริ่มรอบการใช้งานใหม่ \(Overhaul\)/)).not.toBeInTheDocument()
    expect(screen.getByText('ชิ้นงานที่อยู่ระหว่างซ่อมต้องบันทึกรับกลับจากซ่อมก่อนติดตั้ง')).toBeInTheDocument()
  })

  it('an approver records an approved return with a request id; the approval toggle needs the capability', async () => {
    const user = userEvent.setup()
    const posts: { url: string; body: Record<string, unknown>; requestId: string | null }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.endsWith('/api/v1/me')) {
          return jsonResponse({ user_id: 'mgr', roles: ['SUPERVISOR'], capabilities: ['can_manage_repair'],
            data_context: 'TEST' })
        }
        if ((init?.method ?? 'GET') === 'POST') {
          posts.push({ url, body: JSON.parse(String(init?.body)), requestId: headerOf(init, 'X-Request-Id') })
          return jsonResponse(detailWith({ status: 'READY_FOR_INSTALL' }))
        }
        return jsonResponse(detailWith({ status: 'IN_REPAIR' }))
      }),
    )
    renderWithCapabilities()
    await waitFor(() => expect(screen.getByText('รับกลับจากซ่อม')).toBeInTheDocument())
    await user.click(screen.getByText('รับกลับจากซ่อม'))
    await waitFor(() => expect(screen.getByLabelText(/อนุมัติให้เริ่มรอบการใช้งานใหม่เมื่อติดตั้ง/)).toBeInTheDocument())
    await user.type(screen.getByLabelText('เลขที่ใบงานซ่อม (ถ้ามี)'), 'RPR-0001')
    await user.click(screen.getByLabelText(/อนุมัติให้เริ่มรอบการใช้งานใหม่เมื่อติดตั้ง/))
    await user.type(screen.getByLabelText(/รหัสเหตุผลการอนุมัติ/), 'TEST-QUALIFYING')
    await user.click(screen.getByText('ยืนยันรับกลับจากซ่อม'))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].url).toContain('/part-instances/PINST-0001/return-from-repair')
    expect(posts[0].body).toMatchObject({ repair_reference: 'RPR-0001', new_cycle_approved: true,
      approval_reason_code: 'TEST-QUALIFYING' })
    expect(posts[0].requestId).toMatch(/^[0-9a-f-]{36}$/)
  })

  it('without the capability the approval toggle is absent and the body never claims an approval', async () => {
    const user = userEvent.setup()
    const posts: Record<string, unknown>[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.endsWith('/api/v1/me')) {
          return jsonResponse({ user_id: 'tech', roles: ['TECHNICIAN'], capabilities: ['can_view'], data_context: 'TEST' })
        }
        if ((init?.method ?? 'GET') === 'POST') {
          posts.push(JSON.parse(String(init?.body)))
          return jsonResponse(detailWith({ status: 'READY_FOR_INSTALL' }))
        }
        return jsonResponse(detailWith({ status: 'IN_REPAIR' }))
      }),
    )
    renderWithCapabilities()
    await waitFor(() => expect(screen.getByText('รับกลับจากซ่อม')).toBeInTheDocument())
    await user.click(screen.getByText('รับกลับจากซ่อม'))
    expect(screen.queryByLabelText(/อนุมัติให้เริ่มรอบการใช้งานใหม่เมื่อติดตั้ง/)).not.toBeInTheDocument()
    await user.click(screen.getByText('ยืนยันรับกลับจากซ่อม'))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0]).toMatchObject({ new_cycle_approved: false, approval_reason_code: null })
  })

  it('an uncertain outcome is retried with the SAME request id; a definitive refusal starts a new intent', async () => {
    const user = userEvent.setup()
    const ids: (string | null)[] = []
    let attempt = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST') {
          ids.push(headerOf(init, 'X-Request-Id'))
          attempt += 1
          if (attempt === 1) throw new TypeError('network down')
          if (attempt === 2) return jsonResponse({ error: { code: 'PART_TRANSITION_NOT_ALLOWED', message: 'x' } }, 409)
          return jsonResponse(detailWith({ status: 'STOCK' }))
        }
        void input
        return jsonResponse(detailWith({ status: 'READY_FOR_INSTALL' }))
      }),
    )
    renderPage()
    await waitFor(() => expect(screen.getByText(/เปลี่ยนสถานะ/)).toBeInTheDocument())
    await user.click(screen.getByText(/เปลี่ยนสถานะ/))
    await user.selectOptions(screen.getByLabelText('สถานะใหม่'), 'STOCK')
    await user.click(screen.getByText('ยืนยันการเปลี่ยนสถานะ'))
    await waitFor(() => expect(screen.getByText(/ไม่ทราบผลการบันทึก/)).toBeInTheDocument())
    await user.click(screen.getByText('ยืนยันการเปลี่ยนสถานะ'))
    await waitFor(() => expect(screen.getByText('ไม่สามารถเปลี่ยนสถานะชิ้นงานตามที่เลือกได้')).toBeInTheDocument())
    await user.click(screen.getByText('ยืนยันการเปลี่ยนสถานะ'))
    await waitFor(() => expect(ids).toHaveLength(3))
    expect(ids[1]).toBe(ids[0]) // the retry of an uncertain outcome is the same intent
    expect(ids[2]).not.toBe(ids[1]) // after a definitive refusal, a new intent
  })

  it('a physical-identity refusal offers the set-once identifier dialog', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if ((init?.method ?? 'GET') === 'POST' && url.includes('/status')) {
          return jsonResponse({ error: { code: 'PHYSICAL_IDENTITY_INSUFFICIENT', message: 'x',
            details: { reason: 'UNKNOWN_LOCATION' } } }, 409)
        }
        return jsonResponse(detailWith({ status: 'READY_FOR_INSTALL' }))
      }),
    )
    renderPage()
    await waitFor(() => expect(screen.getByText(/เปลี่ยนสถานะ/)).toBeInTheDocument())
    await user.click(screen.getByText(/เปลี่ยนสถานะ/))
    await user.selectOptions(screen.getByLabelText('สถานะใหม่'), 'STOCK')
    await user.click(screen.getByText('ยืนยันการเปลี่ยนสถานะ'))
    await waitFor(() => expect(screen.getByText(/กรุณาเพิ่มหมายเลขซีเรียลหรือป้ายระบุชิ้นก่อน/)).toBeInTheDocument())
    const buttons = screen.getAllByText('เพิ่มหมายเลข/ป้ายระบุชิ้น')
    await user.click(buttons[buttons.length - 1])
    await waitFor(() => expect(screen.getByText('กำหนดได้ครั้งเดียว — แก้ไขภายหลังไม่ได้')).toBeInTheDocument())
  })
})
