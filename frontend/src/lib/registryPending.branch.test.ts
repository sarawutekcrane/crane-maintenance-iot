import { afterEach, describe, expect, it, vi } from 'vitest'
import type { MutationResponse } from './apiClient'
import allowlist from './registryOutcomeAllowlist.json'
import {
  type BranchOperation,
  classifyResponse,
  isAllowlisted,
  mutationPath,
  operationFamily,
  type PendingIntent,
  PendingStore,
  resendRegistryIntent,
  storageKey,
  submitRegistryIntent,
  ZERO_WRITE_ALLOWLIST,
} from './registryPending'
import type { BranchHistory, RegistrationHistory } from './types'

// Phase 7 Batch 7O2c — branch operations in the registry bookkeeping
// (contract Final Rev2 §10.3-§10.4; Outcome Classification Addendum A.2,
// W-OC-01..07 for the five branch operations; NOT_DETERMINED; family-scoped
// settlement). Synthetic data only.

const RID = '11111111-2222-4333-8444-555555555555'
const RID2 = '22222222-2222-4333-8444-555555555555'
const NOW = Date.parse('2026-10-05T03:00:00Z')
const OPS: BranchOperation[] = ['transfer', 'insertion', 'correction', 'cancellation', 'reconcile']

function http(status: number, json: unknown, header: string | null = RID): MutationResponse {
  return { kind: 'http', status, headerRequestId: header, json }
}
function envelope(status: number, code: string, details: Record<string, unknown> | null = null, rid = RID) {
  return http(status, { error: { code, message: code, details, request_id: rid } })
}
function changed(projection: string, extra: Record<string, unknown> = {}) {
  return http(200, {
    request_id: RID, changed: true, record_id: 'ABH-' + 'c'.repeat(32), event_id: 'ABH-' + 'c'.repeat(32),
    projection_write: projection, timeline_status_after: 'VALID', current_branch_id: 'BR-RAYONG', consistency: 'CONSISTENT',
    ...extra,
  })
}
const label = (c: ReturnType<typeof classifyResponse>) => `${c.action}:${c.action === 'REMOVE' ? c.notice : c.state}`

class FakeStorage implements Storage {
  data = new Map<string, string>()
  get length() {
    return this.data.size
  }
  clear() {
    this.data.clear()
  }
  getItem(key: string) {
    return this.data.get(key) ?? null
  }
  key(index: number) {
    return [...this.data.keys()][index] ?? null
  }
  removeItem(key: string) {
    this.data.delete(key)
  }
  setItem(key: string, value: string) {
    this.data.set(key, value)
  }
}

function intent(overrides: Partial<PendingIntent> = {}): PendingIntent {
  return {
    request_id: RID, operation: 'transfer', vehicle_id: 'SYN-V1',
    body: { to_branch_id: 'BR-RAYONG', effective: { mode: 'NOW' }, expected_current_branch_id: null, expected_history_revision: 'BHR1-0' },
    submitted_at: new Date(NOW).toISOString(), state: 'UNKNOWN', page_instance: 'p1', route_epoch: 0, prior_uncertain: true,
    ...overrides,
  }
}

function branchHistory(requestIds: string[], consistency: BranchHistory['consistency'] = 'CONSISTENT', related: string | null = null): BranchHistory {
  return {
    asset_type: 'VEHICLE', asset_id: 'SYN-V1', timeline_status: 'VALID', current: { branch_id: 'BR-RAYONG', source: 'EVENT' },
    master: { state: 'RECORDED', value: 'BR-RAYONG' }, consistency, history_revision: 'BHR1-x', baseline: null, events: [],
    records: requestIds.map((rid, n) => ({
      record_id: `ABH-${n}`, record_kind: 'ASSIGNMENT', entry_operation: 'TRANSFER', event_id: `ABH-${n}`, revision_no: 1,
      supersedes_record_id: null, branch_id: 'BR-RAYONG', effective_at: '2026-09-01T00:00:00+00:00', recorded_from_branch_id: null,
      recorded_from_source: 'NONE', recorded_at: '2026-10-05T00:00:00+00:00', recorded_by: 'u', request_id: rid,
      related_request_id: related, reason_th: null, reconciled_old_master_branch_id: null,
    })),
    excluded_test_rows: 0, issues: {},
  } as BranchHistory
}

function registrationHistory(requestIds: string[]): RegistrationHistory {
  return {
    vehicle_id: 'SYN-V1',
    current: { registration_no: { state: 'NOT_RECORDED', value: null }, registration_province: { state: 'NOT_RECORDED', value: null } },
    consistency: 'CONSISTENT', history_revision: 'RHR1-0', excluded_test_rows: 0, issues: {},
    items: requestIds.map((rid, n) => ({
      change_id: `VRH-${n}`, change_kind: 'CHANGE', old_registration_no: null, old_registration_province_code: null,
      new_registration_no: 'x', new_registration_province_code: null, recorded_at: '2026-10-05T00:00:00+00:00',
      recorded_by: 'u', request_id: rid, related_request_id: null, accepted_exceptions: [], note_th: null,
    })),
  } as RegistrationHistory
}

afterEach(() => vi.unstubAllGlobals())

describe('branch operations in the shared allowlist', () => {
  it('each branch table is exactly the shared JSON table and the families stay apart', () => {
    const data = allowlist as unknown as Record<string, [number, string][]>
    for (const op of OPS) {
      expect(operationFamily(op)).toBe('branch')
      expect([...ZERO_WRITE_ALLOWLIST[op]].sort()).toEqual(data[op].map(([s, c]) => `${s}:${c}`).sort())
      expect(isAllowlisted(op, 403, 'HTTP_ERROR')).toBe(true)
      for (const code of ['BRANCH_HISTORY_WRITE_FAILED', 'BRANCH_PROJECTION_WRITE_FAILED', 'REQUEST_ID_REUSED', 'INTERNAL_ERROR']) {
        expect([...ZERO_WRITE_ALLOWLIST[op]].some((pair) => pair.endsWith(`:${code}`))).toBe(false)
      }
    }
    expect(operationFamily('registration')).toBe('registration')
    expect(operationFamily('registration_reconcile')).toBe('registration')
    // C-c1 / C-c2: an ambiguity refusal of an edit is a proven zero-write outcome
    expect(isAllowlisted('correction', 409, 'BRANCH_TIMELINE_AMBIGUOUS')).toBe(true)
    expect(isAllowlisted('cancellation', 409, 'BRANCH_TIMELINE_AMBIGUOUS')).toBe(true)
    // a registration code is not a branch outcome, and the reverse
    expect(isAllowlisted('transfer', 409, 'REGISTRATION_DUPLICATE')).toBe(false)
    expect(isAllowlisted('registration', 409, 'BRANCH_HISTORY_STALE')).toBe(false)
    expect(isAllowlisted('transfer', 422, 'REASON_REQUIRED')).toBe(false) // transfer has no reason rule
  })

  it('paths: the event id is part of the correction and cancellation path', () => {
    expect(mutationPath('transfer', 'V 1')).toEqual({ path: '/vehicles/V%201/branch-transfers', method: 'POST' })
    expect(mutationPath('insertion', 'V1')).toEqual({ path: '/vehicles/V1/branch-history/insertions', method: 'POST' })
    expect(mutationPath('correction', 'V1', 'ABH-1')).toEqual({ path: '/vehicles/V1/branch-history/events/ABH-1/corrections', method: 'POST' })
    expect(mutationPath('cancellation', 'V1', 'ABH-1')).toEqual({ path: '/vehicles/V1/branch-history/events/ABH-1/cancellations', method: 'POST' })
    expect(mutationPath('reconcile', 'V1')).toEqual({ path: '/vehicles/V1/branch-projection/reconciliations', method: 'POST' })
  })
})

describe('classifyResponse — branch rows (W-OC-01, W-OC-04..07, NOT_DETERMINED)', () => {
  const rows: [string, MutationResponse, string, string][] = [
    ['200 changed WRITTEN', changed('WRITTEN'), 'REMOVE:CONFIRMED_APPLIED', 'KEEP:UNKNOWN'],
    ['200 changed NOT_NEEDED', changed('NOT_NEEDED'), 'REMOVE:CONFIRMED_APPLIED', 'KEEP:UNKNOWN'],
    ['200 changed NOT_DETERMINED', changed('NOT_DETERMINED', { timeline_status_after: 'AMBIGUOUS_ORDER', consistency: 'UNDETERMINED' }),
      'KEEP:RECORDED_PROJECTION_PENDING', 'KEEP:RECORDED_PROJECTION_PENDING'],
    ['200 changed without record id', changed('WRITTEN', { record_id: '' }), 'KEEP:UNKNOWN', 'KEEP:UNKNOWN'],
    ['200 changed unknown projection value', changed('MAYBE'), 'KEEP:UNKNOWN', 'KEEP:UNKNOWN'],
    ['200 registration-shaped body', http(200, { request_id: RID, changed: true, master_write: 'WRITTEN', change: { change_id: 'VRH-1' } }), 'KEEP:UNKNOWN', 'KEEP:UNKNOWN'],
    ['200 no-op', http(200, { request_id: RID, changed: false, warnings: [] }), 'REMOVE:CONFIRMED_NO_OP', 'KEEP:UNKNOWN'],
    ['200 replayed', http(200, { request_id: RID, replayed: true, record_ids: ['ABH-1'], consistency: 'CONSISTENT' }), 'KEEP:UNKNOWN', 'KEEP:UNKNOWN'],
    ['200 header mismatch', http(200, (changed('WRITTEN') as { json: unknown }).json, RID2), 'KEEP:UNKNOWN', 'KEEP:UNKNOWN'],
    ['allowlisted 409 stale', envelope(409, 'BRANCH_HISTORY_STALE', { field: 'history_revision' }), 'REMOVE:CONFIRMED_ZERO_WRITE', 'KEEP:UNKNOWN'],
    ['W1 rejected', envelope(503, 'BRANCH_HISTORY_WRITE_FAILED', { history_write_outcome: 'rejected', projection_write: 'NOT_ATTEMPTED', request_id: RID }),
      'REMOVE:CONFIRMED_ZERO_WRITE', 'KEEP:UNKNOWN'],
    ['W1 unknown', envelope(503, 'BRANCH_HISTORY_WRITE_FAILED', { history_write_outcome: 'unknown' }), 'KEEP:UNKNOWN', 'KEEP:UNKNOWN'],
    ['W2 failed with record', envelope(503, 'BRANCH_PROJECTION_WRITE_FAILED', { event_recorded: true, record_id: 'ABH-1', projection_write_outcome: 'unknown' }),
      'KEEP:RECORDED_PROJECTION_PENDING', 'KEEP:RECORDED_PROJECTION_PENDING'],
    ['W2 failed without record id', envelope(503, 'BRANCH_PROJECTION_WRITE_FAILED', { event_recorded: true }), 'KEEP:UNKNOWN', 'KEEP:UNKNOWN'],
    ['registration W1 code on a branch operation', envelope(503, 'REGISTRATION_HISTORY_WRITE_FAILED', { history_write_outcome: 'rejected' }), 'KEEP:UNKNOWN', 'KEEP:UNKNOWN'],
    ['409 REQUEST_ID_REUSED', envelope(409, 'REQUEST_ID_REUSED'), 'KEEP:CONFLICT', 'KEEP:CONFLICT'],
    ['500 INTERNAL_ERROR', envelope(500, 'INTERNAL_ERROR'), 'KEEP:UNKNOWN', 'KEEP:UNKNOWN'],
    ['transport', { kind: 'transport', error: new Error('network') }, 'KEEP:UNKNOWN', 'KEEP:UNKNOWN'],
  ]
  for (const op of OPS) {
    for (const [name, response, firstExpected, afterExpected] of rows) {
      it(`${op}: ${name}`, () => {
        const first = { request_id: RID, operation: op, prior_uncertain: false }
        expect(label(classifyResponse(response, first))).toBe(firstExpected)
        expect(label(classifyResponse(response, { ...first, prior_uncertain: true }))).toBe(afterExpected)
      })
    }
  }
  it('a branch W2 shape on a registration operation proves nothing', () => {
    const first = { request_id: RID, operation: 'registration' as const, prior_uncertain: false }
    expect(label(classifyResponse(envelope(503, 'BRANCH_PROJECTION_WRITE_FAILED', { event_recorded: true, record_id: 'ABH-1' }), first))).toBe('KEEP:UNKNOWN')
    expect(label(classifyResponse(changed('WRITTEN'), first))).toBe('KEEP:UNKNOWN')
  })
})

describe('family-scoped settlement', () => {
  function seeded() {
    const storage = new FakeStorage()
    const store = new PendingStore(() => storage, () => NOW, 'page-1')
    store.add('u1', intent({ request_id: RID, operation: 'transfer' }))
    store.add('u1', intent({ request_id: RID2, operation: 'registration', body: { registration_no: 'x' } }))
    return { storage, store }
  }

  it('a registration-history read judges only registration intents', () => {
    const { store } = seeded()
    store.settle('u1', 'SYN-V1', registrationHistory([]))
    const byId = Object.fromEntries(store.list('u1', 'SYN-V1').map((i) => [i.request_id, i.state]))
    expect(byId).toEqual({ [RID]: 'UNKNOWN', [RID2]: 'UNCONFIRMED' })
  })

  it('a branch-history read judges only branch intents', () => {
    const { store } = seeded()
    store.settleBranch('u1', 'SYN-V1', branchHistory([]))
    const byId = Object.fromEntries(store.list('u1', 'SYN-V1').map((i) => [i.request_id, i.state]))
    expect(byId).toEqual({ [RID]: 'UNCONFIRMED', [RID2]: 'UNKNOWN' })
    // a registration read containing the branch request id settles nothing of the branch family
    store.settle('u1', 'SYN-V1', registrationHistory([RID]))
    expect(store.list('u1', 'SYN-V1', 'branch').map((i) => i.state)).toEqual(['UNCONFIRMED'])
  })

  it('own record + PROJECTION_MISMATCH or UNDETERMINED keeps RECORDED_PROJECTION_PENDING; CONSISTENT removes with a notice', () => {
    for (const consistency of ['PROJECTION_MISMATCH', 'UNDETERMINED'] as const) {
      const { store } = seeded()
      expect(store.settleBranch('u1', 'SYN-V1', branchHistory([RID], consistency))).toEqual([])
      expect(store.list('u1', 'SYN-V1', 'branch')[0].state).toBe('RECORDED_PROJECTION_PENDING')
    }
    const { store } = seeded()
    const notices = store.settleBranch('u1', 'SYN-V1', branchHistory(['other', RID], 'CONSISTENT'))
    expect(notices).toEqual([{ request_id: RID, operation: 'transfer', intent: 'RECORDED' }])
    expect(store.notices('u1', 'SYN-V1', 'branch')).toEqual(notices)
    expect(store.notices('u1', 'SYN-V1', 'registration')).toEqual([])
    expect(store.list('u1', 'SYN-V1', 'branch')).toEqual([])
    expect(store.list('u1', 'SYN-V1', 'registration')).toHaveLength(1) // untouched
  })

  it('a later record of the vehicle reports RECORDED_LATER_CHANGED', () => {
    const { store } = seeded()
    expect(store.settleBranch('u1', 'SYN-V1', branchHistory([RID, 'later']))[0].intent).toBe('RECORDED_LATER_CHANGED')
  })

  it('related_request_id settles nothing', () => {
    const { store } = seeded()
    store.settleBranch('u1', 'SYN-V1', branchHistory(['reconciliation-request'], 'CONSISTENT', RID))
    expect(store.list('u1', 'SYN-V1', 'branch')[0].state).toBe('UNCONFIRMED')
  })

  it('a failed read changes nothing; an in-flight or CONFLICT intent is not judged', () => {
    const { store } = seeded()
    expect(store.settleBranch('u1', 'SYN-V1', null)).toEqual([])
    expect(store.list('u1', 'SYN-V1', 'branch')[0].state).toBe('UNKNOWN')
    store.markInflight(RID, true)
    store.settleBranch('u1', 'SYN-V1', branchHistory([]))
    expect(store.list('u1', 'SYN-V1', 'branch')[0].state).toBe('UNKNOWN')
  })

  it('a branch read remembered before the user is known is judged by settleLatest', () => {
    const { store } = seeded()
    store.rememberBranchRead('SYN-V1', branchHistory([RID]))
    expect(store.settleLatest('u1', 'SYN-V1')).toEqual([{ request_id: RID, operation: 'transfer', intent: 'RECORDED' }])
    expect(store.settleLatest('u1', 'SYN-V1')).toEqual([]) // used once
  })

  it('both families share the one storage key per user and vehicle', () => {
    const { storage } = seeded()
    const stored = JSON.parse(storage.data.get(storageKey('u1', 'SYN-V1')) ?? '[]') as PendingIntent[]
    expect(stored.map((i) => i.operation)).toEqual(['transfer', 'registration'])
  })
})

describe('dispatch of branch intents', () => {
  it('a NOT_DETERMINED success stays pending and is never removed (W-OC with dispatch)', async () => {
    const storage = new FakeStorage()
    const store = new PendingStore(() => storage, () => NOW, 'page-1')
    let sent: { url: string; init: RequestInit } | null = null
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
      sent = { url, init }
      const rid = new Headers(init.headers).get('X-Request-Id') ?? ''
      return new Response(JSON.stringify({
        request_id: rid, changed: true, record_id: 'ABH-1', event_id: 'ABH-E', projection_write: 'NOT_DETERMINED',
        timeline_status_after: 'AMBIGUOUS_ORDER', current_branch_id: null, consistency: 'UNDETERMINED',
      }), { status: 200, headers: { 'Content-Type': 'application/json', 'X-Request-Id': rid } })
    }))
    const body = { reason_th: 'x', expected_history_revision: 'BHR1-1', expected_master_branch_id: 'BR-RAYONG' }
    const result = await submitRegistryIntent(store, { userId: 'u1', vehicleId: 'SYN-V1', operation: 'cancellation', eventId: 'ABH-E', body, routeEpoch: 0 })
    expect(sent!.url).toContain('/vehicles/SYN-V1/branch-history/events/ABH-E/cancellations')
    expect(JSON.parse(String(sent!.init.body))).toEqual(body)
    expect(label(result.classification)).toBe('KEEP:RECORDED_PROJECTION_PENDING')
    const [kept] = store.list('u1', 'SYN-V1', 'branch')
    expect(kept).toMatchObject({ request_id: result.requestId, state: 'RECORDED_PROJECTION_PENDING', event_id: 'ABH-E', prior_uncertain: true })
    // a pending intent is not resendable (the record exists)
    expect(await resendRegistryIntent(store, 'u1', 'SYN-V1', result.requestId)).toBeNull()
  })

  it('a resend uses the same id, the same body and the same event path', async () => {
    const storage = new FakeStorage()
    const store = new PendingStore(() => storage, () => NOW, 'page-1')
    store.add('u1', intent({ operation: 'correction', event_id: 'ABH-E', state: 'UNCONFIRMED', body: { reason_th: ' r ' } }))
    const seen: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
      seen.push(`${url} ${new Headers(init.headers).get('X-Request-Id')} ${String(init.body)}`)
      return new Response('{}', { status: 500 })
    }))
    await resendRegistryIntent(store, 'u1', 'SYN-V1', RID)
    expect(seen).toHaveLength(1)
    expect(seen[0]).toContain('/branch-history/events/ABH-E/corrections')
    expect(seen[0]).toContain(RID)
    expect(seen[0]).toContain('{"reason_th":" r "}')
  })
})
