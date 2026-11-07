import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import type { PmManagerQueueItem } from '../lib/types'
import { PmManagerQueuePage } from './PmManagerQueuePage'

// R4 / TASK-010 — synthetic payloads only (SYN-* ids).

const QUEUE_PATH = '/api/v1/pm/work-orders/v2-manager-queue'

function item(id: string, overrides: Partial<PmManagerQueueItem> = {}): PmManagerQueueItem {
  return {
    pm_work_order_id: id,
    asset_type: 'VEHICLE',
    asset_id: 'SYN-VEH-1',
    status: 'OPEN',
    opened_at: '2026-11-01T02:15:00Z',
    assignment_status: 'NONE',
    primary_technician: null,
    collaborators: [],
    issues: {},
    ...overrides,
  }
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function queuePage(items: PmManagerQueueItem[], total = items.length, page = 1, dataContext = 'TEST') {
  return json({ items, page, page_size: 50, total_items: total, data_context: dataContext })
}

interface Call {
  path: string
  params: Record<string, string>
}

/** `/me` answers with the given capabilities; queue reads take the next queued response. */
function stub(capabilities: string[], queue: Array<Response | Error>) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost')
      if (url.pathname.endsWith('/me')) {
        return json({ user_id: 'SYN-MANAGER', roles: [], capabilities, data_context: 'TEST' })
      }
      calls.push({ path: url.pathname, params: Object.fromEntries(url.searchParams) })
      const next = queue.shift()
      if (next === undefined) throw new Error(`Unexpected fetch: ${url.toString()}`)
      if (next instanceof Error) throw next
      return next
    }),
  )
  return calls
}

function renderPage(path = '/pm/manager-queue') {
  return render(
    <CapabilitiesProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/pm/manager-queue" element={<PmManagerQueuePage />} />
          <Route path="/pm/work-orders/:workOrderId" element={<p>work order detail</p>} />
          <Route path="/vehicle/:vehicleId/pm" element={<p>vehicle pm page</p>} />
        </Routes>
      </MemoryRouter>
    </CapabilitiesProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('PmManagerQueuePage', () => {
  it('shows each row with Work Order and asset links, lifecycle status, opened time and team', async () => {
    const calls = stub(['can_manage_pm'], [
      queuePage([
        item('SYN-PMWO-1', {
          status: 'IN_PROGRESS',
          assignment_status: 'VALID',
          primary_technician: { technician_id: 'SYN-TEC-1', display_name: 'ช่างหนึ่ง ทดสอบ' },
          collaborators: [{ technician_id: 'SYN-TEC-2', display_name: null }],
        }),
        item('SYN-PMWO-2', { status: 'PENDING_REVIEW', assignment_status: 'AMBIGUOUS' }),
        item('SYN-PMWO-3', { assignment_status: 'DATA_INVALID', issues: { SET_DIGEST_MISMATCH: 1 } }),
      ]),
    ])
    renderPage()
    expect(await screen.findByRole('link', { name: 'SYN-PMWO-1' })).toHaveAttribute('href', '/pm/work-orders/SYN-PMWO-1')
    expect(screen.getAllByRole('link', { name: 'SYN-VEH-1' })[0]).toHaveAttribute('href', '/vehicle/SYN-VEH-1/pm')
    const table = within(screen.getByRole('table'))
    expect(table.getByText('กำลังดำเนินการ')).toBeInTheDocument()
    expect(table.getByText('รอตรวจสอบ')).toBeInTheDocument()
    expect(table.getByText('เปิดงาน')).toBeInTheDocument()
    expect(screen.getByText('หัวหน้า: ช่างหนึ่ง ทดสอบ (SYN-TEC-1)')).toBeInTheDocument()
    expect(screen.getByText(/ผู้ร่วมงาน: SYN-TEC-2/)).toBeInTheDocument()
    expect(screen.getByText('ระบุทีมช่างปัจจุบันไม่ได้')).toBeInTheDocument()
    expect(screen.getByText('ข้อมูลการมอบหมายไม่ถูกต้อง')).toBeInTheDocument()
    expect(screen.getByText(/SET_DIGEST_MISMATCH × 1/)).toBeInTheDocument()
    expect(screen.getByTestId('pm-manager-total')).toHaveTextContent('ทั้งหมด 3 รายการ (ข้อมูลทดสอบ TEST)')
    expect(calls).toEqual([{ path: QUEUE_PATH, params: { page: '1', page_size: '50' } }])
  })

  it('filters by each status on the server and back to All', async () => {
    const user = userEvent.setup()
    const calls = stub(['can_manage_pm'], [
      queuePage([item('SYN-PMWO-1')]),
      queuePage([item('SYN-PMWO-2', { status: 'PENDING_REVIEW' })]),
      queuePage([item('SYN-PMWO-3', { status: 'IN_PROGRESS' })]),
      queuePage([item('SYN-PMWO-1')]),
    ])
    renderPage()
    await screen.findByRole('link', { name: 'SYN-PMWO-1' })
    const filters = screen.getByRole('group', { name: 'กรองตามสถานะใบงาน' })
    await user.click(within(filters).getByRole('button', { name: 'รอตรวจสอบ' }))
    expect(await screen.findByRole('link', { name: 'SYN-PMWO-2' })).toBeInTheDocument()
    expect(within(filters).getByRole('button', { name: 'รอตรวจสอบ' })).toHaveAttribute('aria-pressed', 'true')
    await user.click(within(filters).getByRole('button', { name: 'กำลังดำเนินการ' }))
    expect(await screen.findByRole('link', { name: 'SYN-PMWO-3' })).toBeInTheDocument()
    await user.click(within(filters).getByRole('button', { name: 'ทั้งหมด' }))
    expect(await screen.findByRole('link', { name: 'SYN-PMWO-1' })).toBeInTheDocument()
    expect(calls.map((c) => c.params.status ?? 'ALL')).toEqual(['ALL', 'PENDING_REVIEW', 'IN_PROGRESS', 'ALL'])
  })

  it('pages through the server total and keeps the filter in the URL', async () => {
    const user = userEvent.setup()
    const calls = stub(['can_manage_pm'], [
      queuePage([item('SYN-PMWO-1', { status: 'IN_PROGRESS' })], 120),
      queuePage([item('SYN-PMWO-51', { status: 'IN_PROGRESS' })], 120, 2),
    ])
    renderPage('/pm/manager-queue?status=IN_PROGRESS')
    expect(await screen.findByText('หน้า 1 / 3')).toBeInTheDocument()
    expect(screen.getByText('ทั้งหมด 120 รายการ (ข้อมูลทดสอบ TEST)')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'ถัดไป' }))
    expect(await screen.findByRole('link', { name: 'SYN-PMWO-51' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'SYN-PMWO-1' })).toBeNull()
    expect(screen.getByText('หน้า 2 / 3')).toBeInTheDocument()
    expect(calls.map((c) => c.params)).toEqual([
      { page: '1', page_size: '50', status: 'IN_PROGRESS' },
      { page: '2', page_size: '50', status: 'IN_PROGRESS' },
    ])
  })

  it('an out-of-range page offers the last real page, keeps the filter and never claims all jobs are closed', async () => {
    const user = userEvent.setup()
    const calls = stub(['can_manage_pm'], [
      queuePage([], 60, 99),
      queuePage([item('SYN-PMWO-51', { status: 'IN_PROGRESS' })], 60, 2),
    ])
    renderPage('/pm/manager-queue?status=IN_PROGRESS&page=99')
    const notice = await screen.findByTestId('pm-manager-out-of-range')
    expect(notice).toHaveTextContent('ไม่มีหน้า 99 — มีทั้งหมด 2 หน้า')
    expect(screen.queryByText('ไม่มีใบงาน PM ที่ยังดำเนินการอยู่')).toBeNull()
    expect(screen.queryByText(/ปิดหรือยกเลิกแล้ว/)).toBeNull()
    expect(screen.queryByText(/หน้า 99 \//)).toBeNull() // no impossible "99 / 2" indicator
    await user.click(within(notice).getByRole('button', { name: 'ไปหน้าสุดท้าย (หน้า 2)' }))
    expect(await screen.findByRole('link', { name: 'SYN-PMWO-51' })).toBeInTheDocument()
    expect(screen.getByText('หน้า 2 / 2')).toBeInTheDocument()
    expect(screen.queryByTestId('pm-manager-out-of-range')).toBeNull()
    expect(calls.map((c) => c.params)).toEqual([
      { page: '99', page_size: '50', status: 'IN_PROGRESS' },
      { page: '2', page_size: '50', status: 'IN_PROGRESS' },
    ])
  })

  it.each([
    [1, 'ไม่มีหน้า 7 — มีทั้งหมด 1 หน้า'],
    [0, 'ไม่มีหน้า 7 — ไม่มีใบงานในเงื่อนไขนี้'],
  ])('an out-of-range page with total %i offers the first page', async (total, message) => {
    const user = userEvent.setup()
    const rows = total > 0 ? [item('SYN-PMWO-1', { status: 'PENDING_REVIEW' })] : []
    const calls = stub(['can_manage_pm'], [queuePage([], total, 7), queuePage(rows, total, 1)])
    renderPage('/pm/manager-queue?status=PENDING_REVIEW&page=7')
    const notice = await screen.findByTestId('pm-manager-out-of-range')
    expect(notice).toHaveTextContent(message)
    expect(screen.queryByText('ไม่มีใบงาน PM ที่ยังดำเนินการอยู่')).toBeNull()
    await user.click(within(notice).getByRole('button', { name: 'ไปหน้าแรก' }))
    if (total > 0) {
      expect(await screen.findByRole('link', { name: 'SYN-PMWO-1' })).toBeInTheDocument()
    } else {
      // Only now, on a real page, is the ordinary (filter-specific) empty state shown.
      expect(await screen.findByText('ไม่มีใบงาน PM ที่ยังดำเนินการอยู่')).toBeInTheDocument()
      expect(screen.getByText('ไม่มีใบงานในสถานะที่เลือก')).toBeInTheDocument()
    }
    expect(screen.queryByTestId('pm-manager-out-of-range')).toBeNull()
    expect(calls.map((c) => c.params)).toEqual([
      { page: '7', page_size: '50', status: 'PENDING_REVIEW' },
      { page: '1', page_size: '50', status: 'PENDING_REVIEW' },
    ])
  })

  it('shows the loading state, then the empty state', async () => {
    stub(['can_manage_pm'], [queuePage([], 0, 1, 'REAL')])
    renderPage()
    expect(await screen.findByText('ไม่มีใบงาน PM ที่ยังดำเนินการอยู่')).toBeInTheDocument()
    expect(screen.getByTestId('pm-manager-total')).toHaveTextContent('ทั้งหมด 0 รายการ')
    expect(screen.getByTestId('pm-manager-total')).not.toHaveTextContent('TEST')
  })

  it('replaces rows with an error on a failed refresh and never shows stale data', async () => {
    const user = userEvent.setup()
    stub(['can_manage_pm'], [
      queuePage([item('SYN-PMWO-1')]),
      json({ error: { code: 'TECHNICIAN_ASSIGNMENT_DATA_INVALID', message: 'x', details: null, request_id: 'r1' } }, 500),
    ])
    renderPage()
    await screen.findByRole('link', { name: 'SYN-PMWO-1' })
    await user.click(screen.getByRole('button', { name: 'รีเฟรช' }))
    expect(await screen.findByText('โหลดคิวใบงาน PM ไม่สำเร็จ')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'SYN-PMWO-1' })).toBeNull()
  })

  it('shows the permission state when the server refuses (403)', async () => {
    stub(['can_manage_pm'], [
      json({ error: { code: 'HTTP_ERROR', message: 'denied', details: null, request_id: 'r2' } }, 403),
    ])
    renderPage()
    expect(await screen.findByText('ไม่มีสิทธิ์เข้าถึง')).toBeInTheDocument()
    expect(screen.queryByTestId('pm-manager-total')).toBeNull()
  })

  it('without can_manage_pm shows the permission state and never reads the queue', async () => {
    const calls = stub(['can_view', 'can_manage_repair'], [])
    renderPage()
    expect(await screen.findByText('ไม่มีสิทธิ์เข้าถึง')).toBeInTheDocument()
    expect(calls).toEqual([])
  })

  it('renders through the shared responsive table (table and stacked-card labels)', async () => {
    stub(['can_manage_pm'], [queuePage([item('SYN-PMWO-1')])])
    const { container } = renderPage()
    await screen.findByRole('link', { name: 'SYN-PMWO-1' })
    expect(container.querySelector('.responsive-table')).not.toBeNull()
    expect(container.querySelector('[data-label="ทีมช่าง"]')).not.toBeNull()
  })
})
