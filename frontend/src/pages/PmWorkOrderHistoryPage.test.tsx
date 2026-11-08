import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PmWorkOrderHistoryPage } from './PmWorkOrderHistoryPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderPage(path = '/vehicle/VEH-1046/pm/history') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/vehicle/:vehicleId/pm/history" element={<PmWorkOrderHistoryPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('PmWorkOrderHistoryPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('lists PM work orders newest first with Thai status labels', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          items: [
            {
              pm_work_order_id: 'PMWO-0002',
              asset_type: 'VEHICLE',
              asset_id: 'VEH-1046',
              pm_plan_id: 'PMP-0001',
              revision_id: 'PMREV-0001',
              status: 'CLOSED',
              opened_at: '2026-02-02T00:00:00Z',
              closed_at: '2026-02-02T01:00:00Z',
              result_count: 3,
            },
          ],
          page: 1,
          page_size: 50,
          total_items: 1,
        }),
      ),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ปิดงานแล้ว')).toBeInTheDocument())
    expect(screen.getByText('PMP-0001')).toBeInTheDocument()
  })

  // R4 PM Workflow: every E01 status has its own Thai label (none shows a raw code).
  it.each([
    ['IN_PROGRESS', 'กำลังดำเนินการ'],
    ['PENDING_REVIEW', 'รอตรวจสอบ'],
    ['CANCELLED', 'ยกเลิกแล้ว'],
  ])('labels a %s work order as %s', async (status, label) => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          items: [
            {
              pm_work_order_id: 'PMWO-0003',
              asset_type: 'VEHICLE',
              asset_id: 'VEH-1046',
              pm_plan_id: 'PMP-0001',
              revision_id: 'PMREV-0001',
              status,
              opened_at: '2026-02-03T00:00:00Z',
              closed_at: null,
              result_count: 0,
            },
          ],
          page: 1,
          page_size: 50,
          total_items: 1,
        }),
      ),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText(label)).toBeInTheDocument())
    expect(screen.queryByText(status)).not.toBeInTheDocument()
  })

  it('shows an empty state when no PM history exists', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ items: [], page: 1, page_size: 50, total_items: 0 })),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ยังไม่มีประวัติ PM')).toBeInTheDocument())
  })

  // R4 / TASK-010: every Work Order stays reachable through server pages.
  describe('pagination', () => {
    function workOrder(n: number) {
      return {
        pm_work_order_id: `SYN-PMWO-${n}`,
        asset_type: 'VEHICLE',
        asset_id: 'VEH-1046',
        pm_plan_id: 'PMP-0001',
        revision_id: 'PMREV-0001',
        status: 'CLOSED',
        opened_at: '2026-02-02T00:00:00Z',
        closed_at: '2026-02-02T01:00:00Z',
        result_count: 1,
      }
    }

    /** A fake server holding `total` records, answering each requested page. */
    function server(total: number) {
      const params: Array<Record<string, string>> = []
      vi.stubGlobal(
        'fetch',
        vi.fn(async (input: RequestInfo | URL) => {
          const url = new URL(String(input), 'http://localhost')
          const query = Object.fromEntries(url.searchParams)
          params.push(query)
          const page = Number(query.page)
          const size = Number(query.page_size)
          const from = (page - 1) * size
          const items = Array.from({ length: Math.max(0, Math.min(size, total - from)) }, (_, i) => workOrder(from + i + 1))
          return jsonResponse({ items, page, page_size: size, total_items: total })
        }),
      )
      return params
    }

    it.each([
      [0, 'ยังไม่มีประวัติ PM', false],
      [1, 'SYN-PMWO-1', false],
      [50, 'SYN-PMWO-50', false],
    ])('%i records fit one page with no pager', async (total, visible, pager) => {
      const params = server(total)
      renderPage()
      expect(await screen.findByTestId('pm-history-total')).toHaveTextContent(`ทั้งหมด ${total} รายการ`)
      if (total > 0) {
        expect(screen.getAllByRole('link')).toHaveLength(total)
        expect(screen.getAllByRole('link')[total - 1]).toHaveAttribute('href', `/pm/work-orders/${visible}`)
      } else {
        expect(screen.getByText(visible)).toBeInTheDocument()
      }
      expect(Boolean(screen.queryByRole('button', { name: 'ถัดไป' }))).toBe(pager)
      expect(params).toEqual([{ asset_type: 'VEHICLE', asset_id: 'VEH-1046', page: '1', page_size: '50' }])
    })

    it('51 records: the 51st is on page 2 and reachable', async () => {
      const user = userEvent.setup()
      const params = server(51)
      renderPage()
      expect(await screen.findByText('หน้า 1 / 2')).toBeInTheDocument()
      expect(screen.getAllByRole('link')).toHaveLength(50)
      await user.click(screen.getByRole('button', { name: 'ถัดไป' }))
      expect(await screen.findByText('หน้า 2 / 2')).toBeInTheDocument()
      expect(screen.getAllByRole('link')).toHaveLength(1)
      expect(screen.getByRole('link')).toHaveAttribute('href', '/pm/work-orders/SYN-PMWO-51')
      expect(screen.getByRole('button', { name: 'ถัดไป' })).toBeDisabled()
      expect(params.map((p) => p.page)).toEqual(['1', '2'])
    })

    it('more than 100 records: forward and back through three pages, starting from the URL', async () => {
      const user = userEvent.setup()
      const params = server(120)
      renderPage('/vehicle/VEH-1046/pm/history?page=2')
      expect(await screen.findByText('หน้า 2 / 3')).toBeInTheDocument()
      expect(screen.getAllByRole('link')[0]).toHaveAttribute('href', '/pm/work-orders/SYN-PMWO-51')
      await user.click(screen.getByRole('button', { name: 'ถัดไป' }))
      expect(await screen.findByText('หน้า 3 / 3')).toBeInTheDocument()
      expect(screen.getAllByRole('link')).toHaveLength(20)
      await user.click(screen.getByRole('button', { name: 'ก่อนหน้า' }))
      await user.click(await screen.findByRole('button', { name: 'ก่อนหน้า' }))
      expect(await screen.findByText('หน้า 1 / 3')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'ก่อนหน้า' })).toBeDisabled()
      expect(params.map((p) => p.page)).toEqual(['2', '3', '2', '1'])
    })

    it('a page beyond the last offers the last real page instead of "no history"', async () => {
      const user = userEvent.setup()
      server(60)
      renderPage('/vehicle/VEH-1046/pm/history?page=9')
      const notice = await screen.findByTestId('pm-history-out-of-range')
      expect(notice).toHaveTextContent('ไม่มีหน้า 9 — มีทั้งหมด 2 หน้า')
      expect(screen.queryByText('เริ่มทำ PM ครั้งแรกได้จากหน้าสรุป PM')).toBeNull()
      await user.click(screen.getByRole('button', { name: 'ไปหน้าสุดท้าย (หน้า 2)' }))
      expect(await screen.findByText('หน้า 2 / 2')).toBeInTheDocument()
    })

    it.each([
      [403, 'HTTP_ERROR'],
      [503, 'REGISTRY_DATA_CONTEXT_NOT_CONFIGURED'],
      [500, 'TECHNICIAN_ASSIGNMENT_JOB_DATA_INVALID'],
    ])('a %i read is never shown as empty history', async (status, code) => {
      vi.stubGlobal(
        'fetch',
        vi.fn(async () => jsonResponse({ error: { code, message: 'x', details: null, request_id: 'req-1' } }, status)),
      )
      renderPage()
      if (status === 403) expect(await screen.findByText('ไม่มีสิทธิ์เข้าถึง')).toBeInTheDocument()
      else expect(await screen.findByRole('button', { name: /ลองใหม่/ })).toBeInTheDocument()
      expect(screen.queryByText('ยังไม่มีประวัติ PM')).toBeNull()
      expect(screen.queryByTestId('pm-history-total')).toBeNull()
    })
  })
})
