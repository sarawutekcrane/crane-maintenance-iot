import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { MutationResponse } from './apiClient'
import type { LinkHistory, TimelinePeriod } from './r2History'
import {
  classifyR2Response,
  FAMILIES,
  isR2InFlight,
  newR2RequestId,
  pendingR2Intent,
  r2IntentKey,
  resendR2Write,
  settleR2Intent,
  startR2Write,
  type R2Family,
  type R2Intent,
} from './r2HistoryWrites'

/** R2 Batch R2-C2a — strict, family-aware intent outcomes (owner correction C2a-2). */

const RID = '11111111-2222-4333-8444-555555555555'
const USER = 'dev-user'
const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

function http(status: number, json: unknown, header: string | null = RID): MutationResponse {
  return { kind: 'http', status, headerRequestId: header, json }
}
const err = (code: string, details: Record<string, unknown> | null = null, rid: unknown = RID) => ({
  error: { code, message: 'x', details, request_id: rid },
})
const first = (family: R2Family) => ({ family, request_id: RID, prior_uncertain: false })
const after = (family: R2Family) => ({ family, request_id: RID, prior_uncertain: true })

const caretakerChanged = {
  request_id: RID, changed: true, record_id: 'ECH-1', event_id: 'ECH-1', timeline_status_after: 'VALID',
  current_status: 'EVENT', current_technician_id: 'TEC-TEST-911',
}
const linkChanged = {
  request_id: RID, changed: true, link_event_id: 'PDL-1', previous_driver_id: null, new_driver_id: 'DRV-TEST-901',
  relationship_consistency_after: 'CONSISTENT',
}

describe('classifyR2Response — first attempt', () => {
  it('a correlated, shape-valid change is CONFIRMED and removed', () => {
    const c = classifyR2Response(http(200, caretakerChanged), first('caretaker'))
    expect(c.action).toBe('REMOVE')
    expect(c.result).toMatchObject({ kind: 'applied', recordIds: ['ECH-1'] })
    expect(classifyR2Response(http(200, linkChanged), first('driver-link')).result.kind).toBe('applied')
  })

  it('a correlated no-op is confirmed', () => {
    const c = classifyR2Response(http(200, { request_id: RID, changed: false }), first('responsibility'))
    expect(c).toMatchObject({ action: 'REMOVE', result: { kind: 'no-op' } })
  })

  it('an allowlisted pre-write refusal is a confirmed zero-write', () => {
    const c = classifyR2Response(http(422, err('DRIVER_NOT_ACTIVE', { driver_id: 'DRV-TEST-903' })), first('responsibility'))
    expect(c).toMatchObject({ action: 'REMOVE', result: { kind: 'refused', status: 422, code: 'DRIVER_NOT_ACTIVE' } })
    expect(classifyR2Response(http(403, err('HTTP_ERROR')), first('caretaker')).action).toBe('REMOVE')
  })

  it('a 4xx that is NOT on the family list stays uncertain (no "every 4xx is safe" rule)', () => {
    for (const [status, code] of [[422, 'SOMETHING_NEW'], [404, 'NOT_FOUND'], [409, 'DRIVER_NOT_ACTIVE'], [400, 'HTTP_ERROR']] as const) {
      const c = classifyR2Response(http(status, err(code)), first('responsibility'))
      expect(c).toMatchObject({ action: 'KEEP', state: 'UNKNOWN', result: { kind: 'unknown' } })
    }
    // A caretaker code is not accepted for the responsibility family and vice versa.
    expect(classifyR2Response(http(409, err('CARETAKER_HISTORY_STALE')), first('responsibility')).action).toBe('KEEP')
    expect(classifyR2Response(http(422, err('DRIVER_SCOPE_UNPROVEN')), first('caretaker')).action).toBe('KEEP')
  })

  it('stale is its own confirmed outcome (reload)', () => {
    const c = classifyR2Response(http(409, err('CARETAKER_HISTORY_STALE', { field: 'current_technician_id' })), first('caretaker'))
    expect(c).toMatchObject({ action: 'REMOVE', result: { kind: 'stale' } })
  })

  it('409 REQUEST_ID_REUSED keeps the intent as CONFLICT', () => {
    const c = classifyR2Response(http(409, err('REQUEST_ID_REUSED', { request_id: RID })), first('driver-link'))
    expect(c).toMatchObject({ action: 'KEEP', state: 'CONFLICT', result: { kind: 'conflict' } })
  })

  it('W1 rejected is a zero-write; W1 unknown (or missing outcome) stays uncertain', () => {
    const rejected = classifyR2Response(
      http(503, err('CARETAKER_HISTORY_WRITE_FAILED', { history_write_outcome: 'rejected', request_id: RID })), first('caretaker'))
    expect(rejected).toMatchObject({ action: 'REMOVE', result: { kind: 'refused' } })
    for (const details of [{ history_write_outcome: 'unknown' }, null]) {
      const c = classifyR2Response(http(503, err('CARETAKER_HISTORY_WRITE_FAILED', details)), first('caretaker'))
      expect(c).toMatchObject({ action: 'KEEP', state: 'UNKNOWN' })
    }
  })

  it('a link W2 failure with the event recorded is RECORDED (projection pending), never a success', () => {
    const c = classifyR2Response(
      http(503, err('PERSONNEL_DRIVER_LINK_PROJECTION_WRITE_FAILED', { event_recorded: true, record_id: 'PDL-9', request_id: RID })),
      first('driver-link'))
    expect(c).toMatchObject({ action: 'KEEP', state: 'RECORDED', recordIds: ['PDL-9'], result: { kind: 'recorded-projection-pending' } })
    const unproven = classifyR2Response(http(503, err('PERSONNEL_DRIVER_LINK_PROJECTION_WRITE_FAILED', {})), first('driver-link'))
    expect(unproven).toMatchObject({ action: 'KEEP', state: 'UNKNOWN' })
  })

  it('a first-attempt link MISMATCH is a zero-write that leads to reconciliation', () => {
    const c = classifyR2Response(http(409, err('PERSONNEL_TECHNICIAN_LINK_MISMATCH')), first('technician-link'))
    expect(c).toMatchObject({ action: 'REMOVE', result: { kind: 'mismatch' } })
  })

  it('missing or wrong request-id correlation is uncertain', () => {
    expect(classifyR2Response(http(200, { ...caretakerChanged, request_id: 'other' }), first('caretaker')).action).toBe('KEEP')
    expect(classifyR2Response(http(200, caretakerChanged, 'other-header'), first('caretaker')).action).toBe('KEEP')
    expect(classifyR2Response(http(422, err('DRIVER_NOT_ACTIVE', null, null)), first('responsibility')).action).toBe('KEEP')
    expect(classifyR2Response(http(422, { error: { code: 'DRIVER_NOT_ACTIVE', message: 'x' } }), first('responsibility')).action).toBe('KEEP')
    // An absent response header is accepted when the body correlates.
    expect(classifyR2Response(http(200, caretakerChanged, null), first('caretaker')).action).toBe('REMOVE')
  })

  it('a malformed body is uncertain', () => {
    for (const json of [null, 'text', { request_id: RID, changed: true }, { request_id: RID, changed: 'yes' },
      { ...caretakerChanged, timeline_status_after: 'X' }, { request_id: RID, replayed: true, record_ids: [] }]) {
      expect(classifyR2Response(http(200, json), first('caretaker')).action).toBe('KEEP')
    }
  })

  it('transport failures (network, timeout) and unknown 5xx are uncertain', () => {
    expect(classifyR2Response({ kind: 'transport', error: new Error('timeout') }, first('caretaker')).action).toBe('KEEP')
    expect(classifyR2Response(http(500, err('INTERNAL_ERROR')), first('caretaker')).action).toBe('KEEP')
    expect(classifyR2Response(http(502, null), first('caretaker')).action).toBe('KEEP')
    expect(classifyR2Response(http(500, err('EQUIPMENT_CARETAKER_HISTORY_DATA_INVALID')), first('caretaker')).action).toBe('KEEP')
  })

  it('a replay never removes the intent by itself; it asks for settlement', () => {
    const c = classifyR2Response(http(200, { request_id: RID, replayed: true, record_ids: ['ECH-1'] }), first('caretaker'))
    expect(c).toMatchObject({ action: 'KEEP', recordIds: ['ECH-1'], result: { kind: 'settlement-required' } })
  })
})

describe('classifyR2Response — after an earlier uncertainty', () => {
  it('a success keeps the intent for history settlement', () => {
    const c = classifyR2Response(http(200, caretakerChanged), after('caretaker'))
    expect(c).toMatchObject({ action: 'KEEP', recordIds: ['ECH-1'], result: { kind: 'settlement-required' } })
  })

  it('a refusal raised after the replay lookup does NOT prove the earlier attempt was not recorded (no write lock)', () => {
    // The backend reads the history once, looks the id up in that snapshot and
    // then checks: an earlier attempt still running may append after the read.
    for (const [status, code, family] of [
      [409, 'DRIVER_RESPONSIBILITY_HISTORY_STALE', 'responsibility'], [422, 'DRIVER_NOT_ACTIVE', 'responsibility'],
      [409, 'DRIVER_RESPONSIBILITY_EVENT_SAME_INSTANT', 'responsibility'], [409, 'CARETAKER_HISTORY_STALE', 'caretaker'],
      [422, 'TECHNICIAN_NOT_ACTIVE', 'caretaker'], [404, 'CARETAKER_EVENT_NOT_FOUND', 'caretaker'],
      [409, 'PERSONNEL_DRIVER_LINK_STALE', 'driver-link'], [409, 'DRIVER_ALREADY_LINKED', 'driver-link'],
    ] as const) {
      const c = classifyR2Response(http(status, err(code)), after(family))
      expect(c, code).toMatchObject({ action: 'KEEP', state: 'UNKNOWN', result: { kind: 'unknown', refused: { status, code } } })
      expect(c.result.kind === 'unknown' && c.result.message).toContain('ไม่ได้ยืนยันว่าคำขอครั้งก่อนไม่ได้ถูกบันทึก')
    }
  })

  it('no arbitrary 4xx, unknown code or no-op removes it; REQUEST_ID_REUSED stays a CONFLICT', () => {
    for (const [status, code] of [[403, 'HTTP_ERROR'], [404, 'NOT_FOUND'], [409, 'SOMETHING_NEW'], [422, 'SOMETHING_NEW'], [400, 'HTTP_ERROR']] as const) {
      for (const family of ['caretaker', 'responsibility', 'technician-link'] as const) {
        expect(classifyR2Response(http(status, err(code)), after(family)), `${family} ${status} ${code}`)
          .toMatchObject({ action: 'KEEP', state: 'UNKNOWN' })
      }
    }
    expect(classifyR2Response(http(200, { request_id: RID, changed: false }), after('caretaker')))
      .toMatchObject({ action: 'KEEP', state: 'UNKNOWN', result: { kind: 'unknown' } })
    expect(classifyR2Response(http(409, err('REQUEST_ID_REUSED', { request_id: RID })), after('caretaker')))
      .toMatchObject({ action: 'KEEP', state: 'CONFLICT', result: { kind: 'conflict' } })
  })

  it('a pre-replay refusal (or MISMATCH, or W1 rejected) proves nothing and keeps the intent', () => {
    for (const [status, code, family] of [
      [403, 'HTTP_ERROR', 'caretaker'], [422, 'VALIDATION_ERROR', 'caretaker'], [503, 'REGISTRY_DATA_CONTEXT_NOT_CONFIGURED', 'caretaker'],
      [404, 'PERSONNEL_NOT_FOUND', 'driver-link'], [409, 'PERSONNEL_DRIVER_LINK_MISMATCH', 'driver-link'],
    ] as const) {
      const c = classifyR2Response(http(status, err(code)), after(family))
      expect(c, code).toMatchObject({ action: 'KEEP', state: 'UNKNOWN' })
    }
    const w1 = classifyR2Response(http(503, err('CARETAKER_HISTORY_WRITE_FAILED', { history_write_outcome: 'rejected' })), after('caretaker'))
    expect(w1).toMatchObject({ action: 'KEEP', result: { kind: 'unknown', refused: { status: 503 } } })
  })
})

describe('family tables', () => {
  it('W1 / REUSED / INTERNAL_ERROR are never allowlisted', () => {
    for (const spec of Object.values(FAMILIES)) {
      expect([...spec.preWrite].some((p) => p.endsWith(`:${spec.w1}`) || p.endsWith(':REQUEST_ID_REUSED') || p.endsWith(':INTERNAL_ERROR'))).toBe(false)
    }
  })
})

// ---------------------------------------------------------------------------
// Store: persistence, exact replay, one intent per entity, settlement
// ---------------------------------------------------------------------------

function respond(...responses: Array<() => Response | Promise<Response>>) {
  let i = 0
  const fn = vi.fn(async (_url: string, _init?: RequestInit) => responses[Math.min(i++, responses.length - 1)]())
  vi.stubGlobal('fetch', fn)
  return fn
}
const json = (body: unknown, status = 200, rid?: string) => () =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...(rid ? { 'X-Request-Id': rid } : {}) } })
/** A response echoing the request id the client sent (as the backend does). */
function echo(build: (rid: string) => unknown, status = 200) {
  return vi.fn(async (_url: string, init?: RequestInit) => {
    const rid = ((init?.headers ?? {}) as Record<string, string>)['X-Request-Id']
    return new Response(JSON.stringify(build(rid)), { status, headers: { 'Content-Type': 'application/json', 'X-Request-Id': rid } })
  })
}

const write = (overrides: Partial<Parameters<typeof startR2Write>[0]> = {}) => startR2Write({
  userId: USER, family: 'caretaker', entityId: 'EQP-0002', path: '/equipment/EQP-0002/caretaker-events',
  operation: 'TRANSFER', body: { operation: 'TRANSFER', technician_id: 'TEC-TEST-911', effective: { mode: 'NOW' }, expected_current_technician_id: null },
  ...overrides,
})

describe('startR2Write / resendR2Write', () => {
  beforeEach(() => window.localStorage.clear())
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('generates a UUID v4 from crypto.getRandomValues', () => {
    expect(newR2RequestId()).toMatch(UUID_V4)
  })

  it('persists the intent BEFORE sending and removes it on a confirmed change', async () => {
    let seenDuringRequest: unknown = null
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
      seenDuringRequest = pendingR2Intent(USER, 'caretaker', 'EQP-0002')
      const rid = ((init?.headers ?? {}) as Record<string, string>)['X-Request-Id']
      return new Response(JSON.stringify({ ...caretakerChanged, request_id: rid }), { status: 200, headers: { 'X-Request-Id': rid } })
    }))
    const result = await write()
    expect(result.kind).toBe('applied')
    expect(seenDuringRequest).toMatchObject({ state: 'SUBMITTING', family: 'caretaker', path: '/equipment/EQP-0002/caretaker-events' })
    expect(pendingR2Intent(USER, 'caretaker', 'EQP-0002')).toBeNull()
  })

  it('keeps an uncertain intent, blocks a new write, and resends the SAME id, path and body', async () => {
    const fn = respond(() => Promise.reject(new TypeError('Failed to fetch')))
    const firstResult = await write()
    expect(firstResult.kind).toBe('unknown')
    const intent = pendingR2Intent(USER, 'caretaker', 'EQP-0002') as R2Intent
    expect(intent).toMatchObject({ state: 'UNKNOWN', prior_uncertain: true })
    // No automatic retry.
    expect(fn).toHaveBeenCalledTimes(1)
    // A new, different write on the same entity is refused while the intent is unresolved.
    expect(await write({ body: { operation: 'END', effective: { mode: 'NOW' }, expected_current_technician_id: null } }))
      .toMatchObject({ kind: 'blocked', reason: 'pending' })
    expect(fn).toHaveBeenCalledTimes(1)

    const resend = echo((rid) => ({ request_id: rid, replayed: true, record_ids: ['ECH-1'] }))
    vi.stubGlobal('fetch', resend)
    const replayed = await resendR2Write(USER, 'caretaker', 'EQP-0002')
    expect(replayed?.kind).toBe('settlement-required')
    const [url, init] = resend.mock.calls[0]
    expect(url).toBe('/api/v1/equipment/EQP-0002/caretaker-events')
    expect(((init?.headers ?? {}) as Record<string, string>)['X-Request-Id']).toBe(intent.request_id)
    expect(init?.body).toBe(intent.body_json)
    // Still pending until the history proves it.
    expect(pendingR2Intent(USER, 'caretaker', 'EQP-0002')).toMatchObject({ record_ids: ['ECH-1'] })
  })

  it('settles a timeline intent only when the authoritative history shows its record', async () => {
    respond(() => Promise.reject(new Error('timeout')))
    await write()
    vi.stubGlobal('fetch', echo((rid) => ({ request_id: rid, replayed: true, record_ids: ['ECH-7'] })))
    await resendR2Write(USER, 'caretaker', 'EQP-0002')
    const period = (id: string): TimelinePeriod => ({
      event_id: id, in_force: true, entry_operation: 'TRANSFER', revision_no: '1', head_record_id: id, target_id: 'TEC-TEST-911',
      effective_at: '2026-01-01T00:00:00+00:00', effective_precision: 'DATETIME', derived_end_at: null,
      recorded_at: '2026-01-01T00:00:00+00:00', recorded_by: USER, notes: [],
    })
    expect(settleR2Intent(USER, 'caretaker', 'EQP-0002', { kind: 'timeline', events: [period('ECH-other')] })).toBeNull()
    expect(pendingR2Intent(USER, 'caretaker', 'EQP-0002')).not.toBeNull()
    expect(settleR2Intent(USER, 'caretaker', 'EQP-0002', { kind: 'timeline', events: [period('ECH-7')] })).toEqual({ kind: 'settled', mismatch: false })
    expect(pendingR2Intent(USER, 'caretaker', 'EQP-0002')).toBeNull()
  })

  it('an uncertain timeline intent without a proven record id is never settled by a history read', async () => {
    respond(() => Promise.reject(new Error('timeout')))
    await write()
    expect(settleR2Intent(USER, 'caretaker', 'EQP-0002', { kind: 'timeline', events: [] })).toBeNull()
    expect(pendingR2Intent(USER, 'caretaker', 'EQP-0002')).not.toBeNull()
  })

  it('settles a link intent by its request id in the link history (and reports a MISMATCH)', async () => {
    respond(() => Promise.reject(new Error('timeout')))
    await write({ family: 'driver-link', entityId: 'PER-TEST-912', path: '/personnel/PER-TEST-912/driver-links',
      operation: 'LINK', body: { operation: 'LINK', expected_driver_id: '', new_driver_id: 'DRV-TEST-901', reason_th: 'x' } })
    const intent = pendingR2Intent(USER, 'driver-link', 'PER-TEST-912') as R2Intent
    const history = (requestId: string, consistency: LinkHistory['consistency']): LinkHistory => ({
      personnel_id: 'PER-TEST-912', current_id: null, latest_history_id: 'DRV-TEST-901', consistency, ids_visible: true,
      events: [{ link_event_id: 'PDL-1', event_kind: 'LINK', previous_id: null, new_id: 'DRV-TEST-901', recorded_at: 'x',
        recorded_by: USER, reason_th: 'x', request_id: requestId }],
    })
    expect(settleR2Intent(USER, 'driver-link', 'PER-TEST-912', { kind: 'link', history: history('someone-else', 'CONSISTENT') })).toBeNull()
    expect(settleR2Intent(USER, 'driver-link', 'PER-TEST-912', { kind: 'link', history: history(intent.request_id, 'MISMATCH') }))
      .toEqual({ kind: 'settled', mismatch: true })
  })

  it('a refusal of the resend (even a post-replay STALE) keeps the intent: same id, still resendable, new writes blocked', async () => {
    respond(() => Promise.reject(new Error('timeout')))
    await write()
    const before = pendingR2Intent(USER, 'caretaker', 'EQP-0002') as R2Intent
    vi.stubGlobal('fetch', echo((rid) => err('CARETAKER_HISTORY_STALE', { field: 'current_technician_id' }, rid), 409))
    expect(await resendR2Write(USER, 'caretaker', 'EQP-0002'))
      .toMatchObject({ kind: 'unknown', requestId: before.request_id, refused: { status: 409, code: 'CARETAKER_HISTORY_STALE' } })
    expect(pendingR2Intent(USER, 'caretaker', 'EQP-0002'))
      .toMatchObject({ state: 'UNKNOWN', request_id: before.request_id, body_json: before.body_json, prior_uncertain: true })
    expect(await write()).toMatchObject({ kind: 'blocked', reason: 'pending' })
  })

  it('a CONFLICT intent is kept, cannot be resent, gets no new id and is never settled by a read', async () => {
    const fn = echo((rid) => err('REQUEST_ID_REUSED', { request_id: rid }, rid), 409)
    vi.stubGlobal('fetch', fn)
    expect((await write()).kind).toBe('conflict')
    const intent = pendingR2Intent(USER, 'caretaker', 'EQP-0002') as R2Intent
    expect(intent).toMatchObject({ state: 'CONFLICT' })
    expect(await resendR2Write(USER, 'caretaker', 'EQP-0002')).toBeNull()
    expect(await write()).toMatchObject({ kind: 'blocked', reason: 'pending' })
    expect(fn).toHaveBeenCalledTimes(1)
    const period = { event_id: 'ECH-1', in_force: true, entry_operation: 'TRANSFER', revision_no: '1', head_record_id: 'ECH-1',
      target_id: 'TEC-TEST-911', effective_at: 'x', effective_precision: 'DATETIME', derived_end_at: null, recorded_at: 'x',
      recorded_by: USER, notes: [] } satisfies TimelinePeriod
    // Even a CONFLICT that still carries a record id from an earlier replay is never settled.
    window.localStorage.setItem(r2IntentKey(USER, 'caretaker', 'EQP-0002'), JSON.stringify({ ...intent, record_ids: ['ECH-1'] }))
    expect(settleR2Intent(USER, 'caretaker', 'EQP-0002', { kind: 'timeline', events: [period] })).toBeNull()
    expect(pendingR2Intent(USER, 'caretaker', 'EQP-0002')).toMatchObject({ state: 'CONFLICT', request_id: intent.request_id })
    // A link CONFLICT is not settled by a history event carrying its id (its body may differ).
    vi.stubGlobal('fetch', echo((rid) => err('REQUEST_ID_REUSED', { request_id: rid }, rid), 409))
    await write({ family: 'driver-link', entityId: 'PER-TEST-912', path: '/personnel/PER-TEST-912/driver-links',
      operation: 'LINK', body: { operation: 'LINK', expected_driver_id: '', new_driver_id: 'DRV-TEST-901', reason_th: 'x' } })
    const link = pendingR2Intent(USER, 'driver-link', 'PER-TEST-912') as R2Intent
    const history: LinkHistory = { personnel_id: 'PER-TEST-912', current_id: 'DRV-TEST-901', latest_history_id: 'DRV-TEST-901',
      consistency: 'CONSISTENT', ids_visible: true, events: [{ link_event_id: 'PDL-1', event_kind: 'LINK', previous_id: null,
        new_id: 'DRV-TEST-901', recorded_at: 'x', recorded_by: USER, reason_th: 'x', request_id: link.request_id }] }
    expect(settleR2Intent(USER, 'driver-link', 'PER-TEST-912', { kind: 'link', history })).toBeNull()
    expect(pendingR2Intent(USER, 'driver-link', 'PER-TEST-912')).toMatchObject({ state: 'CONFLICT' })
  })

  it('prevents a concurrent second submission for the same entity', async () => {
    let release: (r: Response) => void = () => {}
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => { release = resolve })))
    const firstWrite = write()
    expect(isR2InFlight(USER, 'caretaker', 'EQP-0002')).toBe(true)
    expect(await write()).toMatchObject({ kind: 'blocked', reason: 'in-flight' })
    release(new Response('{}', { status: 502 }))
    expect((await firstWrite).kind).toBe('unknown')
    // Separate entities and families are independent.
    vi.stubGlobal('fetch', echo((rid) => ({ ...caretakerChanged, request_id: rid })))
    expect((await write({ entityId: 'EQP-0009', path: '/equipment/EQP-0009/caretaker-events' })).kind).toBe('applied')
  })

  it('fails closed (sends nothing) without storage, a user id or a secure random source', async () => {
    const fn = respond(json({}))
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota') })
    expect(await write()).toMatchObject({ kind: 'blocked', reason: 'storage' })
    vi.restoreAllMocks()
    expect(await write({ userId: null })).toMatchObject({ kind: 'blocked', reason: 'no-user' })
    vi.spyOn(crypto, 'getRandomValues').mockImplementation(() => { throw new Error('no crypto') })
    expect(await write()).toMatchObject({ kind: 'blocked', reason: 'crypto' })
    expect(fn).not.toHaveBeenCalled()
  })

  it('an unreadable stored intent blocks new writes and is never resent', async () => {
    const fn = respond(json({}))
    window.localStorage.setItem(r2IntentKey(USER, 'caretaker', 'EQP-0002'), '{broken')
    expect(pendingR2Intent(USER, 'caretaker', 'EQP-0002')).toBe('corrupt')
    expect(await write()).toMatchObject({ kind: 'blocked', reason: 'pending' })
    expect(await resendR2Write(USER, 'caretaker', 'EQP-0002')).toBeNull()
    expect(fn).not.toHaveBeenCalled()
  })

  it('an intent left SUBMITTING by an earlier page is shown as UNKNOWN and resent unchanged', async () => {
    const key = r2IntentKey(USER, 'caretaker', 'EQP-0002')
    const body = { operation: 'END', effective: { mode: 'NOW' }, expected_current_technician_id: 'TEC-TEST-911' }
    window.localStorage.setItem(key, JSON.stringify({
      v: 1, family: 'caretaker', entity_id: 'EQP-0002', request_id: RID, path: '/equipment/EQP-0002/caretaker-events',
      body, body_json: JSON.stringify(body), operation: 'END', created_at: 'x', state: 'SUBMITTING', prior_uncertain: false, record_ids: [],
    }))
    expect(pendingR2Intent(USER, 'caretaker', 'EQP-0002')).toMatchObject({ state: 'UNKNOWN' })
    const fn = respond(json({ request_id: RID, changed: false }, 200, RID))
    // A no-op of a resend proves nothing about the earlier attempt: still pending.
    expect((await resendR2Write(USER, 'caretaker', 'EQP-0002'))?.kind).toBe('unknown')
    expect(fn.mock.calls[0][1]?.body).toBe(JSON.stringify(body))
    expect(pendingR2Intent(USER, 'caretaker', 'EQP-0002')).toMatchObject({ state: 'UNKNOWN', request_id: RID })
  })

  it('keys are per user, family and entity', () => {
    expect(r2IntentKey('u1', 'caretaker', 'EQP-1')).toBe('crane.r2HistoryPending.v1:u1:caretaker:EQP-1')
    expect(pendingR2Intent(null, 'caretaker', 'EQP-1')).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// Uncertain caretaker / responsibility writes against a fake append-only
// backend: the replay is keyed by (request id, exact body) as in the R2f
// contract; the response of a recorded attempt can be lost.
// ---------------------------------------------------------------------------

const TIMELINES = [
  { family: 'caretaker', entity: 'EQP-0002', path: '/equipment/EQP-0002/caretaker-events', prefix: 'ECH',
    body: { operation: 'TRANSFER', technician_id: 'TEC-TEST-911', effective: { mode: 'NOW' }, expected_current_technician_id: null } },
  { family: 'responsibility', entity: 'VEH-1048', path: '/vehicles/VEH-1048/responsible-driver-events', prefix: 'CDR',
    body: { operation: 'TRANSFER', driver_id: 'DRV-TEST-901', effective: { mode: 'NOW' }, expected_current_driver_id: null } },
] as const

function fakeBackend(prefix: string) {
  const history: Array<{ record_id: string; request_id: string; body: string }> = []
  let dropNext: 'before-append' | 'after-append' | null = null
  const fetchFn = vi.fn(async (_url: string, init?: RequestInit) => {
    const rid = ((init?.headers ?? {}) as Record<string, string>)['X-Request-Id']
    const body = String(init?.body)
    const reply = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { 'X-Request-Id': rid } })
    const drop = dropNext
    dropNext = null
    if (drop === 'before-append') throw new TypeError('Failed to fetch')
    const hit = history.filter((h) => h.request_id === rid)
    if (hit.length > 0) {
      if (hit[0].body !== body) return reply(err('REQUEST_ID_REUSED', { request_id: rid }, rid), 409)
      return reply({ request_id: rid, replayed: true, record_ids: hit.map((h) => h.record_id) })
    }
    const recordId = `${prefix}-${history.length + 1}`
    history.push({ record_id: recordId, request_id: rid, body })
    if (drop === 'after-append') throw new TypeError('Failed to fetch')
    return reply({ request_id: rid, changed: true, record_id: recordId, event_id: recordId, timeline_status_after: 'VALID',
      current_status: 'EVENT' })
  })
  return { history, fetchFn, lose: (when: 'before-append' | 'after-append') => { dropNext = when } }
}

const periodOf = (id: string): TimelinePeriod => ({
  event_id: id, in_force: true, entry_operation: 'TRANSFER', revision_no: '1', head_record_id: id, target_id: 'X',
  effective_at: 'x', effective_precision: 'DATETIME', derived_end_at: null, recorded_at: 'x', recorded_by: USER, notes: [],
})

describe.each(TIMELINES)('uncertain $family write: exact replay and settlement', (t) => {
  beforeEach(() => window.localStorage.clear())
  afterEach(() => vi.unstubAllGlobals())
  const start = () => startR2Write({ userId: USER, family: t.family, entityId: t.entity, path: t.path, operation: 'TRANSFER', body: t.body })

  it('recorded, response lost → explicit resend with the SAME id and body is replayed, settled by the history, no second event', async () => {
    const backend = fakeBackend(t.prefix)
    vi.stubGlobal('fetch', backend.fetchFn)
    backend.lose('after-append')
    expect((await start()).kind).toBe('unknown')
    const intent = pendingR2Intent(USER, t.family, t.entity) as R2Intent
    expect(intent).toMatchObject({ state: 'UNKNOWN', body_json: JSON.stringify(t.body) })
    expect(backend.fetchFn).toHaveBeenCalledTimes(1) // no automatic retry

    expect(await resendR2Write(USER, t.family, t.entity))
      .toMatchObject({ kind: 'settlement-required', recordIds: [`${t.prefix}-1`] })
    const [, resend] = backend.fetchFn.mock.calls[1]
    expect(((resend?.headers ?? {}) as Record<string, string>)['X-Request-Id']).toBe(intent.request_id)
    expect(resend?.body).toBe(intent.body_json)
    expect(backend.history).toHaveLength(1) // no second history event
    // The replay alone does not settle: only the authoritative read does.
    expect(pendingR2Intent(USER, t.family, t.entity)).not.toBeNull()
    expect(settleR2Intent(USER, t.family, t.entity, { kind: 'timeline', events: [] })).toBeNull()
    expect(settleR2Intent(USER, t.family, t.entity, { kind: 'timeline', events: [periodOf(`${t.prefix}-1`)] }))
      .toEqual({ kind: 'settled', mismatch: false })
    expect(pendingR2Intent(USER, t.family, t.entity)).toBeNull()
  })

  it('not recorded, response lost → the resend records it once; settled only by the history showing that record', async () => {
    const backend = fakeBackend(t.prefix)
    vi.stubGlobal('fetch', backend.fetchFn)
    backend.lose('before-append')
    expect((await start()).kind).toBe('unknown')
    expect(backend.history).toHaveLength(0)
    expect(await resendR2Write(USER, t.family, t.entity))
      .toMatchObject({ kind: 'settlement-required', recordIds: [`${t.prefix}-1`] })
    expect(backend.history).toHaveLength(1)
    expect(settleR2Intent(USER, t.family, t.entity, { kind: 'timeline', events: [periodOf(`${t.prefix}-other`)] })).toBeNull()
    expect(settleR2Intent(USER, t.family, t.entity, { kind: 'timeline', events: [periodOf(`${t.prefix}-1`)] }))
      .toEqual({ kind: 'settled', mismatch: false })
    // A second resend after settlement is impossible (nothing pending).
    expect(await resendR2Write(USER, t.family, t.entity)).toBeNull()
    expect(backend.history).toHaveLength(1)
  })

  it('unproven settlement stays fail-closed: a refused resend never clears the intent or appends', async () => {
    const backend = fakeBackend(t.prefix)
    vi.stubGlobal('fetch', backend.fetchFn)
    backend.lose('before-append')
    await start()
    vi.stubGlobal('fetch', echo((rid) => err(`${t.family === 'caretaker' ? 'CARETAKER' : 'DRIVER_RESPONSIBILITY'}_HISTORY_STALE`, null, rid), 409))
    expect((await resendR2Write(USER, t.family, t.entity))?.kind).toBe('unknown')
    expect(pendingR2Intent(USER, t.family, t.entity)).toMatchObject({ state: 'UNKNOWN', record_ids: [] })
    expect(settleR2Intent(USER, t.family, t.entity, { kind: 'timeline', events: [periodOf(`${t.prefix}-1`)] })).toBeNull()
    expect(backend.history).toHaveLength(0)
  })
})
