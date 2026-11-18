import { describe, expect, it } from 'vitest'
import { classifyCrewResponse } from './crewWrites'

// R8 early workstream — crew write outcome classification (no duplicate submission,
// no lost response). Synthetic responses only.
function http(status: number, json: unknown) {
  return { kind: 'http' as const, status, headerRequestId: 'r', json }
}
const err = (code: string, details: Record<string, unknown> | null = null) => ({ error: { code, message: 'x', details } })

describe('classifyCrewResponse', () => {
  it('a changed, a no-op and a replayed answer are all settled successes', () => {
    expect(classifyCrewResponse(http(200, { changed: true, warnings: [{ code: 'PERSON_ADJACENT_ASSIGNMENT_REST_WARNING' }] })))
      .toEqual({ kind: 'success', changed: true, replayed: false, warnings: ['PERSON_ADJACENT_ASSIGNMENT_REST_WARNING'] })
    expect(classifyCrewResponse(http(200, { changed: false, existing_event_id: 'E' }))).toMatchObject({ kind: 'success', changed: false })
    expect(classifyCrewResponse(http(200, { replayed: true }))).toMatchObject({ kind: 'success', replayed: true })
  })

  it('a transport failure, an unknown write outcome or a 5xx is UNKNOWN (resend the same id)', () => {
    expect(classifyCrewResponse({ kind: 'transport', error: new Error('net') }).kind).toBe('unknown')
    expect(classifyCrewResponse(http(503, err('CREW_HISTORY_WRITE_FAILED', { history_write_outcome: 'unknown' }))).kind).toBe('unknown')
    expect(classifyCrewResponse(http(500, null)).kind).toBe('unknown')
  })

  it('refusals raised before any write are settled with their Thai message', () => {
    for (const code of ['RESOURCE_CONFLICT', 'CROSS_ROLE_IDENTITY_UNVERIFIED', 'CREW_CONCURRENT_CHANGE',
      'CREW_ASSIGNMENT_STALE', 'PERSONNEL_NOT_ACTIVE', 'CREW_ASSIGNMENT_NOT_AUTHORIZED']) {
      const result = classifyCrewResponse(http(code === 'CREW_ASSIGNMENT_NOT_AUTHORIZED' ? 403 : 409, err(code)))
      expect(result).toMatchObject({ kind: 'refused', code })
      if (result.kind === 'refused') expect(result.message).not.toBe('')
    }
    expect(classifyCrewResponse(http(503, err('CREW_HISTORY_WRITE_FAILED', { history_write_outcome: 'rejected' }))).kind)
      .toBe('refused')
  })

  it('REQUEST_ID_REUSED is a refusal the hook keeps as CONFLICT (never resent)', () => {
    expect(classifyCrewResponse(http(409, err('REQUEST_ID_REUSED')))).toMatchObject({ kind: 'refused', code: 'REQUEST_ID_REUSED' })
  })
})
