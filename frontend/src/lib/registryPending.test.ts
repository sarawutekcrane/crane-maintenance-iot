import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { MutationResponse } from './apiClient'
import allowlist from './registryOutcomeAllowlist.json'
import {
  bannerState,
  classifyResponse,
  isAllowlisted,
  MEMORY_ONLY_TEXT,
  newRequestId,
  PENDING_LIMIT,
  PENDING_TTL_MS,
  type PendingIntent,
  PendingStore,
  resendRegistryIntent,
  storageKey,
  submitRegistryIntent,
  UNKNOWN_TEXT,
  ZERO_WRITE_ALLOWLIST,
} from './registryPending'
import type { RegistrationHistory } from './types'

// Phase 7 Batch 7O2b — registry operation bookkeeping (contract Final Rev2
// §10.3-§10.4; Outcome Classification Addendum A.2, W-OC-01..07, W-11, W-13).
// Synthetic data only.

const RID = '11111111-2222-4333-8444-555555555555'
const OTHER = '99999999-2222-4333-8444-555555555555'

function http(status: number, json: unknown, header: string | null = RID): MutationResponse {
  return { kind: 'http', status, headerRequestId: header, json }
}
function envelope(status: number, code: string, details: Record<string, unknown> | null = null, rid = RID) {
  return http(status, { error: { code, message: code, details, request_id: rid } })
}
const first = { request_id: RID, operation: 'registration' as const, prior_uncertain: false }
const after = { ...first, prior_uncertain: true }
const reconcileFirst = { ...first, operation: 'registration_reconcile' as const }

const applied = http(200, {
  request_id: RID, changed: true, master_write: 'WRITTEN', warnings: [],
  change: { change_id: 'VRH-' + 'a'.repeat(32), recorded_at: '2026-10-05T00:00:00.000001+00:00', request_id: RID },
})

describe('classifyResponse — Addendum A.2 rows (W-OC-01)', () => {
  const rows: [string, MutationResponse, string, string][] = [
    // label, response, first attempt, after prior uncertainty
    ['200 changed:true WRITTEN', applied, 'REMOVE:CONFIRMED_APPLIED', 'KEEP:UNKNOWN'],
    ['200 changed:true NOT_NEEDED', http(200, { ...(applied as { json: object }).json, master_write: 'NOT_NEEDED' }), 'REMOVE:CONFIRMED_APPLIED', 'KEEP:UNKNOWN'],
    ['200 changed:false', http(200, { request_id: RID, changed: false, warnings: [] }), 'REMOVE:CONFIRMED_NO_OP', 'KEEP:UNKNOWN'],
    ['200 replayed with record ids', http(200, { request_id: RID, replayed: true, record_ids: ['VRH-1'], master_state: 'MATCHES', consistency: 'CONSISTENT' }), 'KEEP:UNKNOWN', 'KEEP:UNKNOWN'],
    ['allowlisted 409 stale', envelope(409, 'VEHICLE_REGISTRY_STALE'), 'REMOVE:CONFIRMED_ZERO_WRITE', 'KEEP:UNKNOWN'],
    ['allowlisted 403', envelope(403, 'HTTP_ERROR'), 'REMOVE:CONFIRMED_ZERO_WRITE', 'KEEP:UNKNOWN'],
    ['W1 rejected', envelope(503, 'REGISTRATION_HISTORY_WRITE_FAILED', { history_write_outcome: 'rejected', master_write: 'NOT_ATTEMPTED' }), 'REMOVE:CONFIRMED_ZERO_WRITE', 'KEEP:UNKNOWN'],
    ['W1 unknown', envelope(503, 'REGISTRATION_HISTORY_WRITE_FAILED', { history_write_outcome: 'unknown' }), 'KEEP:UNKNOWN', 'KEEP:UNKNOWN'],
    ['W1 outcome missing', envelope(503, 'REGISTRATION_HISTORY_WRITE_FAILED', {}), 'KEEP:UNKNOWN', 'KEEP:UNKNOWN'],
    ['W2 failed with record', envelope(503, 'VEHICLE_MASTER_WRITE_FAILED', { history_recorded: true, change_id: 'VRH-1' }), 'KEEP:RECORDED_PROJECTION_PENDING', 'KEEP:RECORDED_PROJECTION_PENDING'],
    ['W2 failed without details', envelope(503, 'VEHICLE_MASTER_WRITE_FAILED', null), 'KEEP:UNKNOWN', 'KEEP:UNKNOWN'],
    ['W2 failed without record id', envelope(503, 'VEHICLE_MASTER_WRITE_FAILED', { history_recorded: true }), 'KEEP:UNKNOWN', 'KEEP:UNKNOWN'],
    ['409 REQUEST_ID_REUSED', envelope(409, 'REQUEST_ID_REUSED'), 'KEEP:CONFLICT', 'KEEP:CONFLICT'],
    ['500 INTERNAL_ERROR', envelope(500, 'INTERNAL_ERROR'), 'KEEP:UNKNOWN', 'KEEP:UNKNOWN'],
  ]
  const label = (c: ReturnType<typeof classifyResponse>) => `${c.action}:${c.action === 'REMOVE' ? c.notice : c.state}`
  for (const [name, response, firstExpected, afterExpected] of rows) {
    it(name, () => {
      expect(label(classifyResponse(response, first))).toBe(firstExpected)
      expect(label(classifyResponse(response, after))).toBe(afterExpected)
    })
  }
})

describe('nothing proves anything unless validated and correlated (W-OC-02, W-OC-03)', () => {
  const unknownCases: [string, MutationResponse][] = [
    ['transport error', { kind: 'transport', error: new Error('network') }],
    ['timeout (abort)', { kind: 'transport', error: new DOMException('aborted', 'AbortError') }],
    ['501', envelope(501, 'FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE')],
    ['502 html (no JSON)', http(502, null, null)],
    ['504 html', http(504, null, null)],
    ['non-JSON 200', http(200, null)],
    ['201 with body', http(201, { request_id: RID, changed: true })],
    ['204', http(204, null)],
    ['302', http(302, null)],
    ['200 header missing', http(200, (applied as { json: object }).json, null)],
    ['200 header wrong', http(200, (applied as { json: object }).json, OTHER)],
    ['200 body request id wrong', http(200, { ...(applied as { json: object }).json, request_id: OTHER })],
    ['200 changed missing', http(200, { request_id: RID })],
    ['200 changed not boolean', http(200, { request_id: RID, changed: 'true' })],
    ['200 change id missing', http(200, { request_id: RID, changed: true, master_write: 'WRITTEN', change: {} })],
    ['200 master_write invalid', http(200, { request_id: RID, changed: true, master_write: 'DONE', change: { change_id: 'VRH-1' } })],
    ['200 NOT_DETERMINED on registration (branch-only value)', http(200, { request_id: RID, changed: true, master_write: 'NOT_DETERMINED', change: { change_id: 'VRH-1' } })],
    ['200 no-op that also says replayed', http(200, { request_id: RID, changed: false, replayed: false })],
    ['200 replay without record ids', http(200, { request_id: RID, replayed: true })],
    ['error envelope request id wrong', envelope(409, 'VEHICLE_REGISTRY_STALE', null, OTHER)],
    ['error envelope request id missing', http(409, { error: { code: 'VEHICLE_REGISTRY_STALE', message: 'x', details: null } })],
    ['error without code', http(409, { error: { message: 'x', request_id: RID } })],
    ['error not an object', http(409, { error: 'VEHICLE_REGISTRY_STALE' })],
    ['array body', http(409, [])],
  ]
  for (const [name, response] of unknownCases) {
    it(`${name} -> KEEP UNKNOWN`, () => {
      expect(classifyResponse(response, first)).toMatchObject({ action: 'KEEP', state: 'UNKNOWN' })
    })
  }
})

describe('allowlist per operation (W-OC-04)', () => {
  it('a listed code with the wrong status stays UNKNOWN', () => {
    expect(classifyResponse(envelope(422, 'VEHICLE_REGISTRY_STALE'), first).action).toBe('KEEP')
    expect(classifyResponse(envelope(500, 'HTTP_ERROR'), first).action).toBe('KEEP')
    expect(classifyResponse(envelope(404, 'NOT_FOUND'), first).action).toBe('KEEP')
  })
  it('a code allowlisted only for the other operation stays UNKNOWN', () => {
    expect(classifyResponse(envelope(409, 'MASTER_PAIR_INVALID'), first).action).toBe('KEEP')
    expect(classifyResponse(envelope(409, 'MASTER_PAIR_INVALID'), reconcileFirst).action).toBe('REMOVE')
    expect(classifyResponse(envelope(422, 'REGISTRATION_TEXT_INVALID'), reconcileFirst).action).toBe('KEEP')
    expect(classifyResponse(envelope(422, 'REGISTRATION_TEXT_INVALID'), first).action).toBe('REMOVE')
  })
  it('a branch code or a newly added code stays UNKNOWN until allowlisted', () => {
    for (const code of ['BRANCH_NOT_FOUND', 'BRANCH_HISTORY_STALE', 'SOME_NEW_CODE']) {
      expect(classifyResponse(envelope(422, code), first)).toMatchObject({ action: 'KEEP', state: 'UNKNOWN' })
      expect(classifyResponse(envelope(409, code), first)).toMatchObject({ action: 'KEEP', state: 'UNKNOWN' })
    }
  })
  it('the classifier table is exactly the shared JSON table, with no never-allowlisted code', () => {
    const data = allowlist as unknown as Record<string, [number, string][]>
    for (const op of ['registration', 'registration_reconcile'] as const) {
      expect([...ZERO_WRITE_ALLOWLIST[op]].sort()).toEqual(data[op].map(([s, c]) => `${s}:${c}`).sort())
      for (const code of ['INTERNAL_ERROR', 'NOT_FOUND', 'FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE', 'REQUEST_ID_REUSED']) {
        expect([...ZERO_WRITE_ALLOWLIST[op]].some((pair) => pair.endsWith(`:${code}`))).toBe(false)
      }
    }
    expect(isAllowlisted('registration', 403, 'HTTP_ERROR')).toBe(true)
    expect(isAllowlisted('transfer', 403, 'HTTP_ERROR')).toBe(false) // branch operations arrive with 7O2c
  })
})

describe('wording', () => {
  it('UNKNOWN never says "not saved"', () => {
    expect(UNKNOWN_TEXT).toBe('ยังไม่ทราบผลการบันทึก — ระบบจะตรวจสอบจากประวัติ')
    expect(UNKNOWN_TEXT).not.toContain('ไม่ได้บันทึก')
    expect(MEMORY_ONLY_TEXT).toBe('คำเตือนนี้จะหายเมื่อออกจากหน้า')
  })
  it('request ids are UUIDv4 text', () => {
    const ids = new Set(Array.from({ length: 50 }, () => newRequestId()))
    expect(ids.size).toBe(50)
    for (const id of ids) expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
  })
})

// ---------------------------------------------------------------------------
// Store (W-11, W-13)
// ---------------------------------------------------------------------------

class FakeStorage implements Storage {
  data = new Map<string, string>()
  failing = false
  get length() {
    return this.data.size
  }
  clear() {
    this.data.clear()
  }
  getItem(key: string) {
    if (this.failing) throw new Error('blocked')
    return this.data.get(key) ?? null
  }
  key(index: number) {
    return [...this.data.keys()][index] ?? null
  }
  removeItem(key: string) {
    if (this.failing) throw new Error('blocked')
    this.data.delete(key)
  }
  setItem(key: string, value: string) {
    if (this.failing) throw new Error('quota')
    this.data.set(key, value)
  }
}

const NOW = Date.parse('2026-10-05T03:00:00Z')

function intent(overrides: Partial<PendingIntent> = {}): PendingIntent {
  return {
    request_id: RID, operation: 'registration', vehicle_id: 'SYN-V1',
    body: { registration_no: ' กข 1 ', registration_province_code: null, expected_registration_no: null, expected_registration_province_code: null },
    submitted_at: new Date(NOW).toISOString(), state: 'SUBMITTING', page_instance: 'p1', route_epoch: 0, prior_uncertain: false,
    ...overrides,
  }
}

function history(items: { request_id: string }[], consistency = 'CONSISTENT'): RegistrationHistory {
  return {
    vehicle_id: 'SYN-V1',
    current: { registration_no: { state: 'RECORDED', value: 'x' }, registration_province: { state: 'NOT_RECORDED', value: null } },
    consistency, history_revision: 'RHR1-0', excluded_test_rows: 0, issues: {},
    items: items.map((i, n) => ({
      change_id: `VRH-${n}`, change_kind: 'CHANGE', old_registration_no: null, old_registration_province_code: null,
      new_registration_no: 'x', new_registration_province_code: null, recorded_at: '2026-10-05T00:00:00+00:00',
      recorded_by: 'u', request_id: i.request_id, related_request_id: null, accepted_exceptions: [], note_th: null,
    })),
  }
}

describe('PendingStore', () => {
  let storage: FakeStorage
  let store: PendingStore
  beforeEach(() => {
    storage = new FakeStorage()
    store = new PendingStore(() => storage, () => NOW, 'page-1')
  })

  it('keys by user and vehicle and survives a reload (new page, same storage)', () => {
    store.add('u1', intent())
    expect(storage.data.has(storageKey('u1', 'SYN-V1'))).toBe(true)
    expect(storageKey('u1', 'SYN-V1')).toBe('crane.registryPending.v1:u1:SYN-V1')
    const reloaded = new PendingStore(() => storage, () => NOW, 'page-2')
    expect(reloaded.list('u1', 'SYN-V1')).toHaveLength(1)
    expect(reloaded.list('u1', 'SYN-V1')[0].body).toEqual(intent().body) // exact body kept
    expect(reloaded.list('u2', 'SYN-V1')).toEqual([]) // another user of the browser: display scoping
    expect(reloaded.list('u1', 'SYN-V2')).toEqual([])
  })

  it('keeps at most 5 per user per vehicle (oldest evicted) and drops expired intents at load', () => {
    for (let i = 0; i < PENDING_LIMIT + 2; i++) store.add('u1', intent({ request_id: `r-${i}` }))
    expect(store.list('u1', 'SYN-V1').map((i) => i.request_id)).toEqual(['r-2', 'r-3', 'r-4', 'r-5', 'r-6'])
    const later = new PendingStore(() => storage, () => NOW + PENDING_TTL_MS + 1)
    expect(later.list('u1', 'SYN-V1')).toEqual([])
    expect(storage.data.has(storageKey('u1', 'SYN-V1'))).toBe(false) // pruned at load
  })

  it('falls back to page memory when storage fails, and says so', () => {
    storage.failing = true
    store.add('u1', intent())
    expect(store.isMemoryOnly).toBe(true)
    expect(store.list('u1', 'SYN-V1')).toHaveLength(1)
    const reloaded = new PendingStore(() => storage, () => NOW)
    storage.failing = false
    expect(reloaded.list('u1', 'SYN-V1')).toEqual([]) // lost on reload, as disclosed
  })

  it('applies every response (bookkeeping) and never removes after uncertainty', () => {
    store.add('u1', intent())
    expect(store.applyResponse('u1', 'SYN-V1', RID, 'registration', { kind: 'transport', error: new Error('x') }).classification.state).toBe('UNKNOWN')
    expect(store.list('u1', 'SYN-V1')[0]).toMatchObject({ state: 'UNKNOWN', prior_uncertain: true })
    // a later success of an explicit resend does not remove it (W-OC-06)
    const result = store.applyResponse('u1', 'SYN-V1', RID, 'registration', applied)
    expect(result.classification).toMatchObject({ action: 'KEEP', state: 'UNKNOWN' })
    // a later proven refusal is reported but does not remove it either
    const refused = store.applyResponse('u1', 'SYN-V1', RID, 'registration', envelope(409, 'VEHICLE_REGISTRY_STALE'))
    expect(refused.classification).toMatchObject({ action: 'KEEP', state: 'UNKNOWN', refused: true, errorCode: 'VEHICLE_REGISTRY_STALE' })
    expect(store.list('u1', 'SYN-V1')).toHaveLength(1)
  })

  it('a first-attempt proven outcome removes the intent', () => {
    store.add('u1', intent())
    expect(store.applyResponse('u1', 'SYN-V1', RID, 'registration', envelope(409, 'REGISTRATION_DUPLICATE')).classification.action).toBe('REMOVE')
    expect(store.list('u1', 'SYN-V1')).toEqual([])
  })

  describe('settlement (§10.4)', () => {
    it('not found -> UNCONFIRMED; found but not consistent -> pending; found and consistent -> resolved', () => {
      store.add('u1', intent({ state: 'UNKNOWN', prior_uncertain: true }))
      expect(store.settle('u1', 'SYN-V1', history([{ request_id: 'other' }]))).toEqual([])
      expect(store.list('u1', 'SYN-V1')[0].state).toBe('UNCONFIRMED')
      store.settle('u1', 'SYN-V1', history([{ request_id: RID }], 'MISMATCH'))
      expect(store.list('u1', 'SYN-V1')[0].state).toBe('RECORDED_PROJECTION_PENDING')
      const notices = store.settle('u1', 'SYN-V1', history([{ request_id: RID }]))
      expect(notices).toEqual([{ request_id: RID, operation: 'registration', intent: 'RECORDED' }])
      expect(store.list('u1', 'SYN-V1')).toEqual([])
      expect(store.notices('u1', 'SYN-V1')).toEqual(notices)
    })

    it('names later changes; NO_HISTORY or a matching master proves nothing', () => {
      store.add('u1', intent({ state: 'UNKNOWN' }))
      store.settle('u1', 'SYN-V1', history([], 'NO_HISTORY'))
      expect(store.list('u1', 'SYN-V1')[0].state).toBe('UNCONFIRMED')
      const notices = store.settle('u1', 'SYN-V1', history([{ request_id: RID }, { request_id: 'later' }]))
      expect(notices[0].intent).toBe('RECORDED_LATER_CHANGED')
    })

    it('a failed history read changes nothing; CONFLICT is kept; in-flight intents are not judged', () => {
      store.add('u1', intent({ state: 'UNKNOWN', prior_uncertain: true }))
      store.add('u1', intent({ request_id: 'conflicted', state: 'CONFLICT' }))
      store.add('u1', intent({ request_id: 'flying' }))
      store.markInflight('flying', true)
      expect(store.settle('u1', 'SYN-V1', null)).toEqual([])
      expect(store.list('u1', 'SYN-V1').map((i) => i.state)).toEqual(['UNKNOWN', 'CONFLICT', 'SUBMITTING'])
      store.settle('u1', 'SYN-V1', history([{ request_id: RID }, { request_id: 'conflicted' }, { request_id: 'flying' }]))
      expect(store.list('u1', 'SYN-V1').map((i) => [i.request_id, i.state])).toEqual([
        ['conflicted', 'CONFLICT'],
        ['flying', 'SUBMITTING'],
      ])
    })

    it('a reconciliation whose related_request_id names the original settles nothing by itself', () => {
      store.add('u1', intent({ state: 'RECORDED_PROJECTION_PENDING', prior_uncertain: true }))
      const reconciled = history([{ request_id: 'repair' }], 'MISMATCH')
      reconciled.items[0].related_request_id = RID
      store.settle('u1', 'SYN-V1', reconciled)
      expect(store.list('u1', 'SYN-V1')[0].state).toBe('UNCONFIRMED') // the original's own record is not in this read
    })

    it('a SUBMITTING intent left by another page is judged (it is not in flight here)', () => {
      const other = new PendingStore(() => storage, () => NOW, 'page-crashed')
      other.add('u1', intent())
      store.settle('u1', 'SYN-V1', history([]))
      expect(store.list('u1', 'SYN-V1')[0].state).toBe('UNCONFIRMED')
    })

    it('a read kept before the user id was known is judged once', () => {
      store.add('u1', intent({ state: 'UNKNOWN' }))
      store.rememberRead('SYN-V1', history([{ request_id: RID }]))
      expect(store.settleLatest('u1', 'SYN-V1')).toHaveLength(1)
      store.add('u1', intent({ request_id: 'again', state: 'UNKNOWN' }))
      expect(store.settleLatest('u1', 'SYN-V1')).toEqual([]) // consumed: never re-used
      expect(store.list('u1', 'SYN-V1')[0].state).toBe('UNKNOWN')
    })
  })

  it('acknowledgement removes only the client intent', () => {
    store.add('u1', intent({ state: 'UNKNOWN' }))
    store.add('u1', intent({ request_id: 'keep', state: 'UNKNOWN' }))
    store.acknowledge('u1', 'SYN-V1', RID)
    expect(store.list('u1', 'SYN-V1').map((i) => i.request_id)).toEqual(['keep'])
  })

  it('banner precedence: CONFLICT > RECORDED_PROJECTION_PENDING > UNKNOWN/UNCONFIRMED > SUBMITTING', () => {
    const of = (...states: PendingIntent['state'][]) => bannerState(states.map((state, n) => intent({ request_id: `r${n}`, state })))
    expect(of('SUBMITTING', 'UNKNOWN')).toBe('UNKNOWN')
    expect(of('UNCONFIRMED', 'RECORDED_PROJECTION_PENDING', 'SUBMITTING')).toBe('RECORDED_PROJECTION_PENDING')
    expect(of('RECORDED_PROJECTION_PENDING', 'CONFLICT')).toBe('CONFLICT')
    expect(of()).toBeNull()
  })

  it('two tabs: a late success in one tab after the other settled it is harmless (idempotent by request id)', () => {
    const tabB = new PendingStore(() => storage, () => NOW, 'tab-b')
    store.add('u1', intent({ state: 'UNKNOWN', prior_uncertain: true }))
    tabB.settle('u1', 'SYN-V1', history([{ request_id: RID }]))
    const late = store.applyResponse('u1', 'SYN-V1', RID, 'registration', applied)
    expect(late.found).toBe(false)
    expect(store.list('u1', 'SYN-V1')).toEqual([])
  })
})

// ---------------------------------------------------------------------------
// Dispatch: persisted before the request, never resent automatically (W-11)
// ---------------------------------------------------------------------------

describe('submit and explicit resend', () => {
  let storage: FakeStorage
  let store: PendingStore
  beforeEach(() => {
    storage = new FakeStorage()
    store = new PendingStore(() => storage, () => Date.now(), 'page-1')
  })
  afterEach(() => vi.unstubAllGlobals())

  it('writes the intent before fetch is called, sends its id, and removes it on a proven outcome', async () => {
    const seen: { stored: string | null; requestId: string | null; body: unknown }[] = []
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init: RequestInit) => {
      const headers = new Headers(init.headers)
      seen.push({ stored: storage.getItem(storageKey('u1', 'SYN-V1')), requestId: headers.get('X-Request-Id'), body: JSON.parse(String(init.body)) })
      const rid = headers.get('X-Request-Id') as string
      return new Response(JSON.stringify({ request_id: rid, changed: false, warnings: [] }), {
        status: 200, headers: { 'Content-Type': 'application/json', 'X-Request-Id': rid },
      })
    }))
    const body = { registration_no: ' กข 1 ', registration_province_code: null, expected_registration_no: null, expected_registration_province_code: null }
    const result = await submitRegistryIntent(store, { userId: 'u1', vehicleId: 'SYN-V1', operation: 'registration', body, routeEpoch: 3 })
    expect(seen).toHaveLength(1)
    const stored = JSON.parse(seen[0].stored as string) as PendingIntent[]
    expect(stored[0]).toMatchObject({ request_id: result.requestId, state: 'SUBMITTING', body, route_epoch: 3, page_instance: 'page-1' })
    expect(seen[0].requestId).toBe(result.requestId)
    expect(seen[0].body).toEqual(body) // exact text, not trimmed
    expect(result.classification).toMatchObject({ action: 'REMOVE', notice: 'CONFIRMED_NO_OP' })
    expect(store.list('u1', 'SYN-V1')).toEqual([])
  })

  it('an unknown outcome is kept, nothing is resent automatically, and an explicit resend reuses id and body', async () => {
    const fetchMock = vi.fn(async () => new Response('<html>bad gateway</html>', { status: 502 }))
    vi.stubGlobal('fetch', fetchMock)
    const body = { registration_no: '0012', registration_province_code: 'TH-21', expected_registration_no: null, expected_registration_province_code: null }
    const result = await submitRegistryIntent(store, { userId: 'u1', vehicleId: 'SYN-V1', operation: 'registration', body, routeEpoch: 0 })
    expect(result.classification).toMatchObject({ action: 'KEEP', state: 'UNKNOWN' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(fetchMock).toHaveBeenCalledTimes(1) // no automatic resend
    const kept = store.list('u1', 'SYN-V1')[0]
    expect(kept).toMatchObject({ request_id: result.requestId, body, state: 'UNKNOWN' })

    fetchMock.mockImplementation(async () =>
      new Response(JSON.stringify({ error: { code: 'VEHICLE_REGISTRY_STALE', message: 'x', details: null, request_id: result.requestId } }), {
        status: 409, headers: { 'Content-Type': 'application/json', 'X-Request-Id': result.requestId },
      }),
    )
    const resent = await resendRegistryIntent(store, 'u1', 'SYN-V1', result.requestId)
    const [, init] = fetchMock.mock.calls[1] as unknown as [string, RequestInit]
    expect(new Headers(init.headers).get('X-Request-Id')).toBe(result.requestId)
    expect(JSON.parse(String(init.body))).toEqual(body)
    expect(resent?.classification).toMatchObject({ action: 'KEEP', state: 'UNKNOWN', refused: true })
    expect(store.list('u1', 'SYN-V1')).toHaveLength(1) // a refused resend never proves the first attempt wrote nothing
  })

  it('a resend is refused for pending or conflicting intents', async () => {
    store.add('u1', intent({ state: 'RECORDED_PROJECTION_PENDING', prior_uncertain: true }))
    expect(await resendRegistryIntent(store, 'u1', 'SYN-V1', RID)).toBeNull()
    store.add('u1', intent({ request_id: 'c', state: 'CONFLICT', prior_uncertain: true }))
    expect(await resendRegistryIntent(store, 'u1', 'SYN-V1', 'c')).toBeNull()
  })

  it('a response for a vehicle that is no longer shown is still applied to its own intent (W-13)', async () => {
    let release!: (r: Response) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => { release = resolve })))
    const pending = submitRegistryIntent(store, { userId: 'u1', vehicleId: 'SYN-V1', operation: 'registration', body: { registration_no: 'a' }, routeEpoch: 1 })
    const [entry] = store.list('u1', 'SYN-V1')
    expect(store.isInflight(entry.request_id)).toBe(true)
    // meanwhile another view reads SYN-V1's history: the sender's in-flight intent is not judged
    store.settle('u1', 'SYN-V1', history([]))
    expect(store.list('u1', 'SYN-V1')[0].state).toBe('SUBMITTING')
    release(new Response(JSON.stringify({ request_id: entry.request_id, changed: false, warnings: [] }), {
      status: 200, headers: { 'Content-Type': 'application/json', 'X-Request-Id': entry.request_id },
    }))
    await pending
    expect(store.list('u1', 'SYN-V1')).toEqual([])
    expect(store.list('u1', 'SYN-V2')).toEqual([])
  })
})

// ---------------------------------------------------------------------------
// R1 fix 2: a late response is classified by the operation of the intent that
// sent it, even when that intent is already gone; it is never recreated.
// ---------------------------------------------------------------------------

describe('late response keeps its original operation', () => {
  let storage: FakeStorage
  let tabA: PendingStore
  let tabB: PendingStore
  beforeEach(() => {
    storage = new FakeStorage()
    tabA = new PendingStore(() => storage, () => Date.now(), 'tab-a')
    tabB = new PendingStore(() => storage, () => Date.now(), 'tab-b')
  })
  afterEach(() => vi.unstubAllGlobals())

  function deferredFetch() {
    const release: { fn?: (r: Response) => void } = {}
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => { release.fn = resolve })))
    return release
  }
  function coded(status: number, code: string, rid: string) {
    return new Response(JSON.stringify({ error: { code, message: code, details: null, request_id: rid } }), {
      status, headers: { 'Content-Type': 'application/json', 'X-Request-Id': rid },
    })
  }
  async function sendThenSettleElsewhere(operation: 'registration' | 'registration_reconcile') {
    const release = deferredFetch()
    const pending = submitRegistryIntent(tabA, { userId: 'u1', vehicleId: 'SYN-V1', operation, body: { mode: 'ACCEPT_MASTER' }, routeEpoch: 0 })
    const [entry] = tabA.list('u1', 'SYN-V1')
    // another tab settles it (it is not in flight THERE)
    tabB.settle('u1', 'SYN-V1', history([{ request_id: entry.request_id }]))
    expect(tabA.list('u1', 'SYN-V1')).toEqual([])
    return { release, pending, rid: entry.request_id }
  }

  it('A: a registration late response after another tab settled it is harmless', async () => {
    const { release, pending, rid } = await sendThenSettleElsewhere('registration')
    release.fn?.(coded(409, 'VEHICLE_REGISTRY_STALE', rid))
    const result = await pending
    expect(result.found).toBe(false)
    expect(result.classification).toMatchObject({ action: 'KEEP', state: 'UNKNOWN', refused: true, errorCode: 'VEHICLE_REGISTRY_STALE' })
    expect(storage.data.has(storageKey('u1', 'SYN-V1'))).toBe(false) // not recreated
  })

  it('B/C: a registration_reconcile late response is classified by reconcile rules (409 MASTER_PAIR_INVALID)', async () => {
    const { release, pending, rid } = await sendThenSettleElsewhere('registration_reconcile')
    release.fn?.(coded(409, 'MASTER_PAIR_INVALID', rid))
    const result = await pending
    expect(result.found).toBe(false)
    // recognised as a proven refusal of THIS operation (reported, never a removal)
    expect(result.classification).toMatchObject({ action: 'KEEP', state: 'UNKNOWN', refused: true, errorCode: 'MASTER_PAIR_INVALID' })
    expect(tabA.list('u1', 'SYN-V1')).toEqual([])
  })

  it('C (contrast): the same code on a registration late response is not a refusal', async () => {
    const { release, pending, rid } = await sendThenSettleElsewhere('registration')
    release.fn?.(coded(409, 'MASTER_PAIR_INVALID', rid))
    const result = await pending
    expect(result.classification.refused).toBeUndefined()
    expect(result.classification).toMatchObject({ action: 'KEEP', state: 'UNKNOWN' })
  })

  it('D: a registration-only code never becomes a registration_reconcile refusal', async () => {
    const { release, pending, rid } = await sendThenSettleElsewhere('registration_reconcile')
    release.fn?.(coded(422, 'REGISTRATION_TEXT_INVALID', rid))
    const result = await pending
    expect(result.classification.refused).toBeUndefined()
    expect(result.classification).toMatchObject({ action: 'KEEP', state: 'UNKNOWN' })
  })

  it('direct call: applyResponse uses the supplied operation for a missing intent', () => {
    const response = envelope(409, 'MASTER_PAIR_INVALID')
    expect(tabA.applyResponse('u1', 'SYN-V1', RID, 'registration_reconcile', response)).toMatchObject({
      found: false, classification: { refused: true },
    })
    expect(tabA.applyResponse('u1', 'SYN-V1', RID, 'registration', response).classification.refused).toBeUndefined()
    expect(storage.data.size).toBe(0)
  })

  it('E: acknowledgement while the request is in flight is never undone by the late response', async () => {
    const release = deferredFetch()
    const pending = submitRegistryIntent(tabA, { userId: 'u1', vehicleId: 'SYN-V1', operation: 'registration_reconcile', body: { mode: 'APPLY_RECORDED' }, routeEpoch: 0 })
    const [entry] = tabA.list('u1', 'SYN-V1')
    tabB.acknowledge('u1', 'SYN-V1', entry.request_id) // another tab acknowledges it
    tabB.add('u1', intent({ request_id: 'other-intent', state: 'UNKNOWN', prior_uncertain: true }))
    release.fn?.(new Response(JSON.stringify({
      request_id: entry.request_id, changed: true, master_write: 'WRITTEN', warnings: [],
      change: { change_id: 'VRH-1', recorded_at: 'x', request_id: entry.request_id },
    }), { status: 200, headers: { 'Content-Type': 'application/json', 'X-Request-Id': entry.request_id } }))
    const result = await pending
    expect(result.found).toBe(false)
    expect(result.classification).toMatchObject({ action: 'KEEP', state: 'UNKNOWN' }) // after uncertainty: never a removal
    expect(tabA.list('u1', 'SYN-V1').map((i) => i.request_id)).toEqual(['other-intent']) // not recreated, other intact
    expect(tabA.isInflight(entry.request_id)).toBe(false)
  })
})
