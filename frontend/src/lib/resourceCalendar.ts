/**
 * R8 early workstream — Resource Calendar date math and grouping (pure).
 * All dates are Asia/Bangkok calendar dates (YYYY-MM-DD); the backend returns
 * one entry per labelled unit (a night shift keeps its start date, A2-3.3), so an
 * entry belongs to exactly one day cell. Windows never exceed the backend's 42 days.
 */
import { addDays, isIsoDate } from './e2Assignments'
import type { CalendarEntry, CalendarView } from './types'

export type CalendarScale = 'MONTH' | 'WEEK' | 'DAY'
export const CALENDAR_SCALES: readonly CalendarScale[] = ['MONTH', 'WEEK', 'DAY']
export const CALENDAR_VIEWS: readonly CalendarView[] = ['VEHICLES', 'PERSONNEL', 'BOTH']
export const MAX_WINDOW_DAYS = 42

/** Weekday of a calendar date, 0 = Sunday (UTC math on the date itself). */
export function weekday(day: string): number {
  return new Date(`${day}T00:00:00Z`).getUTCDay()
}

export function startOfWeek(day: string): string {
  return addDays(day, -weekday(day))
}

/** The visible window of a scale around an anchor date (inclusive). */
export function calendarWindow(scale: CalendarScale, anchor: string): { from: string; to: string; days: string[] } {
  let from: string
  let count: number
  if (scale === 'DAY') {
    from = anchor
    count = 1
  } else if (scale === 'WEEK') {
    from = startOfWeek(anchor)
    count = 7
  } else {
    from = startOfWeek(`${anchor.slice(0, 7)}-01`)
    count = MAX_WINDOW_DAYS // six full weeks always cover the month
  }
  const days = Array.from({ length: count }, (_, n) => addDays(from, n))
  return { from, to: days[days.length - 1], days }
}

/** The anchor after moving one step of the scale (+1 / -1). */
export function moveAnchor(scale: CalendarScale, anchor: string, step: 1 | -1): string {
  if (scale === 'DAY') return addDays(anchor, step)
  if (scale === 'WEEK') return addDays(anchor, 7 * step)
  const [y, m] = anchor.split('-').map(Number)
  const month = new Date(Date.UTC(y, m - 1 + step, 1))
  return month.toISOString().slice(0, 10)
}

export function entriesByDay(entries: readonly CalendarEntry[]): Map<string, CalendarEntry[]> {
  const out = new Map<string, CalendarEntry[]>()
  for (const entry of entries) {
    const list = out.get(entry.label_date) ?? []
    list.push(entry)
    out.set(entry.label_date, list)
  }
  return out
}

/** The grouping key and label of an entry for a view. */
export function groupOf(entry: CalendarEntry, view: CalendarView): { key: string; label: string } {
  if (view === 'PERSONNEL') {
    if (entry.personnel_id) return { key: `P:${entry.personnel_id}`, label: entry.personnel_name ?? entry.personnel_id }
    if (entry.driver_id) {
      return { key: `D:${entry.driver_id}`, label: `${entry.driver_name ?? entry.driver_id} (คนขับ — ยังยืนยันตัวบุคคลไม่ได้)` }
    }
    return { key: 'UNKNOWN', label: 'ไม่ทราบผู้ได้รับมอบหมาย' }
  }
  return { key: `V:${entry.vehicle_id}`, label: entry.machine_no ? `${entry.machine_no} (${entry.vehicle_id})` : entry.vehicle_id }
}

/** Entries grouped for the day drawer: VEHICLES / PERSONNEL group by that axis, BOTH by vehicle. */
export function groupEntries(entries: readonly CalendarEntry[], view: CalendarView): { key: string; label: string; entries: CalendarEntry[] }[] {
  const groups = new Map<string, { key: string; label: string; entries: CalendarEntry[] }>()
  for (const entry of entries) {
    const g = groupOf(entry, view === 'BOTH' ? 'VEHICLES' : view)
    const group = groups.get(g.key) ?? { ...g, entries: [] }
    group.entries.push(entry)
    groups.set(g.key, group)
  }
  return [...groups.values()].sort((a, b) => a.label.localeCompare(b.label, 'th'))
}

export function readCalendarParams(params: URLSearchParams, today: string): {
  scale: CalendarScale
  view: CalendarView
  anchor: string
} {
  const scale = params.get('scale')
  const view = params.get('view')
  const anchor = params.get('date') ?? ''
  return {
    scale: (CALENDAR_SCALES as readonly string[]).includes(scale ?? '') ? (scale as CalendarScale) : 'MONTH',
    view: (CALENDAR_VIEWS as readonly string[]).includes(view ?? '') ? (view as CalendarView) : 'BOTH',
    anchor: isIsoDate(anchor) ? anchor : today,
  }
}
