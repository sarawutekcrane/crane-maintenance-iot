import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import { DepartmentHistoryPanel } from './DepartmentHistoryPanel'

/** R2 Batch R2-C2a — the read-only R2f-g department history (shapes from the API schema). */

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const ALL_CAPS = ['can_view', 'can_manage_personnel', 'can_manage_department', 'can_link_personnel_technician',
  'can_link_personnel_account', 'can_link_personnel_driver', 'can_assign_equipment_caretaker', 'can_assign_crane_driver']

function stub(history: () => Response) {
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/me')) return json({ user_id: 'dev-user', roles: [], capabilities: ALL_CAPS, data_context: 'TEST' })
    if (url.endsWith('/personnel/PER-TEST-911/department-history')) return history()
    throw new Error(`Unexpected fetch: ${url}`)
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

function renderPanel() {
  return render(
    <CapabilitiesProvider>
      <MemoryRouter><DepartmentHistoryPanel personnelId="PER-TEST-911" /></MemoryRouter>
    </CapabilitiesProvider>,
  )
}

const period = (over: Record<string, unknown>) => ({
  event_id: 'PDH-1', in_force: true, entry_operation: 'TRANSFER', revision_no: '1', head_record_id: 'PDH-1',
  department_id: 'DEPT-SYN-A', effective_at: '2026-02-01T00:00:00+00:00', effective_precision: 'DATETIME',
  derived_end_at: null, recorded_at: '2026-02-01T00:00:01+00:00', recorded_by: 'synthetic-mover', notes: [], ...over,
})

describe('DepartmentHistoryPanel', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('Mock/TEST today: the empty history state, with the approved title', async () => {
    stub(() => json({ personnel_id: 'PER-TEST-911', timeline_status: 'VALID', current_status: 'NONE', current_department_id: null,
      current_since: null, as_of: null, as_of_status: null, as_of_department_id: null, as_of_since: null, events: [] }))
    renderPanel()
    expect(screen.getByRole('heading', { name: 'ประวัติการสังกัดแผนก' })).toBeInTheDocument()
    expect(await screen.findAllByText('ยังไม่มีประวัติการสังกัดแผนก')).not.toHaveLength(0)
  })

  it('a non-empty history shows department ids only: no name, no link, no department-detail read, no move control', async () => {
    const fn = stub(() => json({ personnel_id: 'PER-TEST-911', timeline_status: 'VALID', current_status: 'EVENT',
      current_department_id: 'DEPT-SYN-B', current_since: '2026-03-01T00:00:00+00:00', as_of: null, as_of_status: null,
      as_of_department_id: null, as_of_since: null,
      events: [period({}), period({ event_id: 'PDH-2', head_record_id: 'PDH-2', department_id: 'DEPT-SYN-B',
        effective_at: '2026-03-01T00:00:00+00:00' })] }))
    renderPanel()
    const panel = await screen.findByTestId('department-history')
    expect(within(panel).getAllByText('DEPT-SYN-B').length).toBeGreaterThan(0)
    expect(within(panel).getByText('DEPT-SYN-A')).toBeInTheDocument()
    expect(within(panel).getAllByText('synthetic-mover')).toHaveLength(2)
    expect(within(panel).queryByRole('link')).not.toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument() // even with every capability
    const urls = fn.mock.calls.map(([u]) => String(u))
    expect(urls.some((u) => u.includes('/departments'))).toBe(false)
  })

  it('a failed read is an error (never "no history"); an invalid body is an error too', async () => {
    stub(() => json({ error: { code: 'PERSONNEL_DEPARTMENT_HISTORY_READ_FAILED', message: 'x', details: null, request_id: 'r-9' } }, 503))
    renderPanel()
    expect(await screen.findByText('โหลดประวัติการสังกัดแผนกไม่สำเร็จ')).toBeInTheDocument()
    expect(screen.getByText(/r-9/)).toBeInTheDocument()
    expect(screen.queryByText('ยังไม่มีประวัติการสังกัดแผนก')).not.toBeInTheDocument()
    vi.unstubAllGlobals()
  })

  it('an unexpected body is not shown as an empty history', async () => {
    stub(() => json({ personnel_id: 'PER-TEST-911', events: 'nope' }))
    renderPanel()
    expect(await screen.findByText('ข้อมูลที่ได้รับจากระบบไม่อยู่ในรูปแบบที่รองรับ จึงไม่แสดงผล')).toBeInTheDocument()
  })

  it('404 for a personnel outside the server scope is a controlled error', async () => {
    stub(() => json({ error: { code: 'PERSONNEL_NOT_FOUND', message: 'x', details: null, request_id: 'r-1' } }, 404))
    renderPanel()
    expect(await screen.findByText('โหลดประวัติการสังกัดแผนกไม่สำเร็จ')).toBeInTheDocument()
  })
})
