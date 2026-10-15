import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import { PersonnelLinksPanel } from './PersonnelLinksPanel'

/** R2 Batch R2-C2a — Personnel relationships: three links, histories, redaction, LINK / UNLINK / RELINK / RECONCILE. */

const json = (body: unknown, status = 200, rid?: string) => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json', ...(rid ? { 'X-Request-Id': rid } : {}) },
})
const P = 'PER-TEST-912'
const TECHNICIAN = { technician_id: 'TEC-TEST-912', first_name: 'ช่างทดสอบ', last_name: 'ลำดับสอง', active_status: 'ACTIVE' }
const relationships = (account: Record<string, unknown> = { resolution: 'RESOLVED', user_id: 'USR-TEST-912' }, driver: Record<string, unknown> = { resolution: 'UNSET', driver_id: null }) => ({
  personnel_id: P, technician: { resolution: 'RESOLVED', technician_id: 'TEC-TEST-912', technician: TECHNICIAN }, account, driver,
})
const empty = (f: string, current: string | null, extra: Record<string, unknown> = {}) => ({
  personnel_id: P, [`current_${f}`]: current, [`latest_history_${f}`]: null, relationship_consistency: 'NO_HISTORY', events: [], ...extra,
})
const linkEvent = (f: string, rid: string, next: string | null) => ({ link_event_id: 'PDL-1', event_kind: 'LINK', [`previous_${f}`]: null,
  [`new_${f}`]: next, recorded_at: '2026-10-15T05:00:00+00:00', recorded_by: 'dev-user', reason_th: 'เชื่อมโยงทดสอบ', request_id: rid })
const DRIVERS = { items: [{ driver_id: 'DRV-TEST-901', driver_name_th: 'ผู้ขับทดสอบ หนึ่ง', phone: null, license_no: null,
  license_expiry_date: null, active_status: 'ACTIVE', note_th: null }], page: 1, page_size: 200, total_items: 1 }

interface Responder {
  caps: string[]
  rel?: unknown
  driverHistory?: unknown[]
  accountHistory?: unknown
  post?: (url: string, body: Record<string, unknown>, rid: string) => Response | Promise<Response>
}

function stub(r: Responder) {
  let driverReads = 0
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/me')) return json({ user_id: 'dev-user', roles: [], capabilities: r.caps, data_context: 'TEST' })
    if (init?.method === 'POST') {
      const rid = (init.headers as Record<string, string>)['X-Request-Id']
      return r.post ? r.post(url, JSON.parse(String(init.body)), rid) : json({}, 500)
    }
    if (url.endsWith(`/personnel/${P}/relationships`)) return json(r.rel ?? relationships())
    if (url.endsWith('/technician-links/history')) return json(empty('technician_id', 'TEC-TEST-912'))
    if (url.endsWith('/account-links/history')) return json(r.accountHistory ?? { ...empty('user_id', 'USR-TEST-912'), user_ids_visible: true })
    if (url.endsWith('/driver-links/history')) {
      const list = r.driverHistory ?? [empty('driver_id', null)]
      return json(list[Math.min(driverReads++, list.length - 1)])
    }
    if (url.includes('/drivers?')) return json(DRIVERS)
    if (url.includes('/technicians?')) return json({ items: [TECHNICIAN], page: 1, page_size: 200, total_items: 1 })
    throw new Error(`Unexpected fetch: ${url}`)
  })
  vi.stubGlobal('fetch', fn)
  return fn
}
const posts = (fn: ReturnType<typeof stub>) => fn.mock.calls.filter(([, init]) => init?.method === 'POST')

const renderPanel = () => render(
  <CapabilitiesProvider><MemoryRouter><PersonnelLinksPanel personnelId={P} /></MemoryRouter></CapabilitiesProvider>,
)

describe('PersonnelLinksPanel', () => {
  beforeEach(() => window.localStorage.clear())
  afterEach(() => vi.unstubAllGlobals())

  it('shows the three resolutions with the approved title and the TEST context', async () => {
    stub({ caps: ['can_view'] })
    renderPanel()
    expect(screen.getByRole('heading', { name: 'ความเชื่อมโยงข้อมูลบุคลากร' })).toBeInTheDocument()
    expect(await screen.findByTestId('link-technician-id')).toHaveTextContent('TEC-TEST-912 ช่างทดสอบ ลำดับสอง')
    expect(screen.getByTestId('link-account-id')).toHaveTextContent('USR-TEST-912')
    expect(screen.getByTestId('link-driver-resolution')).toHaveTextContent('ยังไม่ได้เชื่อมโยง')
    expect(screen.getByTestId('v2-data-context')).toHaveTextContent('TEST')
    // can_view only: no link controls at all.
    await waitFor(() => expect(screen.queryAllByText('ยังไม่มีประวัติความเชื่อมโยง')).toHaveLength(3))
    for (const kind of ['technician', 'account', 'driver']) expect(screen.queryByTestId(`link-${kind}-actions`)).not.toBeInTheDocument()
  })

  it('a redacted account id is shown as hidden in the current link and the history, never reconstructed', async () => {
    stub({
      caps: ['can_view'],
      rel: relationships({ resolution: 'RESOLVED' }),
      accountHistory: { ...empty('user_id', null), user_ids_visible: false,
        events: [{ ...linkEvent('user_id', 'rid-a', null), previous_user_id: null }] },
    })
    renderPanel()
    expect(await screen.findByTestId('link-account-id')).toHaveTextContent('ซ่อนไว้')
    expect(screen.getByTestId('link-account-resolution')).toHaveTextContent('เชื่อมโยงแล้ว')
    const section = screen.getByTestId('link-account')
    await waitFor(() => expect(within(section).getAllByText(/ซ่อนไว้/).length).toBeGreaterThan(1))
    expect(section).not.toHaveTextContent('USR-TEST')
  })

  it('each link kind follows its own capability (driver-link only)', async () => {
    stub({ caps: ['can_view', 'can_link_personnel_driver'] })
    renderPanel()
    expect(await screen.findByTestId('link-driver-actions')).toBeInTheDocument()
    expect(screen.queryByTestId('link-technician-actions')).not.toBeInTheDocument()
    expect(screen.queryByTestId('link-account-actions')).not.toBeInTheDocument()
  })

  it('LINK a driver: explicit choice, exact body and path, history re-read and settled', async () => {
    let sentRid = ''
    const fn = stub({
      caps: ['can_view', 'can_link_personnel_driver'],
      post: (_url, _body, rid) => {
        sentRid = rid
        return json({ request_id: rid, changed: true, link_event_id: 'PDL-1', previous_driver_id: null, new_driver_id: 'DRV-TEST-901',
          relationship_consistency_after: 'CONSISTENT' }, 200, rid)
      },
      driverHistory: [empty('driver_id', null), { ...empty('driver_id', 'DRV-TEST-901'), relationship_consistency: 'CONSISTENT',
        latest_history_driver_id: 'DRV-TEST-901', events: [linkEvent('driver_id', 'x', 'DRV-TEST-901')] }],
    })
    renderPanel()
    const user = userEvent.setup()
    await user.click(within(await screen.findByTestId('link-driver-actions')).getByRole('button', { name: 'เชื่อมโยง' }))
    const dialog = screen.getByTestId('link-dialog')
    await waitFor(() => expect(within(dialog).getByLabelText('รหัสคนขับ/ผู้ควบคุม').tagName).toBe('SELECT'))
    expect(within(dialog).getByLabelText('รหัสคนขับ/ผู้ควบคุม')).toHaveValue('')
    await user.selectOptions(within(dialog).getByLabelText('รหัสคนขับ/ผู้ควบคุม'), 'DRV-TEST-901')
    await user.type(within(dialog).getByLabelText('เหตุผล (บังคับ)'), 'มอบหมายคนขับ')
    await user.click(within(dialog).getByRole('button', { name: 'ยืนยันเชื่อมโยง' }))
    await waitFor(() => expect(posts(fn)).toHaveLength(1))
    expect(String(posts(fn)[0][0])).toBe(`/api/v1/personnel/${P}/driver-links`)
    expect(JSON.parse(String(posts(fn)[0][1]?.body))).toEqual({ operation: 'LINK', expected_driver_id: '', new_driver_id: 'DRV-TEST-901',
      reason_th: 'มอบหมายคนขับ' })
    expect(sentRid).toMatch(/^[0-9a-f-]{36}$/)
    expect(await within(screen.getByTestId('link-driver')).findByText('บันทึกเรียบร้อยแล้ว')).toBeInTheDocument()
    expect(await within(screen.getByTestId('link-driver')).findByText('เชื่อมโยงทดสอบ')).toBeInTheDocument()
  })

  it('UNLINK sends no new id; the account id is typed (no account list exists)', async () => {
    const fn = stub({
      caps: ['can_view', 'can_link_personnel_account'],
      post: (_u, _b, rid) => json({ request_id: rid, changed: false }, 200, rid),
    })
    renderPanel()
    const user = userEvent.setup()
    await user.click(within(await screen.findByTestId('link-account-actions')).getByRole('button', { name: 'ยกเลิกการเชื่อมโยง' }))
    const dialog = screen.getByTestId('link-dialog')
    expect(within(dialog).queryByLabelText(/รหัสบัญชีผู้ใช้/)).not.toBeInTheDocument()
    await user.type(within(dialog).getByLabelText('เหตุผล (บังคับ)'), 'ยกเลิกบัญชี')
    await user.click(within(dialog).getByRole('button', { name: 'ยืนยันยกเลิกการเชื่อมโยง' }))
    await waitFor(() => expect(posts(fn)).toHaveLength(1))
    expect(JSON.parse(String(posts(fn)[0][1]?.body))).toEqual({ operation: 'UNLINK', expected_user_id: 'USR-TEST-912', reason_th: 'ยกเลิกบัญชี' })
    await user.click(within(screen.getByTestId('link-account-actions')).getByRole('button', { name: 'เปลี่ยนการเชื่อมโยง' }))
    expect(within(screen.getByTestId('link-dialog')).getByLabelText('รหัสบัญชีผู้ใช้ (user_id)').tagName).toBe('INPUT')
    // No account-list request was ever made.
    expect(fn.mock.calls.some(([u]) => /user-accounts|\/users\?/.test(String(u)))).toBe(false)
  })

  it('a projection (W2) failure is "recorded, not consistent": it settles by request id and offers RECONCILE', async () => {
    let rid1 = ''
    const fn = stub({ caps: ['can_view', 'can_link_personnel_driver'] })
    // The history after the failure: the event is recorded, the cell is not.
    const mismatch = () => ({ ...empty('driver_id', null), latest_history_driver_id: 'DRV-TEST-901', relationship_consistency: 'MISMATCH',
      events: [linkEvent('driver_id', rid1, 'DRV-TEST-901')] })
    fn.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/me')) return json({ user_id: 'dev-user', roles: [], capabilities: ['can_view', 'can_link_personnel_driver'], data_context: 'TEST' })
      if (init?.method === 'POST') {
        const rid = (init.headers as Record<string, string>)['X-Request-Id']
        if (url.endsWith('/reconcile')) {
          return json({ request_id: rid, changed: true, link_event_id: 'PDL-2', previous_driver_id: null, new_driver_id: 'DRV-TEST-901',
            relationship_consistency_after: 'CONSISTENT' }, 200, rid)
        }
        rid1 = rid
        return json({ error: { code: 'PERSONNEL_DRIVER_LINK_PROJECTION_WRITE_FAILED', message: 'x',
          details: { event_recorded: true, record_id: 'PDL-1', request_id: rid, projection_write_outcome: 'rejected' }, request_id: rid } }, 503, rid)
      }
      if (url.endsWith(`/personnel/${P}/relationships`)) return json(relationships())
      if (url.endsWith('/driver-links/history')) return json(rid1 ? mismatch() : empty('driver_id', null))
      if (url.endsWith('/technician-links/history')) return json(empty('technician_id', 'TEC-TEST-912'))
      if (url.endsWith('/account-links/history')) return json({ ...empty('user_id', 'USR-TEST-912'), user_ids_visible: true })
      if (url.includes('/drivers?')) return json(DRIVERS)
      throw new Error(`Unexpected fetch: ${url}`)
    })
    renderPanel()
    const user = userEvent.setup()
    await user.click(within(await screen.findByTestId('link-driver-actions')).getByRole('button', { name: 'เชื่อมโยง' }))
    const dialog = screen.getByTestId('link-dialog')
    await waitFor(() => expect(within(dialog).getByLabelText('รหัสคนขับ/ผู้ควบคุม').tagName).toBe('SELECT'))
    await user.selectOptions(within(dialog).getByLabelText('รหัสคนขับ/ผู้ควบคุม'), 'DRV-TEST-901')
    await user.type(within(dialog).getByLabelText('เหตุผล (บังคับ)'), 'ทดสอบ')
    await user.click(within(dialog).getByRole('button', { name: 'ยืนยันเชื่อมโยง' }))
    const section = screen.getByTestId('link-driver')
    // Settled against the history (own request id) and reported as recorded-but-inconsistent.
    expect(await within(section).findByText(/คำขอเดิมถูกบันทึกแล้ว แต่ข้อมูลปัจจุบันยังไม่ตรงกับประวัติ/)).toBeInTheDocument()
    expect(within(section).queryByTestId('r2-pending-intent')).not.toBeInTheDocument()
    await user.click(within(section).getByRole('button', { name: 'ปรับข้อมูลให้ตรงกับประวัติ' }))
    const reconcile = screen.getByTestId('link-dialog')
    expect(within(reconcile).getByLabelText('รหัสคำขอที่เกี่ยวข้อง')).toHaveValue(rid1)
    await user.type(within(reconcile).getByLabelText('เหตุผล (บังคับ)'), 'ปรับข้อมูล')
    await user.click(within(reconcile).getByRole('button', { name: 'ยืนยันปรับข้อมูลให้ตรงกับประวัติ' }))
    await waitFor(() => expect(posts(fn)).toHaveLength(2))
    expect(String(posts(fn)[1][0])).toBe(`/api/v1/personnel/${P}/driver-links/reconcile`)
    expect(JSON.parse(String(posts(fn)[1][1]?.body))).toEqual({ expected_driver_id: '', related_request_id: rid1, reason_th: 'ปรับข้อมูล' })
  })

  it('a stale link is a confirmed refusal that asks for a reload', async () => {
    stub({ caps: ['can_view', 'can_link_personnel_technician'], post: (_u, _b, rid) => json({ error: {
      code: 'PERSONNEL_TECHNICIAN_LINK_STALE', message: 'x', details: { field: 'technician_id' }, request_id: rid } }, 409, rid) })
    renderPanel()
    const user = userEvent.setup()
    await user.click(within(await screen.findByTestId('link-technician-actions')).getByRole('button', { name: 'ยกเลิกการเชื่อมโยง' }))
    const dialog = screen.getByTestId('link-dialog')
    await user.type(within(dialog).getByLabelText('เหตุผล (บังคับ)'), 'x')
    await user.click(within(dialog).getByRole('button', { name: 'ยืนยันยกเลิกการเชื่อมโยง' }))
    const section = screen.getByTestId('link-technician')
    expect(await within(section).findByTestId('r2-write-message')).toHaveTextContent('เปลี่ยนไปหลังจากที่โหลดข้อมูล')
    expect(within(section).queryByTestId('r2-pending-intent')).not.toBeInTheDocument()
  })
})
