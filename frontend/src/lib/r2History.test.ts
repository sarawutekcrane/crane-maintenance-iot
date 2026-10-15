import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from './apiClient'
import {
  LINK_KINDS,
  parseCaretakers,
  parseDepartmentHistory,
  parseDriverVehicles,
  parseLinkHistory,
  parseRelationships,
  parseResponsibleDrivers,
  readFailure,
  readR2,
  sortPeriods,
  technicianName,
  type TimelinePeriod,
} from './r2History'

/** R2 Batch R2-C2a — exact response contracts of the R2f read routes (shapes
 * taken from the live mock backend responses). */

const period = (over: Partial<Record<string, unknown>> = {}) => ({
  event_id: 'CDR-1', in_force: true, entry_operation: 'TRANSFER', revision_no: '1', head_record_id: 'CDR-1',
  driver_id: 'DRV-TEST-901', effective_at: '2026-01-04T17:00:00+00:00', effective_precision: 'DATE',
  derived_end_at: null, recorded_at: '2026-10-15T12:28:53.694420+00:00', recorded_by: 'dev-user', notes: [], ...over,
})

describe('relationships', () => {
  const body = {
    personnel_id: 'PER-TEST-911',
    technician: { resolution: 'RESOLVED', technician_id: 'TEC-TEST-911',
      technician: { technician_id: 'TEC-TEST-911', first_name: 'ช่างทดสอบ', last_name: 'ลำดับหนึ่ง', active_status: 'ACTIVE' } },
    account: { resolution: 'RESOLVED', user_id: 'USR-TEST-911' },
    driver: { resolution: 'UNSET', driver_id: null },
  }

  it('parses the three resolutions', () => {
    const r = parseRelationships(body)!
    expect(r.technician).toMatchObject({ resolution: 'RESOLVED', id: 'TEC-TEST-911', visible: true })
    expect(technicianName(r.technician.technician)).toBe('ช่างทดสอบ ลำดับหนึ่ง')
    expect(r.account).toMatchObject({ id: 'USR-TEST-911', visible: true })
    expect(r.driver).toMatchObject({ resolution: 'UNSET', id: null })
  })

  it('an omitted account user_id is REDACTED (not "unset"); technician / driver ids may not be omitted', () => {
    const redacted = parseRelationships({ ...body, account: { resolution: 'RESOLVED' } })!
    expect(redacted.account).toMatchObject({ resolution: 'RESOLVED', id: null, visible: false })
    expect(parseRelationships({ ...body, driver: { resolution: 'UNSET' } })).toBeNull()
  })

  it('rejects unknown resolutions and malformed bodies', () => {
    expect(parseRelationships({ ...body, driver: { resolution: 'MAYBE', driver_id: null } })).toBeNull()
    expect(parseRelationships(null)).toBeNull()
    expect(parseRelationships({ ...body, technician: { resolution: 'RESOLVED', technician_id: 'x', technician: { technician_id: 1 } } })).toBeNull()
  })
})

describe('link history', () => {
  const driver = {
    personnel_id: 'PER-TEST-912', current_driver_id: 'DRV-TEST-901', latest_history_driver_id: 'DRV-TEST-901',
    relationship_consistency: 'CONSISTENT',
    events: [{ link_event_id: 'PDL-1', event_kind: 'LINK', previous_driver_id: null, new_driver_id: 'DRV-TEST-901',
      recorded_at: '2026-10-15T12:28:53.625633+00:00', recorded_by: 'dev-user', reason_th: 'ทดสอบ', request_id: 'rid-1' }],
  }

  it('parses a driver-link history with request ids', () => {
    const h = parseLinkHistory(driver, LINK_KINDS.driver)!
    expect(h).toMatchObject({ current_id: 'DRV-TEST-901', consistency: 'CONSISTENT', ids_visible: true })
    expect(h.events[0]).toMatchObject({ event_kind: 'LINK', previous_id: null, new_id: 'DRV-TEST-901', request_id: 'rid-1' })
  })

  it('account history needs user_ids_visible; redacted ids are null', () => {
    const account = { personnel_id: 'P', user_ids_visible: false, current_user_id: null, latest_history_user_id: null,
      relationship_consistency: 'NO_HISTORY', events: [] }
    expect(parseLinkHistory(account, LINK_KINDS.account)).toMatchObject({ ids_visible: false, current_id: null })
    const { user_ids_visible: _omit, ...missing } = account
    void _omit
    expect(parseLinkHistory(missing, LINK_KINDS.account)).toBeNull()
  })

  it('rejects a history of the wrong kind or with a malformed event', () => {
    expect(parseLinkHistory(driver, LINK_KINDS.technician)).toBeNull()
    expect(parseLinkHistory({ ...driver, events: [{ ...driver.events[0], event_kind: 'MOVE' }] }, LINK_KINDS.driver)).toBeNull()
  })
})

describe('timelines', () => {
  it('parses the permanent responsible-driver timeline (ids only, no reason)', () => {
    const t = parseResponsibleDrivers({ vehicle_id: 'VEH-1048', timeline_status: 'VALID', current_status: 'EVENT',
      current_driver_id: 'DRV-TEST-901', current_since: '2026-01-04T17:00:00+00:00', events: [period()] })!
    expect(t.current_id).toBe('DRV-TEST-901')
    expect(t.events[0]).toMatchObject({ target_id: 'DRV-TEST-901', effective_precision: 'DATE' })
    expect('reason_th' in t.events[0]).toBe(false)
  })

  it('parses the caretaker timeline with the current technician', () => {
    const t = parseCaretakers({ equipment_id: 'EQP-0002', timeline_status: 'VALID', current_status: 'NONE',
      current_technician_id: null, current_since: null, current_technician_resolution: 'NONE', current_technician: null, events: [] })!
    expect(t).toMatchObject({ current_status: 'NONE', current_technician: null, events: [] })
    expect(parseCaretakers({ equipment_id: 'E', timeline_status: 'VALID', current_status: 'NONE', current_technician_id: null,
      current_since: null, current_technician_resolution: 'WHATEVER', current_technician: null, events: [] })).toBeNull()
  })

  it('department history: TRANSFER / INSERTION only, department ids only', () => {
    const ok = parseDepartmentHistory({ personnel_id: 'P', timeline_status: 'VALID', current_status: 'EVENT',
      current_department_id: 'DEPT-SYN-A', current_since: '2026-02-01T00:00:00+00:00',
      events: [period({ driver_id: undefined, department_id: 'DEPT-SYN-A' })] })!
    expect(ok.events[0].target_id).toBe('DEPT-SYN-A')
    expect(parseDepartmentHistory({ personnel_id: 'P', timeline_status: 'VALID', current_status: 'ENDED',
      current_department_id: null, current_since: null, events: [] })).toBeNull()
    expect(parseDepartmentHistory({ personnel_id: 'P', timeline_status: 'VALID', current_status: 'EVENT',
      current_department_id: null, current_since: null, events: [period({ department_id: 'D', entry_operation: 'END' })] })).toBeNull()
  })

  it('driver → vehicles: current responsibilities only', () => {
    expect(parseDriverVehicles({ driver_id: 'DRV-TEST-901', items: [{ vehicle_id: 'VEH-1048', since: 's', event_id: 'e' }] }))
      .toEqual({ driver_id: 'DRV-TEST-901', items: [{ vehicle_id: 'VEH-1048', since: 's', event_id: 'e' }] })
    expect(parseDriverVehicles({ driver_id: 'D', items: [{ vehicle_id: 1 }] })).toBeNull()
  })

  it('sorts newest effective first, ties by latest recorded', () => {
    const p = (id: string, eff: string, rec: string) =>
      ({ ...(period() as unknown as TimelinePeriod), event_id: id, effective_at: eff, recorded_at: rec })
    const sorted = sortPeriods([p('a', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'), p('b', '2026-03-01T00:00:00Z', '2026-01-01T00:00:00Z'),
      p('c', '2026-01-01T00:00:00Z', '2026-05-01T00:00:00Z')])
    expect(sorted.map((e) => e.event_id)).toEqual(['b', 'c', 'a'])
  })
})

describe('readR2 / readFailure', () => {
  afterEach(() => vi.unstubAllGlobals())

  const envelope = (status: number, code: string) =>
    new ApiError(status, { error: { code, message: 'x', details: null, request_id: 'rid' } })

  it('classifies read failures distinctly', () => {
    expect(readFailure(envelope(403, 'HTTP_ERROR')).kind).toBe('forbidden')
    expect(readFailure(envelope(404, 'PERSONNEL_NOT_FOUND')).kind).toBe('not-found')
    expect(readFailure(envelope(422, 'VEHICLE_SCOPE_UNPROVEN')).kind).toBe('scope')
    expect(readFailure(envelope(409, 'DRIVER_RESPONSIBILITY_TIMELINE_AMBIGUOUS')).kind).toBe('conflict')
    expect(readFailure(envelope(503, 'REGISTRY_DATA_CONTEXT_NOT_CONFIGURED')).kind).toBe('unavailable')
    expect(readFailure(envelope(500, 'CRANE_DRIVER_RESPONSIBILITY_HISTORY_DATA_INVALID')).kind).toBe('invalid')
    expect(readFailure(new Error('network')).kind).toBe('error')
    expect(readFailure(envelope(422, 'VEHICLE_SCOPE_UNPROVEN')).requestId).toBe('rid')
  })

  it('a body of the wrong shape is an error, never "no data"', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ items: 'nope' }), { status: 200 })))
    const state = await readR2('/drivers/D/vehicles', parseDriverVehicles)
    expect(state).toMatchObject({ kind: 'error', failure: { kind: 'invalid' } })
  })
})
