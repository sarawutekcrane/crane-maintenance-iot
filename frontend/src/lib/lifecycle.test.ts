import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  classifyLifecycleResponse,
  pendingLifecycleIntent,
  resendLifecycleAction,
  startLifecycleAction,
} from './lifecycle'

const RID = '11111111-2222-4333-8444-555555555555'

function http(status: number, json: unknown) {
  return { kind: 'http' as const, status, headerRequestId: RID, json }
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('R2e lifecycle request bookkeeping', () => {
  beforeEach(() => window.localStorage.clear())
  afterEach(() => vi.unstubAllGlobals())

  it('classifies proven outcomes and keeps uncertainty as unknown', () => {
    expect(classifyLifecycleResponse(http(200, { changed: true }), RID).kind).toBe('changed')
    expect(classifyLifecycleResponse(http(200, { changed: false }), RID).kind).toBe('no-op')
    expect(classifyLifecycleResponse(http(200, { replayed: true, record_ids: [] }), RID).kind).toBe('replayed')
    const stale = classifyLifecycleResponse(http(409, { error: { code: 'PERSONNEL_LIFECYCLE_STALE' } }), RID)
    expect(stale).toMatchObject({ kind: 'stale', message: 'ข้อมูลถูกเปลี่ยนโดยผู้ใช้อื่น กรุณาโหลดข้อมูลล่าสุดก่อนดำเนินการอีกครั้ง' })
    expect(classifyLifecycleResponse(http(403, { error: { code: 'HTTP_ERROR' } }), RID).kind).toBe('refused')
    const rejected = http(503, { error: { code: 'PERSONNEL_LIFECYCLE_HISTORY_WRITE_FAILED', details: { history_write_outcome: 'rejected' } } })
    expect(classifyLifecycleResponse(rejected, RID).kind).toBe('refused')
    const unknown = http(503, { error: { code: 'PERSONNEL_LIFECYCLE_HISTORY_WRITE_FAILED', details: { history_write_outcome: 'unknown' } } })
    expect(classifyLifecycleResponse(unknown, RID).kind).toBe('unknown')
    const recorded = http(503, { error: { code: 'DEPARTMENT_LIFECYCLE_STATE_WRITE_FAILED', details: { event_recorded: true } } })
    expect(classifyLifecycleResponse(recorded, RID).kind).toBe('recorded-state-pending')
    expect(classifyLifecycleResponse(http(500, { error: { code: 'INTERNAL_ERROR' } }), RID).kind).toBe('unknown')
    expect(classifyLifecycleResponse({ kind: 'transport', error: new Error('x') }, RID).kind).toBe('unknown')
  })

  it('stores the intent before sending, keeps it on an unknown outcome, and resends the SAME request id', async () => {
    const seen: Array<{ rid: string | null; body: string; storedBefore: boolean }> = []
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init: RequestInit) => {
      seen.push({
        rid: new Headers(init.headers).get('X-Request-Id'),
        body: String(init.body),
        storedBefore: pendingLifecycleIntent('u1', 'personnel', 'P1') !== null,
      })
      return seen.length === 1 ? new Response('', { status: 502 }) : jsonResponse({ changed: true })
    }))
    const body = { expected_active_status: 'ACTIVE', reason_th: 'ทดสอบ' }
    const first = await startLifecycleAction('u1', 'personnel', 'P1', 'deactivations', body)
    expect(first.kind).toBe('unknown')
    expect(seen[0].storedBefore).toBe(true)
    const kept = pendingLifecycleIntent('u1', 'personnel', 'P1')
    expect(kept?.requestId).toBe(seen[0].rid)
    expect(fetch).toHaveBeenCalledTimes(1) // never retried automatically
    const again = await resendLifecycleAction('u1', 'personnel', 'P1')
    expect(again?.kind).toBe('changed')
    expect(seen[1].rid).toBe(seen[0].rid)
    expect(seen[1].body).toBe(seen[0].body)
    expect(pendingLifecycleIntent('u1', 'personnel', 'P1')).toBeNull()
  })

  it('classifies a lifecycle MISMATCH as its own outcome for both entities (review fix R2)', () => {
    for (const code of ['PERSONNEL_LIFECYCLE_MISMATCH', 'DEPARTMENT_LIFECYCLE_MISMATCH']) {
      const result = classifyLifecycleResponse(http(409, { error: { code } }), RID)
      expect(result).toMatchObject({ kind: 'mismatch', code })
      expect(result.kind).not.toBe('stale')
    }
    // STALE stays stale, and a consistent replay stays a proven completed replay
    expect(classifyLifecycleResponse(http(409, { error: { code: 'DEPARTMENT_LIFECYCLE_STALE' } }), RID).kind).toBe('stale')
    expect(classifyLifecycleResponse(http(200, { replayed: true, record_ids: ['x'] }), RID).kind).toBe('replayed')
  })

  it('unknown -> same-id resend -> MISMATCH clears the pending intent (department)', async () => {
    const ids: Array<string | null> = []
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init: RequestInit) => {
      ids.push(new Headers(init.headers).get('X-Request-Id'))
      return ids.length === 1
        ? new Response('', { status: 502 })
        : jsonResponse({ error: { code: 'DEPARTMENT_LIFECYCLE_MISMATCH' } }, 409)
    }))
    const first = await startLifecycleAction('u1', 'departments', 'D1', 'deactivations', { expected_is_active: true })
    expect(first.kind).toBe('unknown')
    expect(pendingLifecycleIntent('u1', 'departments', 'D1')).not.toBeNull()
    const again = await resendLifecycleAction('u1', 'departments', 'D1')
    expect(again?.kind).toBe('mismatch')
    expect(ids[1]).toBe(ids[0])
    expect(pendingLifecycleIntent('u1', 'departments', 'D1')).toBeNull()
  })

  it('removes the intent on a proven refusal', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ error: { code: 'PERSONNEL_LIFECYCLE_STALE' } }, 409)))
    const result = await startLifecycleAction('u1', 'personnel', 'P1', 'deactivations', {})
    expect(result.kind).toBe('stale')
    expect(pendingLifecycleIntent('u1', 'personnel', 'P1')).toBeNull()
  })
})
