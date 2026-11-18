import { describe, expect, it } from 'vitest'
import {
  calendarWindow,
  entriesByDay,
  groupEntries,
  MAX_WINDOW_DAYS,
  moveAnchor,
  readCalendarParams,
  startOfWeek,
} from './resourceCalendar'
import type { CalendarEntry } from './types'

// R8 early workstream — calendar date math and grouping (Asia/Bangkok dates). Synthetic data.
function entry(overrides: Partial<CalendarEntry>): CalendarEntry {
  return {
    kind: 'CREW', event_id: 'E1', vehicle_id: 'VEH-1', machine_no: 'TC-1', personnel_id: 'P1',
    personnel_name: 'ช่าง หนึ่ง', driver_id: null, driver_name: null, identity: 'LINKED', role: 'RIGGER',
    role_note_th: null, mode: 'FULL_DAY', label_date: '2026-11-20', effective_start: '2026-11-19T17:00:00+00:00',
    effective_end: '2026-11-20T17:00:00+00:00', status: 'VALID', ...overrides,
  }
}

describe('resourceCalendar', () => {
  it('a month window starts on the Sunday on or before the 1st and never exceeds 42 days', () => {
    const w = calendarWindow('MONTH', '2026-11-18')
    expect(w.from).toBe('2026-11-01') // 2026-11-01 is a Sunday
    expect(w.days).toHaveLength(MAX_WINDOW_DAYS)
    expect(w.to).toBe('2026-12-12')
    const feb = calendarWindow('MONTH', '2027-02-10')
    expect(feb.from).toBe('2027-01-31')
    expect(feb.days.length).toBeLessThanOrEqual(MAX_WINDOW_DAYS)
  })

  it('week and day windows', () => {
    expect(calendarWindow('WEEK', '2026-11-18')).toMatchObject({ from: '2026-11-15', to: '2026-11-21' })
    expect(calendarWindow('DAY', '2026-11-18')).toMatchObject({ from: '2026-11-18', to: '2026-11-18' })
    expect(startOfWeek('2026-11-15')).toBe('2026-11-15')
  })

  it('moves across month and year boundaries', () => {
    expect(moveAnchor('MONTH', '2026-12-31', 1)).toBe('2027-01-01')
    expect(moveAnchor('MONTH', '2026-01-15', -1)).toBe('2025-12-01')
    expect(moveAnchor('WEEK', '2026-12-28', 1)).toBe('2027-01-04')
    expect(moveAnchor('DAY', '2026-12-31', 1)).toBe('2027-01-01')
  })

  it('places each entry on its labelled day only (a night shift keeps its start date)', () => {
    const night = entry({ event_id: 'N', mode: 'NIGHT_SHIFT', label_date: '2026-11-20',
      effective_start: '2026-11-20T15:00:00+00:00', effective_end: '2026-11-20T23:00:00+00:00' })
    const map = entriesByDay([entry({}), night])
    expect(map.get('2026-11-20')?.map((e) => e.event_id)).toEqual(['E1', 'N'])
    expect(map.get('2026-11-21')).toBeUndefined()
  })

  it('groups by vehicle or person; an unlinked driver is labelled unverified, never merged into a person', () => {
    const driver = entry({ kind: 'DRIVER', event_id: 'D', personnel_id: null, personnel_name: null, driver_id: 'DRV-1',
      driver_name: 'ผู้ขับ', identity: 'UNLINKED', role: 'DRIVER' })
    const byPerson = groupEntries([entry({}), driver], 'PERSONNEL')
    expect(byPerson.map((g) => g.key).sort()).toEqual(['D:DRV-1', 'P:P1'])
    expect(byPerson.find((g) => g.key === 'D:DRV-1')?.label).toContain('ยังยืนยันตัวบุคคลไม่ได้')
    expect(groupEntries([entry({}), driver], 'VEHICLES').map((g) => g.key)).toEqual(['V:VEH-1'])
    expect(groupEntries([entry({}), driver], 'BOTH')).toHaveLength(1)
  })

  it('reads the URL defensively', () => {
    expect(readCalendarParams(new URLSearchParams('scale=WEEK&view=PERSONNEL&date=2026-11-20'), '2026-11-18')).toEqual({
      scale: 'WEEK', view: 'PERSONNEL', anchor: '2026-11-20' })
    expect(readCalendarParams(new URLSearchParams('scale=YEAR&view=ALL&date=2026-02-30'), '2026-11-18')).toEqual({
      scale: 'MONTH', view: 'BOTH', anchor: '2026-11-18' })
  })
})
