import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import { RepairRequestDetailPage } from './RepairRequestDetailPage'

// R3 L10 / R3-F1 (Owner rules, D8-A): the Maintenance Department Manager
// (can_cancel_repair_request) cancels a duplicate PENDING Repair Request of any source,
// by hand, with a reason. Synthetic stubs only; the backend is authoritative.

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const MANAGER = { user_id: 'USR-MGR', roles: [], capabilities: ['can_view', 'can_manage_repair', 'can_close_repair', 'can_manage_finding_repair', 'can_cancel_repair_request'] }
// MAINTENANCE manages repairs but never holds can_cancel_repair_request (D8-A).
const MAINTENANCE = { user_id: 'USR-M', roles: [], capabilities: ['can_view', 'can_manage_repair', 'can_close_repair', 'can_manage_pm'] }

function request(overrides: Record<string, unknown> = {}) {
  return {
    repair_request_id: 'RRQ-0007', vehicle_id: 'VEH-1046', reported_at: '2026-10-01T02:00:00Z',
    reported_by_user_id: 'USR-T', reporter_type: null, reporter_driver_id: null, reporter_name_snapshot_th: null,
    report_channel: null, symptom_th: 'น้ำมันรั่ว', priority: null, request_status: 'PENDING', reviewed_by_user_id: null,
    reviewed_at: null, repair_id: null, converted_at: null, note_th: null, meter_snapshot_id: null,
    cancelled_at: null, cancelled_by_user_id: null, cancel_reason_th: null, duplicate_of_repair_id: null,
    duplicate_of_repair_request_id: null, source_type: 'FINDING', source_id: 'FND-0001',
    ...overrides,
  }
}

function stub(me: unknown, detail: unknown, onPost?: () => Response) {
  const posts: { url: string; body: unknown }[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/me')) return json(me)
    if (init?.method === 'POST') {
      posts.push({ url, body: JSON.parse(String(init.body)) })
      return onPost ? onPost() : json({}, 500)
    }
    if (url.includes('/repair-requests/RRQ-0007')) return json(detail)
    throw new Error(`Unexpected fetch ${url}`)
  }))
  return posts
}

function renderPage() {
  return render(
    <CapabilitiesProvider>
      <MemoryRouter initialEntries={['/repair-requests/RRQ-0007']}>
        <Routes>
          <Route path="/repair-requests/:repairRequestId" element={<RepairRequestDetailPage />} />
        </Routes>
      </MemoryRouter>
    </CapabilitiesProvider>,
  )
}

describe('RepairRequestDetailPage — R3 L10 duplicate cancellation', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('the manager cancels with a mandatory reason and an optional Work Order reference', async () => {
    const user = userEvent.setup()
    const cancelled = request({ request_status: 'CANCELLED', cancelled_at: '2026-10-02T03:00:00Z',
      cancelled_by_user_id: 'USR-MGR', cancel_reason_th: 'ซ้ำกับใบงานที่กำลังซ่อม', duplicate_of_repair_id: 'RPR-0001' })
    const posts = stub(MANAGER, request(), () => json(cancelled))
    renderPage()
    const button = await screen.findByRole('button', { name: 'ยกเลิกคำขอแจ้งซ่อม' })
    await user.click(button)
    expect(screen.getByRole('alert')).toHaveTextContent('กรุณาระบุเหตุผลในการยกเลิกคำขอแจ้งซ่อม')
    expect(posts).toHaveLength(0)
    await user.type(screen.getByLabelText('เหตุผลในการยกเลิก (จำเป็น)'), 'ซ้ำกับใบงานที่กำลังซ่อม')
    await user.type(screen.getByLabelText(/เลขใบงานซ่อมที่ดำเนินการกับข้อบกพร่องเดียวกัน/), 'RPR-0001')
    await user.click(button)
    await waitFor(() => expect(screen.getByTestId('repair-request-cancelled')).toHaveTextContent('ซ้ำกับใบงานที่กำลังซ่อม'))
    expect(posts[0]).toEqual({ url: '/api/v1/repair-requests/RRQ-0007/cancellation',
      body: { reason_th: 'ซ้ำกับใบงานที่กำลังซ่อม', duplicate_of_repair_id: 'RPR-0001' } })
    expect(screen.getByText('ยกเลิกแล้ว')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'RPR-0001' })).toHaveAttribute('href', '/repairs/RPR-0001')
    expect(screen.queryByRole('button', { name: 'ยกเลิกคำขอแจ้งซ่อม' })).toBeNull()
  })

  it('MAINTENANCE (no can_cancel_repair_request) is not offered the cancellation', async () => {
    stub(MAINTENANCE, request())
    renderPage()
    await waitFor(() => expect(screen.getByText('รหัสคำขอ: RRQ-0007')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'ยกเลิกคำขอแจ้งซ่อม' })).toBeNull()
  })

  it('an ordinary manual report (no Finding provenance) can be cancelled by the manager (R3-F1)', async () => {
    const user = userEvent.setup()
    const manual = request({ source_type: null, source_id: null, reported_by_user_id: 'driver-1' })
    const posts = stub(MANAGER, manual, () => json({ ...manual, request_status: 'CANCELLED', cancelled_at: '2026-10-02T03:00:00Z',
      cancelled_by_user_id: 'USR-MGR', cancel_reason_th: 'แจ้งซ้ำ' }))
    renderPage()
    await user.type(await screen.findByLabelText('เหตุผลในการยกเลิก (จำเป็น)'), 'แจ้งซ้ำ')
    await user.click(screen.getByRole('button', { name: 'ยกเลิกคำขอแจ้งซ่อม' }))
    await waitFor(() => expect(screen.getByTestId('repair-request-cancelled')).toHaveTextContent('USR-MGR'))
    expect(posts[0].body).toEqual({ reason_th: 'แจ้งซ้ำ', duplicate_of_repair_id: null })
    expect(screen.getByText(/เบรก|น้ำมันรั่ว/)).toBeInTheDocument() // the original description stays visible
  })

  it('a converted or cancelled request offers no cancellation', async () => {
    stub(MANAGER, request({ request_status: 'CONVERTED', repair_id: 'RPR-0002' }))
    renderPage()
    await waitFor(() => expect(screen.getByText('รหัสคำขอ: RRQ-0007')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'ยกเลิกคำขอแจ้งซ่อม' })).toBeNull()
  })

  it('a backend refusal is shown in Thai and nothing changes', async () => {
    const user = userEvent.setup()
    stub(MANAGER, request(), () => json({ error: { code: 'REPAIR_REQUEST_NOT_PENDING', message: 'x', details: null } }, 409))
    renderPage()
    await user.type(await screen.findByLabelText('เหตุผลในการยกเลิก (จำเป็น)'), 'ซ้ำ')
    await user.click(screen.getByRole('button', { name: 'ยกเลิกคำขอแจ้งซ่อม' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('ยกเลิกได้เฉพาะคำขอที่ยังรอตรวจรับ'))
    expect(screen.getByText('รอตรวจรับ')).toBeInTheDocument()
  })
})
