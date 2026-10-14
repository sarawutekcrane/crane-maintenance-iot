import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { MutationResponse } from './apiClient'
import { serverSignalsFrom } from './serverSignals'
import {
  assignmentModelOf,
  buildAssignmentBody,
  classifyAssignmentResponse,
  dismissAssignmentIntent,
  fetchAllTechnicians,
  pendingAssignmentIntent,
  resendAssignment,
  selectionProblem,
  startAssignment,
  TECHNICIAN_MAX_PAGES,
  type AssignmentSet,
} from './technicianV2'

const RID = 'req-1'
const http = (status: number, json: unknown, headerRequestId: string | null = 'hdr-1'): MutationResponse => ({
  kind: 'http',
  status,
  headerRequestId,
  json,
})
const err = (code: string, details: Record<string, unknown> = {}) => ({ error: { code, message: 'x', details } })

const CURRENT: AssignmentSet = {
  assignment_set_id: 'SET-1',
  assigned_at: '2026-01-01T00:00:00Z',
  assigned_by_user_id: 'SYN-USER',
  primary_technician_id: 'TEC-A',
  collaborator_technician_ids: ['TEC-B'],
  reason_th: null,
  record_ids: ['R1', 'R2'],
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

describe('serverSignalsFrom (fail closed)', () => {
  it('enables V2 only for an exact boolean true with a known context', () => {
    expect(serverSignalsFrom({ user_id: 'u', roles: [], capabilities: [], technician_assignment_v2_enabled: true, data_context: 'TEST' }))
      .toEqual({ v2Enabled: true, dataContext: 'TEST', ok: true })
    expect(serverSignalsFrom({ user_id: 'u', roles: [], capabilities: [], technician_assignment_v2_enabled: false, data_context: 'REAL' }))
      .toEqual({ v2Enabled: false, dataContext: 'REAL', ok: true })
  })

  it.each([
    ['missing flag', { data_context: 'TEST' }],
    ['string "true"', { technician_assignment_v2_enabled: 'true', data_context: 'TEST' }],
    ['number 1', { technician_assignment_v2_enabled: 1, data_context: 'TEST' }],
    ['null flag', { technician_assignment_v2_enabled: null, data_context: 'TEST' }],
    ['missing context', { technician_assignment_v2_enabled: true }],
    ['lower-case context', { technician_assignment_v2_enabled: true, data_context: 'test' }],
  ])('%s → V2 disabled', (_name, extra) => {
    const signals = serverSignalsFrom({ user_id: 'u', roles: [], capabilities: [], ...extra })
    expect(signals.v2Enabled).toBe(false)
    expect(signals.ok).toBe(false)
  })

  it('never reports REAL unless the server said exactly REAL', () => {
    for (const value of ['real', 'REAL ', 'PRODUCTION', '', null, undefined, 1]) {
      const signals = serverSignalsFrom({ user_id: 'u', roles: [], capabilities: [], technician_assignment_v2_enabled: true, data_context: value })
      expect(signals.dataContext).toBe('UNKNOWN')
    }
    expect(serverSignalsFrom({ user_id: 'u', roles: [], capabilities: [], technician_assignment_v2_enabled: false, data_context: 'UNCONFIGURED' }).dataContext)
      .toBe('UNCONFIGURED')
    expect(serverSignalsFrom(null)).toEqual({ v2Enabled: false, dataContext: 'UNKNOWN', ok: false })
  })
})

describe('assignmentModelOf', () => {
  it('accepts only the two exact markers', () => {
    expect(assignmentModelOf('TECHNICIAN_V2')).toBe('TECHNICIAN_V2')
    expect(assignmentModelOf('LEGACY')).toBe('LEGACY')
    for (const value of ['INVALID', 'technician_v2', '', null, undefined, 'V2']) expect(assignmentModelOf(value)).toBe('INVALID')
  })
})

describe('selectionProblem / buildAssignmentBody', () => {
  const listed = new Set(['TEC-A', 'TEC-B', 'TEC-C'])
  it('requires exactly one PRIMARY, no duplicate, PRIMARY not a COLLABORATOR, listed ids only', () => {
    expect(selectionProblem('', [], listed)?.code).toBe('PRIMARY_REQUIRED')
    expect(selectionProblem('TEC-A', ['TEC-B', 'TEC-B'], listed)?.code).toBe('DUPLICATE_ASSIGNEE')
    expect(selectionProblem('TEC-A', ['TEC-A'], listed)?.code).toBe('PRIMARY_AS_COLLABORATOR')
    expect(selectionProblem('Somchai', [], listed)?.code).toBe('UNKNOWN_TECHNICIAN')
    expect(selectionProblem('TEC-A', ['USR-1'], listed)?.code).toBe('UNKNOWN_TECHNICIAN')
    expect(selectionProblem('TEC-A', ['TEC-B', 'TEC-C'], listed)).toBeNull()
  })

  it('always sends the exact expected_current (null when there is no current set)', () => {
    expect(buildAssignmentBody('TEC-A', [], null, '')).toEqual({
      primary_technician_id: 'TEC-A',
      collaborator_technician_ids: [],
      expected_current: null,
    })
    expect(buildAssignmentBody('TEC-C', ['TEC-A'], CURRENT, '  เปลี่ยนกะ ')).toEqual({
      primary_technician_id: 'TEC-C',
      collaborator_technician_ids: ['TEC-A'],
      expected_current: { primary_technician_id: 'TEC-A', collaborator_technician_ids: ['TEC-B'] },
      reason_th: 'เปลี่ยนกะ',
    })
  })

  it('never carries a legacy technician field', () => {
    const body = buildAssignmentBody('TEC-A', ['TEC-B'], CURRENT, 'r') as unknown as Record<string, unknown>
    for (const legacy of ['primary_technician', 'collaborators', 'user_id', 'technician_name']) expect(body).not.toHaveProperty(legacy)
  })
})

describe('classifyAssignmentResponse', () => {
  it('200 changed / no-op / replayed are proven', () => {
    expect(classifyAssignmentResponse(http(200, { request_id: RID, changed: true, record_ids: [], current: CURRENT }), RID).kind).toBe('changed')
    expect(classifyAssignmentResponse(http(200, { request_id: RID, changed: false }), RID).kind).toBe('no-op')
    expect(classifyAssignmentResponse(http(200, { request_id: RID, replayed: true, record_ids: [] }), RID).kind).toBe('replayed')
  })

  it('409 STALE is its own outcome (reload and reconfirm), never success', () => {
    expect(classifyAssignmentResponse(http(409, err('TECHNICIAN_ASSIGNMENT_STALE')), RID).kind).toBe('stale')
  })

  it.each([
    [403, 'HTTP_ERROR'],
    [404, 'REPAIR_NOT_FOUND'],
    [409, 'ASSIGNMENT_MODEL_MISMATCH'],
    [409, 'REQUEST_ID_REUSED'],
    [409, 'TECHNICIAN_ASSIGNMENT_ORDER_AMBIGUOUS'],
    [422, 'TECHNICIAN_SCOPE_UNPROVEN'],
    [422, 'TECHNICIAN_NOT_ACTIVE'],
    [500, 'TECHNICIAN_ASSIGNMENT_DATA_INVALID'],
    [500, 'ASSIGNMENT_MODEL_DATA_INVALID'],
    [503, 'REGISTRY_DATA_CONTEXT_NOT_CONFIGURED'],
    [503, 'TECHNICIAN_ASSIGNMENT_READ_FAILED'],
  ])('%i %s is a proven refusal with its code and request id', (status, code) => {
    const result = classifyAssignmentResponse(http(status, err(code)), RID)
    expect(result).toMatchObject({ kind: 'refused', code, status, requestId: 'hdr-1' })
  })

  it('WRITE_FAILED rejected is a refusal; unknown stays UNKNOWN', () => {
    expect(classifyAssignmentResponse(http(503, err('TECHNICIAN_ASSIGNMENT_WRITE_FAILED', { write_outcome: 'rejected' })), RID).kind).toBe('refused')
    expect(classifyAssignmentResponse(http(503, err('TECHNICIAN_ASSIGNMENT_WRITE_FAILED', { write_outcome: 'unknown' })), RID))
      .toMatchObject({ kind: 'unknown', requestId: RID })
  })

  it('transport, unlisted 5xx, a non-envelope body and a 200 without a known shape are UNKNOWN, never success', () => {
    expect(classifyAssignmentResponse({ kind: 'transport', error: new Error('net') }, RID).kind).toBe('unknown')
    expect(classifyAssignmentResponse(http(500, err('INTERNAL_ERROR')), RID).kind).toBe('unknown')
    expect(classifyAssignmentResponse(http(502, null), RID).kind).toBe('unknown')
    expect(classifyAssignmentResponse(http(200, { ok: true }), RID).kind).toBe('unknown')
  })
})

describe('request intent (R2e pattern)', () => {
  let calls: { url: string; init: RequestInit }[]
  beforeEach(() => {
    calls = []
  })

  function stubFetch(responder: () => Response | Promise<Response>) {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init: RequestInit) => {
        calls.push({ url, init })
        return responder()
      }),
    )
  }

  const body = buildAssignmentBody('TEC-A', ['TEC-B'], null, '')

  it('stores the intent before sending and clears it on a proven outcome', async () => {
    let seenDuringSend: unknown = 'not-checked'
    stubFetch(() => {
      seenDuringSend = pendingAssignmentIntent('SYN-USER', 'REPAIR', 'RPR-1')
      return jsonResponse({ request_id: 'x', changed: true, record_ids: [], current: CURRENT })
    })
    const result = await startAssignment('SYN-USER', 'REPAIR', 'RPR-1', body)
    expect(result.kind).toBe('changed')
    expect(seenDuringSend).toMatchObject({ body })
    expect(pendingAssignmentIntent('SYN-USER', 'REPAIR', 'RPR-1')).toBeNull()
    expect(calls[0].url).toBe('/api/v1/repairs/RPR-1/technician-assignments')
    expect(calls[0].init.method).toBe('POST')
    expect(JSON.parse(String(calls[0].init.body))).toEqual(body)
    expect((calls[0].init.headers as Record<string, string>)['X-Request-Id']).toBeTruthy()
  })

  it('keeps the intent on an unknown outcome and resends the SAME id and body, never automatically', async () => {
    stubFetch(() => Promise.reject(new TypeError('network down')))
    const first = await startAssignment('SYN-USER', 'PM', 'PMWO-1', body)
    expect(first.kind).toBe('unknown')
    expect(calls).toHaveLength(1) // no automatic retry
    const intent = pendingAssignmentIntent('SYN-USER', 'PM', 'PMWO-1')
    expect(intent).not.toBeNull()
    stubFetch(() => jsonResponse({ request_id: intent!.requestId, replayed: true, record_ids: [] }))
    const second = await resendAssignment('SYN-USER', 'PM', 'PMWO-1')
    expect(second?.kind).toBe('replayed')
    expect(calls[1].url).toBe('/api/v1/pm/work-orders/PMWO-1/technician-assignments')
    expect((calls[1].init.headers as Record<string, string>)['X-Request-Id']).toBe(intent!.requestId)
    expect(JSON.parse(String(calls[1].init.body))).toEqual(intent!.body)
    expect(pendingAssignmentIntent('SYN-USER', 'PM', 'PMWO-1')).toBeNull()
  })

  it('a stale conflict clears the intent (nothing was written) and is not retried', async () => {
    stubFetch(() => jsonResponse(err('TECHNICIAN_ASSIGNMENT_STALE'), 409))
    const result = await startAssignment('SYN-USER', 'REPAIR', 'RPR-2', body)
    expect(result.kind).toBe('stale')
    expect(calls).toHaveLength(1)
    expect(pendingAssignmentIntent('SYN-USER', 'REPAIR', 'RPR-2')).toBeNull()
  })

  it('intents are per user, kind and job', () => {
    window.localStorage.setItem(
      'crane.technicianAssignmentPending.v1:SYN-USER:REPAIR:RPR-3',
      JSON.stringify({ requestId: 'r', body, createdAt: 'now' }),
    )
    expect(pendingAssignmentIntent('SYN-USER', 'REPAIR', 'RPR-3')?.requestId).toBe('r')
    expect(pendingAssignmentIntent('OTHER', 'REPAIR', 'RPR-3')).toBeNull()
    expect(pendingAssignmentIntent('SYN-USER', 'PM', 'RPR-3')).toBeNull()
    dismissAssignmentIntent('SYN-USER', 'REPAIR', 'RPR-3')
    expect(pendingAssignmentIntent('SYN-USER', 'REPAIR', 'RPR-3')).toBeNull()
  })
})

describe('fetchAllTechnicians', () => {
  const tech = (n: number) => ({ technician_id: `TEC-${n}`, first_name: 'ช่าง', last_name: String(n), active_status: 'ACTIVE' })

  it('walks the existing page / page_size parameters only', async () => {
    const urls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        urls.push(url)
        const page = Number(new URL(url, 'http://x').searchParams.get('page'))
        const items = page === 1 ? Array.from({ length: 200 }, (_, i) => tech(i)) : [tech(200)]
        return jsonResponse({ items, page, page_size: 200, total_items: 201 })
      }),
    )
    const result = await fetchAllTechnicians()
    expect(result.ok && result.data.length).toBe(201)
    expect(urls).toEqual(['/api/v1/technicians?page=1&page_size=200', '/api/v1/technicians?page=2&page_size=200'])
  })

  it('a failed page fails the whole read (never a partial picker)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) =>
        url.includes('page=1')
          ? jsonResponse({ items: [tech(1)], page: 1, page_size: 200, total_items: 300 })
          : jsonResponse(err('REGISTRY_DATA_CONTEXT_NOT_CONFIGURED'), 503),
      ),
    )
    const result = await fetchAllTechnicians()
    expect(result.ok).toBe(false)
  })

  it('a total that never completes is bounded and fails closed', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ items: [tech(1)], page: 1, page_size: 200, total_items: 10 ** 9 }))
    vi.stubGlobal('fetch', fetchMock)
    const result = await fetchAllTechnicians()
    expect(result.ok).toBe(false)
    expect(fetchMock).toHaveBeenCalledTimes(TECHNICIAN_MAX_PAGES)
  })
})
