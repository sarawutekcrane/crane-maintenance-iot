import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import { CaretakerPanel } from './CaretakerPanel'

/** R2 Batch R2-C2a — the R2f-d equipment caretaker panel (synthetic data; shapes from the live API). */

const json = (body: unknown, status = 200, rid?: string) => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json', ...(rid ? { 'X-Request-Id': rid } : {}) },
})
const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

const NONE = { equipment_id: 'EQP-0002', timeline_status: 'VALID', current_status: 'NONE', current_technician_id: null,
  current_since: null, current_technician_resolution: 'NONE', current_technician: null, events: [] }
const period = { event_id: 'ECH-1', in_force: true, entry_operation: 'TRANSFER', revision_no: '1', head_record_id: 'ECH-1',
  technician_id: 'TEC-TEST-911', effective_at: '2026-10-15T05:00:00+00:00', effective_precision: 'DATETIME',
  derived_end_at: null, recorded_at: '2026-10-15T05:00:00.5+00:00', recorded_by: 'dev-user', notes: [] }
const ASSIGNED = { ...NONE, current_status: 'EVENT', current_technician_id: 'TEC-TEST-911', current_since: period.effective_at,
  current_technician_resolution: 'RESOLVED',
  current_technician: { technician_id: 'TEC-TEST-911', first_name: 'ช่างทดสอบ', last_name: 'ลำดับหนึ่ง', active_status: 'ACTIVE' },
  events: [period] }
const TECHNICIANS = { items: [
  { technician_id: 'TEC-TEST-911', first_name: 'ช่างทดสอบ', last_name: 'ลำดับหนึ่ง', active_status: 'ACTIVE' },
  { technician_id: 'TEC-TEST-912', first_name: 'ช่างทดสอบ', last_name: 'ลำดับสอง', active_status: 'ACTIVE' },
], page: 1, page_size: 200, total_items: 2 }

type Post = (body: Record<string, unknown>, rid: string, call: number) => Response | Promise<Response>

function stub({ caps = ['can_view', 'can_assign_equipment_caretaker'], reads = [NONE], post }: {
  caps?: string[]; reads?: unknown[]; post?: Post
}) {
  let read = 0
  let posts = 0
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/me')) return json({ user_id: 'dev-user', roles: [], capabilities: caps, data_context: 'TEST' })
    if (url.includes('/technicians?')) return json(TECHNICIANS)
    if (init?.method === 'POST') {
      const rid = (init.headers as Record<string, string>)['X-Request-Id']
      return post ? post(JSON.parse(String(init.body)), rid, posts++) : json({}, 500)
    }
    if (url.endsWith('/equipment/EQP-0002/caretakers')) return json(reads[Math.min(read++, reads.length - 1)])
    throw new Error(`Unexpected fetch: ${url}`)
  })
  vi.stubGlobal('fetch', fn)
  return fn
}
const posts = (fn: ReturnType<typeof stub>) => fn.mock.calls.filter(([, init]) => init?.method === 'POST')
const caretakerReads = (fn: ReturnType<typeof stub>) => fn.mock.calls.filter(([u, init]) => !init?.method && String(u).endsWith('/caretakers'))

const renderPanel = () => render(
  <CapabilitiesProvider><MemoryRouter><CaretakerPanel equipmentId="EQP-0002" /></MemoryRouter></CapabilitiesProvider>,
)

async function transferTo(technicianId: string) {
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'กำหนดผู้ดูแล' }))
  const dialog = screen.getByTestId('timeline-event-dialog')
  await user.selectOptions(within(dialog).getByLabelText('รหัสช่าง'), technicianId)
  await user.click(within(dialog).getByRole('button', { name: /^ยืนยัน/ }))
  return user
}

describe('CaretakerPanel', () => {
  beforeEach(() => window.localStorage.clear())
  afterEach(() => vi.unstubAllGlobals())

  it('shows the current caretaker, history and the TEST context; a can_view-only user gets no controls', async () => {
    stub({ caps: ['can_view'], reads: [ASSIGNED] })
    renderPanel()
    expect(screen.getByRole('heading', { name: 'ผู้ดูแลอุปกรณ์และประวัติ' })).toBeInTheDocument()
    expect(await screen.findByTestId('caretaker-current')).toHaveTextContent('TEC-TEST-911')
    expect(screen.getByTestId('caretaker-current')).toHaveTextContent('ช่างทดสอบ ลำดับหนึ่ง')
    expect(screen.getByTestId('v2-data-context')).toHaveTextContent('TEST')
    expect(screen.queryByTestId('caretaker-actions')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /ผู้ดูแล/ })).not.toBeInTheDocument()
  })

  it('TRANSFER (first assignment): explicit technician, exact body, UUID request id, success and authoritative re-read', async () => {
    const fn = stub({ reads: [NONE, ASSIGNED], post: (_body, rid) => json({ request_id: rid, changed: true, record_id: 'ECH-1',
      event_id: 'ECH-1', timeline_status_after: 'VALID', current_status: 'EVENT', current_technician_id: 'TEC-TEST-911' }, 200, rid) })
    renderPanel()
    await transferTo('TEC-TEST-911')
    expect(await screen.findByText('บันทึกเรียบร้อยแล้ว')).toBeInTheDocument()
    const [, init] = posts(fn)[0]
    expect(String(posts(fn)[0][0])).toBe('/api/v1/equipment/EQP-0002/caretaker-events')
    expect(JSON.parse(String(init?.body))).toEqual({ operation: 'TRANSFER', technician_id: 'TEC-TEST-911', effective: { mode: 'NOW' },
      expected_current_technician_id: null })
    expect(((init?.headers ?? {}) as Record<string, string>)['X-Request-Id']).toMatch(UUID_V4)
    await waitFor(() => expect(screen.getByTestId('caretaker-current')).toHaveTextContent('TEC-TEST-911'))
    expect(caretakerReads(fn)).toHaveLength(2)
    expect(screen.queryByTestId('r2-pending-intent')).not.toBeInTheDocument()
  })

  it('a refusal keeps the dialog open with its message and records nothing pending', async () => {
    stub({ post: (_b, rid) => json({ error: { code: 'TECHNICIAN_NOT_ACTIVE', message: 'x', details: null, request_id: rid } }, 422, rid) })
    renderPanel()
    await transferTo('TEC-TEST-912')
    const dialog = screen.getByTestId('timeline-event-dialog')
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('ไม่อยู่ในสถานะใช้งาน')
    expect(screen.queryByTestId('r2-pending-intent')).not.toBeInTheDocument()
  })

  it('409 stale: the dialog closes and the panel re-reads', async () => {
    const fn = stub({ reads: [NONE, ASSIGNED], post: (_b, rid) => json({ error: { code: 'CARETAKER_HISTORY_STALE', message: 'x',
      details: { field: 'current_technician_id' }, request_id: rid } }, 409, rid) })
    renderPanel()
    await transferTo('TEC-TEST-911')
    expect(await screen.findByTestId('r2-write-message')).toHaveTextContent('ข้อมูลผู้ดูแลเปลี่ยนไปหลังจากที่โหลดข้อมูล')
    await waitFor(() => expect(caretakerReads(fn)).toHaveLength(2))
    expect(screen.queryByTestId('timeline-event-dialog')).not.toBeInTheDocument()
  })

  it('an unknown outcome keeps the intent: no new write, explicit resend with the SAME id and body, settled by the history', async () => {
    let firstRid = ''
    let firstBody = ''
    const fn = stub({
      reads: [NONE, { ...ASSIGNED, events: [{ ...period, event_id: 'ECH-7', head_record_id: 'ECH-7' }] }],
      post: (body, rid, call) => {
        if (call === 0) {
          firstRid = rid
          firstBody = JSON.stringify(body)
          return Promise.reject(new TypeError('Failed to fetch'))
        }
        return json({ request_id: rid, replayed: true, record_ids: ['ECH-7'] }, 200, rid)
      },
    })
    renderPanel()
    const user = await transferTo('TEC-TEST-911')
    const pending = await screen.findByTestId('r2-pending-intent')
    expect(pending).toHaveTextContent(firstRid)
    expect(screen.queryByTestId('caretaker-actions')).not.toBeInTheDocument() // no new intent while unresolved
    expect(posts(fn)).toHaveLength(1) // no automatic retry
    await user.click(within(pending).getByRole('button', { name: 'ส่งคำขอเดิมอีกครั้ง' }))
    await waitFor(() => expect(posts(fn)).toHaveLength(2))
    const [, resend] = posts(fn)[1]
    expect(((resend?.headers ?? {}) as Record<string, string>)['X-Request-Id']).toBe(firstRid)
    expect(resend?.body).toBe(firstBody)
    // The replay is settled only by the authoritative history read that shows record ECH-7.
    expect(await screen.findByText('ตรวจสอบกับประวัติล่าสุดแล้ว: คำขอเดิมถูกบันทึกแล้ว')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByTestId('r2-pending-intent')).not.toBeInTheDocument())
  })

  it('a refused resend (post-replay STALE) keeps the intent pending with the same id and explains why', async () => {
    let firstRid = ''
    const fn = stub({
      reads: [NONE, ASSIGNED],
      post: (_body, rid, call) => {
        if (call === 0) {
          firstRid = rid
          return Promise.reject(new TypeError('Failed to fetch'))
        }
        return json({ error: { code: 'CARETAKER_HISTORY_STALE', message: 'x', details: null, request_id: rid } }, 409, rid)
      },
    })
    renderPanel()
    const user = await transferTo('TEC-TEST-911')
    await user.click(within(await screen.findByTestId('r2-pending-intent')).getByRole('button', { name: 'ส่งคำขอเดิมอีกครั้ง' }))
    expect(await screen.findByTestId('r2-write-message')).toHaveTextContent('ไม่ได้ยืนยันว่าคำขอครั้งก่อนไม่ได้ถูกบันทึก')
    const pending = screen.getByTestId('r2-pending-intent')
    expect(pending).toHaveTextContent(firstRid)
    expect(within(pending).getByRole('button', { name: 'ส่งคำขอเดิมอีกครั้ง' })).toBeInTheDocument()
    expect(screen.queryByTestId('caretaker-actions')).not.toBeInTheDocument()
    expect(posts(fn)).toHaveLength(2)
    expect(caretakerReads(fn)).toHaveLength(1) // nothing confirmed: no re-read was triggered by the refusal
  })

  it('a duplicate submission is impossible while the request is in flight', async () => {
    let release: (r: Response) => void = () => {}
    const fn = stub({ post: () => new Promise<Response>((resolve) => { release = resolve }) })
    renderPanel()
    await transferTo('TEC-TEST-911')
    const dialog = screen.getByTestId('timeline-event-dialog')
    expect(within(dialog).getByRole('button', { name: 'กำลังบันทึก...' })).toBeDisabled()
    expect(posts(fn)).toHaveLength(1)
    release(json({}, 502))
    expect(await screen.findByTestId('r2-pending-intent')).toBeInTheDocument()
  })

  it('an equipment outside the server data scope shows the scope state and no controls', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/me')) return json({ user_id: 'dev-user', roles: [], capabilities: ['can_assign_equipment_caretaker'], data_context: 'TEST' })
      if (url.includes('/technicians?')) return json(TECHNICIANS)
      return json({ error: { code: 'EQUIPMENT_SCOPE_UNPROVEN', message: 'x', details: null, request_id: 'r' } }, 422)
    }))
    renderPanel()
    expect(await screen.findByTestId('r2-scope-unproven')).toHaveTextContent('ไม่อยู่ในขอบเขตข้อมูลปัจจุบัน')
    expect(screen.queryByTestId('caretaker-actions')).not.toBeInTheDocument()
  })

  it('an assigned caretaker offers change / end / insertion / correction / cancellation', async () => {
    stub({ reads: [ASSIGNED] })
    renderPanel()
    const actions = await screen.findByTestId('caretaker-actions')
    for (const name of ['เปลี่ยนผู้ดูแล', 'สิ้นสุดการดูแล', 'เพิ่มประวัติย้อนหลัง', 'แก้ไขรายการ', 'ยกเลิกรายการ']) {
      expect(within(actions).getByRole('button', { name })).toBeInTheDocument()
    }
  })
})
