import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import { branchWriteText } from '../lib/labels'
import { registryPendingStore, storageKey } from '../lib/registryPending'
import { VehicleDetailPage } from './VehicleDetailPage'

// Phase 7 Batch 7O2c — the branch actions on Vehicle Detail: C-c3 (the
// read-only panel and the separate, initially closed "จัดการประวัติสาขา"
// area), capability gating, request bodies (Bangkok +07:00), NOT_DETERMINED
// never shown as success, W2 failure kept pending, reconciliation only on a
// mismatch, and family-scoped settlement. Synthetic data only.

const TS = '2026-01-15T08:00:00Z'
const E1 = 'ABH-' + '1'.repeat(32)
const E2 = 'ABH-' + '2'.repeat(32)
const ALL = ['can_view', 'can_transfer_vehicle_branch', 'can_correct_branch_history']

function json(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } })
}

function detail(id: string) {
  const field = (value: string | null) => (value === null ? { state: 'NOT_RECORDED', value: null } : { state: 'RECORDED', value })
  return {
    vehicle: {
      vehicle_id: id, machine_no: `M-${id}`, model_id: 'SYN-MODEL', serial_number: null, operational_status: 'WORKING',
      created_at: TS, updated_at: TS,
      registry: { registration_no: field(null), registration_province: field(null), responsible_branch: field('BR-SYN-A') },
    },
    model: null,
    components: [],
  }
}

function event(id: string, branch: string, at: string, from: string | null) {
  return {
    event_id: id, in_force: true, head_record_id: id, revision_no: 1, to_branch_id: branch, effective_at: at,
    effective_precision: 'DATETIME', derived_from_branch_id: from, original_entry_from_branch_id: from,
    original_entry_from_source: from ? 'EVENT' : 'BASELINE', head_entry_from_branch_id: from,
    head_entry_from_source: from ? 'EVENT' : 'BASELINE', derived_end_at: null, notes: [],
  }
}

function record(id: string, branch: string, at: string, rid: string) {
  return {
    record_id: id, record_kind: 'ASSIGNMENT', entry_operation: 'TRANSFER', event_id: id, revision_no: 1,
    supersedes_record_id: null, branch_id: branch, effective_at: at, recorded_from_branch_id: null,
    recorded_from_source: 'BASELINE', recorded_at: '2026-09-01T00:00:00+00:00', recorded_by: 'u', request_id: rid,
    related_request_id: null, reason_th: null, reconciled_old_master_branch_id: null,
  }
}

function branchHistory(id: string, opts: { consistency?: string; master?: string | null; extraRequestIds?: string[] } = {}) {
  const rids = opts.extraRequestIds ?? []
  return {
    asset_type: 'VEHICLE', asset_id: id, timeline_status: 'VALID', current: { branch_id: 'BR-SYN-A', source: 'EVENT' },
    master: opts.master === null ? { state: 'NOT_RECORDED', value: null } : { state: 'RECORDED', value: opts.master ?? 'BR-SYN-A' },
    consistency: opts.consistency ?? 'CONSISTENT', history_revision: 'BHR1-rev', baseline: { branch_id: 'BR-SYN-B', source: 'IMPORTED_MASTER' },
    events: [event(E1, 'BR-SYN-B', '2026-08-01T00:00:00+00:00', null), event(E2, 'BR-SYN-A', '2026-09-01T00:00:00+00:00', 'BR-SYN-B')],
    records: [
      record(E1, 'BR-SYN-B', '2026-08-01T00:00:00+00:00', 'seed-1'),
      record(E2, 'BR-SYN-A', '2026-09-01T00:00:00+00:00', 'seed-2'),
      ...rids.map((rid, n) => record(`ABH-x${n}`, 'BR-SYN-A', '2026-09-02T00:00:00+00:00', rid)),
    ],
    excluded_test_rows: 0, issues: {},
  }
}

const REGISTRATION_HISTORY = (id: string) => ({
  vehicle_id: id,
  current: { registration_no: { state: 'NOT_RECORDED', value: null }, registration_province: { state: 'NOT_RECORDED', value: null } },
  consistency: 'NO_HISTORY', history_revision: 'RHR1-0', excluded_test_rows: 0, issues: {}, items: [],
})

type Handler = (init: RequestInit, rid: string) => Response | Promise<Response>

function installApi(capabilities: string[], extra: Record<string, Handler> = {}) {
  const calls: { key: string; body: unknown; rid: string }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = new URL(String(input), 'http://localhost')
      const method = (init.method ?? 'GET').toUpperCase()
      const key = `${method} ${url.pathname.replace('/api/v1', '')}`
      const rid = new Headers(init.headers).get('X-Request-Id') ?? ''
      calls.push({ key, body: init.body ? JSON.parse(String(init.body)) : null, rid })
      if (extra[key]) return extra[key](init, rid)
      if (key === 'GET /me') return json({ user_id: 'u1', roles: ['MAINTENANCE_MANAGER'], capabilities, is_dev_auth: true })
      if (key === 'GET /branches') {
        return json({ items: [
          { branch_id: 'BR-SYN-A', branch_name: 'สาขาเอ', is_active: true },
          { branch_id: 'BR-SYN-B', branch_name: 'สาขาบี', is_active: true },
          { branch_id: 'BR-SYN-C', branch_name: 'สาขาซี', is_active: true },
          { branch_id: 'BR-SYN-OLD', branch_name: 'สาขาเก่า', is_active: false },
        ] })
      }
      if (key === 'GET /provinces') return json({ items: [] })
      const match = /^GET \/vehicles\/([^/]+)(\/status-history|\/branch-history|\/registration-history|\/latest-location)?$/.exec(key)
      if (match) {
        const id = decodeURIComponent(match[1])
        if (match[2] === '/status-history') return json([])
        if (match[2] === '/branch-history') return json(branchHistory(id))
        if (match[2] === '/registration-history') return json(REGISTRATION_HISTORY(id))
        if (match[2] === '/latest-location') return json({ error: { code: 'NOT_FOUND', message: 'x', details: null, request_id: 'x' } }, 404)
        return json(detail(id))
      }
      throw new Error(`unexpected request ${key}`)
    }),
  )
  return calls
}

function renderPage(path: string) {
  return render(
    <CapabilitiesProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/vehicle/:vehicleId" element={<VehicleDetailPage />} />
        </Routes>
      </MemoryRouter>
    </CapabilitiesProvider>,
  )
}

const ACTIONS = ['เพิ่มประวัติย้อนหลัง', 'แก้ไขประวัติ', 'ยกเลิกรายการ']

beforeEach(() => window.localStorage.clear())
afterEach(() => vi.unstubAllGlobals())

describe('C-c3: read-only panel, separate initially closed management area', () => {
  it('renders the actions only after "จัดการประวัติสาขา" is opened, never inside the panel', async () => {
    installApi(ALL)
    const user = userEvent.setup()
    renderPage('/vehicle/SYN-C3')
    const toggle = await screen.findByRole('button', { name: 'จัดการประวัติสาขา' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    for (const name of ACTIONS) expect(screen.queryByRole('button', { name })).toBeNull()
    const panel = await screen.findByTestId('branch-history-panel')
    await within(panel).findAllByText('สาขาเอ')
    expect(within(panel).queryAllByRole('button')).toHaveLength(0)
    expect(panel).not.toContainElement(toggle)
    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    const area = screen.getByTestId('branch-history-actions')
    for (const name of ACTIONS) expect(within(area).getByRole('button', { name })).toBeInTheDocument()
    expect(panel).not.toContainElement(area)
    expect(within(panel).queryAllByRole('button')).toHaveLength(0) // still read-only
    // no "แก้ไข"-only button appears on the page before the area is opened again
    await user.click(toggle)
    for (const name of ACTIONS) expect(screen.queryByRole('button', { name })).toBeNull()
  })
})

describe('capability gating', () => {
  it.each([
    [['can_view'], false, false],
    [['can_view', 'can_transfer_vehicle_branch'], true, false],
    [['can_view', 'can_correct_branch_history'], false, true],
    [ALL, true, true],
  ])('%j → transfer %s, manage %s', async (caps, transfer, manage) => {
    installApi(caps as string[])
    renderPage('/vehicle/SYN-G1')
    await screen.findByTestId('branch-history-panel')
    await screen.findAllByText('สาขาเอ')
    await waitFor(() => expect(screen.queryByRole('button', { name: 'ย้ายสาขา' }) !== null).toBe(transfer))
    expect(screen.queryByRole('button', { name: 'จัดการประวัติสาขา' }) !== null).toBe(manage)
    expect(screen.queryByRole('button', { name: 'ปรับข้อมูลสาขาปัจจุบันให้ตรงกับประวัติ' })).toBeNull() // CONSISTENT
  })
})

describe('transfer', () => {
  it('sends the expected values and a Bangkok +07:00 DATETIME, then re-reads the history', async () => {
    const calls = installApi(ALL, {
      'POST /vehicles/SYN-T1/branch-transfers': (_init, rid) =>
        json({ request_id: rid, changed: true, record_id: 'ABH-new', event_id: 'ABH-new', projection_write: 'WRITTEN',
          timeline_status_after: 'VALID', current_branch_id: 'BR-SYN-C', consistency: 'CONSISTENT' }, 200, { 'X-Request-Id': rid }),
    })
    const user = userEvent.setup()
    renderPage('/vehicle/SYN-T1')
    await user.click(await screen.findByRole('button', { name: 'ย้ายสาขา' }))
    const dialog = screen.getByTestId('branch-change-dialog')
    expect(within(dialog).getByRole('option', { name: /สาขาเก่า/ })).toBeDisabled()
    await user.selectOptions(within(dialog).getByLabelText('สาขา'), 'BR-SYN-C')
    await user.click(within(dialog).getByLabelText('ระบุวันที่และเวลา'))
    const input = within(dialog).getByLabelText('วันที่และเวลาที่มีผล')
    await user.clear(input)
    await user.type(input, '2026-09-20T08:30')
    await user.type(within(dialog).getByLabelText('หมายเหตุ (ไม่บังคับ)'), '  หมายเหตุ ')
    const historyReads = calls.filter((c) => c.key === 'GET /vehicles/SYN-T1/branch-history').length
    await user.click(within(dialog).getByRole('button', { name: 'ยืนยันการบันทึกสาขา' }))
    expect(await screen.findByTestId('branch-write-message')).toHaveTextContent(branchWriteText.applied)
    const sent = calls.find((c) => c.key === 'POST /vehicles/SYN-T1/branch-transfers')!
    expect(sent.body).toEqual({
      to_branch_id: 'BR-SYN-C', effective: { mode: 'DATETIME', at: '2026-09-20T08:30:00+07:00' },
      expected_current_branch_id: 'BR-SYN-A', expected_history_revision: 'BHR1-rev', note_th: '  หมายเหตุ ',
    })
    expect(sent.rid).toMatch(/^[0-9a-f-]{36}$/)
    await waitFor(() => expect(calls.filter((c) => c.key === 'GET /vehicles/SYN-T1/branch-history').length).toBeGreaterThan(historyReads))
    expect(registryPendingStore.list('u1', 'SYN-T1')).toEqual([])
  })

  it('NOW is the default for a transfer; an empty note is omitted', async () => {
    const calls = installApi(ALL, {
      'POST /vehicles/SYN-T2/branch-transfers': (_init, rid) => json({ request_id: rid, changed: false, warnings: [] }, 200, { 'X-Request-Id': rid }),
    })
    const user = userEvent.setup()
    renderPage('/vehicle/SYN-T2')
    await user.click(await screen.findByRole('button', { name: 'ย้ายสาขา' }))
    const dialog = screen.getByTestId('branch-change-dialog')
    await user.selectOptions(within(dialog).getByLabelText('สาขา'), 'BR-SYN-A')
    await user.click(within(dialog).getByRole('button', { name: 'ยืนยันการบันทึกสาขา' }))
    expect(await screen.findByTestId('branch-write-message')).toHaveTextContent(branchWriteText.noop)
    expect(calls.find((c) => c.key.startsWith('POST'))!.body).toEqual({
      to_branch_id: 'BR-SYN-A', effective: { mode: 'NOW' }, expected_current_branch_id: 'BR-SYN-A', expected_history_revision: 'BHR1-rev',
    })
  })
})

describe('history edits', () => {
  it('a reason is required before anything is sent; the correction is prefilled and keeps the reason exactly', async () => {
    const calls = installApi(ALL, {
      [`POST /vehicles/SYN-E1/branch-history/events/${E1}/corrections`]: (_init, rid) =>
        json({ request_id: rid, changed: true, record_id: 'ABH-c', event_id: E1, projection_write: 'NOT_NEEDED',
          timeline_status_after: 'VALID', current_branch_id: 'BR-SYN-A', consistency: 'CONSISTENT' }, 200, { 'X-Request-Id': rid }),
    })
    const user = userEvent.setup()
    renderPage('/vehicle/SYN-E1')
    await user.click(await screen.findByRole('button', { name: 'จัดการประวัติสาขา' }))
    await user.click(screen.getByRole('button', { name: 'แก้ไขประวัติ' }))
    const dialog = screen.getByTestId('branch-change-dialog')
    expect(within(dialog).queryByLabelText('ตอนนี้')).toBeNull() // NOW is a transfer-only mode
    await user.selectOptions(within(dialog).getByLabelText('รายการในประวัติ'), E1)
    expect(within(dialog).getByLabelText('สาขา')).toHaveValue('BR-SYN-B')
    expect(within(dialog).getByLabelText('วันที่และเวลาที่มีผล')).toHaveValue('2026-08-01T07:00')
    await user.type(within(dialog).getByLabelText('เหตุผล (บังคับ)'), '   ')
    await user.click(within(dialog).getByRole('button', { name: 'ยืนยันการบันทึกสาขา' }))
    expect(within(dialog).getByText('กรุณาระบุเหตุผล')).toBeInTheDocument()
    expect(calls.some((c) => c.key.startsWith('POST'))).toBe(false)
    await user.type(within(dialog).getByLabelText('เหตุผล (บังคับ)'), 'แก้เวลา ')
    await user.click(within(dialog).getByRole('button', { name: 'ยืนยันการบันทึกสาขา' }))
    expect(await screen.findByTestId('branch-write-message')).toHaveTextContent(branchWriteText.applied)
    expect(calls.find((c) => c.key.startsWith('POST'))!.body).toEqual({
      to_branch_id: 'BR-SYN-B', effective: { mode: 'DATETIME', at: '2026-08-01T07:00:00+07:00' }, reason_th: '   แก้เวลา ',
      expected_history_revision: 'BHR1-rev', expected_master_branch_id: 'BR-SYN-A',
    })
  })

  it('NOT_DETERMINED is kept as recorded-not-consistent and never described as success', async () => {
    let rid = ''
    installApi(ALL, {
      [`POST /vehicles/SYN-N1/branch-history/events/${E2}/cancellations`]: (_init, r) => {
        rid = r
        return json({ request_id: r, changed: true, record_id: 'ABH-cx', event_id: E2, projection_write: 'NOT_DETERMINED',
          timeline_status_after: 'AMBIGUOUS_ORDER', current_branch_id: null, consistency: 'UNDETERMINED' }, 200, { 'X-Request-Id': r })
      },
      'GET /vehicles/SYN-N1/branch-history': () => json({ ...branchHistory('SYN-N1', { extraRequestIds: rid ? [rid] : [] }),
        consistency: rid ? 'UNDETERMINED' : 'CONSISTENT', timeline_status: rid ? 'AMBIGUOUS_ORDER' : 'VALID',
        current: rid ? { branch_id: null, source: 'UNDETERMINED' } : { branch_id: 'BR-SYN-A', source: 'EVENT' } }),
    })
    const user = userEvent.setup()
    renderPage('/vehicle/SYN-N1')
    await user.click(await screen.findByRole('button', { name: 'จัดการประวัติสาขา' }))
    await user.click(screen.getByRole('button', { name: 'ยกเลิกรายการ' }))
    const dialog = screen.getByTestId('branch-change-dialog')
    await user.selectOptions(within(dialog).getByLabelText('รายการในประวัติ'), E2)
    await user.type(within(dialog).getByLabelText('เหตุผล (บังคับ)'), 'ผิด')
    await user.click(within(dialog).getByRole('button', { name: 'ยืนยันการบันทึกสาขา' }))
    const message = await screen.findByTestId('branch-write-message')
    expect(message).toHaveTextContent(branchWriteText.notDetermined)
    expect(message).not.toHaveTextContent(branchWriteText.applied)
    const banner = await screen.findByTestId('branch-intent-banner')
    expect(banner).toHaveTextContent(branchWriteText.pending)
    // the re-read finds the record but UNDETERMINED: still pending, not removed
    await waitFor(() => expect(registryPendingStore.list('u1', 'SYN-N1', 'branch')[0]?.state).toBe('RECORDED_PROJECTION_PENDING'))
    expect(screen.queryByTestId('branch-settlement-notice')).toBeNull()
  })
})

describe('write failures and reconciliation', () => {
  it('W2 failure keeps the intent pending; a later CONSISTENT read settles it with a notice', async () => {
    let rid = ''
    let fixed = false
    installApi(ALL, {
      'POST /vehicles/SYN-W2/branch-transfers': (_init, r) => {
        rid = r
        return json({ error: { code: 'BRANCH_PROJECTION_WRITE_FAILED', message: 'x', request_id: r,
          details: { event_recorded: true, record_id: 'ABH-w', projection_write_outcome: 'unknown', request_id: r } } }, 503)
      },
      'GET /vehicles/SYN-W2/branch-history': () =>
        json(branchHistory('SYN-W2', { extraRequestIds: rid ? [rid] : [], consistency: rid && !fixed ? 'PROJECTION_MISMATCH' : 'CONSISTENT' })),
    })
    const user = userEvent.setup()
    renderPage('/vehicle/SYN-W2')
    await user.click(await screen.findByRole('button', { name: 'ย้ายสาขา' }))
    const dialog = screen.getByTestId('branch-change-dialog')
    await user.selectOptions(within(dialog).getByLabelText('สาขา'), 'BR-SYN-C')
    await user.click(within(dialog).getByRole('button', { name: 'ยืนยันการบันทึกสาขา' }))
    const banner = await screen.findByTestId('branch-intent-banner')
    expect(banner).toHaveTextContent(branchWriteText.pending)
    // the mismatch read offers the reconciliation
    const reconcile = await screen.findByRole('button', { name: 'ปรับข้อมูลสาขาปัจจุบันให้ตรงกับประวัติ' })
    expect(reconcile).toBeInTheDocument()
    fixed = true
    await user.click(within(banner).getByRole('button', { name: 'ตรวจสอบผลจากประวัติสาขาอีกครั้ง' }))
    await waitFor(() => expect(screen.queryByTestId('branch-intent-banner')).toBeNull())
    expect(screen.getByTestId('branch-settlement-notice')).toHaveTextContent(branchWriteText.settled)
  })

  it('reconciliation sends the master value and the pending request as an audit link', async () => {
    const pending = '44444444-2222-4333-8444-555555555555'
    window.localStorage.setItem(storageKey('u1', 'SYN-R1'), JSON.stringify([{
      request_id: pending, operation: 'transfer', vehicle_id: 'SYN-R1', body: {}, submitted_at: new Date().toISOString(),
      state: 'RECORDED_PROJECTION_PENDING', page_instance: 'old', route_epoch: 0, prior_uncertain: true,
    }]))
    const calls = installApi(ALL, {
      'GET /vehicles/SYN-R1/branch-history': () =>
        json(branchHistory('SYN-R1', { consistency: 'PROJECTION_MISMATCH', master: 'BR-SYN-C', extraRequestIds: [pending] })),
      'POST /vehicles/SYN-R1/branch-projection/reconciliations': (_init, rid) =>
        json({ error: { code: 'BRANCH_HISTORY_STALE', message: 'x', details: { field: 'master_branch_id' }, request_id: rid } }, 409),
    })
    const user = userEvent.setup()
    renderPage('/vehicle/SYN-R1')
    await user.click(await screen.findByRole('button', { name: 'ปรับข้อมูลสาขาปัจจุบันให้ตรงกับประวัติ' }))
    const dialog = screen.getByTestId('branch-change-dialog')
    expect(within(dialog).getByLabelText('รหัสคำขอที่เกี่ยวข้อง (ไม่บังคับ)')).toHaveValue(pending)
    await user.type(within(dialog).getByLabelText('เหตุผล (บังคับ)'), 'ปรับ')
    await user.click(within(dialog).getByRole('button', { name: 'ยืนยันการบันทึกสาขา' }))
    expect(await screen.findByTestId('branch-write-message')).toHaveTextContent('ประวัติสาขาหรือสาขาปัจจุบันเปลี่ยนไปแล้ว')
    expect(calls.find((c) => c.key.startsWith('POST'))!.body).toEqual({
      reason_th: 'ปรับ', expected_history_revision: 'BHR1-rev', expected_master_branch_id: 'BR-SYN-C', related_request_id: pending,
    })
    // the related link settled nothing: the earlier intent is still pending
    expect(registryPendingStore.list('u1', 'SYN-R1', 'branch').map((i) => i.request_id)).toEqual([pending])
  })
})

describe('family-scoped settlement on the page', () => {
  it('a branch read never settles a registration intent and the registration banner ignores branch intents', async () => {
    const regRid = '55555555-2222-4333-8444-555555555555'
    const branchRid = '66666666-2222-4333-8444-555555555555'
    const now = new Date().toISOString()
    window.localStorage.setItem(storageKey('u1', 'SYN-F1'), JSON.stringify([
      { request_id: regRid, operation: 'registration', vehicle_id: 'SYN-F1', body: { registration_no: 'x' }, submitted_at: now,
        state: 'UNKNOWN', page_instance: 'old', route_epoch: 0, prior_uncertain: true },
      { request_id: branchRid, operation: 'transfer', vehicle_id: 'SYN-F1', body: {}, submitted_at: now,
        state: 'UNKNOWN', page_instance: 'old', route_epoch: 0, prior_uncertain: true },
    ]))
    installApi([...ALL, 'can_edit_vehicle_registration'], {
      // the branch history contains the REGISTRATION request id: it must settle nothing
      'GET /vehicles/SYN-F1/branch-history': () => json(branchHistory('SYN-F1', { extraRequestIds: [regRid, branchRid] })),
      'GET /vehicles/SYN-F1/registration-history': () => json(REGISTRATION_HISTORY('SYN-F1')),
    })
    renderPage('/vehicle/SYN-F1')
    await waitFor(() => expect(screen.getByTestId('branch-settlement-notice')).toHaveTextContent(branchRid))
    await waitFor(() => expect(registryPendingStore.list('u1', 'SYN-F1').map((i) => [i.request_id, i.state])).toEqual([[regRid, 'UNCONFIRMED']]))
    const registrationBanner = await screen.findByTestId('registration-intent-banner')
    expect(registrationBanner).toHaveTextContent(regRid)
    expect(registrationBanner).not.toHaveTextContent(branchRid)
    expect(screen.queryByTestId('branch-intent-banner')).toBeNull()
  })
})
