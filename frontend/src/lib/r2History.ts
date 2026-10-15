/**
 * R2 Batch R2-C2a — response contracts of the existing R2f read routes the
 * relationship / history panels use (R2f-a/b/c/e relationships and link
 * histories, R2f-g department history, R2f-d equipment caretaker, R2f-f
 * permanent responsible driver). Every reader validates the exact documented
 * shape: a body that does not match is an error, never "no history".
 *
 * IDs are shown as returned. Nothing here resolves a department name (the
 * department master is operational-only), invents a reason the read does not
 * return, or derives one authority from another (R2f-f permanent
 * responsibility is never E2 operational driving).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, apiGet } from './apiClient'
import {
  CAN_LINK_PERSONNEL_ACCOUNT,
  CAN_LINK_PERSONNEL_DRIVER,
  CAN_LINK_PERSONNEL_TECHNICIAN,
} from './capabilityNames'
import { describeErrorCode } from './labels'

type Obj = Record<string, unknown>
export const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v)
const isStr = (v: unknown): v is string => typeof v === 'string'
const isStrOrNull = (v: unknown): v is string | null => v === null || typeof v === 'string'
const oneOf = <T extends string>(v: unknown, values: readonly T[]): v is T =>
  typeof v === 'string' && (values as readonly string[]).includes(v)

// ---------------------------------------------------------------------------
// Read state
// ---------------------------------------------------------------------------

/** How a failed read is shown. `scope` = the id exists only outside the
 * server's data scope (`*_SCOPE_UNPROVEN`); `unavailable` = the server has no
 * data context / a source could not be read; never shown as "no data". */
export type ReadFailureKind = 'forbidden' | 'not-found' | 'scope' | 'conflict' | 'unavailable' | 'invalid' | 'error'

export interface ReadFailure {
  kind: ReadFailureKind
  status: number | null
  code: string | null
  message: string
  requestId: string | null
}

export type ReadState<T> = { kind: 'loading' } | { kind: 'error'; failure: ReadFailure } | { kind: 'ready'; data: T }

export const INVALID_RESPONSE_MESSAGE = 'ข้อมูลที่ได้รับจากระบบไม่อยู่ในรูปแบบที่รองรับ จึงไม่แสดงผล'

export function readFailure(error: ApiError | Error): ReadFailure {
  if (!(error instanceof ApiError)) {
    return { kind: 'error', status: null, code: null, message: 'เชื่อมต่อระบบไม่สำเร็จ กรุณาลองใหม่อีกครั้ง', requestId: null }
  }
  const { status, code } = error
  const kind: ReadFailureKind =
    status === 403 ? 'forbidden'
      : status === 404 ? 'not-found'
        : status === 422 && code.endsWith('_SCOPE_UNPROVEN') ? 'scope'
          : status === 409 ? 'conflict'
            : status === 503 ? 'unavailable'
              : status === 500 ? 'invalid'
                : 'error'
  return { kind, status, code, message: describeErrorCode(code), requestId: error.requestId ?? null }
}

/** ONE GET with exact-shape validation. */
export async function readR2<T>(path: string, parse: (json: unknown) => T | null): Promise<ReadState<T>> {
  const result = await apiGet<unknown>(path)
  if (!result.ok) return { kind: 'error', failure: readFailure(result.error) }
  const data = parse(result.data)
  if (data === null) {
    return { kind: 'error', failure: { kind: 'invalid', status: 200, code: null, message: INVALID_RESPONSE_MESSAGE, requestId: null } }
  }
  return { kind: 'ready', data }
}

/** One validated read of `path`, re-read on `reload()` and when the path
 * changes; `parse` must be stable (a module function or a memoized one); a
 * new `onData` never causes a re-read. A
 * late answer of an older read never replaces a newer one. */
export function useR2Read<T>(
  path: string,
  parse: (json: unknown) => T | null,
  /** Called with every successful read (e.g. pending-intent settlement). */
  onData?: (data: T) => void,
): [ReadState<T>, () => void] {
  const [result, setResult] = useState<{ key: string; state: ReadState<T> } | null>(null)
  const [version, setVersion] = useState(0)
  // The latest callback, without re-reading when only the callback changes.
  const onDataRef = useRef(onData)
  useEffect(() => {
    onDataRef.current = onData
  })
  const key = `${path}#${version}`
  useEffect(() => {
    let cancelled = false
    void readR2(path, parse).then((next) => {
      if (cancelled) return
      if (next.kind === 'ready') onDataRef.current?.(next.data)
      setResult({ key, state: next })
    })
    return () => {
      cancelled = true
    }
  }, [path, parse, key])
  const reload = useCallback(() => setVersion((v) => v + 1), [])
  // A re-read of the same path keeps showing the last good data until the new
  // answer arrives (no flicker, child panels stay mounted); a new path starts
  // from loading.
  const state: ReadState<T> =
    result !== null && (result.key === key || (result.state.kind === 'ready' && result.key.startsWith(`${path}#`)))
      ? result.state
      : { kind: 'loading' }
  return [state, reload]
}

// ---------------------------------------------------------------------------
// R2f-a/b/c/e — Personnel relationships and link histories
// ---------------------------------------------------------------------------

export const RESOLUTIONS = ['RESOLVED', 'UNSET', 'MISSING', 'AMBIGUOUS', 'SCOPE_UNPROVEN'] as const
export type Resolution = (typeof RESOLUTIONS)[number]
export const CONSISTENCIES = ['NO_HISTORY', 'CONSISTENT', 'MISMATCH'] as const
export type LinkConsistency = (typeof CONSISTENCIES)[number]
export const LINK_EVENT_KINDS = ['LINK', 'UNLINK', 'RELINK', 'RECONCILIATION'] as const
export type LinkEventKind = (typeof LINK_EVENT_KINDS)[number]

export type LinkKind = 'technician' | 'account' | 'driver'

export interface LinkKindSpec {
  kind: LinkKind
  /** URL segment: /personnel/{id}/{segment}, …/reconcile, …/history */
  segment: 'technician-links' | 'account-links' | 'driver-links'
  /** The id column: technician_id / user_id / driver_id. */
  idField: 'technician_id' | 'user_id' | 'driver_id'
  capability: string
  /** Error-code prefix of the link (e.g. PERSONNEL_DRIVER_LINK). */
  label: string
  /** Error-code prefix of the link target (TECHNICIAN / USER_ACCOUNT / DRIVER). */
  targetLabel: string
  /** Error-code prefix of the target master read. */
  targetReadPrefix: string
  title: string
  targetName: string
}

export const LINK_KINDS: Record<LinkKind, LinkKindSpec> = {
  technician: {
    kind: 'technician', segment: 'technician-links', idField: 'technician_id', capability: CAN_LINK_PERSONNEL_TECHNICIAN,
    label: 'PERSONNEL_TECHNICIAN_LINK', targetLabel: 'TECHNICIAN', targetReadPrefix: 'TECHNICIAN_MASTER',
    title: 'ช่าง (Technician)', targetName: 'รหัสช่าง',
  },
  account: {
    kind: 'account', segment: 'account-links', idField: 'user_id', capability: CAN_LINK_PERSONNEL_ACCOUNT,
    label: 'PERSONNEL_ACCOUNT_LINK', targetLabel: 'USER_ACCOUNT', targetReadPrefix: 'USER_ACCOUNT',
    title: 'บัญชีผู้ใช้ (Account)', targetName: 'รหัสบัญชีผู้ใช้ (user_id)',
  },
  driver: {
    kind: 'driver', segment: 'driver-links', idField: 'driver_id', capability: CAN_LINK_PERSONNEL_DRIVER,
    label: 'PERSONNEL_DRIVER_LINK', targetLabel: 'DRIVER', targetReadPrefix: 'DRIVER_MASTER',
    title: 'คนขับ/ผู้ควบคุม (Driver)', targetName: 'รหัสคนขับ/ผู้ควบคุม',
  },
}

export interface TechnicianSummary {
  technician_id: string
  first_name: string | null
  last_name: string | null
  active_status: string | null
}

function parseTechnician(v: unknown): TechnicianSummary | null {
  if (!isObj(v) || !isStr(v.technician_id) || !isStrOrNull(v.first_name) || !isStrOrNull(v.last_name)
      || !isStrOrNull(v.active_status)) return null
  return { technician_id: v.technician_id, first_name: v.first_name, last_name: v.last_name, active_status: v.active_status }
}

export interface LinkResolution {
  resolution: Resolution
  /** The linked id; null when UNSET or when redacted (`visible` false). */
  id: string | null
  /** False when the server omitted the id (account ids without the account-link capability). */
  visible: boolean
  technician: TechnicianSummary | null
}

export interface PersonnelRelationships {
  personnel_id: string
  technician: LinkResolution
  account: LinkResolution
  driver: LinkResolution
}

function parseResolution(v: unknown, idField: string, redactable: boolean): LinkResolution | null {
  if (!isObj(v) || !oneOf(v.resolution, RESOLUTIONS)) return null
  const present = idField in v
  if (!present && !redactable) return null
  const id = present ? v[idField] : null
  if (!isStrOrNull(id)) return null
  let technician: TechnicianSummary | null = null
  if (v.technician !== undefined && v.technician !== null) {
    technician = parseTechnician(v.technician)
    if (technician === null) return null
  }
  return { resolution: v.resolution, id, visible: present, technician }
}

export function parseRelationships(json: unknown): PersonnelRelationships | null {
  if (!isObj(json) || !isStr(json.personnel_id)) return null
  const technician = parseResolution(json.technician, 'technician_id', false)
  const account = parseResolution(json.account, 'user_id', true)
  const driver = parseResolution(json.driver, 'driver_id', false)
  if (!technician || !account || !driver) return null
  return { personnel_id: json.personnel_id, technician, account, driver }
}

export interface LinkEvent {
  link_event_id: string
  event_kind: LinkEventKind
  previous_id: string | null
  new_id: string | null
  recorded_at: string
  recorded_by: string
  reason_th: string
  request_id: string
}

export interface LinkHistory {
  personnel_id: string
  current_id: string | null
  latest_history_id: string | null
  consistency: LinkConsistency
  /** Account history only: false when the server redacted every user id. */
  ids_visible: boolean
  events: LinkEvent[]
}

export function parseLinkHistory(json: unknown, spec: LinkKindSpec): LinkHistory | null {
  const f = spec.idField
  if (!isObj(json) || !isStr(json.personnel_id) || !isStrOrNull(json[`current_${f}`])
      || !isStrOrNull(json[`latest_history_${f}`]) || !oneOf(json.relationship_consistency, CONSISTENCIES)
      || !Array.isArray(json.events)) return null
  let idsVisible = true
  if (spec.kind === 'account') {
    if (typeof json.user_ids_visible !== 'boolean') return null
    idsVisible = json.user_ids_visible
  }
  const events: LinkEvent[] = []
  for (const e of json.events) {
    if (!isObj(e) || !isStr(e.link_event_id) || !oneOf(e.event_kind, LINK_EVENT_KINDS) || !isStrOrNull(e[`previous_${f}`])
        || !isStrOrNull(e[`new_${f}`]) || !isStr(e.recorded_at) || !isStr(e.recorded_by) || !isStr(e.reason_th)
        || !isStr(e.request_id)) return null
    events.push({
      link_event_id: e.link_event_id, event_kind: e.event_kind,
      previous_id: e[`previous_${f}`] as string | null, new_id: e[`new_${f}`] as string | null,
      recorded_at: e.recorded_at, recorded_by: e.recorded_by, reason_th: e.reason_th, request_id: e.request_id,
    })
  }
  return {
    personnel_id: json.personnel_id,
    current_id: json[`current_${f}`] as string | null,
    latest_history_id: json[`latest_history_${f}`] as string | null,
    consistency: json.relationship_consistency,
    ids_visible: idsVisible,
    events,
  }
}

// ---------------------------------------------------------------------------
// Effective-dated timelines (R2f-g department, R2f-d caretaker, R2f-f driver)
// ---------------------------------------------------------------------------

export const TIMELINE_STATUSES = ['VALID', 'AMBIGUOUS_ORDER'] as const
export type TimelineStatus = (typeof TIMELINE_STATUSES)[number]
export const CURRENT_STATUSES = ['EVENT', 'ENDED', 'NONE', 'UNDETERMINED'] as const
export type CurrentStatus = (typeof CURRENT_STATUSES)[number]
export const ENTRY_OPERATIONS = ['TRANSFER', 'INSERTION', 'END'] as const
export type EntryOperation = (typeof ENTRY_OPERATIONS)[number]
export const PRECISIONS = ['DATE', 'DATETIME'] as const

/** One period of an effective-dated timeline; `target_id` is the department /
 * technician / driver id of the period (null for an END). The reads return
 * no reason text, so none is shown. */
export interface TimelinePeriod {
  event_id: string
  in_force: boolean
  entry_operation: EntryOperation
  revision_no: string
  head_record_id: string
  target_id: string | null
  effective_at: string
  effective_precision: string
  derived_end_at: string | null
  recorded_at: string
  recorded_by: string
  notes: string[]
}

function parsePeriod(e: unknown, targetField: string, operations: readonly string[]): TimelinePeriod | null {
  if (!isObj(e) || !isStr(e.event_id) || typeof e.in_force !== 'boolean' || !oneOf(e.entry_operation, operations)
      || !isStr(e.revision_no) || !isStr(e.head_record_id) || !isStrOrNull(e[targetField]) || !isStr(e.effective_at)
      || !isStr(e.effective_precision) || !isStrOrNull(e.derived_end_at) || !isStr(e.recorded_at)
      || !isStr(e.recorded_by) || !Array.isArray(e.notes) || !e.notes.every(isStr)) return null
  return {
    event_id: e.event_id, in_force: e.in_force, entry_operation: e.entry_operation as EntryOperation,
    revision_no: e.revision_no, head_record_id: e.head_record_id, target_id: e[targetField] as string | null,
    effective_at: e.effective_at, effective_precision: e.effective_precision, derived_end_at: e.derived_end_at,
    recorded_at: e.recorded_at, recorded_by: e.recorded_by, notes: e.notes as string[],
  }
}

function parsePeriods(events: unknown, targetField: string, operations: readonly string[]): TimelinePeriod[] | null {
  if (!Array.isArray(events)) return null
  const out: TimelinePeriod[] = []
  for (const e of events) {
    const period = parsePeriod(e, targetField, operations)
    if (period === null) return null
    out.push(period)
  }
  return out
}

export interface DepartmentHistory {
  personnel_id: string
  timeline_status: TimelineStatus
  current_status: 'EVENT' | 'NONE' | 'UNDETERMINED'
  current_department_id: string | null
  current_since: string | null
  events: TimelinePeriod[]
}

export function parseDepartmentHistory(json: unknown): DepartmentHistory | null {
  if (!isObj(json) || !isStr(json.personnel_id) || !oneOf(json.timeline_status, TIMELINE_STATUSES)
      || !oneOf(json.current_status, ['EVENT', 'NONE', 'UNDETERMINED'] as const)
      || !isStrOrNull(json.current_department_id) || !isStrOrNull(json.current_since)) return null
  const events = parsePeriods(json.events, 'department_id', ['TRANSFER', 'INSERTION'])
  if (events === null) return null
  return {
    personnel_id: json.personnel_id, timeline_status: json.timeline_status, current_status: json.current_status,
    current_department_id: json.current_department_id, current_since: json.current_since, events,
  }
}

export const TECHNICIAN_RESOLUTIONS = ['RESOLVED', 'NONE', 'UNDETERMINED', 'UNRESOLVED'] as const

export interface CaretakerTimeline {
  equipment_id: string
  timeline_status: TimelineStatus
  current_status: CurrentStatus
  current_id: string | null
  current_since: string | null
  current_technician_resolution: (typeof TECHNICIAN_RESOLUTIONS)[number]
  current_technician: TechnicianSummary | null
  events: TimelinePeriod[]
}

export function parseCaretakers(json: unknown): CaretakerTimeline | null {
  if (!isObj(json) || !isStr(json.equipment_id) || !oneOf(json.timeline_status, TIMELINE_STATUSES)
      || !oneOf(json.current_status, CURRENT_STATUSES) || !isStrOrNull(json.current_technician_id)
      || !isStrOrNull(json.current_since) || !oneOf(json.current_technician_resolution, TECHNICIAN_RESOLUTIONS)) return null
  let technician: TechnicianSummary | null = null
  if (json.current_technician !== null) {
    technician = parseTechnician(json.current_technician)
    if (technician === null) return null
  }
  const events = parsePeriods(json.events, 'technician_id', ENTRY_OPERATIONS)
  if (events === null) return null
  return {
    equipment_id: json.equipment_id, timeline_status: json.timeline_status, current_status: json.current_status,
    current_id: json.current_technician_id, current_since: json.current_since,
    current_technician_resolution: json.current_technician_resolution, current_technician: technician, events,
  }
}

export interface ResponsibilityTimeline {
  vehicle_id: string
  timeline_status: TimelineStatus
  current_status: CurrentStatus
  current_id: string | null
  current_since: string | null
  events: TimelinePeriod[]
}

export function parseResponsibleDrivers(json: unknown): ResponsibilityTimeline | null {
  if (!isObj(json) || !isStr(json.vehicle_id) || !oneOf(json.timeline_status, TIMELINE_STATUSES)
      || !oneOf(json.current_status, CURRENT_STATUSES) || !isStrOrNull(json.current_driver_id)
      || !isStrOrNull(json.current_since)) return null
  const events = parsePeriods(json.events, 'driver_id', ENTRY_OPERATIONS)
  if (events === null) return null
  return {
    vehicle_id: json.vehicle_id, timeline_status: json.timeline_status, current_status: json.current_status,
    current_id: json.current_driver_id, current_since: json.current_since, events,
  }
}

export interface DriverVehicles {
  driver_id: string
  items: { vehicle_id: string; since: string; event_id: string }[]
}

export function parseDriverVehicles(json: unknown): DriverVehicles | null {
  if (!isObj(json) || !isStr(json.driver_id) || !Array.isArray(json.items)) return null
  const items: DriverVehicles['items'] = []
  for (const item of json.items) {
    if (!isObj(item) || !isStr(item.vehicle_id) || !isStr(item.since) || !isStr(item.event_id)) return null
    items.push({ vehicle_id: item.vehicle_id, since: item.since, event_id: item.event_id })
  }
  return { driver_id: json.driver_id, items }
}

/** Technician list (`GET /technicians`, server scope) for names and the picker. */
export function parseTechnicianPage(json: unknown): TechnicianSummary[] | null {
  if (!isObj(json) || !Array.isArray(json.items)) return null
  const out: TechnicianSummary[] = []
  for (const item of json.items) {
    const technician = parseTechnician(item)
    if (technician === null) return null
    out.push(technician)
  }
  return out
}

export function technicianName(t: TechnicianSummary | null | undefined): string | null {
  if (!t) return null
  const name = [t.first_name, t.last_name].filter((p): p is string => !!p && p.trim() !== '').join(' ')
  return name === '' ? null : name
}

/** Display order: newest effective first (ties: latest recorded first). The
 * server's own order is not assumed. */
export function sortPeriods(events: readonly TimelinePeriod[]): TimelinePeriod[] {
  return [...events].sort((a, b) => {
    const byEffective = Date.parse(b.effective_at) - Date.parse(a.effective_at)
    return byEffective !== 0 ? byEffective : Date.parse(b.recorded_at) - Date.parse(a.recorded_at)
  })
}

/** Driver Master list (`GET /drivers`, existing Phase 6 read) for driver names
 * and the explicit picker. It is not server-scoped: the backend still proves
 * every chosen driver (scope, ACTIVE) before recording anything. */
export interface DriverSummary {
  driver_id: string
  driver_name_th: string
  active_status: string | null
}

export function parseDriverPage(json: unknown): DriverSummary[] | null {
  if (!isObj(json) || !Array.isArray(json.items)) return null
  const out: DriverSummary[] = []
  for (const item of json.items) {
    if (!isObj(item) || !isStr(item.driver_id) || !isStr(item.driver_name_th) || !isStrOrNull(item.active_status)) return null
    out.push({ driver_id: item.driver_id, driver_name_th: item.driver_name_th, active_status: item.active_status })
  }
  return out
}
