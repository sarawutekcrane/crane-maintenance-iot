import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { MutationResponse } from './apiClient'
import type { E2HistoryRecord, E2VehicleHistory } from './e2Assignments'
import {
  classifyE2Response,
  e2IntentKey,
  E2_PRE_WRITE,
  isE2InFlight,
  pendingE2Intent,
  resendE2Write,
  settleE2Intent,
  startE2Write,
  type E2Intent,
} from './e2Writes'

/** R2 Batch R2-C2b — E2 pending intents (strict outcomes, exact replay, history settlement). */

const RID = '11111111-2222-4333-8444-555555555555'
const USER = 'dev-user'
const VEH = 'VEH-1048'
const PATH = '/vehicles/VEH-1048/operational-driver-assignment-operations'

const http = (status: number, json: unknown, header: string | null = RID): MutationResponse =>
  ({ kind: 'http', status, headerRequestId: header, json })
const err = (code: string, details: Record<string, unknown> | null = null, rid: unknown = RID) =>
  ({ error: { code, message: 'x', details, request_id: rid } })
const first = { request_id: RID, prior_uncertain: false }
const after = { request_id: RID, prior_uncertain: true }
const changed = (rid = RID) => ({ request_id: rid, changed: true, operation_id: 'ODO-1', record_ids: ['ODA-1'], event_ids: ['ODA-1'],
  warnings: [{ code: 'NO_PERMANENT_RESPONSIBLE_DRIVER', event_id: null, driver_id: null, vehicle_id: VEH, related_event_id: null }] })
const replayed = (rid = RID) => ({ request_id: rid, replayed: true, operation_id: 'ODO-1', record_ids: ['ODA-1'], event_ids: ['ODA-1'] })

describe('classifyE2Response — first attempt', () => {
  it('a correlated, shape-valid change is removed, with its warnings', () => {
    const c = classifyE2Response(http(200, changed()), first)
    expect(c).toMatchObject({ action: 'REMOVE', result: { kind: 'applied', recordIds: ['ODA-1'], eventIds: ['ODA-1'] } })
    expect(c.result.kind === 'applied' && c.result.warnings[0].code).toBe('NO_PERMANENT_RESPONSIBLE_DRIVER')
  })

  it('a correlated duplicate / no-op is removed and names the existing assignment (B27)', () => {
    expect(classifyE2Response(http(200, { request_id: RID, changed: false, existing_event_id: 'ODA-9' }), first))
      .toMatchObject({ action: 'REMOVE', result: { kind: 'no-op', existingEventId: 'ODA-9' } })
    expect(classifyE2Response(http(200, { request_id: RID, changed: false, existing_event_id: null }), first))
      .toMatchObject({ action: 'REMOVE', result: { kind: 'no-op', existingEventId: null } })
  })

  it('every listed pre-write refusal is a confirmed zero-write', () => {
    for (const p of E2_PRE_WRITE) {
      const [status, code] = [Number(p.split(':')[0]), p.split(':').slice(1).join(':')]
      expect(classifyE2Response(http(status, err(code)), first).action, p).toBe('REMOVE')
    }
  })

  it('stale and concurrent-change refusals ask for a reload; overlap refusals carry the axis details', () => {
    expect(classifyE2Response(http(409, err('E2_ASSIGNMENT_STALE', { event_id: 'ODA-1', field: 'revision_no' })), first).result.kind).toBe('stale')
    expect(classifyE2Response(http(409, err('E2_CONCURRENT_CHANGE')), first).result.kind).toBe('stale')
    const overlap = classifyE2Response(http(409, err('E2_VEHICLE_CONFLICT', {
      axis: 'VEHICLE', conflicting_event_id: 'ODA-1',
      first: { event_id: 'ODA-1', vehicle_id: VEH, assigned_driver_id: 'DRV-TEST-901', label_date: '2026-10-21', start: 'a', end: 'b' },
      second: { event_id: 'ODA-2', vehicle_id: VEH, assigned_driver_id: 'DRV-TEST-902', label_date: '2026-10-21', start: 'c', end: 'd' },
    })), first)
    expect(overlap.result).toMatchObject({ kind: 'refused', overlap: { axis: 'VEHICLE', conflicting_event_id: 'ODA-1', second: { assigned_driver_id: 'DRV-TEST-902' } } })
  })

  it('REAL writes (409) and Google Sheets mode (501) are confirmed refusals with an explicit message', () => {
    const real = classifyE2Response(http(409, err('E2_REAL_WRITES_NOT_ENABLED')), first)
    expect(real.result).toMatchObject({ kind: 'refused', code: 'E2_REAL_WRITES_NOT_ENABLED' })
    expect(real.result.kind === 'refused' && real.result.message).toContain('R11')
    const sheets = classifyE2Response(http(501, err('FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE')), first)
    expect(sheets.result.kind === 'refused' && sheets.result.message).toContain('Mock/TEST')
  })

  it('a code not on the list, a wrong status, a 500 or a transport failure stays UNKNOWN', () => {
    for (const r of [http(422, err('SOMETHING_NEW')), http(404, err('E2_VEHICLE_CONFLICT')), http(400, err('HTTP_ERROR')),
      http(500, err('E2_HISTORY_DATA_INVALID')), http(500, err('INTERNAL_ERROR')), http(502, null),
      { kind: 'transport', error: new Error('timeout') } as MutationResponse]) {
      expect(classifyE2Response(r, first)).toMatchObject({ action: 'KEEP', state: 'UNKNOWN', result: { kind: 'unknown' } })
    }
  })

  it('REQUEST_ID_REUSED is a CONFLICT; W1 rejected is a zero-write; W1 unknown stays UNKNOWN', () => {
    expect(classifyE2Response(http(409, err('REQUEST_ID_REUSED', { request_id: RID })), first))
      .toMatchObject({ action: 'KEEP', state: 'CONFLICT', result: { kind: 'conflict' } })
    expect(classifyE2Response(http(503, err('E2_HISTORY_WRITE_FAILED', { history_write_outcome: 'rejected', request_id: RID })), first).action)
      .toBe('REMOVE')
    for (const details of [{ history_write_outcome: 'unknown' }, null]) {
      expect(classifyE2Response(http(503, err('E2_HISTORY_WRITE_FAILED', details)), first)).toMatchObject({ action: 'KEEP', state: 'UNKNOWN' })
    }
  })

  it('missing correlation or a malformed body is UNKNOWN; a replay asks for settlement', () => {
    expect(classifyE2Response(http(200, changed('other')), first).action).toBe('KEEP')
    expect(classifyE2Response(http(200, changed(), 'other-header'), first).action).toBe('KEEP')
    expect(classifyE2Response(http(409, err('E2_ASSIGNMENT_STALE', null, null)), first).action).toBe('KEEP')
    for (const bad of [{ ...changed(), record_ids: [] }, { ...changed(), warnings: [{ code: 1 }] }, { ...changed(), operation_id: '' },
      { request_id: RID, changed: 'yes' }, { ...replayed(), record_ids: [] }, { request_id: RID, changed: false, existing_event_id: 5 }]) {
      expect(classifyE2Response(http(200, bad), first).action, JSON.stringify(bad)).toBe('KEEP')
    }
    expect(classifyE2Response(http(200, replayed()), first))
      .toMatchObject({ action: 'KEEP', recordIds: ['ODA-1'], result: { kind: 'settlement-required' } })
    expect(classifyE2Response(http(200, changed(), null), first).action).toBe('REMOVE') // no header, body correlates
  })
})

describe('classifyE2Response — after an earlier uncertainty', () => {
  it('no refusal, no no-op and no concurrent-change response removes the intent', () => {
    for (const p of E2_PRE_WRITE) {
      const [status, code] = [Number(p.split(':')[0]), p.split(':').slice(1).join(':')]
      const c = classifyE2Response(http(status, err(code)), after)
      expect(c, p).toMatchObject({ action: 'KEEP', state: 'UNKNOWN', result: { kind: 'unknown', refused: { status, code } } })
      expect(c.result.kind === 'unknown' && c.result.message).toContain('ไม่ได้ยืนยันว่าคำขอครั้งก่อนไม่ได้ถูกบันทึก')
    }
    expect(classifyE2Response(http(200, { request_id: RID, changed: false, existing_event_id: 'ODA-1' }), after))
      .toMatchObject({ action: 'KEEP', state: 'UNKNOWN' })
    expect(classifyE2Response(http(503, err('E2_HISTORY_WRITE_FAILED', { history_write_outcome: 'rejected' })), after))
      .toMatchObject({ action: 'KEEP', result: { kind: 'unknown', refused: { status: 503 } } })
  })

  it('a success or replay keeps it for settlement; REUSED stays a CONFLICT', () => {
    expect(classifyE2Response(http(200, changed()), after)).toMatchObject({ action: 'KEEP', result: { kind: 'settlement-required' } })
    expect(classifyE2Response(http(200, replayed()), after)).toMatchObject({ action: 'KEEP', result: { kind: 'settlement-required' } })
    expect(classifyE2Response(http(409, err('REQUEST_ID_REUSED')), after)).toMatchObject({ state: 'CONFLICT' })
  })

  it('the pre-write list never contains W1, REUSED or a 500', () => {
    expect([...E2_PRE_WRITE].some((p) => p.endsWith(':E2_HISTORY_WRITE_FAILED') || p.endsWith(':REQUEST_ID_REUSED') || p.startsWith('500:')))
      .toBe(false)
  })
})

// ---------------------------------------------------------------------------
// Store and the fake append-only backend
// ---------------------------------------------------------------------------

const createBody = { operation: 'CREATE', driver_id: 'DRV-TEST-901', mode: 'FULL_DAY', start_date: '2026-10-20', end_date: '2026-10-22' }
const write = (over: Partial<Parameters<typeof startE2Write>[0]> = {}) =>
  startE2Write({ userId: USER, vehicleId: VEH, path: PATH, operation: 'CREATE', body: createBody, ...over })

function headers(init?: RequestInit) {
  return (init?.headers ?? {}) as Record<string, string>
}

/** The R2-C1 contract in miniature: replay by (request id, exact body); history rows keep the request id. */
function fakeBackend() {
  const rows: Array<{ record_id: string; request_id: string; body: string }> = []
  let drop: 'before' | 'after' | null = null
  const fetchFn = vi.fn(async (_url: string, init?: RequestInit) => {
    const rid = headers(init)['X-Request-Id']
    const body = String(init?.body)
    const reply = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { 'X-Request-Id': rid } })
    const lose = drop
    drop = null
    if (lose === 'before') throw new TypeError('Failed to fetch')
    const hits = rows.filter((r) => r.request_id === rid)
    if (hits.length > 0) {
      if (hits[0].body !== body) return reply(err('REQUEST_ID_REUSED', { request_id: rid }, rid), 409)
      return reply({ request_id: rid, replayed: true, operation_id: 'ODO-1', record_ids: hits.map((h) => h.record_id), event_ids: ['ODA-1'] })
    }
    rows.push({ record_id: `ODA-${rows.length + 1}`, request_id: rid, body })
    if (lose === 'after') throw new TypeError('Failed to fetch')
    return reply({ ...changed(rid), record_ids: [`ODA-${rows.length}`] })
  })
  const history = (): E2VehicleHistory => ({
    vehicle_id: VEH, events: [],
    records: rows.map((r) => ({ record_id: r.record_id, request_id: r.request_id } as unknown as E2HistoryRecord)),
  })
  return { rows, fetchFn, history, lose: (when: 'before' | 'after') => { drop = when } }
}

describe('startE2Write / resendE2Write / settleE2Intent', () => {
  beforeEach(() => window.localStorage.clear())
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('persists the exact id and body BEFORE sending and removes it on a confirmed change', async () => {
    let during: unknown = null
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
      during = pendingE2Intent(USER, VEH)
      const rid = headers(init)['X-Request-Id']
      return new Response(JSON.stringify(changed(rid)), { status: 200, headers: { 'X-Request-Id': rid } })
    }))
    expect((await write()).kind).toBe('applied')
    expect(during).toMatchObject({ state: 'SUBMITTING', path: PATH, body_json: JSON.stringify(createBody) })
    expect(pendingE2Intent(USER, VEH)).toBeNull()
  })

  it('recorded, response lost: no retry, new writes blocked, explicit resend of the SAME id and body is replayed, settled by request_id, no duplicate', async () => {
    const backend = fakeBackend()
    vi.stubGlobal('fetch', backend.fetchFn)
    backend.lose('after')
    expect((await write()).kind).toBe('unknown')
    const intent = pendingE2Intent(USER, VEH) as E2Intent
    expect(intent).toMatchObject({ state: 'UNKNOWN', prior_uncertain: true })
    expect(backend.fetchFn).toHaveBeenCalledTimes(1)
    expect(await write({ body: { ...createBody, driver_id: 'DRV-TEST-902' } })).toMatchObject({ kind: 'blocked', reason: 'pending' })
    expect(backend.fetchFn).toHaveBeenCalledTimes(1)

    expect(await resendE2Write(USER, VEH)).toMatchObject({ kind: 'settlement-required', recordIds: ['ODA-1'] })
    const [url, init] = backend.fetchFn.mock.calls[1]
    expect(url).toBe(`/api/v1${PATH}`)
    expect(headers(init)['X-Request-Id']).toBe(intent.request_id)
    expect(init?.body).toBe(intent.body_json)
    expect(backend.rows).toHaveLength(1)
    // The replay alone does not settle: only the authoritative history does.
    expect(pendingE2Intent(USER, VEH)).not.toBeNull()
    expect(settleE2Intent(USER, VEH, { vehicle_id: VEH, events: [], records: [] })).toBe(false)
    expect(settleE2Intent(USER, 'VEH-OTHER', backend.history())).toBe(false)
    expect(settleE2Intent(USER, VEH, backend.history())).toBe(true)
    expect(pendingE2Intent(USER, VEH)).toBeNull()
  })

  it('not recorded, response lost: the resend records it once and is settled by its request id', async () => {
    const backend = fakeBackend()
    vi.stubGlobal('fetch', backend.fetchFn)
    backend.lose('before')
    await write()
    expect(backend.rows).toHaveLength(0)
    expect((await resendE2Write(USER, VEH))?.kind).toBe('settlement-required')
    expect(backend.rows).toHaveLength(1)
    expect(settleE2Intent(USER, VEH, backend.history())).toBe(true)
    expect(await resendE2Write(USER, VEH)).toBeNull()
    expect(backend.rows).toHaveLength(1)
  })

  it('a refused resend (stale, concurrent change, no-op) keeps the intent with the same id; nothing is appended', async () => {
    const backend = fakeBackend()
    vi.stubGlobal('fetch', backend.fetchFn)
    backend.lose('before')
    await write()
    const before = pendingE2Intent(USER, VEH) as E2Intent
    for (const response of [err('E2_ASSIGNMENT_STALE'), err('E2_CONCURRENT_CHANGE'), err('E2_VEHICLE_CONFLICT')]) {
      vi.stubGlobal('fetch', vi.fn(async (_u: string, init?: RequestInit) => {
        const rid = headers(init)['X-Request-Id']
        return new Response(JSON.stringify({ error: { ...response.error, request_id: rid } }), { status: 409, headers: { 'X-Request-Id': rid } })
      }))
      expect((await resendE2Write(USER, VEH))?.kind).toBe('unknown')
      expect(pendingE2Intent(USER, VEH)).toMatchObject({ state: 'UNKNOWN', request_id: before.request_id, body_json: before.body_json })
    }
    vi.stubGlobal('fetch', vi.fn(async (_u: string, init?: RequestInit) => {
      const rid = headers(init)['X-Request-Id']
      return new Response(JSON.stringify({ request_id: rid, changed: false, existing_event_id: 'ODA-1' }), { status: 200, headers: { 'X-Request-Id': rid } })
    }))
    expect((await resendE2Write(USER, VEH))?.kind).toBe('unknown')
    expect(pendingE2Intent(USER, VEH)).toMatchObject({ request_id: before.request_id })
    expect(backend.rows).toHaveLength(0)
  })

  it('a CONFLICT is kept, never resent, gets no new id and is never settled by a history read', async () => {
    const backend = fakeBackend()
    vi.stubGlobal('fetch', backend.fetchFn)
    backend.lose('after')
    await write()
    const intent = pendingE2Intent(USER, VEH) as E2Intent
    // Force a REUSED answer for the stored id (as if another body was recorded under it).
    backend.rows[0].body = 'another body'
    expect((await resendE2Write(USER, VEH))?.kind).toBe('conflict')
    expect(pendingE2Intent(USER, VEH)).toMatchObject({ state: 'CONFLICT', request_id: intent.request_id })
    expect(await resendE2Write(USER, VEH)).toBeNull()
    expect(await write()).toMatchObject({ kind: 'blocked', reason: 'pending' })
    expect(settleE2Intent(USER, VEH, backend.history())).toBe(false)
    expect(pendingE2Intent(USER, VEH)).toMatchObject({ state: 'CONFLICT' })
    expect(backend.fetchFn).toHaveBeenCalledTimes(2)
  })

  it('one request in flight per vehicle; vehicles are independent', async () => {
    let release: (r: Response) => void = () => {}
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => { release = resolve })))
    const pending = write()
    expect(isE2InFlight(USER, VEH)).toBe(true)
    expect(await write()).toMatchObject({ kind: 'blocked', reason: 'in-flight' })
    // In flight: not judged by a history read either.
    expect(settleE2Intent(USER, VEH, { vehicle_id: VEH, events: [], records: [] })).toBe(false)
    release(new Response('{}', { status: 502 }))
    expect((await pending).kind).toBe('unknown')
    vi.stubGlobal('fetch', vi.fn(async (_u: string, init?: RequestInit) => {
      const rid = headers(init)['X-Request-Id']
      return new Response(JSON.stringify(changed(rid)), { status: 200, headers: { 'X-Request-Id': rid } })
    }))
    expect((await write({ vehicleId: 'VEH-TEST-901', path: '/vehicles/VEH-TEST-901/operational-driver-assignment-operations' })).kind).toBe('applied')
  })

  it('fails closed (sends nothing) without storage, a user id or a secure random source', async () => {
    const fn = vi.fn()
    vi.stubGlobal('fetch', fn)
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota') })
    expect(await write()).toMatchObject({ kind: 'blocked', reason: 'storage' })
    vi.restoreAllMocks()
    expect(await write({ userId: null })).toMatchObject({ kind: 'blocked', reason: 'no-user' })
    vi.spyOn(crypto, 'getRandomValues').mockImplementation(() => { throw new Error('no crypto') })
    expect(await write()).toMatchObject({ kind: 'blocked', reason: 'crypto' })
    expect(fn).not.toHaveBeenCalled()
  })

  it('an unreadable stored intent blocks new writes and is never resent; a stale SUBMITTING one shows as UNKNOWN', async () => {
    const fn = vi.fn()
    vi.stubGlobal('fetch', fn)
    window.localStorage.setItem(e2IntentKey(USER, VEH), '{broken')
    expect(pendingE2Intent(USER, VEH)).toBe('corrupt')
    expect(await write()).toMatchObject({ kind: 'blocked', reason: 'pending' })
    expect(await resendE2Write(USER, VEH)).toBeNull()
    expect(fn).not.toHaveBeenCalled()
    window.localStorage.setItem(e2IntentKey(USER, VEH), JSON.stringify({
      v: 1, vehicle_id: VEH, request_id: RID, path: PATH, body: createBody, body_json: JSON.stringify(createBody),
      operation: 'CREATE', created_at: 'x', state: 'SUBMITTING', prior_uncertain: false, record_ids: [],
    }))
    expect(pendingE2Intent(USER, VEH)).toMatchObject({ state: 'UNKNOWN' })
    expect(e2IntentKey('u1', 'VEH-1')).toBe('crane.e2Pending.v1:u1:VEH-1')
  })
})
