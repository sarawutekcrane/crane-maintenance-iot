import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import { E2DriverAssignmentsPanel } from './E2DriverAssignmentsPanel'

/** R2 Batch R2-C2b — READ ONLY driver axis of E2 (shapes from the R2-C1 mock). */

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const unit = (over: Record<string, unknown> = {}) => ({ event_id: 'ODA-N', revision_no: '1', vehicle_id: 'VEH-1048',
  assigned_driver_id: 'DRV-TEST-902', mode: 'NIGHT_SHIFT', label_date: '2026-10-22', effective_start: '2026-10-22T13:00:00+00:00',
  effective_end: '2026-10-22T23:00:00+00:00', ...over })
const SCHEDULE = { driver_id: 'DRV-TEST-902', timeline_status: 'VALID',
  intervals: [unit(), unit({ event_id: 'ODA-S', vehicle_id: 'VEH-TEST-901', mode: 'FULL_DAY', label_date: '2026-10-21',
    effective_start: '2026-10-20T17:00:00+00:00', effective_end: '2026-10-21T17:00:00+00:00' })],
  conflicts: [], warnings: [{ code: 'ADJACENT_ASSIGNMENT_REST_WARNING', event_id: 'ODA-N', driver_id: 'DRV-TEST-902', vehicle_id: 'VEH-1048', related_event_id: 'ODA-S' }] }

function stub(answer: () => Response, caps = ['can_view', 'can_assign_crane_driver']) {
  const fn = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/me')) return json({ user_id: 'dev-user', roles: [], capabilities: caps, data_context: 'TEST' })
    if (url.includes('/drivers/DRV-TEST-902/operational-driver-assignments?')) return answer()
    throw new Error(`Unexpected fetch: ${url}`)
  })
  vi.stubGlobal('fetch', fn)
  return fn
}
const renderPanel = () => render(
  <CapabilitiesProvider><MemoryRouter><E2DriverAssignmentsPanel driverId="DRV-TEST-902" /></MemoryRouter></CapabilitiesProvider>,
)

describe('E2DriverAssignmentsPanel', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists the driver\'s units across vehicles with Vehicle Detail links; read only even with the write capability', async () => {
    const fn = stub(() => json(SCHEDULE))
    renderPanel()
    expect(screen.getByTestId('e2-note')).toHaveTextContent('เป็นข้อมูลการมอบหมาย ไม่ใช่การยืนยันว่าได้ขับรถจริง')
    const table = await screen.findByTestId('e2-intervals')
    expect(within(table).getByRole('link', { name: 'VEH-1048' })).toHaveAttribute('href', '/vehicle/VEH-1048')
    expect(within(table).getByRole('link', { name: 'VEH-TEST-901' })).toHaveAttribute('href', '/vehicle/VEH-TEST-901')
    expect(table).toHaveTextContent('กะกลางคืน')
    expect(table).toHaveTextContent('20:00 – 06:00 (+1 วัน)')
    expect(table).toHaveTextContent('00:00 – 24:00')
    expect(screen.getByTestId('e2-warnings')).toHaveTextContent('ผู้ขับมีการมอบหมายต่อเนื่องติดกัน')
    expect(screen.queryByRole('button', { name: /มอบหมาย|ยกเลิก|แก้ไข/ })).not.toBeInTheDocument()
    expect(fn.mock.calls.every(([, init]) => !init?.method)).toBe(true)
    expect(String(fn.mock.calls.find(([u]) => String(u).includes('operational'))?.[0])).toMatch(/from=\d{4}-\d{2}-\d{2}&to=\d{4}-\d{2}-\d{2}$/)
  })

  it('the filter re-reads the chosen window and mode', async () => {
    const fn = stub(() => json(SCHEDULE))
    const user = userEvent.setup()
    renderPanel()
    await screen.findByTestId('e2-intervals')
    await user.clear(screen.getByLabelText('ตั้งแต่วันที่'))
    await user.type(screen.getByLabelText('ตั้งแต่วันที่'), '2026-10-21')
    await user.clear(screen.getByLabelText('ถึงวันที่'))
    await user.type(screen.getByLabelText('ถึงวันที่'), '2026-10-22')
    await user.selectOptions(screen.getByLabelText('รูปแบบ'), 'FULL_DAY')
    await user.click(screen.getByRole('button', { name: 'แสดงตามช่วงที่เลือก' }))
    await waitFor(() => expect(String(fn.mock.calls.at(-1)?.[0]))
      .toBe('/api/v1/drivers/DRV-TEST-902/operational-driver-assignments?from=2026-10-21&to=2026-10-22&mode=FULL_DAY'))
  })

  it('a conflicted driver timeline shows the conflict', async () => {
    stub(() => json({ ...SCHEDULE, timeline_status: 'CONFLICTED',
      conflicts: [{ axis: 'DRIVER', key: 'DRV-TEST-902', first: unit(), second: unit({ event_id: 'ODA-X', vehicle_id: 'VEH-TEST-901' }) }] }))
    renderPanel()
    expect(await screen.findByTestId('e2-timeline-conflicted')).toHaveTextContent('ข้อมูลการมอบหมายขัดแย้งกัน')
    expect(screen.getByTestId('e2-conflicts')).toHaveTextContent('ODA-X')
  })

  it('Google Sheets mode (501) is an informational unavailable state; an out-of-scope driver gets the scope state', async () => {
    stub(() => json({ error: { code: 'FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE', message: 'x', details: null, request_id: 'r' } }, 501))
    const { unmount } = renderPanel()
    expect(await screen.findByTestId('e2-unavailable')).toHaveTextContent('Mock/TEST')
    unmount()
    stub(() => json({ error: { code: 'DRIVER_SCOPE_UNPROVEN', message: 'x', details: { driver_id: 'DRV-TEST-902' }, request_id: 'r' } }, 422))
    renderPanel()
    expect(await screen.findByTestId('e2-scope-unproven')).toBeInTheDocument()
  })

  it('a malformed answer is an error, never "no assignment"', async () => {
    stub(() => json({ driver_id: 'DRV-TEST-902', timeline_status: 'VALID', intervals: [{ event_id: 'x' }], conflicts: [], warnings: [] }))
    renderPanel()
    expect(await screen.findByText('ข้อมูลที่ได้รับจากระบบไม่อยู่ในรูปแบบที่รองรับ จึงไม่แสดงผล')).toBeInTheDocument()
    expect(screen.queryByText('ไม่มีการมอบหมายขับรถในช่วงที่เลือก')).not.toBeInTheDocument()
  })
})
