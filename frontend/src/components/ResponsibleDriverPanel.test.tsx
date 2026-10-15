import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import { ResponsibleDriverPanel } from './ResponsibleDriverPanel'

/** R2 Batch R2-C2a — the R2f-f PERMANENT responsible driver on Vehicle Detail (synthetic data). */

const json = (body: unknown, status = 200, rid?: string) => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json', ...(rid ? { 'X-Request-Id': rid } : {}) },
})
const NONE = { vehicle_id: 'VEH-1048', timeline_status: 'VALID', current_status: 'NONE', current_driver_id: null,
  current_since: null, events: [] }
const period = { event_id: 'CDR-1', in_force: true, entry_operation: 'TRANSFER', revision_no: '1', head_record_id: 'CDR-1',
  driver_id: 'DRV-TEST-901', effective_at: '2026-01-04T17:00:00+00:00', effective_precision: 'DATE', derived_end_at: null,
  recorded_at: '2026-10-15T05:00:00+00:00', recorded_by: 'dev-user', notes: [] }
const ASSIGNED = { ...NONE, current_status: 'EVENT', current_driver_id: 'DRV-TEST-901', current_since: period.effective_at, events: [period] }
const DRIVERS = { items: [
  { driver_id: 'DRV-TEST-901', driver_name_th: 'ผู้ขับทดสอบ หนึ่ง', phone: null, license_no: null, license_expiry_date: null, active_status: 'ACTIVE', note_th: null },
  { driver_id: 'DRV-TEST-903', driver_name_th: 'ผู้ขับทดสอบ สาม', phone: null, license_no: null, license_expiry_date: null, active_status: 'INACTIVE', note_th: null },
], page: 1, page_size: 200, total_items: 2 }

function stub({ caps = ['can_view', 'can_assign_crane_driver'], reads = [NONE], post }: {
  caps?: string[]; reads?: unknown[]; post?: (body: Record<string, unknown>, rid: string) => Response
}) {
  let read = 0
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/me')) return json({ user_id: 'dev-user', roles: [], capabilities: caps, data_context: 'TEST' })
    if (url.includes('/drivers?')) return json(DRIVERS)
    if (init?.method === 'POST') {
      const rid = (init.headers as Record<string, string>)['X-Request-Id']
      return post ? post(JSON.parse(String(init.body)), rid) : json({}, 500)
    }
    if (url.endsWith('/vehicles/VEH-1048/responsible-drivers')) return json(reads[Math.min(read++, reads.length - 1)])
    throw new Error(`Unexpected fetch: ${url}`)
  })
  vi.stubGlobal('fetch', fn)
  return fn
}
const posts = (fn: ReturnType<typeof stub>) => fn.mock.calls.filter(([, init]) => init?.method === 'POST')

const renderPanel = () => render(
  <CapabilitiesProvider><MemoryRouter><ResponsibleDriverPanel vehicleId="VEH-1048" /></MemoryRouter></CapabilitiesProvider>,
)

describe('ResponsibleDriverPanel', () => {
  beforeEach(() => window.localStorage.clear())
  afterEach(() => vi.unstubAllGlobals())

  it('is labelled as permanent responsibility, never as actual driving, and reads no E2 data', async () => {
    const fn = stub({ caps: ['can_view'], reads: [ASSIGNED] })
    renderPanel()
    expect(screen.getByRole('heading', { name: 'ผู้รับผิดชอบรถประจำ' })).toBeInTheDocument()
    expect(screen.getByTestId('responsible-driver-note')).toHaveTextContent('ผู้รับผิดชอบรถประจำ ไม่ได้ยืนยันว่าเป็นผู้ขับรถจริงในแต่ละวัน')
    const current = await screen.findByTestId('responsible-driver-current')
    expect(within(current).getByRole('link', { name: 'DRV-TEST-901' })).toHaveAttribute('href', '/drivers/DRV-TEST-901')
    await waitFor(() => expect(current).toHaveTextContent('ผู้ขับทดสอบ หนึ่ง'))
    expect(screen.queryByText(/กะ|การมอบหมายผู้ขับรถตามวัน/)).not.toBeInTheDocument()
    expect(fn.mock.calls.map(([u]) => String(u)).some((u) => u.includes('operational-driver'))).toBe(false)
    expect(screen.queryByTestId('responsible-driver-actions')).not.toBeInTheDocument() // can_view only
  })

  it('a driver is never chosen automatically: no POST until one is explicitly selected', async () => {
    const fn = stub({ post: (_b, rid) => json({ request_id: rid, changed: true, record_id: 'CDR-1', event_id: 'CDR-1',
      timeline_status_after: 'VALID', current_status: 'EVENT', current_driver_id: 'DRV-TEST-901' }, 200, rid), reads: [NONE, ASSIGNED] })
    renderPanel()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'กำหนดผู้รับผิดชอบ' }))
    const dialog = screen.getByTestId('timeline-event-dialog')
    await waitFor(() => expect(within(dialog).getByLabelText('รหัสคนขับ/ผู้ควบคุม').tagName).toBe('SELECT'))
    expect(within(dialog).getByLabelText('รหัสคนขับ/ผู้ควบคุม')).toHaveValue('')
    await user.click(within(dialog).getByRole('button', { name: /^ยืนยัน/ }))
    expect(posts(fn)).toHaveLength(0)
    await user.selectOptions(within(dialog).getByLabelText('รหัสคนขับ/ผู้ควบคุม'), 'DRV-TEST-901')
    await user.click(within(dialog).getByLabelText('ระบุวันที่'))
    await user.type(within(dialog).getByLabelText('วันที่มีผล'), '2026-01-05')
    await user.click(within(dialog).getByRole('button', { name: /^ยืนยัน/ }))
    await waitFor(() => expect(posts(fn)).toHaveLength(1))
    expect(String(posts(fn)[0][0])).toBe('/api/v1/vehicles/VEH-1048/responsible-driver-events')
    expect(JSON.parse(String(posts(fn)[0][1]?.body))).toEqual({ operation: 'TRANSFER', driver_id: 'DRV-TEST-901',
      effective: { mode: 'DATE', date: '2026-01-05' }, expected_current_driver_id: null })
    expect(await screen.findByText('บันทึกเรียบร้อยแล้ว')).toBeInTheDocument()
  })

  it('an INACTIVE (or out-of-scope) driver is refused by the backend and shown in the dialog', async () => {
    stub({ post: (_b, rid) => json({ error: { code: 'DRIVER_NOT_ACTIVE', message: 'x', details: { driver_id: 'DRV-TEST-903' },
      request_id: rid } }, 422, rid) })
    renderPanel()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'กำหนดผู้รับผิดชอบ' }))
    const dialog = screen.getByTestId('timeline-event-dialog')
    await waitFor(() => expect(within(dialog).getByLabelText('รหัสคนขับ/ผู้ควบคุม').tagName).toBe('SELECT'))
    await user.selectOptions(within(dialog).getByLabelText('รหัสคนขับ/ผู้ควบคุม'), 'DRV-TEST-903')
    await user.click(within(dialog).getByRole('button', { name: /^ยืนยัน/ }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('ไม่อยู่ในสถานะใช้งาน')
    expect(screen.queryByTestId('r2-pending-intent')).not.toBeInTheDocument()
  })

  it('END of the current responsibility sends the expected current driver and no driver id', async () => {
    const fn = stub({ reads: [ASSIGNED], post: (_b, rid) => json({ request_id: rid, changed: false }, 200, rid) })
    renderPanel()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'สิ้นสุดความรับผิดชอบ' }))
    await user.click(within(screen.getByTestId('timeline-event-dialog')).getByRole('button', { name: /^ยืนยัน/ }))
    await waitFor(() => expect(posts(fn)).toHaveLength(1))
    expect(JSON.parse(String(posts(fn)[0][1]?.body))).toEqual({ operation: 'END', effective: { mode: 'NOW' }, expected_current_driver_id: 'DRV-TEST-901' })
    expect(await screen.findByText('ข้อมูลเป็นค่านี้อยู่แล้ว ไม่มีการเปลี่ยนแปลง')).toBeInTheDocument()
  })

  it('a vehicle outside the server data scope shows the scope state and no controls', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/me')) return json({ user_id: 'dev-user', roles: [], capabilities: ['can_assign_crane_driver'], data_context: 'TEST' })
      if (url.includes('/drivers?')) return json(DRIVERS)
      return json({ error: { code: 'VEHICLE_SCOPE_UNPROVEN', message: 'x', details: null, request_id: 'r' } }, 422)
    }))
    renderPanel()
    expect(await screen.findByTestId('r2-scope-unproven')).toBeInTheDocument()
    expect(screen.queryByTestId('responsible-driver-actions')).not.toBeInTheDocument()
  })

  it('REQUEST_ID_REUSED keeps a CONFLICT intent that cannot be resent', async () => {
    stub({ post: (_b, rid) => json({ error: { code: 'REQUEST_ID_REUSED', message: 'x', details: { request_id: rid }, request_id: rid } }, 409, rid) })
    renderPanel()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'กำหนดผู้รับผิดชอบ' }))
    const dialog = screen.getByTestId('timeline-event-dialog')
    await waitFor(() => expect(within(dialog).getByLabelText('รหัสคนขับ/ผู้ควบคุม').tagName).toBe('SELECT'))
    await user.selectOptions(within(dialog).getByLabelText('รหัสคนขับ/ผู้ควบคุม'), 'DRV-TEST-901')
    await user.click(within(dialog).getByRole('button', { name: /^ยืนยัน/ }))
    const pending = await screen.findByTestId('r2-pending-intent')
    expect(pending).toHaveTextContent('รหัสคำขอขัดแย้ง')
    expect(within(pending).getByTestId('r2-conflict-escalation')).toHaveTextContent('กรุณาแจ้งผู้ดูแลระบบพร้อมรหัสคำขอนี้เพื่อตรวจสอบ')
    expect(within(pending).queryByRole('button', { name: 'ส่งคำขอเดิมอีกครั้ง' })).not.toBeInTheDocument()
    expect(screen.queryByTestId('responsible-driver-actions')).not.toBeInTheDocument()
  })

  it('an unknown outcome keeps the intent: explicit resend with the SAME id and body, replay settled only by the history', async () => {
    let call = 0
    let firstRid = ''
    let firstBody = ''
    const fn = stub({
      reads: [NONE, ASSIGNED],
      post: (body, rid) => {
        if (call++ === 0) {
          firstRid = rid
          firstBody = JSON.stringify(body)
          return json({}, 504)
        }
        return json({ request_id: rid, replayed: true, record_ids: ['CDR-1'] }, 200, rid)
      },
    })
    renderPanel()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'กำหนดผู้รับผิดชอบ' }))
    const dialog = screen.getByTestId('timeline-event-dialog')
    await waitFor(() => expect(within(dialog).getByLabelText('รหัสคนขับ/ผู้ควบคุม').tagName).toBe('SELECT'))
    await user.selectOptions(within(dialog).getByLabelText('รหัสคนขับ/ผู้ควบคุม'), 'DRV-TEST-901')
    await user.click(within(dialog).getByRole('button', { name: /^ยืนยัน/ }))
    const pending = await screen.findByTestId('r2-pending-intent')
    expect(pending).toHaveTextContent(firstRid)
    expect(posts(fn)).toHaveLength(1) // no automatic retry
    expect(screen.queryByTestId('responsible-driver-actions')).not.toBeInTheDocument()
    await user.click(within(pending).getByRole('button', { name: 'ส่งคำขอเดิมอีกครั้ง' }))
    await waitFor(() => expect(posts(fn)).toHaveLength(2))
    const [, resend] = posts(fn)[1]
    expect(((resend?.headers ?? {}) as Record<string, string>)['X-Request-Id']).toBe(firstRid)
    expect(resend?.body).toBe(firstBody)
    expect(await screen.findByText('ตรวจสอบกับประวัติล่าสุดแล้ว: คำขอเดิมถูกบันทึกแล้ว')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByTestId('r2-pending-intent')).not.toBeInTheDocument())
    expect(posts(fn)).toHaveLength(2)
  })
})
