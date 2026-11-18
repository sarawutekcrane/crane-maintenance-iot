import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ResourceCalendarPage } from './ResourceCalendarPage'

// R8 early workstream — Resource Calendar page (addendum 2026-11-11; OD-7 = A). Synthetic data.
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const ENTRIES = [
  { kind: 'DRIVER', event_id: 'ODA-1', vehicle_id: 'VEH-1048', machine_no: 'TC-14', personnel_id: null, personnel_name: null,
    driver_id: 'DRV-TEST-901', driver_name: 'ผู้ขับทดสอบ หนึ่ง', identity: 'UNLINKED', role: 'DRIVER', role_note_th: null,
    mode: 'FULL_DAY', label_date: '2026-11-20', effective_start: '2026-11-19T17:00:00+00:00',
    effective_end: '2026-11-20T17:00:00+00:00', status: 'IDENTITY_UNVERIFIED' },
  { kind: 'CREW', event_id: 'CRA-1', vehicle_id: 'VEH-1048', machine_no: 'TC-14', personnel_id: 'PER-TEST-911',
    personnel_name: 'ช่าง เก้าหนึ่งหนึ่ง', driver_id: null, driver_name: null, identity: 'LINKED', role: 'SIGNALMAN',
    role_note_th: null, mode: 'DAY_SHIFT', label_date: '2026-11-20', effective_start: '2026-11-20T06:00:00+00:00',
    effective_end: '2026-11-20T10:00:00+00:00', status: 'IDENTITY_UNVERIFIED' },
]

function installApi(response: () => Response) {
  const calls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://localhost')
    calls.push(`${url.pathname.replace('/api/v1', '')}${url.search}`)
    if (url.pathname === '/api/v1/resource-calendar') return response()
    throw new Error(`Unexpected fetch: ${url.pathname}`)
  }))
  return calls
}

const calendar = (view = 'BOTH') =>
  json({ view, date_from: '2026-11-01', date_to: '2026-12-12', time_zone: 'Asia/Bangkok', entries: ENTRIES,
    conflicts: [{ code: 'CROSS_ROLE_IDENTITY_UNVERIFIED', first_event_id: 'ODA-1', second_event_id: 'CRA-1', personnel_id: 'PER-TEST-911' }] })

function renderAt(path = '/resource-calendar?date=2026-11-18') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ResourceCalendarPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2026-11-18T03:00:00Z'))
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('ResourceCalendarPage', () => {
  it('requests one bounded month window and marks days that need review', async () => {
    const calls = installApi(() => calendar())
    renderAt()
    const day = await screen.findByRole('button', { name: /คนขับ 1 ทีมงาน 1 มีรายการที่ต้องตรวจสอบ/ })
    expect(within(day).getByText('ตรวจสอบ')).toBeInTheDocument()
    expect(calls).toEqual(['/resource-calendar?from=2026-11-01&to=2026-12-12&view=BOTH'])
  })

  it('clicking a day lists each person with their own interval, role, vehicle and status', async () => {
    const user = userEvent.setup()
    installApi(() => calendar())
    renderAt()
    await user.click(await screen.findByRole('button', { name: /คนขับ 1 ทีมงาน 1/ }))
    expect(screen.getByText(/ผู้ขับทดสอบ หนึ่ง · คนขับ/)).toBeInTheDocument()
    expect(screen.getByText(/ช่าง เก้าหนึ่งหนึ่ง · Signalman/)).toBeInTheDocument()
    expect(screen.getByText('13:00 – 17:00')).toBeInTheDocument() // the crew member's own shift (Bangkok)
    expect(screen.getByText('00:00 – 24:00')).toBeInTheDocument() // the driver's full day
    expect(screen.getAllByRole('link', { name: 'TC-14' })[0]).toHaveAttribute('href', '/vehicle/VEH-1048')
    expect(screen.getAllByText(/ยืนยันตัวบุคคลไม่ได้/).length).toBeGreaterThanOrEqual(2)
  })

  it('an empty day says no recorded assignment, never a verified free person', async () => {
    const user = userEvent.setup()
    installApi(() => calendar())
    renderAt()
    await user.click(await screen.findByRole('button', { name: /^21 พ.ย. 2569/ }))
    expect(screen.getByText('ไม่มีการมอบหมายที่บันทึกไว้ในวันนี้ (ไม่ได้ยืนยันว่าบุคคลว่าง)')).toBeInTheDocument()
  })

  it('switches the view and the scale through the URL', async () => {
    const user = userEvent.setup()
    const calls = installApi(() => calendar())
    renderAt()
    await screen.findByRole('button', { name: /คนขับ 1 ทีมงาน 1/ })
    await user.click(screen.getByRole('button', { name: 'ตามบุคลากร' }))
    await user.click(screen.getByRole('button', { name: 'สัปดาห์' }))
    expect(calls).toContain('/resource-calendar?from=2026-11-01&to=2026-12-12&view=PERSONNEL')
    expect(calls).toContain('/resource-calendar?from=2026-11-15&to=2026-11-21&view=PERSONNEL')
  })

  it('a 403 shows the permission state and no data', async () => {
    installApi(() => json({ error: { code: 'HTTP_ERROR', message: 'x', details: null, request_id: 'r' } }, 403))
    renderAt()
    expect((await screen.findAllByText(/ไม่มีสิทธิ์/)).length).toBeGreaterThanOrEqual(1)
    expect(screen.queryByText('ช่าง เก้าหนึ่งหนึ่ง')).not.toBeInTheDocument()
  })
})
