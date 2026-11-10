import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { TechnicianWorkTimeResponse } from '../lib/types'
import { TechnicianWorkTimePage } from './TechnicianWorkTimePage'

// R5 — one technician across Work Orders (RM-9, RM-11). Synthetic data only.

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const BODY: TechnicianWorkTimeResponse = {
  technician_id: 'TEC-B', from: '2026-11-01T17:00:00Z', to: '2026-11-08T16:59:59Z',
  entries: [
    {
      entry_id: 'E1', revision: 1, record_kind: 'ENTRY', work_kind: 'REPAIR', job_id: 'RPR-1', technician_id: 'TEC-B',
      started_at: '2026-11-02T01:00:00Z', ended_at: '2026-11-02T09:00:00Z', time_class: 'REGULAR', description: 'ซ่อมปั๊ม',
      breaks: [], recorded_by: 'USR-B', recorded_at: '2026-11-02T10:00:00Z', reason: null, request_id: 'r', request_fingerprint: 'f',
      member_set_id: 'S', is_test_data: 'TRUE', test_batch_id: 'B',
    },
    {
      entry_id: 'E2', revision: 1, record_kind: 'ENTRY', work_kind: 'PM', job_id: 'PMW-1', technician_id: 'TEC-B',
      started_at: '2026-11-02T10:00:00Z', ended_at: '2026-11-02T12:00:00Z', time_class: 'OVERTIME', description: 'PM',
      breaks: [], recorded_by: 'USR-B', recorded_at: '2026-11-02T13:00:00Z', reason: null, request_id: 'r2', request_fingerprint: 'f',
      member_set_id: 'S', is_test_data: 'TRUE', test_batch_id: 'B',
    },
  ],
  totals: { regular_seconds: 8 * 3600, overtime_seconds: 2 * 3600, total_seconds: 10 * 3600, workdays: ['2026-11-02'] },
}

function renderAt(responder: (url: string) => Response) {
  const urls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    urls.push(String(input))
    return responder(String(input))
  }))
  render(
    <MemoryRouter initialEntries={['/work-time/assignees/TEC-B']}>
      <Routes>
        <Route path="/work-time/assignees/:assigneeId" element={<TechnicianWorkTimePage />} />
      </Routes>
    </MemoryRouter>,
  )
  return urls
}

afterEach(() => vi.unstubAllGlobals())

describe('TechnicianWorkTimePage', () => {
  it('shows regular, overtime, total man-hours and actual workdays across Repair and PM', async () => {
    const urls = renderAt(() => json(BODY))
    expect(await screen.findByTestId('twt-regular')).toHaveTextContent('8 ชม.')
    expect(screen.getByTestId('twt-overtime')).toHaveTextContent('2 ชม.')
    expect(screen.getByTestId('twt-total')).toHaveTextContent('10 ชม.')
    expect(screen.getByTestId('twt-workdays')).toHaveTextContent('1 วัน')
    expect(screen.getAllByTestId('twt-entry')).toHaveLength(2)
    expect(screen.getByRole('link', { name: 'งานซ่อม RPR-1' })).toHaveAttribute('href', '/repairs/RPR-1')
    expect(screen.getByRole('link', { name: 'งาน PM PMW-1' })).toHaveAttribute('href', '/pm/work-orders/PMW-1')
    expect(urls[0]).toMatch(/^\/api\/v1\/work-time\/assignees\/TEC-B\?from=.*%2B07%3A00&to=.*%2B07%3A00$/)
  })

  it('a 403 is shown as a permission refusal, not as empty data', async () => {
    renderAt(() => json({ error: { code: 'WORK_TIME_READ_FORBIDDEN', message: 'x', details: null, request_id: 'r' } }, 403))
    expect(await screen.findByText(/คุณดูเวลาทำงานของช่างคนอื่นไม่ได้/)).toBeInTheDocument()
    expect(screen.queryByTestId('twt-total')).toBeNull()
  })
})
