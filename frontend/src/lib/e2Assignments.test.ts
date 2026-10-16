import { describe, expect, it } from 'vitest'
import {
  addDays,
  assignmentStates,
  bangkokParts,
  bangkokToday,
  defaultE2Window,
  driverSchedulePath,
  formatE2Shift,
  formatE2Span,
  inclusiveDays,
  isHhMm,
  isIsoDate,
  operationPath,
  parseDriverSchedule,
  parseVehicleHistory,
  parseVehicleSchedule,
  sortRecords,
  validateE2Filter,
  vehicleHistoryPath,
  vehicleSchedulePath,
} from './e2Assignments'

/** R2 Batch R2-C2b — E2 read contracts (shapes captured from the R2-C1 mock backend). */

const interval = (over: Record<string, unknown> = {}) => ({
  event_id: 'ODA-1', revision_no: '1', vehicle_id: 'VEH-1048', assigned_driver_id: 'DRV-TEST-901', mode: 'FULL_DAY',
  label_date: '2026-10-20', effective_start: '2026-10-19T17:00:00+00:00', effective_end: '2026-10-20T17:00:00+00:00',
  ...over,
})
const warning = { code: 'NO_PERMANENT_RESPONSIBLE_DRIVER', event_id: null, driver_id: null, vehicle_id: 'VEH-1048', related_event_id: null }
const schedule = (over: Record<string, unknown> = {}) => ({
  vehicle_id: 'VEH-1048', timeline_status: 'VALID', current_status: 'NONE', current: null,
  intervals: [interval()], unknown: [], conflicts: [], warnings: [warning], ...over,
})
const record = (over: Record<string, unknown> = {}) => ({
  record_id: 'ODA-1', operation_id: 'ODO-1', record_kind: 'ASSIGNMENT', entry_operation: 'CREATE', event_id: 'ODA-1',
  revision_no: '1', supersedes_record_id: null, assigned_driver_id: 'DRV-TEST-901', mode: 'FULL_DAY',
  start_date: '2026-10-20', end_date: '2026-10-22', shift_start_time: null, shift_end_time: null, shift_end_day_offset: null,
  excluded_dates: [], related_event_id: null, relation: null, early_end_at: null, voided: false, handover_kind: null,
  predecessor_event_id: null, predecessor_revision_no: null, successor_event_id: null, successor_revision_no: null,
  handover_at: null, unknown_start_at: null, unknown_end_at: null, reason_th: null,
  recorded_at: '2026-10-16T00:24:28.000000+00:00', recorded_by: 'dev-user', request_id: '11111111-1111-4111-8111-000000000001',
  ...over,
})

describe('parsers', () => {
  it('accept the exact vehicle schedule, with a current unit, conflicts and UNKNOWN spans', () => {
    const parsed = parseVehicleSchedule(schedule({
      current_status: 'ASSIGNED', current: interval(),
      unknown: [{ vehicle_id: 'VEH-1048', start: '2026-10-22T13:00:00+00:00', end: '2026-10-22T15:00:00+00:00', handover_event_id: 'ODA-H' }],
      conflicts: [{ axis: 'VEHICLE', key: 'VEH-1048', first: interval(), second: interval({ event_id: 'ODA-2', assigned_driver_id: 'DRV-TEST-902' }) }],
    }))
    expect(parsed).toMatchObject({ current_status: 'ASSIGNED', current: { event_id: 'ODA-1' }, unknown: [{ handover_event_id: 'ODA-H' }] })
    expect(parsed?.conflicts[0].second.assigned_driver_id).toBe('DRV-TEST-902')
    expect(parsed?.warnings).toEqual([warning])
  })

  it('reject any shape that is not exactly documented (never "no assignment")', () => {
    for (const bad of [
      null, [], schedule({ timeline_status: 'INVALID' }), schedule({ current_status: 'UNDETERMINED' }),
      schedule({ intervals: [interval({ mode: 'NO_SHIFT' })] }), schedule({ intervals: [interval({ assigned_driver_id: null })] }),
      schedule({ intervals: undefined }), schedule({ warnings: [{ code: 'X' }] }), schedule({ current: { event_id: 'x' } }),
      schedule({ conflicts: [{ axis: 'BOTH', key: 'k', first: interval(), second: interval() }] }),
    ]) {
      expect(parseVehicleSchedule(bad)).toBeNull()
    }
  })

  it('accept the driver schedule across vehicles', () => {
    const parsed = parseDriverSchedule({ driver_id: 'DRV-TEST-902', timeline_status: 'CONFLICTED',
      intervals: [interval({ vehicle_id: 'VEH-TEST-901' })], conflicts: [], warnings: [] })
    expect(parsed).toMatchObject({ driver_id: 'DRV-TEST-902', timeline_status: 'CONFLICTED', intervals: [{ vehicle_id: 'VEH-TEST-901' }] })
    expect(parseDriverSchedule({ driver_id: 'D', timeline_status: 'VALID', intervals: [], conflicts: [] })).toBeNull()
  })

  it('accept the history with every record kind, and reject malformed rows', () => {
    const history = {
      vehicle_id: 'VEH-1048',
      events: [{ event_id: 'ODA-1', kind: 'ASSIGNMENT', lifecycle: 'ACTIVE', revision_no: '2', head_record_id: 'ODA-R' },
        { event_id: 'ODA-H', kind: 'HANDOVER', lifecycle: 'IN_FORCE', revision_no: '1', head_record_id: 'ODA-H' }],
      records: [record(),
        record({ record_id: 'ODA-R', record_kind: 'REVISION', entry_operation: 'SUBSTITUTE', revision_no: '2',
          supersedes_record_id: 'ODA-1', excluded_dates: ['2026-10-21'], reason_th: 'แทน' }),
        record({ record_id: 'ODA-H', record_kind: 'HANDOVER', event_id: 'ODA-H', assigned_driver_id: null, mode: null,
          start_date: null, end_date: null, handover_kind: 'H2', predecessor_event_id: 'ODA-1', predecessor_revision_no: '1',
          successor_event_id: 'ODA-2', successor_revision_no: '1', handover_at: '2026-10-22T13:00:00+00:00' })],
    }
    const parsed = parseVehicleHistory(history)
    expect(parsed?.records).toHaveLength(3)
    expect(parsed?.records[1].excluded_dates).toEqual(['2026-10-21'])
    for (const bad of [record({ record_kind: 'DELETE' }), record({ entry_operation: 'ASSIGN' }), record({ voided: 'FALSE' }),
      record({ request_id: undefined }), record({ excluded_dates: '2026-10-21' }), record({ reason_th: 5 })]) {
      expect(parseVehicleHistory({ ...history, records: [bad] }), JSON.stringify(bad)).toBeNull()
    }
    expect(parseVehicleHistory({ ...history, events: [{ ...history.events[0], lifecycle: 'GONE' }] })).toBeNull()
  })
})

describe('assignmentStates', () => {
  it('pairs each ASSIGNMENT event with its latest state row; a CANCELLATION keeps the prior state', () => {
    const history = parseVehicleHistory({
      vehicle_id: 'VEH-1048',
      events: [
        { event_id: 'ODA-1', kind: 'ASSIGNMENT', lifecycle: 'CANCELLED', revision_no: '3', head_record_id: 'ODA-C' },
        { event_id: 'ODA-H', kind: 'HANDOVER', lifecycle: 'IN_FORCE', revision_no: '1', head_record_id: 'ODA-H' },
      ],
      records: [
        record(),
        record({ record_id: 'ODA-R', record_kind: 'REVISION', entry_operation: 'REVISE', revision_no: '2', end_date: '2026-10-25' }),
        record({ record_id: 'ODA-C', record_kind: 'CANCELLATION', entry_operation: 'CANCEL', revision_no: '3',
          assigned_driver_id: null, mode: null, start_date: null, end_date: null }),
      ],
    })!
    const states = assignmentStates(history)
    expect(states).toHaveLength(1) // handovers are not assignments
    expect(states[0].event.lifecycle).toBe('CANCELLED')
    expect(states[0].state).toMatchObject({ record_id: 'ODA-R', end_date: '2026-10-25' })
  })

  it('sorts history rows newest first', () => {
    const rows = sortRecords([record({ record_id: 'A', recorded_at: '2026-10-16T00:00:00+00:00' }) as never,
      record({ record_id: 'B', recorded_at: '2026-10-17T00:00:00+00:00' }) as never])
    expect(rows.map((r) => r.record_id)).toEqual(['B', 'A'])
  })
})

describe('Asia/Bangkok dates and times', () => {
  it('today, windows and day arithmetic follow the Bangkok calendar (UTC+7)', () => {
    // 2026-10-15 17:30 UTC is already 2026-10-16 00:30 in Bangkok.
    expect(bangkokToday(new Date('2026-10-15T17:30:00Z'))).toBe('2026-10-16')
    expect(bangkokToday(new Date('2026-10-15T16:59:59Z'))).toBe('2026-10-15')
    expect(defaultE2Window(new Date('2026-10-15T17:30:00Z'))).toEqual({ from: '2026-10-09', to: '2026-11-15' })
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01')
    expect(inclusiveDays('2026-10-20', '2026-10-22')).toBe(3)
    expect(isIsoDate('2026-02-30')).toBe(false)
    expect(isHhMm('24:00')).toBe(false)
    expect(isHhMm('23:59')).toBe(true)
    expect(bangkokParts('2026-10-19T17:00:00+00:00')).toEqual({ date: '2026-10-20', time: '00:00' })
    expect(bangkokParts('2026-10-20')).toBeNull()
  })

  it('a FULL_DAY unit ends at "24:00" of its own date, never 00:00 of the next', () => {
    expect(formatE2Span('2026-10-19T17:00:00+00:00', '2026-10-20T17:00:00+00:00', '2026-10-20')).toBe('00:00 – 24:00')
  })

  it('a night shift keeps its start date and marks the next-day end', () => {
    expect(formatE2Span('2026-10-22T13:00:00+00:00', '2026-10-22T23:00:00+00:00', '2026-10-22')).toBe('20:00 – 06:00 (+1 วัน)')
  })

  it('a FULL_DAY clipped by an H2 handover ends at the handover instant', () => {
    expect(formatE2Span('2026-10-21T17:00:00+00:00', '2026-10-22T13:00:00+00:00', '2026-10-22')).toBe('00:00 – 20:00')
  })

  it('applied shift times show the next-day designation and the 24-hour case', () => {
    expect(formatE2Shift('08:00', '17:00', '0')).toBe('08:00 – 17:00')
    expect(formatE2Shift('20:00', '06:00', '1')).toBe('20:00 – 06:00 (+1 วัน)')
    expect(formatE2Shift('07:00', '07:00', '1')).toBe('07:00 – 07:00 (+1 วัน, 24 ชั่วโมง)')
    expect(formatE2Shift(null, null, null)).toBeNull()
  })
})

describe('paths and filters', () => {
  it('use the four existing routes with the G-1 from / to / mode filters only', () => {
    const filter = { from: '2026-10-09', to: '2026-11-15', mode: '' as const }
    expect(vehicleSchedulePath('VEH-1048', filter)).toBe('/vehicles/VEH-1048/operational-driver-assignments?from=2026-10-09&to=2026-11-15')
    expect(driverSchedulePath('DRV-TEST-901', { ...filter, mode: 'NIGHT_SHIFT' }))
      .toBe('/drivers/DRV-TEST-901/operational-driver-assignments?from=2026-10-09&to=2026-11-15&mode=NIGHT_SHIFT')
    expect(vehicleHistoryPath('VEH-1048')).toBe('/vehicles/VEH-1048/operational-driver-assignment-history')
    expect(operationPath('VEH 1')).toBe('/vehicles/VEH%201/operational-driver-assignment-operations')
  })

  it('refuse an invalid or reversed range before any read', () => {
    expect(validateE2Filter({ from: '2026-10-09', to: '2026-10-08', mode: '' })).toContain('ต้องไม่อยู่ก่อน')
    expect(validateE2Filter({ from: '', to: '2026-10-08', mode: '' })).not.toBeNull()
    expect(validateE2Filter({ from: '2026-10-08', to: '2026-10-08', mode: 'FULL_DAY' })).toBeNull()
  })
})
