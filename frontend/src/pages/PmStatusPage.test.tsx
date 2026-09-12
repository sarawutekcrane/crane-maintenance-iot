import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PmStatusPage } from './PmStatusPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const planStatusBody = [
  {
    plan: {
      pm_plan_id: 'PMP-0001',
      plan_code: 'PLAN1',
      asset_type: 'VEHICLE',
      name: 'แผนบำรุงรักษาเชิงป้องกัน PLAN1 (ข้อมูลตัวอย่างชั่วคราวสำหรับพัฒนา/ทดสอบระบบ)',
      model_ids: [],
    },
    active_revision: {
      revision_id: 'PMREV-0001',
      pm_plan_id: 'PMP-0001',
      revision_number: 1,
      effective_date: '2026-01-01',
      source_revision_note: null,
      created_at: '2026-01-15T08:00:00Z',
    },
    last_completed_work_order_id: null,
    last_completed_at: null,
    last_completed_meter_snapshot_id: null,
    due_status: 'UNKNOWN',
    due_status_note:
      'PM due/remaining calculation requires approved decisions E02 (warning windows), E03 (completion baseline), and E04 (missing-counter behavior); not implemented in Phase 4.',
  },
]

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/vehicle/VEH-1046/pm']}>
      <Routes>
        <Route path="/vehicle/:vehicleId/pm" element={<PmStatusPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('PmStatusPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows the plan status, active revision, and unresolved due-status note in Thai', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(planStatusBody)))

    renderPage()

    await waitFor(() =>
      expect(screen.getByText(/แผนบำรุงรักษาเชิงป้องกัน PLAN1/)).toBeInTheDocument(),
    )
    expect(screen.getByText('รหัสแผน: PLAN1')).toBeInTheDocument()
    expect(screen.getByText('รุ่นรายการงานปัจจุบัน: รุ่นที่ 1')).toBeInTheDocument()
    expect(screen.getByText('ไม่สามารถคำนวณได้ในขณะนี้')).toBeInTheDocument()
    expect(screen.getByText(/E02.*E03.*E04/)).toBeInTheDocument()
    expect(screen.getByText('ยังไม่มีประวัติ')).toBeInTheDocument()
  })

  it('opens a new PM work order and posts the correct plan/asset', async () => {
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
        if (method === 'GET' && url.includes('/pm/plans/status')) return jsonResponse(planStatusBody)
        if (method === 'POST' && url.includes('/pm/work-orders')) {
          return jsonResponse({
            work_order: {
              pm_work_order_id: 'PMWO-0001',
              asset_type: 'VEHICLE',
              asset_id: 'VEH-1046',
              pm_plan_id: 'PMP-0001',
              revision_id: 'PMREV-0001',
              due_reason: null,
              status: 'OPEN',
              opened_at: '2026-02-01T00:00:00Z',
              opened_by: 'dev-user',
              closed_at: null,
              closed_by: null,
              note: null,
            },
            results: [],
          })
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('เริ่มทำ PM')).toBeInTheDocument())
    await user.click(screen.getByText('เริ่มทำ PM'))

    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.url.includes('/pm/work-orders'))).toBe(
        true,
      ),
    )
    const openCall = calls.find((c) => c.method === 'POST' && c.url.includes('/pm/work-orders'))
    expect(openCall?.body).toMatchObject({
      asset_type: 'VEHICLE',
      asset_id: 'VEH-1046',
      pm_plan_id: 'PMP-0001',
    })
  })

  it('shows an empty state when no PM plan applies to the asset', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse([])))

    renderPage()

    await waitFor(() =>
      expect(
        screen.getByText('ยังไม่มีแผนบำรุงรักษาที่ใช้งานสำหรับสินทรัพย์นี้'),
      ).toBeInTheDocument(),
    )
  })
})
