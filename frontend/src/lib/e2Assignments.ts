/**
 * R2 Batch R2-C2b — the E2 operational driver assignment read contracts
 * (backend R2-C1: `operational_driver_assignment_routes.py` / `_schemas.py`).
 *
 * E2 records the ASSIGNED driver of a vehicle for a date range, a day shift or
 * a night shift. It is NOT the R2f-f permanent responsible driver and NOT the
 * legacy Phase 6 vehicle-driver assignment: nothing here reads either, and an
 * assignment is never shown as proof of actual driving (G-2).
 *
 * Every reader validates the exact documented shape: a body that does not
 * match is an error, never "no assignment". All instants are UTC with an
 * offset; they are shown in Asia/Bangkok (UTC+7, no daylight saving — the same
 * fixed offset the backend uses for its unit boundaries).
 */
import { isObj } from './r2History'

type Obj = Record<string, unknown>
const isStr = (v: unknown): v is string => typeof v === 'string'
const isStrOrNull = (v: unknown): v is string | null => v === null || typeof v === 'string'
const oneOf = <T extends string>(v: unknown, values: readonly T[]): v is T =>
  typeof v === 'string' && (values as readonly string[]).includes(v)
const strArray = (v: unknown): v is string[] => Array.isArray(v) && v.every(isStr)

export const E2_MODES = ['FULL_DAY', 'DAY_SHIFT', 'NIGHT_SHIFT'] as const
export type E2Mode = (typeof E2_MODES)[number]
export const E2_SHIFT_MODES: readonly E2Mode[] = ['DAY_SHIFT', 'NIGHT_SHIFT']

export const E2_OPERATIONS = ['CREATE', 'REVISE', 'SUBSTITUTE', 'CANCEL', 'EARLY_END'] as const
export type E2Operation = (typeof E2_OPERATIONS)[number]

export const E2_TIMELINE_STATUSES = ['VALID', 'CONFLICTED'] as const
export const E2_CURRENT_STATUSES = ['ASSIGNED', 'UNKNOWN', 'NONE', 'CONFLICTED'] as const
export const E2_LIFECYCLES = ['ACTIVE', 'CANCELLED', 'VOIDED', 'IN_FORCE'] as const
export const E2_RECORD_KINDS = ['ASSIGNMENT', 'REVISION', 'HANDOVER', 'CANCELLATION'] as const
export const E2_EVENT_KINDS = ['ASSIGNMENT', 'HANDOVER'] as const

/** Backend DQ-7: an assignment covers at most 366 inclusive days; a new start
 * is at most 366 days ahead (the backend checks both; shown as hints only). */
export const E2_MAX_RANGE_DAYS = 366
export const E2_MAX_REASON_LENGTH = 500

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** One derived effective unit (half-open UTC instants; `label_date` is the
 * Bangkok date the unit belongs to — a night shift keeps its start date). */
export interface E2Interval {
  event_id: string
  revision_no: string
  vehicle_id: string
  /** The ASSIGNED driver — never a verified actual driver. */
  assigned_driver_id: string
  mode: E2Mode
  label_date: string
  effective_start: string
  effective_end: string
}

export interface E2Unknown {
  vehicle_id: string
  start: string
  end: string
  handover_event_id: string
}

export interface E2Conflict {
  axis: 'VEHICLE' | 'DRIVER'
  key: string
  first: E2Interval
  second: E2Interval
}

export interface E2Warning {
  code: string
  event_id: string | null
  driver_id: string | null
  vehicle_id: string | null
  related_event_id: string | null
}

export interface E2VehicleSchedule {
  vehicle_id: string
  timeline_status: (typeof E2_TIMELINE_STATUSES)[number]
  current_status: (typeof E2_CURRENT_STATUSES)[number]
  current: E2Interval | null
  intervals: E2Interval[]
  unknown: E2Unknown[]
  conflicts: E2Conflict[]
  warnings: E2Warning[]
}

export interface E2DriverSchedule {
  driver_id: string
  timeline_status: (typeof E2_TIMELINE_STATUSES)[number]
  intervals: E2Interval[]
  conflicts: E2Conflict[]
  warnings: E2Warning[]
}

export interface E2HistoryEvent {
  event_id: string
  kind: (typeof E2_EVENT_KINDS)[number]
  lifecycle: (typeof E2_LIFECYCLES)[number]
  revision_no: string
  head_record_id: string
}

/** One immutable stored row (original, revision, handover or cancellation). */
export interface E2HistoryRecord {
  record_id: string
  operation_id: string
  record_kind: (typeof E2_RECORD_KINDS)[number]
  entry_operation: E2Operation
  event_id: string
  revision_no: string
  supersedes_record_id: string | null
  assigned_driver_id: string | null
  mode: string | null
  start_date: string | null
  end_date: string | null
  shift_start_time: string | null
  shift_end_time: string | null
  shift_end_day_offset: string | null
  excluded_dates: string[]
  related_event_id: string | null
  relation: string | null
  early_end_at: string | null
  voided: boolean
  handover_kind: string | null
  predecessor_event_id: string | null
  predecessor_revision_no: string | null
  successor_event_id: string | null
  successor_revision_no: string | null
  handover_at: string | null
  unknown_start_at: string | null
  unknown_end_at: string | null
  reason_th: string | null
  recorded_at: string
  recorded_by: string
  request_id: string
}

export interface E2VehicleHistory {
  vehicle_id: string
  events: E2HistoryEvent[]
  records: E2HistoryRecord[]
}

// ---------------------------------------------------------------------------
// Parsers (exact shapes)
// ---------------------------------------------------------------------------

function parseInterval(v: unknown): E2Interval | null {
  if (!isObj(v) || !isStr(v.event_id) || !isStr(v.revision_no) || !isStr(v.vehicle_id) || !isStr(v.assigned_driver_id)
      || !oneOf(v.mode, E2_MODES) || !isStr(v.label_date) || !isStr(v.effective_start) || !isStr(v.effective_end)) return null
  return {
    event_id: v.event_id, revision_no: v.revision_no, vehicle_id: v.vehicle_id, assigned_driver_id: v.assigned_driver_id,
    mode: v.mode, label_date: v.label_date, effective_start: v.effective_start, effective_end: v.effective_end,
  }
}

function parseList<T>(v: unknown, item: (x: unknown) => T | null): T[] | null {
  if (!Array.isArray(v)) return null
  const out: T[] = []
  for (const x of v) {
    const parsed = item(x)
    if (parsed === null) return null
    out.push(parsed)
  }
  return out
}

function parseUnknown(v: unknown): E2Unknown | null {
  if (!isObj(v) || !isStr(v.vehicle_id) || !isStr(v.start) || !isStr(v.end) || !isStr(v.handover_event_id)) return null
  return { vehicle_id: v.vehicle_id, start: v.start, end: v.end, handover_event_id: v.handover_event_id }
}

function parseConflict(v: unknown): E2Conflict | null {
  if (!isObj(v) || !oneOf(v.axis, ['VEHICLE', 'DRIVER'] as const) || !isStr(v.key)) return null
  const first = parseInterval(v.first)
  const second = parseInterval(v.second)
  if (first === null || second === null) return null
  return { axis: v.axis, key: v.key, first, second }
}

export function parseE2Warning(v: unknown): E2Warning | null {
  if (!isObj(v) || !isStr(v.code)) return null
  const fields = ['event_id', 'driver_id', 'vehicle_id', 'related_event_id'] as const
  if (!fields.every((f) => isStrOrNull(v[f]))) return null
  return {
    code: v.code,
    event_id: v.event_id as string | null,
    driver_id: v.driver_id as string | null,
    vehicle_id: v.vehicle_id as string | null,
    related_event_id: v.related_event_id as string | null,
  }
}

export function parseE2Warnings(v: unknown): E2Warning[] | null {
  return parseList(v, parseE2Warning)
}

export function parseVehicleSchedule(json: unknown): E2VehicleSchedule | null {
  if (!isObj(json) || !isStr(json.vehicle_id) || !oneOf(json.timeline_status, E2_TIMELINE_STATUSES)
      || !oneOf(json.current_status, E2_CURRENT_STATUSES)) return null
  const current = json.current === null ? null : parseInterval(json.current)
  if (json.current !== null && current === null) return null
  const intervals = parseList(json.intervals, parseInterval)
  const unknown = parseList(json.unknown, parseUnknown)
  const conflicts = parseList(json.conflicts, parseConflict)
  const warnings = parseE2Warnings(json.warnings)
  if (!intervals || !unknown || !conflicts || !warnings) return null
  return {
    vehicle_id: json.vehicle_id, timeline_status: json.timeline_status, current_status: json.current_status,
    current, intervals, unknown, conflicts, warnings,
  }
}

export function parseDriverSchedule(json: unknown): E2DriverSchedule | null {
  if (!isObj(json) || !isStr(json.driver_id) || !oneOf(json.timeline_status, E2_TIMELINE_STATUSES)) return null
  const intervals = parseList(json.intervals, parseInterval)
  const conflicts = parseList(json.conflicts, parseConflict)
  const warnings = parseE2Warnings(json.warnings)
  if (!intervals || !conflicts || !warnings) return null
  return { driver_id: json.driver_id, timeline_status: json.timeline_status, intervals, conflicts, warnings }
}

const RECORD_NULLABLE = [
  'supersedes_record_id', 'assigned_driver_id', 'mode', 'start_date', 'end_date', 'shift_start_time', 'shift_end_time',
  'shift_end_day_offset', 'related_event_id', 'relation', 'early_end_at', 'handover_kind', 'predecessor_event_id',
  'predecessor_revision_no', 'successor_event_id', 'successor_revision_no', 'handover_at', 'unknown_start_at',
  'unknown_end_at', 'reason_th',
] as const

function parseRecord(v: unknown): E2HistoryRecord | null {
  if (!isObj(v) || !isStr(v.record_id) || !isStr(v.operation_id) || !oneOf(v.record_kind, E2_RECORD_KINDS)
      || !oneOf(v.entry_operation, E2_OPERATIONS) || !isStr(v.event_id) || !isStr(v.revision_no)
      || !strArray(v.excluded_dates) || typeof v.voided !== 'boolean' || !isStr(v.recorded_at) || !isStr(v.recorded_by)
      || !isStr(v.request_id) || !RECORD_NULLABLE.every((f) => isStrOrNull(v[f]))) return null
  const o = v as Obj
  const out: Record<string, unknown> = {}
  for (const f of RECORD_NULLABLE) out[f] = o[f]
  return {
    ...(out as Pick<E2HistoryRecord, (typeof RECORD_NULLABLE)[number]>),
    record_id: v.record_id, operation_id: v.operation_id, record_kind: v.record_kind,
    entry_operation: v.entry_operation, event_id: v.event_id, revision_no: v.revision_no,
    excluded_dates: [...v.excluded_dates], voided: v.voided, recorded_at: v.recorded_at, recorded_by: v.recorded_by,
    request_id: v.request_id,
  }
}

function parseEvent(v: unknown): E2HistoryEvent | null {
  if (!isObj(v) || !isStr(v.event_id) || !oneOf(v.kind, E2_EVENT_KINDS) || !oneOf(v.lifecycle, E2_LIFECYCLES)
      || !isStr(v.revision_no) || !isStr(v.head_record_id)) return null
  return { event_id: v.event_id, kind: v.kind, lifecycle: v.lifecycle, revision_no: v.revision_no, head_record_id: v.head_record_id }
}

export function parseVehicleHistory(json: unknown): E2VehicleHistory | null {
  if (!isObj(json) || !isStr(json.vehicle_id)) return null
  const events = parseList(json.events, parseEvent)
  const records = parseList(json.records, parseRecord)
  if (!events || !records) return null
  return { vehicle_id: json.vehicle_id, events, records }
}

// ---------------------------------------------------------------------------
// Assignment states (from the stored history; the backend derives coverage)
// ---------------------------------------------------------------------------

/** One logical ASSIGNMENT event and its latest STATE row (the newest
 * ASSIGNMENT / REVISION revision; a terminal CANCELLATION carries no state).
 * `state` is null only if the history holds no state row for the event. */
export interface E2AssignmentState {
  event: E2HistoryEvent
  state: E2HistoryRecord | null
}

const revisionNumber = (r: { revision_no: string }) => Number.parseInt(r.revision_no, 10) || 0

export function assignmentStates(history: E2VehicleHistory): E2AssignmentState[] {
  return history.events
    .filter((e) => e.kind === 'ASSIGNMENT')
    .map((event) => {
      const rows = history.records
        .filter((r) => r.event_id === event.event_id && (r.record_kind === 'ASSIGNMENT' || r.record_kind === 'REVISION'))
        .sort((a, b) => revisionNumber(b) - revisionNumber(a))
      return { event, state: rows[0] ?? null }
    })
    .sort((a, b) => (b.state?.start_date ?? '').localeCompare(a.state?.start_date ?? ''))
}

/** History rows, newest first (recorded time, then revision). */
export function sortRecords(records: readonly E2HistoryRecord[]): E2HistoryRecord[] {
  return [...records].sort((a, b) => {
    const t = Date.parse(b.recorded_at) - Date.parse(a.recorded_at)
    if (t !== 0 && !Number.isNaN(t)) return t
    return revisionNumber(b) - revisionNumber(a)
  })
}

// ---------------------------------------------------------------------------
// Asia/Bangkok dates and times (UTC+7, no DST)
// ---------------------------------------------------------------------------

const BANGKOK_OFFSET_MS = 7 * 60 * 60 * 1000
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/
const TIME_RE = /^([01]\d|2[0-3]):[0-5]\d$/

export const isIsoDate = (v: string): boolean => {
  if (!DATE_RE.test(v)) return false
  const d = new Date(`${v}T00:00:00Z`)
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === v
}
export const isHhMm = (v: string): boolean => TIME_RE.test(v)

/** The Bangkok calendar date of an instant (default: now). */
export function bangkokToday(now: Date = new Date()): string {
  return new Date(now.getTime() + BANGKOK_OFFSET_MS).toISOString().slice(0, 10)
}

export function addDays(day: string, n: number): string {
  const d = new Date(`${day}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}

/** Inclusive calendar days of [from, to] (0 when to < from). */
export function inclusiveDays(from: string, to: string): number {
  const ms = Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)
  return ms < 0 ? 0 : Math.round(ms / 86_400_000) + 1
}

/** The owner-approved default schedule window: Bangkok today −7 to +30 days. */
export function defaultE2Window(now: Date = new Date()): { from: string; to: string } {
  const today = bangkokToday(now)
  return { from: addDays(today, -7), to: addDays(today, 30) }
}

/** Bangkok wall clock of an instant, or null when it is not an offset-bearing instant. */
export function bangkokParts(iso: string): { date: string; time: string } | null {
  if (!/(Z|[+-]\d{2}:?\d{2})$/i.test(iso)) return null
  const ms = Date.parse(iso)
  if (Number.isNaN(ms)) return null
  const local = new Date(ms + BANGKOK_OFFSET_MS).toISOString()
  return { date: local.slice(0, 10), time: local.slice(11, 16) }
}

const thaiDate = new Intl.DateTimeFormat('th-TH', { dateStyle: 'medium', timeZone: 'UTC' })

/** A Bangkok calendar date (YYYY-MM-DD) as Thai text. */
export function formatE2Date(day: string | null): string {
  if (day === null) return '-'
  if (!isIsoDate(day)) return day
  return thaiDate.format(new Date(`${day}T00:00:00Z`))
}

/** An instant in Bangkok as "<Thai date> HH:MM" (text that is not an instant is returned unchanged). */
export function formatE2Instant(iso: string | null): string {
  if (iso === null) return '-'
  const p = bangkokParts(iso)
  return p === null ? iso : `${formatE2Date(p.date)} ${p.time}`
}

/**
 * The effective span of a unit in Bangkok, relative to its labelled date:
 * the end of a FULL_DAY (next day 00:00) is shown as "24:00" of its last day
 * (A2-3.2), and an end on a later date is marked "(+1 วัน)" (a night shift
 * keeps its start date, A2-3.3).
 */
export function formatE2Span(start: string, end: string, labelDate: string): string {
  const s = bangkokParts(start)
  const e = bangkokParts(end)
  if (s === null || e === null) return `${start} – ${end}`
  const startText = s.date === labelDate ? s.time : `${formatE2Date(s.date)} ${s.time}`
  let endText: string
  if (e.time === '00:00' && e.date === addDays(labelDate, 1)) endText = '24:00'
  else if (e.date === labelDate) endText = e.time
  else {
    const days = inclusiveDays(labelDate, e.date) - 1
    endText = days > 0 ? `${e.time} (+${days} วัน)` : `${formatE2Date(e.date)} ${e.time}`
  }
  return `${startText} – ${endText}`
}

/** An instant span that may cross dates, both ends with their Bangkok date. */
export function formatE2Range(start: string, end: string): string {
  return `${formatE2Instant(start)} – ${formatE2Instant(end)}`
}

/** Applied shift times as stored ("HH:MM", offset "0" / "1"); null when no shift. */
export function formatE2Shift(start: string | null, end: string | null, offset: string | number | null): string | null {
  if (start === null || end === null) return null
  const next = String(offset) === '1'
  if (next && start === end) return `${start} – ${end} (+1 วัน, 24 ชั่วโมง)`
  return `${start} – ${end}${next ? ' (+1 วัน)' : ''}`
}

// ---------------------------------------------------------------------------
// Paths
// ---------------------------------------------------------------------------

export interface E2Filter {
  from: string
  to: string
  mode: E2Mode | ''
}

function query(filter: E2Filter): string {
  const params = new URLSearchParams({ from: filter.from, to: filter.to })
  if (filter.mode) params.set('mode', filter.mode)
  return params.toString()
}

export const vehicleSchedulePath = (vehicleId: string, filter: E2Filter) =>
  `/vehicles/${encodeURIComponent(vehicleId)}/operational-driver-assignments?${query(filter)}`
export const vehicleHistoryPath = (vehicleId: string) =>
  `/vehicles/${encodeURIComponent(vehicleId)}/operational-driver-assignment-history`
export const driverSchedulePath = (driverId: string, filter: E2Filter) =>
  `/drivers/${encodeURIComponent(driverId)}/operational-driver-assignments?${query(filter)}`
export const operationPath = (vehicleId: string) =>
  `/vehicles/${encodeURIComponent(vehicleId)}/operational-driver-assignment-operations`

/** A filter the backend accepts (valid dates, `to` not before `from`), or an error text. */
export function validateE2Filter(filter: E2Filter): string | null {
  if (!isIsoDate(filter.from) || !isIsoDate(filter.to)) return 'กรุณาระบุวันที่เริ่มต้นและวันที่สิ้นสุดให้ถูกต้อง'
  if (filter.to < filter.from) return 'วันที่สิ้นสุดต้องไม่อยู่ก่อนวันที่เริ่มต้น'
  return null
}
