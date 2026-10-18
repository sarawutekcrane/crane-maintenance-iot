import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import { bangkokToday } from '../lib/e2Assignments'
import { E2VehicleAssignmentsPanel } from './E2VehicleAssignmentsPanel'

/** R2 Batch R2-C2b — the E2 vehicle panel against stubbed R2-C1 contracts (shapes from the real mock). */

const json = (body: unknown, status = 200, rid?: string) => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json', ...(rid ? { 'X-Request-Id': rid } : {}) },
})
const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
const VEH = 'VEH-1048'

const interval = { event_id: 'ODA-1', revision_no: '1', vehicle_id: VEH, assigned_driver_id: 'DRV-TEST-901', mode: 'FULL_DAY',
  label_date: '2026-10-20', effective_start: '2026-10-19T17:00:00+00:00', effective_end: '2026-10-20T17:00:00+00:00' }
const NO_PERMANENT = { code: 'NO_PERMANENT_RESPONSIBLE_DRIVER', event_id: null, driver_id: null, vehicle_id: VEH, related_event_id: null }
const SCHEDULE = { vehicle_id: VEH, timeline_status: 'VALID', current_status: 'NONE', current: null, intervals: [interval],
  unknown: [], conflicts: [], warnings: [NO_PERMANENT] }
const EMPTY_SCHEDULE = { ...SCHEDULE, intervals: [], warnings: [] }
const record = (over: Record<string, unknown> = {}) => ({
  record_id: 'ODA-1', operation_id: 'ODO-1', record_kind: 'ASSIGNMENT', entry_operation: 'CREATE', event_id: 'ODA-1',
  revision_no: '1', supersedes_record_id: null, assigned_driver_id: 'DRV-TEST-901', mode: 'FULL_DAY', start_date: '2026-10-20',
  end_date: '2026-10-22', shift_start_time: null, shift_end_time: null, shift_end_day_offset: null, excluded_dates: [],
  related_event_id: null, relation: null, early_end_at: null, voided: false, handover_kind: null, predecessor_event_id: null,
  predecessor_revision_no: null, successor_event_id: null, successor_revision_no: null, handover_at: null, unknown_start_at: null,
  unknown_end_at: null, reason_th: null, recorded_at: '2026-10-16T00:24:28.000000+00:00', recorded_by: 'dev-user',
  request_id: 'req-original', ...over,
})
const HISTORY = { vehicle_id: VEH, events: [{ event_id: 'ODA-1', kind: 'ASSIGNMENT', lifecycle: 'ACTIVE', revision_no: '1', head_record_id: 'ODA-1' }],
  records: [record()] }
const EMPTY_HISTORY = { vehicle_id: VEH, events: [], records: [] }
const DRIVERS = { items: [
  { driver_id: 'DRV-TEST-901', driver_name_th: 'ผู้ขับทดสอบ หนึ่ง', phone: null, license_no: null, license_expiry_date: null, active_status: 'ACTIVE', note_th: null },
  { driver_id: 'DRV-TEST-902', driver_name_th: 'ผู้ขับทดสอบ สอง', phone: null, license_no: null, license_expiry_date: null, active_status: 'ACTIVE', note_th: null },
], page: 1, page_size: 200, total_items: 2 }

type Post = (body: Record<string, unknown>, rid: string, call: number) => Response | Promise<Response>

function stub({ caps = ['can_view', 'can_assign_crane_driver'], schedules = [SCHEDULE], histories = [HISTORY], post, read }: {
  caps?: string[]; schedules?: unknown[]; histories?: unknown[]; post?: Post; read?: (url: string) => Response | null
}) {
  let s = 0
  let h = 0
  let calls = 0
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/me')) return json({ user_id: 'dev-user', roles: [], capabilities: caps, data_context: 'TEST' })
    if (url.includes('/drivers?')) return json(DRIVERS)
    if (init?.method === 'POST') {
      const rid = (init.headers as Record<string, string>)['X-Request-Id']
      return post ? post(JSON.parse(String(init.body)), rid, calls++) : json({}, 500)
    }
    const custom = read?.(url)
    if (custom) return custom
    if (url.includes(`/vehicles/${VEH}/operational-driver-assignments?`)) return json(schedules[Math.min(s++, schedules.length - 1)])
    if (url.endsWith(`/vehicles/${VEH}/operational-driver-assignment-history`)) return json(histories[Math.min(h++, histories.length - 1)])
    throw new Error(`Unexpected fetch: ${url}`)
  })
  vi.stubGlobal('fetch', fn)
  return fn
}
const posts = (fn: ReturnType<typeof stub>) => fn.mock.calls.filter(([, init]) => init?.method === 'POST')
const reads = (fn: ReturnType<typeof stub>, part: string) => fn.mock.calls.filter(([u, init]) => !init?.method && String(u).includes(part))
const ridOf = (call: unknown[]) => ((call[1] as RequestInit).headers as Record<string, string>)['X-Request-Id']

const renderPanel = () => render(
  <CapabilitiesProvider><MemoryRouter><E2VehicleAssignmentsPanel vehicleId={VEH} /></MemoryRouter></CapabilitiesProvider>,
)

async function cancelFirst(reason = 'ไม่ใช้รถ') {
  const user = userEvent.setup()
  const row = await screen.findByTestId('e2-row-actions-ODA-1')
  await user.click(within(row).getByRole('button', { name: 'ยกเลิกการมอบหมายก่อนเริ่ม' }))
  const dialog = screen.getByTestId('e2-operation-dialog')
  await user.type(within(dialog).getByLabelText('เหตุผล (บังคับ)'), reason)
  await user.click(within(dialog).getByRole('button', { name: /^ยืนยัน/ }))
  return user
}

describe('E2VehicleAssignmentsPanel', () => {
  beforeEach(() => window.localStorage.clear())
  afterEach(() => vi.unstubAllGlobals())

  it('can_view only: note, status, schedule (FULL_DAY to 24:00), warnings, history; no controls; E2 routes only', async () => {
    const fn = stub({ caps: ['can_view'] })
    renderPanel()
    expect(screen.getByRole('heading', { name: 'การมอบหมายผู้ขับรถตามวัน/กะ' })).toBeInTheDocument()
    expect(screen.getByTestId('e2-note')).toHaveTextContent('เป็นข้อมูลการมอบหมาย ไม่ใช่การยืนยันว่าได้ขับรถจริง')
    expect(await screen.findByTestId('e2-current-status')).toHaveTextContent('ไม่มีการมอบหมายในขณะนี้')
    expect(screen.getByTestId('e2-intervals')).toHaveTextContent('00:00 – 24:00')
    expect(screen.getByTestId('e2-intervals')).toHaveTextContent('ทั้งวัน')
    expect(screen.getByTestId('e2-warnings')).toHaveTextContent('ยังไม่มีผู้รับผิดชอบรถประจำ')
    expect(await screen.findByTestId('e2-history')).toHaveTextContent('req-original')
    expect(screen.queryByTestId('e2-actions')).not.toBeInTheDocument()
    expect(screen.queryByTestId('e2-row-actions-ODA-1')).not.toBeInTheDocument()
    const urls = fn.mock.calls.map(([u]) => String(u))
    // Never the R2f-f permanent panel's route nor the legacy Phase 6 `/vehicles/{id}/driver-assignments`.
    expect(urls.some((u) => u.includes('responsible-driver') || /\/vehicles\/[^/]+\/driver-assignments/.test(u))).toBe(false)
    // The default window: Bangkok today -7 .. +30.
    expect(urls.find((u) => u.includes('operational-driver-assignments?'))).toContain(`from=`)
    expect(posts(fn)).toHaveLength(0)
  })

  it('the date / mode filter re-reads with the chosen window; a reversed range is refused locally', async () => {
    const fn = stub({ caps: ['can_view'] })
    const user = userEvent.setup()
    renderPanel()
    await screen.findByTestId('e2-current-status')
    const from = screen.getByLabelText('ตั้งแต่วันที่')
    const to = screen.getByLabelText('ถึงวันที่')
    await user.clear(from)
    await user.type(from, '2026-10-20')
    await user.clear(to)
    await user.type(to, '2026-10-19')
    await user.click(screen.getByRole('button', { name: 'แสดงตามช่วงที่เลือก' }))
    expect(screen.getByRole('alert')).toHaveTextContent('ต้องไม่อยู่ก่อน')
    const before = reads(fn, 'operational-driver-assignments?').length
    await user.clear(to)
    await user.type(to, '2026-10-25')
    await user.selectOptions(screen.getByLabelText('รูปแบบ'), 'NIGHT_SHIFT')
    await user.click(screen.getByRole('button', { name: 'แสดงตามช่วงที่เลือก' }))
    await waitFor(() => expect(reads(fn, 'operational-driver-assignments?').length).toBe(before + 1))
    expect(String(reads(fn, 'operational-driver-assignments?').at(-1)?.[0]))
      .toBe(`/api/v1/vehicles/${VEH}/operational-driver-assignments?from=2026-10-20&to=2026-10-25&mode=NIGHT_SHIFT`)
  })

  it('CREATE: explicit driver and mode, exact body, UUID request id, warnings shown, authoritative re-read', async () => {
    const fn = stub({
      schedules: [EMPTY_SCHEDULE, SCHEDULE], histories: [EMPTY_HISTORY, HISTORY],
      post: (_b, rid) => json({ request_id: rid, changed: true, operation_id: 'ODO-1', record_ids: ['ODA-1'], event_ids: ['ODA-1'],
        warnings: [NO_PERMANENT] }, 200, rid),
    })
    const user = userEvent.setup()
    renderPanel()
    await user.click(await screen.findByRole('button', { name: 'มอบหมายใหม่' }))
    const dialog = screen.getByTestId('e2-operation-dialog')
    await waitFor(() => expect(within(dialog).getByLabelText('ผู้ขับที่ได้รับมอบหมาย').tagName).toBe('SELECT'))
    const today = bangkokToday()
    await user.selectOptions(within(dialog).getByLabelText('ผู้ขับที่ได้รับมอบหมาย'), 'DRV-TEST-901')
    await user.selectOptions(within(dialog).getByLabelText('รูปแบบการมอบหมาย'), 'FULL_DAY')
    await user.type(within(dialog).getByLabelText('วันที่เริ่มต้น'), today)
    await user.type(within(dialog).getByLabelText('วันที่สิ้นสุด (รวมวันนี้)'), today)
    await user.click(within(dialog).getByRole('button', { name: /^ยืนยัน/ }))
    expect(await screen.findByText('บันทึกเรียบร้อยแล้ว')).toBeInTheDocument()
    expect(screen.getByTestId('e2-write-warnings')).toHaveTextContent('แจ้งเตือนเท่านั้น')
    const [url, init] = posts(fn)[0]
    expect(String(url)).toBe(`/api/v1/vehicles/${VEH}/operational-driver-assignment-operations`)
    expect(JSON.parse(String(init?.body))).toEqual({ operation: 'CREATE', driver_id: 'DRV-TEST-901', mode: 'FULL_DAY', start_date: today, end_date: today })
    expect(ridOf(posts(fn)[0])).toMatch(UUID_V4)
    await waitFor(() => expect(reads(fn, 'operational-driver-assignment-history').length).toBe(2))
    expect(screen.queryByTestId('e2-pending-intent')).not.toBeInTheDocument()
  })

  it('a row operation sends the event and its revision; a stale refusal closes the dialog and re-reads', async () => {
    const fn = stub({ post: (_b, rid) => json({ error: { code: 'E2_ASSIGNMENT_STALE', message: 'x', details: { event_id: 'ODA-1', field: 'revision_no' }, request_id: rid } }, 409, rid) })
    renderPanel()
    await cancelFirst()
    expect(JSON.parse(String(posts(fn)[0][1]?.body))).toEqual({ operation: 'CANCEL', event_id: 'ODA-1', expected_revision_no: '1', reason_th: 'ไม่ใช้รถ' })
    expect(await screen.findByTestId('e2-write-message')).toHaveTextContent('การมอบหมายเปลี่ยนไปหลังจากที่โหลดข้อมูล')
    expect(screen.queryByTestId('e2-operation-dialog')).not.toBeInTheDocument()
    await waitFor(() => expect(reads(fn, 'operational-driver-assignment-history').length).toBe(2))
    expect(screen.queryByTestId('e2-pending-intent')).not.toBeInTheDocument()
  })

  it('a conflict refusal stays in the dialog with the vehicle-axis details; a REAL-write refusal explains R11', async () => {
    let call = 0
    stub({
      post: (_b, rid) => (call++ === 0
        ? json({ error: { code: 'E2_ASSIGNMENT_ALREADY_STARTED', message: 'x', details: { event_id: 'ODA-1' }, request_id: rid } }, 409, rid)
        : json({ error: { code: 'E2_REAL_WRITES_NOT_ENABLED', message: 'x', details: null, request_id: rid } }, 409, rid)),
    })
    renderPanel()
    const user = await cancelFirst()
    const dialog = screen.getByTestId('e2-operation-dialog')
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('การมอบหมายนี้เริ่มแล้ว')
    await user.click(within(dialog).getByRole('button', { name: /^ยืนยัน/ }))
    await waitFor(() => expect(within(dialog).getByRole('alert')).toHaveTextContent('R11'))
    expect(screen.queryByTestId('e2-pending-intent')).not.toBeInTheDocument()
  })

  it('an overlap refusal shows both intervals', async () => {
    stub({
      post: (_b, rid) => json({ error: { code: 'E2_DRIVER_CONFLICT', message: 'x', request_id: rid, details: {
        axis: 'DRIVER', conflicting_event_id: 'ODA-OTHER',
        first: { event_id: 'ODA-1', vehicle_id: VEH, assigned_driver_id: 'DRV-TEST-901', label_date: '2026-10-21', start: '2026-10-20T17:00:00+00:00', end: '2026-10-21T17:00:00+00:00' },
        second: { event_id: 'ODA-OTHER', vehicle_id: 'VEH-TEST-901', assigned_driver_id: 'DRV-TEST-901', label_date: '2026-10-21', start: '2026-10-21T01:00:00+00:00', end: '2026-10-21T10:00:00+00:00' },
      } } }, 409, rid),
    })
    renderPanel()
    await cancelFirst()
    const overlap = await screen.findByTestId('e2-overlap')
    expect(overlap).toHaveTextContent('ผู้ขับ')
    expect(overlap).toHaveTextContent('ODA-OTHER')
    expect(overlap).toHaveTextContent('08:00 – 17:00')
  })

  it('an unknown outcome keeps the intent: no automatic retry, actions hidden, same-id resend, settled only by the history request_id', async () => {
    let firstRid = ''
    let firstBody = ''
    const fn = stub({
      histories: [HISTORY, HISTORY, { ...HISTORY, records: [record(), record({ record_id: 'ODA-C', record_kind: 'CANCELLATION',
        entry_operation: 'CANCEL', revision_no: '2', assigned_driver_id: null, mode: null, start_date: null, end_date: null,
        request_id: '__RID__' })] }],
      post: (b, rid, call) => {
        if (call === 0) {
          firstRid = rid
          firstBody = JSON.stringify(b)
          return Promise.reject(new TypeError('Failed to fetch'))
        }
        return json({ request_id: rid, replayed: true, operation_id: 'ODO-9', record_ids: ['ODA-C'], event_ids: ['ODA-1'] }, 200, rid)
      },
    })
    // The settling history carries the ORIGINAL request id.
    fn.mockImplementation(((orig) => async (input: RequestInfo | URL, init?: RequestInit) => {
      const response = await orig(input, init)
      if (String(input).endsWith('operational-driver-assignment-history')) {
        const text = (await response.text()).replace('__RID__', firstRid)
        return new Response(text, { status: response.status, headers: response.headers })
      }
      return response
    })(fn.getMockImplementation()!))
    renderPanel()
    const user = await cancelFirst()
    const pending = await screen.findByTestId('e2-pending-intent')
    expect(pending).toHaveTextContent(firstRid)
    expect(posts(fn)).toHaveLength(1)
    expect(screen.queryByTestId('e2-actions')).not.toBeInTheDocument()
    expect(screen.queryByTestId('e2-row-actions-ODA-1')).not.toBeInTheDocument()
    // An unknown outcome triggers no re-read by itself; a history read WITHOUT the request id does not settle it.
    expect(reads(fn, 'operational-driver-assignment-history')).toHaveLength(1)
    await user.click(within(pending).getByRole('button', { name: 'โหลดประวัติล่าสุดเพื่อตรวจสอบ' }))
    await waitFor(() => expect(reads(fn, 'operational-driver-assignment-history').length).toBe(2))
    expect(screen.getByTestId('e2-pending-intent')).toBeInTheDocument()
    await user.click(within(screen.getByTestId('e2-pending-intent')).getByRole('button', { name: 'ส่งคำขอเดิมอีกครั้ง' }))
    await waitFor(() => expect(posts(fn)).toHaveLength(2))
    expect(ridOf(posts(fn)[1])).toBe(firstRid)
    expect(posts(fn)[1][1]?.body).toBe(firstBody)
    expect(await screen.findByText('ตรวจสอบกับประวัติการมอบหมายแล้ว: คำขอเดิมถูกบันทึกแล้ว')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByTestId('e2-pending-intent')).not.toBeInTheDocument())
    expect(posts(fn)).toHaveLength(2)
  })

  it('a refused resend keeps the intent pending and explains that it proves nothing', async () => {
    const fn = stub({
      post: (_b, rid, call) => (call === 0
        ? json({}, 504)
        : json({ error: { code: 'E2_ASSIGNMENT_ALREADY_STARTED', message: 'x', details: null, request_id: rid } }, 409, rid)),
    })
    renderPanel()
    const user = await cancelFirst()
    const pending = await screen.findByTestId('e2-pending-intent')
    const rid = ridOf(posts(fn)[0])
    await user.click(within(pending).getByRole('button', { name: 'ส่งคำขอเดิมอีกครั้ง' }))
    expect(await screen.findByTestId('e2-write-message')).toHaveTextContent('ไม่ได้ยืนยันว่าคำขอครั้งก่อนไม่ได้ถูกบันทึก')
    expect(screen.getByTestId('e2-pending-intent')).toHaveTextContent(rid)
    expect(ridOf(posts(fn)[1])).toBe(rid)
  })

  it('REQUEST_ID_REUSED keeps a CONFLICT that cannot be resent and escalates to an administrator', async () => {
    stub({ post: (_b, rid) => json({ error: { code: 'REQUEST_ID_REUSED', message: 'x', details: { request_id: rid }, request_id: rid } }, 409, rid) })
    renderPanel()
    await cancelFirst()
    const pending = await screen.findByTestId('e2-pending-intent')
    expect(pending).toHaveTextContent('รหัสคำขอขัดแย้ง')
    expect(within(pending).getByTestId('e2-conflict-escalation')).toHaveTextContent('กรุณาแจ้งผู้ดูแลระบบ')
    expect(within(pending).queryByRole('button', { name: 'ส่งคำขอเดิมอีกครั้ง' })).not.toBeInTheDocument()
  })

  it('Google Sheets mode (501): an informational unavailable state, no controls, no write workaround', async () => {
    const fn = stub({ read: () => json({ error: { code: 'FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE', message: 'x', details: null, request_id: 'r' } }, 501) })
    renderPanel()
    expect(await screen.findByTestId('e2-unavailable')).toHaveTextContent('R11')
    expect(screen.getByTestId('e2-unavailable')).toHaveAttribute('role', 'status')
    expect(screen.queryByRole('button', { name: 'มอบหมายใหม่' })).not.toBeInTheDocument()
    expect(posts(fn)).toHaveLength(0)
  })

  it('a vehicle outside the server data scope shows the scope state and no controls', async () => {
    stub({ read: () => json({ error: { code: 'VEHICLE_SCOPE_UNPROVEN', message: 'x', details: null, request_id: 'r' } }, 422) })
    renderPanel()
    expect(await screen.findByTestId('e2-scope-unproven')).toHaveTextContent('ไม่อยู่ในขอบเขตข้อมูลปัจจุบัน')
    expect(screen.getByTestId('e2-scope-unproven')).toHaveAttribute('role', 'status')
    expect(screen.queryByTestId('r2-scope-unproven')).not.toBeInTheDocument() // the page's other panels keep their own test id
    expect(screen.queryByTestId('e2-actions')).not.toBeInTheDocument()
  })

  it('a CONFLICTED timeline is never resolved by a guess: conflicts, UNKNOWN spans and the status are shown', async () => {
    const second = { ...interval, event_id: 'ODA-2', assigned_driver_id: 'DRV-TEST-902' }
    stub({ caps: ['can_view'], schedules: [{ ...SCHEDULE, timeline_status: 'CONFLICTED', current_status: 'CONFLICTED',
      conflicts: [{ axis: 'VEHICLE', key: VEH, first: interval, second }],
      unknown: [{ vehicle_id: VEH, start: '2026-10-22T13:00:00+00:00', end: '2026-10-22T15:00:00+00:00', handover_event_id: 'ODA-H' }] }] })
    renderPanel()
    expect(await screen.findByTestId('e2-current-status')).toHaveTextContent('ข้อมูลการมอบหมายขัดแย้งกัน')
    expect(screen.getByTestId('e2-timeline-conflicted')).toHaveTextContent('ระบบไม่เดาผู้ขับให้')
    expect(screen.getByTestId('e2-conflicts')).toHaveTextContent('ODA-2')
    expect(screen.getByTestId('e2-unknown')).toHaveTextContent('สถานะการมอบหมายไม่แน่ชัด')
    expect(screen.getByTestId('e2-unknown')).toHaveTextContent('ODA-H')
  })

  it('the current assignment names the assigned driver with a link (never an actual driver)', async () => {
    stub({ caps: ['can_view'], schedules: [{ ...SCHEDULE, current_status: 'ASSIGNED', current: interval }] })
    renderPanel()
    const current = await screen.findByTestId('e2-current-status')
    expect(within(current).getByRole('link', { name: 'DRV-TEST-901' })).toHaveAttribute('href', '/drivers/DRV-TEST-901')
    await waitFor(() => expect(current).toHaveTextContent('ผู้ขับทดสอบ หนึ่ง'))
  })
})

// ---------------------------------------------------------------------------
// R2 Batch R2-C4 — REV5 acceptance corrections (B02, B06, B25, B26, B29)
// ---------------------------------------------------------------------------

describe('E2VehicleAssignmentsPanel — R2-C4 acceptance', () => {
  beforeEach(() => window.localStorage.clear())
  afterEach(() => vi.unstubAllGlobals())

  const DAY = '2026-10-21'
  const dayQuery = (mode: string) => `from=${DAY}&to=${DAY}&mode=${mode}`
  /** Answers a read whose query matches `query` with `answer`, everything else with the defaults. */
  const onQuery = (query: string, answer: () => Response | Promise<Response>) =>
    (url: string) => (url.includes('operational-driver-assignments?') && url.includes(query) ? (answer() as Response) : null)

  async function showRange(from: string, to: string, mode: string) {
    const user = userEvent.setup()
    await screen.findByTestId('e2-current-status')
    await user.clear(screen.getByLabelText('ตั้งแต่วันที่'))
    await user.type(screen.getByLabelText('ตั้งแต่วันที่'), from)
    await user.clear(screen.getByLabelText('ถึงวันที่'))
    await user.type(screen.getByLabelText('ถึงวันที่'), to)
    await user.selectOptions(screen.getByLabelText('รูปแบบ'), mode)
    await user.click(screen.getByRole('button', { name: 'แสดงตามช่วงที่เลือก' }))
  }

  it('B02 (A6.3): the no-permanent-driver warning carries the exact REV5 wording and stays non-blocking', async () => {
    stub({})
    renderPanel()
    const warnings = await screen.findByTestId('e2-warnings')
    expect(warnings).toHaveTextContent('ยังไม่ได้กำหนดผู้รับผิดชอบประจำรถ')
    expect(warnings).toHaveTextContent('แจ้งเตือนเท่านั้น ไม่ห้ามบันทึก')
    expect(screen.getByRole('button', { name: 'มอบหมายใหม่' })).toBeEnabled() // the warning never blocks a write
  })

  it('B29: the shared E2 note states that only the ASSIGNED driver is shown and no actual-driver evidence exists', async () => {
    stub({ caps: ['can_view'] })
    renderPanel()
    const note = screen.getByTestId('e2-note')
    expect(note).toHaveTextContent('ระบบ E2 แสดงผู้ขับที่ได้รับมอบหมายเท่านั้น ไม่มีข้อมูลยืนยันผู้ขับจริง')
    expect(note).toHaveTextContent('เป็นข้อมูลการมอบหมาย ไม่ใช่การยืนยันว่าได้ขับรถจริง')
  })

  it('B25 / B26: both inactive-driver warnings render, and the assignment and its history are kept unchanged', async () => {
    const warnings = [
      { code: 'DRIVER_NOT_ACTIVE', event_id: 'ODA-1', driver_id: 'DRV-TEST-901', vehicle_id: VEH, related_event_id: null },
      { code: 'FUTURE_ASSIGNMENT_DRIVER_NOT_ACTIVE_PENDING_REVIEW', event_id: 'ODA-1', driver_id: 'DRV-TEST-901', vehicle_id: VEH,
        related_event_id: null },
    ]
    stub({ caps: ['can_view'], schedules: [{ ...SCHEDULE, warnings }] })
    renderPanel()
    const shown = await screen.findByTestId('e2-warnings')
    expect(shown).toHaveTextContent('ผู้ขับของการมอบหมายนี้ไม่อยู่ในสถานะใช้งาน (ACTIVE) แล้ว') // B26
    expect(shown).toHaveTextContent('การมอบหมายล่วงหน้านี้มีผู้ขับที่ไม่อยู่ในสถานะใช้งาน ต้องตรวจสอบ') // B25
    expect(shown).toHaveTextContent('ODA-1')
    // Retained, not silently cancelled: the unit, the ACTIVE assignment and its history row are still shown.
    expect(screen.getByTestId('e2-intervals')).toHaveTextContent('DRV-TEST-901')
    expect(await screen.findByTestId('e2-assignments')).toHaveTextContent('มีผล')
    expect(screen.getByTestId('e2-history')).toHaveTextContent('req-original')
  })

  it('B06 (A3.5): one date + one shift with no unit of that shift shows "ยังไม่ได้ระบุผู้ได้รับมอบหมาย"', async () => {
    // A NIGHT unit labelled the previous date that runs into this date does not count for this date's night shift.
    const prevNight = { ...interval, event_id: 'ODA-N', mode: 'NIGHT_SHIFT', label_date: '2026-10-20',
      effective_start: '2026-10-20T13:00:00+00:00', effective_end: '2026-10-20T23:00:00+00:00' }
    stub({ caps: ['can_view'], read: onQuery(dayQuery('NIGHT_SHIFT'), () => json({ ...EMPTY_SCHEDULE, intervals: [prevNight] })) })
    renderPanel()
    await showRange(DAY, DAY, 'NIGHT_SHIFT')
    const label = await screen.findByTestId('e2-unassigned-shift')
    expect(label).toHaveTextContent('ยังไม่ได้ระบุผู้ได้รับมอบหมาย')
    expect(label).toHaveTextContent('กะกลางคืน')
    // Never filled from permanent responsibility: no driver is named for the empty shift.
    expect(label).not.toHaveTextContent('DRV-')
    // The schedule, warnings and history stay as they were.
    expect(screen.getByTestId('e2-intervals')).toHaveTextContent('ODA-N')
    expect(screen.getByTestId('e2-history')).toBeInTheDocument()
  })

  it('B06: a day shift with an assignment on that date shows no "unassigned" label', async () => {
    const dayUnit = { ...interval, mode: 'DAY_SHIFT', label_date: DAY, effective_start: '2026-10-21T01:00:00+00:00',
      effective_end: '2026-10-21T10:00:00+00:00' }
    stub({ caps: ['can_view'], read: onQuery(dayQuery('DAY_SHIFT'), () => json({ ...EMPTY_SCHEDULE, intervals: [dayUnit] })) })
    renderPanel()
    await showRange(DAY, DAY, 'DAY_SHIFT')
    await waitFor(() => expect(screen.getByTestId('e2-intervals')).toHaveTextContent('กะกลางวัน'))
    expect(screen.queryByTestId('e2-unassigned-shift')).not.toBeInTheDocument()
  })

  it('B06 negatives: several dates, all modes or FULL_DAY never show the conclusion', async () => {
    const fn = stub({ caps: ['can_view'], schedules: [EMPTY_SCHEDULE] })
    renderPanel()
    await showRange(DAY, '2026-10-22', 'NIGHT_SHIFT') // several dates
    await waitFor(() => expect(String(reads(fn, 'operational-driver-assignments?').at(-1)?.[0])).toContain('to=2026-10-22'))
    expect(screen.queryByTestId('e2-unassigned-shift')).not.toBeInTheDocument()
    await showRange(DAY, DAY, '') // all modes
    await waitFor(() => expect(String(reads(fn, 'operational-driver-assignments?').at(-1)?.[0])).not.toContain('mode='))
    expect(screen.queryByTestId('e2-unassigned-shift')).not.toBeInTheDocument()
    await showRange(DAY, DAY, 'FULL_DAY') // not a shift
    await waitFor(() => expect(String(reads(fn, 'operational-driver-assignments?').at(-1)?.[0])).toContain('mode=FULL_DAY'))
    expect(screen.queryByTestId('e2-unassigned-shift')).not.toBeInTheDocument()
  })

  it('B06 negatives: UNKNOWN, CONFLICTED timeline or a conflict on that date never show the conclusion', async () => {
    const second = { ...interval, event_id: 'ODA-2', label_date: DAY }
    for (const answer of [
      { ...EMPTY_SCHEDULE, unknown: [{ vehicle_id: VEH, start: '2026-10-21T13:00:00+00:00', end: '2026-10-21T15:00:00+00:00', handover_event_id: 'ODA-H' }] },
      { ...EMPTY_SCHEDULE, timeline_status: 'CONFLICTED', current_status: 'CONFLICTED' },
      { ...EMPTY_SCHEDULE, conflicts: [{ axis: 'VEHICLE', key: VEH, first: { ...interval, label_date: DAY }, second }] },
    ]) {
      const fn = stub({ caps: ['can_view'], read: onQuery(dayQuery('NIGHT_SHIFT'), () => json(answer)) })
      const { unmount } = renderPanel()
      await showRange(DAY, DAY, 'NIGHT_SHIFT')
      await waitFor(() => expect(reads(fn, dayQuery('NIGHT_SHIFT')).length).toBe(1))
      await screen.findByTestId('e2-vehicle-schedule')
      expect(screen.queryByTestId('e2-unassigned-shift'), JSON.stringify(answer).slice(0, 60)).not.toBeInTheDocument()
      unmount()
      vi.unstubAllGlobals()
      window.localStorage.clear()
    }
  })

  it('B06 negatives: a read failure, an out-of-scope vehicle or a pending read never show the conclusion', async () => {
    let release: (r: Response) => void = () => {}
    for (const answer of [
      () => json({ error: { code: 'E2_HISTORY_READ_FAILED', message: 'x', details: null, request_id: 'r' } }, 503),
      () => json({ error: { code: 'VEHICLE_SCOPE_UNPROVEN', message: 'x', details: null, request_id: 'r' } }, 422),
      () => new Promise<Response>((resolve) => { release = resolve }),
    ]) {
      const fn = stub({ caps: ['can_view'], read: onQuery(dayQuery('DAY_SHIFT'), answer) })
      const { unmount } = renderPanel()
      await showRange(DAY, DAY, 'DAY_SHIFT')
      await waitFor(() => expect(reads(fn, dayQuery('DAY_SHIFT')).length).toBe(1))
      expect(screen.queryByTestId('e2-unassigned-shift')).not.toBeInTheDocument()
      unmount()
      vi.unstubAllGlobals()
    }
    release(json(EMPTY_SCHEDULE))
  })
})
