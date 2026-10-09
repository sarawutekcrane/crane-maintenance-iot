import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import { PersonnelDetailPage } from './PersonnelDetailPage'
import { PersonnelListPage } from './PersonnelListPage'

/** R2 Batch R2e — personnel list / detail / lifecycle UI (synthetic data only). */

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const SYN = ' (สังเคราะห์)'
const people = {
  items: [
    { personnel_id: 'PER-SYN-001', first_name: 'หนึ่ง' + SYN, last_name: 'ทดสอบ', active_status: 'ACTIVE' },
    { personnel_id: 'PER-SYN-002', first_name: 'สอง' + SYN, last_name: 'ทดสอบ', active_status: 'INACTIVE' },
    { personnel_id: 'PER-SYN-003', first_name: 'สาม' + SYN, last_name: null, active_status: null },
  ],
  page: 1,
  page_size: 50,
  total_items: 3,
}

function history(current: string | null, consistency = 'NO_HISTORY', events: unknown[] = []) {
  return { entity_id: 'PER-SYN-001', current_state: current, latest_history_state: null,
    lifecycle_consistency: consistency, events }
}

interface Responder {
  me?: string[]
  record?: unknown
  history?: unknown
  historyStatus?: number
  post?: (call: number) => Response
}

function stubFetch(r: Responder) {
  let posts = 0
  const fn = vi.fn(async (input: string, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/me')) return jsonResponse({ user_id: 'dev-user', roles: [], capabilities: r.me ?? ['can_view'] })
    if (init?.method === 'POST') return r.post ? r.post(posts++) : jsonResponse({ changed: true })
    if (url.includes('/lifecycle-history')) return jsonResponse(r.history ?? history('ACTIVE'), r.historyStatus ?? 200)
    if (url.includes('/personnel/')) return jsonResponse(r.record ?? people.items[0])
    return jsonResponse(people)
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

function posts(fn: ReturnType<typeof stubFetch>) {
  return fn.mock.calls.filter(([, init]) => init?.method === 'POST')
}

function LocationProbe() {
  const location = useLocation()
  return <p data-testid="location">{location.pathname + location.search}</p>
}

function renderAt(path: string) {
  return render(
    <CapabilitiesProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/personnel" element={<><PersonnelListPage /><LocationProbe /></>} />
          <Route path="/personnel/:personnelId" element={<PersonnelDetailPage />} />
        </Routes>
      </MemoryRouter>
    </CapabilitiesProvider>,
  )
}

describe('PersonnelListPage (R2E-51/53/54/59/60/61)', () => {
  beforeEach(() => window.localStorage.clear())
  afterEach(() => vi.unstubAllGlobals())

  it('lists ids distinctly, keeps inactive rows and shows unknown status safely', async () => {
    stubFetch({})
    renderAt('/personnel')
    expect(await screen.findByText('PER-SYN-001')).toBeInTheDocument()
    expect(screen.getByText('PER-SYN-001').tagName).toBe('CODE')
    expect(screen.getByText('ปิดใช้งาน')).toBeInTheDocument() // inactive stays visible
    expect(screen.getByText('ไม่ทราบสถานะ')).toBeInTheDocument() // null is never shown as active
    expect(screen.getAllByText('ใช้งาน')).toHaveLength(1)
    // responsive table: every cell carries its column label for the stacked layout
    const cell = screen.getByText('PER-SYN-003').closest('td')
    expect(cell).toHaveAttribute('data-label', 'รหัสบุคลากร')
  })

  it('restores search text and page from the URL and links back to it', async () => {
    const fn = stubFetch({})
    renderAt('/personnel?q=%E0%B8%AA%E0%B8%AD%E0%B8%87&page=2')
    await screen.findByText('PER-SYN-002')
    expect(fn.mock.calls.some(([url]) => String(url).includes('/personnel?page=2&page_size=50'))).toBe(true)
    expect(screen.queryByText('PER-SYN-001')).toBeNull() // filtered by the URL search text
    expect(screen.getByLabelText('ค้นหาในหน้านี้ (รหัส/ชื่อ)')).toHaveValue('สอง')
    const user = userEvent.setup()
    await user.click(screen.getByText('PER-SYN-002'))
    const back = await screen.findByRole('link', { name: /กลับไปหน้ารายชื่อบุคลากร/ })
    expect(back).toHaveAttribute('href', '/personnel?q=%E0%B8%AA%E0%B8%AD%E0%B8%87&page=2')
  })

  it('shows a read failure as an error, never as an empty list', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: string) =>
      String(input).endsWith('/me')
        ? jsonResponse({ user_id: 'u', roles: [], capabilities: ['can_view'] })
        : jsonResponse({ error: { code: 'PERSONNEL_MASTER_READ_FAILED', message: 'x' } }, 503)))
    renderAt('/personnel')
    expect(await screen.findByText('อ่านข้อมูลบุคลากรไม่สำเร็จ กรุณาลองใหม่อีกครั้ง')).toBeInTheDocument()
    expect(screen.queryByText('ไม่พบบุคลากร')).toBeNull()
  })
})

describe('PersonnelDetailPage lifecycle (R2E-55..R2E-59, R2E-62)', () => {
  beforeEach(() => window.localStorage.clear())
  afterEach(() => vi.unstubAllGlobals())

  it('requires a reason, shows identity and states, and sends the expected state with a request id', async () => {
    const fn = stubFetch({ me: ['can_view', 'can_manage_personnel'] })
    renderAt('/personnel/PER-SYN-001')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'ปิดใช้งาน' }))
    const dialog = screen.getByRole('alertdialog')
    expect(within(dialog).getByText('PER-SYN-001')).toBeInTheDocument()
    expect(within(dialog).getByText('ใช้งาน')).toBeInTheDocument()
    expect(within(dialog).getByText('ปิดใช้งาน')).toBeInTheDocument()
    expect(within(dialog).getByText(/ไม่ปิดการเข้าสู่ระบบ/)).toBeInTheDocument() // not a login action
    expect(within(dialog).getByText(/ไม่มีการลบข้อมูล/)).toBeInTheDocument()
    const confirm = within(dialog).getByRole('button', { name: 'ยืนยันปิดใช้งาน' })
    expect(confirm).toBeDisabled()
    await user.type(within(dialog).getByLabelText('เหตุผล (จำเป็น)'), '   ')
    expect(confirm).toBeDisabled() // whitespace is not a reason
    await user.type(within(dialog).getByLabelText('เหตุผล (จำเป็น)'), 'ลาออก (ทดสอบ)')
    await user.click(confirm)
    await waitFor(() => expect(posts(fn)).toHaveLength(1))
    const [url, init] = posts(fn)[0]
    expect(String(url)).toBe('/api/v1/personnel/PER-SYN-001/deactivations')
    expect(new Headers(init?.headers).get('X-Request-Id')).toMatch(/^[0-9a-f-]{36}$/)
    expect(JSON.parse(String(init?.body))).toEqual({ expected_active_status: 'ACTIVE', reason_th: '   ลาออก (ทดสอบ)' })
    expect(await screen.findByText('บันทึกเรียบร้อยแล้ว')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /บัญชี|เข้าสู่ระบบ/ })).toBeNull()
  })

  it('shows a stale conflict with a reload action and never retries', async () => {
    const fn = stubFetch({
      me: ['can_view', 'can_manage_personnel'],
      post: () => jsonResponse({ error: { code: 'PERSONNEL_LIFECYCLE_STALE', details: { field: 'active_status' } } }, 409),
    })
    renderAt('/personnel/PER-SYN-001')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'ปิดใช้งาน' }))
    await user.type(screen.getByLabelText('เหตุผล (จำเป็น)'), 'เหตุผล')
    await user.click(screen.getByRole('button', { name: 'ยืนยันปิดใช้งาน' }))
    expect(await screen.findByText('ข้อมูลถูกเปลี่ยนโดยผู้ใช้อื่น กรุณาโหลดข้อมูลล่าสุดก่อนดำเนินการอีกครั้ง')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'โหลดข้อมูลล่าสุด' })).toBeInTheDocument()
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(posts(fn)).toHaveLength(1)
  })

  it('on MISMATCH offers only an explicit reconciliation', async () => {
    const fn = stubFetch({ me: ['can_view', 'can_manage_personnel'], history: history('ACTIVE', 'MISMATCH', [{
      lifecycle_event_id: 'PLH-1', event_kind: 'DEACTIVATE', previous_state: 'ACTIVE', new_state: 'INACTIVE',
      recorded_at: '2026-10-01T00:00:00+00:00', recorded_by: 'dev-user', reason_th: 'ทดสอบ' }]) })
    renderAt('/personnel/PER-SYN-001')
    expect(await screen.findByText(/ไม่ตรงกับประวัติสถานะล่าสุด/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'ปิดใช้งาน' })).toBeNull()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'ซิงก์สถานะให้ตรงกับประวัติล่าสุด' }))
    await user.type(screen.getByLabelText('เหตุผล (จำเป็น)'), 'ซิงก์')
    await user.click(screen.getByRole('button', { name: 'ยืนยันซิงก์สถานะให้ตรงกับประวัติล่าสุด' }))
    await waitFor(() => expect(posts(fn)).toHaveLength(1))
    expect(String(posts(fn)[0][0])).toBe('/api/v1/personnel/PER-SYN-001/lifecycle-reconciliations')
  })

  it('an unknown outcome is kept and can only be resent with the same request id', async () => {
    const fn = stubFetch({ me: ['can_view', 'can_manage_personnel'], post: (n) =>
      n === 0 ? new Response('', { status: 502 }) : jsonResponse({ replayed: true, record_ids: ['PLH-1'] }) })
    renderAt('/personnel/PER-SYN-001')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'ปิดใช้งาน' }))
    await user.type(screen.getByLabelText('เหตุผล (จำเป็น)'), 'เหตุผล')
    await user.click(screen.getByRole('button', { name: 'ยืนยันปิดใช้งาน' }))
    expect(await screen.findByText(/ไม่ทราบผลการบันทึก/)).toBeInTheDocument()
    expect(screen.queryByText('บันทึกเรียบร้อยแล้ว')).toBeNull()
    await user.click(screen.getByRole('button', { name: 'ส่งคำขอเดิมอีกครั้ง' }))
    await waitFor(() => expect(posts(fn)).toHaveLength(2))
    const ids = posts(fn).map(([, init]) => new Headers(init?.headers).get('X-Request-Id'))
    expect(ids[1]).toBe(ids[0])
  })

  it('unknown -> same-id resend -> MISMATCH: no success, pending cleared, reload, explicit reconciliation (review fix R2)', async () => {
    const event = { lifecycle_event_id: 'PLH-1', event_kind: 'DEACTIVATE', previous_state: 'ACTIVE',
      new_state: 'INACTIVE', recorded_at: '2026-10-01T00:00:00+00:00', recorded_by: 'dev-user', reason_th: 'ทดสอบ' }
    let posted = 0
    const historyGets: number[] = []
    const fn = vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/me')) return jsonResponse({ user_id: 'dev-user', roles: [], capabilities: ['can_view', 'can_manage_personnel'] })
      if (init?.method === 'POST') {
        posted += 1
        return posted === 1
          ? new Response('', { status: 502 }) // unknown: the W1 may have been applied
          : jsonResponse({ error: { code: 'PERSONNEL_LIFECYCLE_MISMATCH', message: 'x' } }, 409)
      }
      if (url.includes('/lifecycle-history')) {
        historyGets.push(posted)
        // after the (unknown, applied) first attempt the history holds the event; the record does not
        return jsonResponse(posted === 0 ? history('ACTIVE') : history('ACTIVE', 'MISMATCH', [event]))
      }
      if (url.includes('/personnel/')) return jsonResponse(people.items[0])
      return jsonResponse(people)
    })
    vi.stubGlobal('fetch', fn)
    renderAt('/personnel/PER-SYN-001')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'ปิดใช้งาน' }))
    await user.type(screen.getByLabelText('เหตุผล (จำเป็น)'), 'เหตุผล')
    await user.click(screen.getByRole('button', { name: 'ยืนยันปิดใช้งาน' }))
    expect(await screen.findByText(/ไม่ทราบผลการบันทึก/)).toBeInTheDocument()
    expect(window.localStorage.length).toBe(1) // the unknown intent is kept
    await user.click(screen.getByRole('button', { name: 'ส่งคำขอเดิมอีกครั้ง' }))
    expect(await screen.findByText(/พบว่าประวัติการเปลี่ยนสถานะถูกบันทึกแล้ว แต่สถานะข้อมูลหลักยังไม่ตรงกัน/)).toBeInTheDocument()
    const ids = posts(fn).map(([, i]) => new Headers(i?.headers).get('X-Request-Id'))
    expect(ids).toHaveLength(2)
    expect(ids[1]).toBe(ids[0]) // the SAME request id
    expect(screen.queryByText('บันทึกเรียบร้อยแล้ว')).toBeNull()
    expect(window.localStorage.length).toBe(0) // proven outcome: pending intent cleared
    expect(screen.queryByRole('button', { name: 'ส่งคำขอเดิมอีกครั้ง' })).toBeNull()
    expect(screen.queryByRole('alertdialog')).toBeNull()
    // lifecycle data reloaded: the refreshed MISMATCH history offers only the explicit reconciliation
    expect(await screen.findByRole('button', { name: 'ซิงก์สถานะให้ตรงกับประวัติล่าสุด' })).toBeInTheDocument()
    expect(historyGets.filter((n) => n === 2).length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: 'ปิดใช้งาน' })).toBeNull()
    expect(posts(fn)).toHaveLength(2) // nothing reconciles automatically
  })

  it('a consistent replay after an unknown outcome is still a completed replay', async () => {
    const fn = stubFetch({ me: ['can_view', 'can_manage_personnel'], post: (n) =>
      n === 0 ? new Response('', { status: 502 }) : jsonResponse({ request_id: 'x', replayed: true, record_ids: ['PLH-1'] }) })
    renderAt('/personnel/PER-SYN-001')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'ปิดใช้งาน' }))
    await user.type(screen.getByLabelText('เหตุผล (จำเป็น)'), 'เหตุผล')
    await user.click(screen.getByRole('button', { name: 'ยืนยันปิดใช้งาน' }))
    await user.click(await screen.findByRole('button', { name: 'ส่งคำขอเดิมอีกครั้ง' }))
    expect(await screen.findByText('บันทึกเรียบร้อยแล้ว')).toBeInTheDocument()
    expect(posts(fn)).toHaveLength(2)
    expect(window.localStorage.length).toBe(0)
  })

  it('a known state-write failure (recorded, state pending) is shown as such, not as success', async () => {
    stubFetch({ me: ['can_view', 'can_manage_personnel'], post: () => jsonResponse({ error: {
      code: 'PERSONNEL_LIFECYCLE_STATE_WRITE_FAILED', details: { event_recorded: true } } }, 503) })
    renderAt('/personnel/PER-SYN-001')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'ปิดใช้งาน' }))
    await user.type(screen.getByLabelText('เหตุผล (จำเป็น)'), 'เหตุผล')
    await user.click(screen.getByRole('button', { name: 'ยืนยันปิดใช้งาน' }))
    expect(await screen.findByText(/บันทึกประวัติแล้ว แต่ปรับสถานะของข้อมูลหลักไม่สำเร็จ/)).toBeInTheDocument()
    expect(screen.queryByText('บันทึกเรียบร้อยแล้ว')).toBeNull()
    expect(window.localStorage.length).toBe(0)
  })

  it('hides controls without the capability and still shows a backend 403', async () => {
    stubFetch({ me: ['can_view'] })
    renderAt('/personnel/PER-SYN-001')
    expect(await screen.findByText('สถานะปัจจุบัน:')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'ปิดใช้งาน' })).toBeNull()
    window.localStorage.clear()
    vi.unstubAllGlobals()
    stubFetch({ me: ['can_view', 'can_manage_personnel'], post: () =>
      jsonResponse({ error: { code: 'HTTP_ERROR', message: 'forbidden' } }, 403) })
    renderAt('/personnel/PER-SYN-001')
    const user = userEvent.setup()
    const [button] = await screen.findAllByRole('button', { name: 'ปิดใช้งาน' })
    await user.click(button)
    await user.type(screen.getByLabelText('เหตุผล (จำเป็น)'), 'เหตุผล')
    await user.click(screen.getByRole('button', { name: 'ยืนยันปิดใช้งาน' }))
    expect(await within(screen.getByRole('alertdialog')).findByRole('alert')).toBeInTheDocument()
  })

  it('an unknown current state disables lifecycle actions; a history read error is not "no history"', async () => {
    stubFetch({ me: ['can_view', 'can_manage_personnel'], history: history(null) })
    renderAt('/personnel/PER-SYN-001')
    expect(await screen.findByText(/ไม่ทราบสถานะของข้อมูลนี้/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'ปิดใช้งาน' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'เปิดใช้งานอีกครั้ง' })).toBeNull()
    vi.unstubAllGlobals()
    stubFetch({ me: ['can_view'], history: { error: { code: 'PERSONNEL_LIFECYCLE_HISTORY_SCHEMA_INVALID', message: 'x' } },
      historyStatus: 500 })
    renderAt('/personnel/PER-SYN-001')
    expect(await screen.findByText('ประวัติสถานะบุคลากรยังไม่พร้อมใช้งานในระบบ')).toBeInTheDocument()
  })
})
