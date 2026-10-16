/**
 * R2 Batch R2-C2b — request intents of the E2 operational driver assignment
 * write route (`POST /vehicles/{id}/operational-driver-assignment-operations`).
 * Its own module (owner decision D1): the accepted `r2HistoryWrites.ts` and
 * `registryPending.ts` are untouched; only the shared UUID generator is reused.
 *
 * Backend contract (R2-C1, `operational_driver_assignment.py`), VERIFIED:
 * 403 → 422 REQUEST_ID_REQUIRED → body → 503 context → 409 REAL refusal → ONE
 * history read → vehicle / references → REPLAY (same id + body → replayed with
 * the original record ids; different body → 409 REQUEST_ID_REUSED) → stale →
 * operation rules → conflicts on both axes → eligibility → ONE atomic append
 * (W1). After W1 the only outcomes are success, E2_CONCURRENT_CHANGE (the
 * mock's single-process version guard: nothing written) and 503
 * E2_HISTORY_WRITE_FAILED {history_write_outcome}. The vehicle history read
 * returns every stored row WITH its `request_id`.
 *
 * Rules (fail closed):
 * - The intent (UUID v4, exact path, exact serialized body) is stored and read
 *   back BEFORE sending, under `crane.e2Pending.v1:<userId>:<vehicleId>`. No
 *   user id, no secure random source or no working storage → nothing is sent.
 * - One unresolved intent per user / vehicle; one request in flight.
 * - Default outcome: KEEP as UNKNOWN. A first attempt is removed only for a
 *   correlated, shape-valid success / no-op or a refusal on the explicit
 *   PRE_WRITE list (every code on it is raised before W1, or — for
 *   E2_CONCURRENT_CHANGE — by the version guard with nothing written).
 * - Once an attempt was uncertain, NO response removes the intent (no refusal,
 *   no no-op, no E2_CONCURRENT_CHANGE): the backend looks the id up in a
 *   history snapshot and holds no production lock, so an earlier attempt may
 *   still append after a resend's read. Only the authoritative vehicle history
 *   showing a row with this exact `request_id` settles it.
 * - 409 REQUEST_ID_REUSED → CONFLICT: never resent, never settled by a read
 *   (the id is recorded with another body); an administrator must investigate.
 * - Never an automatic retry and never a new id: a resend is an explicit user
 *   action with the SAME id, path and stored body.
 *
 * The mock version guard is a single-process guarantee only (R11 owns
 * production atomicity). localStorage is not a security boundary.
 */
import { useCallback, useMemo, useState, useSyncExternalStore } from 'react'
import { apiMutation, type MutationResponse } from './apiClient'
import {
  E2_MAX_REASON_LENGTH,
  E2_MODES,
  E2_SHIFT_MODES,
  isHhMm,
  isIsoDate,
  parseE2Warnings,
  type E2AssignmentState,
  type E2Mode,
  type E2Operation,
  type E2VehicleHistory,
  type E2Warning,
} from './e2Assignments'
import { describeE2ErrorCode } from './labels'
import { isObj } from './r2History'
import { newR2RequestId } from './r2HistoryWrites'

export type E2IntentState = 'SUBMITTING' | 'UNKNOWN' | 'CONFLICT'

export interface E2Intent {
  v: 1
  vehicle_id: string
  request_id: string
  path: string
  body: Record<string, unknown>
  body_json: string
  operation: string
  created_at: string
  state: E2IntentState
  prior_uncertain: boolean
  /** Record ids proven by a correlated success / replay (shown, not needed for settlement). */
  record_ids: string[]
}

export type E2BlockedReason = 'no-user' | 'crypto' | 'storage' | 'pending' | 'in-flight'

/** Conflict details of 409 E2_VEHICLE_CONFLICT / E2_DRIVER_CONFLICT. */
export interface E2OverlapDetails {
  axis: string
  conflicting_event_id: string | null
  first: E2OverlapInterval | null
  second: E2OverlapInterval | null
}
export interface E2OverlapInterval {
  event_id: string
  vehicle_id: string
  assigned_driver_id: string
  label_date: string
  start: string
  end: string
}

export type E2WriteResult =
  | { kind: 'applied'; recordIds: string[]; eventIds: string[]; warnings: E2Warning[] }
  | { kind: 'no-op'; existingEventId: string | null }
  | { kind: 'refused'; status: number; code: string; message: string; overlap: E2OverlapDetails | null }
  | { kind: 'stale'; code: string; message: string }
  | { kind: 'conflict'; code: string; message: string; requestId: string }
  | { kind: 'unknown'; requestId: string; message: string; refused?: { status: number; code: string } }
  | { kind: 'settlement-required'; requestId: string; recordIds: string[]; message: string }
  | { kind: 'blocked'; reason: E2BlockedReason; message: string }

// ---------------------------------------------------------------------------
// The pre-write list (each code raised before the single append W1)
// ---------------------------------------------------------------------------

const pair = (status: number, code: string) => `${status}:${code}`

/** Raised before W1 (source: operational_driver_assignment.py, _routes.py,
 * request_id_dependency.py, registry_write_support.py, reference_read.py). */
export const E2_PRE_WRITE: ReadonlySet<string> = new Set([
  pair(403, 'HTTP_ERROR'),
  ...[
    'REQUEST_ID_REQUIRED', 'VALIDATION_ERROR', 'REASON_REQUIRED', 'E2_OPERATION_INVALID', 'E2_DATE_INVALID',
    'E2_TIME_INVALID', 'E2_RANGE_INVALID', 'E2_RANGE_TOO_LONG', 'E2_SHIFT_REQUIRED', 'E2_SHIFT_NOT_ALLOWED',
    'E2_SHIFT_DURATION_INVALID', 'E2_MODE_INVALID', 'E2_SPLIT_INVALID', 'E2_EARLY_END_INVALID',
    'E2_SUBSTITUTION_DRIVER_UNCHANGED', 'VEHICLE_SCOPE_UNPROVEN', 'DRIVER_NOT_FOUND', 'DRIVER_SCOPE_UNPROVEN',
    'DRIVER_NOT_ACTIVE', 'PERSONNEL_NOT_ACTIVE',
  ].map((code) => pair(422, code)),
  pair(404, 'VEHICLE_NOT_FOUND'),
  pair(404, 'E2_ASSIGNMENT_NOT_FOUND'),
  ...[
    'E2_REAL_WRITES_NOT_ENABLED', 'E2_VEHICLE_CONFLICT', 'E2_DRIVER_CONFLICT', 'E2_ASSIGNMENT_STALE',
    'E2_ASSIGNMENT_CANCELLED', 'E2_ASSIGNMENT_VOIDED', 'E2_ASSIGNMENT_ALREADY_STARTED', 'E2_ASSIGNMENT_NOT_STARTED',
    'E2_ASSIGNMENT_ALREADY_ENDED', 'E2_HANDOVER_NOT_PERMITTED', 'E2_HANDOVER_INVALIDATED',
    'E2_SUBSTITUTION_UNIT_INVALID', 'E2_TIMELINE_CONFLICTED', 'E2_CONCURRENT_CHANGE', 'VEHICLE_ID_AMBIGUOUS',
    'DRIVER_ID_AMBIGUOUS', 'DRIVER_PERSONNEL_AMBIGUOUS',
  ].map((code) => pair(409, code)),
  pair(501, 'FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE'),
  ...[
    'REGISTRY_DATA_CONTEXT_NOT_CONFIGURED', 'E2_HISTORY_READ_FAILED', 'VEHICLE_MASTER_READ_FAILED',
    'DRIVER_MASTER_READ_FAILED', 'PERSONNEL_MASTER_READ_FAILED',
  ].map((code) => pair(503, code)),
])

const W1_FAILED = 'E2_HISTORY_WRITE_FAILED'
/** Confirmed refusals after which the panel re-reads (the data changed meanwhile). */
const STALE_CODES = new Set(['E2_ASSIGNMENT_STALE', 'E2_CONCURRENT_CHANGE'])

// ---------------------------------------------------------------------------
// Messages
// ---------------------------------------------------------------------------

export const E2_UNKNOWN_MESSAGE =
  'ไม่ทราบผลการบันทึก (อาจบันทึกแล้วหรือยังไม่บันทึก) ระบบไม่ได้ส่งซ้ำอัตโนมัติ กรุณาโหลดประวัติล่าสุดเพื่อตรวจสอบ หรือกด "ส่งคำขอเดิมอีกครั้ง"'
export const E2_SETTLEMENT_MESSAGE = 'ระบบตอบรับคำขอนี้แล้ว กำลังตรวจสอบกับประวัติการมอบหมายก่อนปิดรายการค้าง'
export const E2_CONFLICT_MESSAGE =
  'รหัสคำขอนี้ถูกใช้กับข้อมูลอื่นแล้ว ระบบไม่ได้บันทึกคำขอนี้ซ้ำ รายการค้างนี้ต้องตรวจสอบก่อนบันทึกรายการใหม่'
export const E2_CONFLICT_ESCALATION =
  'ระบบยืนยันผลของคำขอนี้จากหน้าจอนี้ไม่ได้ และจะไม่ส่งคำขอใหม่แทน กรุณาแจ้งผู้ดูแลระบบพร้อมรหัสคำขอนี้เพื่อตรวจสอบ'
export const E2_RESEND_REFUSED_MESSAGE =
  'การส่งคำขอเดิมอีกครั้งถูกปฏิเสธ แต่การปฏิเสธนี้ไม่ได้ยืนยันว่าคำขอครั้งก่อนไม่ได้ถูกบันทึก รายการค้างจึงยังคงอยู่: '
export const E2_SETTLED_TEXT = 'ตรวจสอบกับประวัติการมอบหมายแล้ว: คำขอเดิมถูกบันทึกแล้ว'

const BLOCKED_MESSAGES: Record<E2BlockedReason, string> = {
  'no-user': 'ยังระบุผู้ใช้งานไม่ได้ จึงยังบันทึกไม่ได้ กรุณาโหลดหน้านี้ใหม่',
  crypto: 'เบราว์เซอร์นี้สร้างรหัสคำขอที่ปลอดภัยไม่ได้ จึงไม่ส่งคำขอ',
  storage: 'บันทึกรายการคำขอไว้ในเบราว์เซอร์ไม่ได้ จึงไม่ส่งคำขอ (เพื่อไม่ให้เกิดคำขอที่ติดตามผลไม่ได้)',
  pending: 'ยังมีคำขอเดิมที่ยังไม่ทราบผลหรือรอตรวจสอบ ต้องจัดการคำขอนั้นก่อน',
  'in-flight': 'กำลังส่งคำขออยู่ กรุณารอผลก่อน',
}

// ---------------------------------------------------------------------------
// Storage
// ---------------------------------------------------------------------------

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
export const E2_STORAGE_PREFIX = 'crane.e2Pending.v1'

export function e2IntentKey(userId: string, vehicleId: string): string {
  return `${E2_STORAGE_PREFIX}:${userId}:${vehicleId}`
}

const inflight = new Set<string>()
const listeners = new Set<() => void>()

export function subscribeE2Intents(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function emit(): void {
  for (const listener of listeners) listener()
}

function store(key: string, intent: E2Intent): boolean {
  try {
    const raw = JSON.stringify(intent)
    window.localStorage.setItem(key, raw)
    return window.localStorage.getItem(key) === raw
  } catch {
    return false
  }
}

function remove(key: string): void {
  try {
    window.localStorage.removeItem(key)
  } catch {
    // The intent simply stays visible.
  }
}

function isIntent(v: unknown): v is E2Intent {
  return isObj(v) && v.v === 1 && typeof v.vehicle_id === 'string' && typeof v.request_id === 'string'
    && UUID_V4.test(v.request_id) && typeof v.path === 'string' && isObj(v.body) && typeof v.body_json === 'string'
    && JSON.stringify(v.body) === v.body_json && typeof v.operation === 'string' && typeof v.created_at === 'string'
    && ['SUBMITTING', 'UNKNOWN', 'CONFLICT'].includes(v.state as string) && typeof v.prior_uncertain === 'boolean'
    && Array.isArray(v.record_ids) && v.record_ids.every((r) => typeof r === 'string')
}

/** The stored intent. An unparseable entry is `corrupt` (it still blocks new
 * writes). A SUBMITTING intent with no request in flight on this page is UNKNOWN. */
export function pendingE2Intent(userId: string | null, vehicleId: string): E2Intent | 'corrupt' | null {
  if (!userId) return null
  const key = e2IntentKey(userId, vehicleId)
  let raw: string | null
  try {
    raw = window.localStorage.getItem(key)
  } catch {
    return null
  }
  if (raw === null) return null
  try {
    const parsed: unknown = JSON.parse(raw)
    if (!isIntent(parsed) || parsed.vehicle_id !== vehicleId) return 'corrupt'
    return parsed.state === 'SUBMITTING' && !inflight.has(key) ? { ...parsed, state: 'UNKNOWN' } : parsed
  } catch {
    return 'corrupt'
  }
}

export function isE2InFlight(userId: string | null, vehicleId: string): boolean {
  return !!userId && inflight.has(e2IntentKey(userId, vehicleId))
}

// ---------------------------------------------------------------------------
// Classification
// ---------------------------------------------------------------------------

export interface E2Classification {
  action: 'REMOVE' | 'KEEP'
  state?: E2IntentState
  recordIds?: string[]
  result: E2WriteResult
}

const nonEmpty = (v: unknown): v is string => typeof v === 'string' && v.length > 0
const idList = (v: unknown, minLength: number): v is string[] =>
  Array.isArray(v) && v.length >= minLength && v.every(nonEmpty)

function overlapInterval(v: unknown): E2OverlapInterval | null {
  if (!isObj(v)) return null
  const fields = ['event_id', 'vehicle_id', 'assigned_driver_id', 'label_date', 'start', 'end'] as const
  if (!fields.every((f) => typeof v[f] === 'string')) return null
  return {
    event_id: v.event_id as string, vehicle_id: v.vehicle_id as string, assigned_driver_id: v.assigned_driver_id as string,
    label_date: v.label_date as string, start: v.start as string, end: v.end as string,
  }
}

function overlapDetails(code: string, details: Record<string, unknown> | null): E2OverlapDetails | null {
  if ((code !== 'E2_VEHICLE_CONFLICT' && code !== 'E2_DRIVER_CONFLICT') || details === null) return null
  return {
    axis: typeof details.axis === 'string' ? details.axis : '',
    conflicting_event_id: typeof details.conflicting_event_id === 'string' ? details.conflicting_event_id : null,
    first: overlapInterval(details.first),
    second: overlapInterval(details.second),
  }
}

/** The outcome of ONE response for the intent (pure; exported for tests). */
export function classifyE2Response(
  response: MutationResponse,
  intent: Pick<E2Intent, 'request_id' | 'prior_uncertain'>,
): E2Classification {
  const rid = intent.request_id
  const unknown = (refused?: { status: number; code: string }): E2Classification => ({
    action: 'KEEP', state: 'UNKNOWN',
    result: {
      kind: 'unknown', requestId: rid,
      message: refused ? `${E2_RESEND_REFUSED_MESSAGE}${describeE2ErrorCode(refused.code)}` : E2_UNKNOWN_MESSAGE,
      ...(refused ? { refused } : {}),
    },
  })
  const settle = (recordIds: string[]): E2Classification => ({
    action: 'KEEP', state: 'UNKNOWN', recordIds,
    result: { kind: 'settlement-required', requestId: rid, recordIds, message: E2_SETTLEMENT_MESSAGE },
  })
  if (response.kind !== 'http') return unknown()
  if (response.headerRequestId !== null && response.headerRequestId !== rid) return unknown()
  const { status, json } = response
  if (!isObj(json)) return unknown()

  if (status === 200) {
    if (json.request_id !== rid) return unknown()
    if ('replayed' in json) {
      const valid = json.replayed === true && nonEmpty(json.operation_id) && idList(json.record_ids, 1)
        && idList(json.event_ids, 1)
      // A replay proves the request was recorded; settle it against the history.
      return valid ? settle(json.record_ids as string[]) : unknown()
    }
    if (json.changed === false) {
      const existing = json.existing_event_id
      if (existing !== undefined && existing !== null && !nonEmpty(existing)) return unknown()
      // A no-op of a resend proves nothing about the earlier attempt (header).
      if (intent.prior_uncertain) return unknown()
      return { action: 'REMOVE', result: { kind: 'no-op', existingEventId: nonEmpty(existing) ? existing : null } }
    }
    if (json.changed === true) {
      const warnings = parseE2Warnings(json.warnings)
      if (!nonEmpty(json.operation_id) || !idList(json.record_ids, 1) || !idList(json.event_ids, 1) || warnings === null) {
        return unknown()
      }
      const recordIds = json.record_ids as string[]
      if (intent.prior_uncertain) return settle(recordIds)
      return {
        action: 'REMOVE', recordIds,
        result: { kind: 'applied', recordIds, eventIds: json.event_ids as string[], warnings },
      }
    }
    return unknown()
  }

  if (!isObj(json.error) || typeof json.error.code !== 'string' || json.error.request_id !== rid) return unknown()
  const code = json.error.code
  const details = isObj(json.error.details) ? json.error.details : null
  const message = describeE2ErrorCode(code)
  if (status === 409 && code === 'REQUEST_ID_REUSED') {
    return { action: 'KEEP', state: 'CONFLICT', result: { kind: 'conflict', code, message: E2_CONFLICT_MESSAGE, requestId: rid } }
  }
  if (status === 503 && code === W1_FAILED) {
    const rejected = details?.history_write_outcome === 'rejected'
    if (rejected && !intent.prior_uncertain) {
      return { action: 'REMOVE', result: { kind: 'refused', status, code, message, overlap: null } }
    }
    return unknown(rejected ? { status, code } : undefined)
  }
  const preWrite = E2_PRE_WRITE.has(pair(status, code))
  // After an uncertainty no refusal proves the earlier attempt was not recorded.
  if (intent.prior_uncertain) return unknown(preWrite ? { status, code } : undefined)
  if (!preWrite) return unknown()
  if (STALE_CODES.has(code)) return { action: 'REMOVE', result: { kind: 'stale', code, message } }
  return { action: 'REMOVE', result: { kind: 'refused', status, code, message, overlap: overlapDetails(code, details) } }
}

// ---------------------------------------------------------------------------
// Send / resend / settle
// ---------------------------------------------------------------------------

async function dispatch(key: string, intent: E2Intent): Promise<E2WriteResult> {
  inflight.add(key)
  emit()
  let response: MutationResponse
  try {
    response = await apiMutation(intent.path, 'POST', JSON.parse(intent.body_json), { requestId: intent.request_id })
  } finally {
    inflight.delete(key)
  }
  const outcome = classifyE2Response(response, intent)
  if (outcome.action === 'REMOVE') {
    remove(key)
  } else {
    store(key, {
      ...intent,
      state: outcome.state ?? 'UNKNOWN',
      prior_uncertain: true,
      record_ids: outcome.recordIds ?? intent.record_ids,
    })
  }
  emit()
  return outcome.result
}

function blocked(reason: E2BlockedReason): E2WriteResult {
  return { kind: 'blocked', reason, message: BLOCKED_MESSAGES[reason] }
}

export interface E2WriteRequest {
  userId: string | null
  vehicleId: string
  path: string
  operation: string
  body: Record<string, unknown>
}

/** A NEW user intent: a new id, stored (and read back) before sending. */
export async function startE2Write(request: E2WriteRequest): Promise<E2WriteResult> {
  const { userId, vehicleId } = request
  if (!userId) return blocked('no-user')
  const key = e2IntentKey(userId, vehicleId)
  if (inflight.has(key)) return blocked('in-flight')
  if (pendingE2Intent(userId, vehicleId) !== null) return blocked('pending')
  const requestId = newR2RequestId()
  if (requestId === null) return blocked('crypto')
  const intent: E2Intent = {
    v: 1, vehicle_id: vehicleId, request_id: requestId, path: request.path, body: request.body,
    body_json: JSON.stringify(request.body), operation: request.operation, created_at: new Date().toISOString(),
    state: 'SUBMITTING', prior_uncertain: false, record_ids: [],
  }
  if (!store(key, intent)) {
    remove(key)
    return blocked('storage')
  }
  emit()
  return dispatch(key, intent)
}

/** The explicit resend of the stored UNKNOWN intent: SAME id, path and body. */
export async function resendE2Write(userId: string | null, vehicleId: string): Promise<E2WriteResult | null> {
  if (!userId) return blocked('no-user')
  const key = e2IntentKey(userId, vehicleId)
  if (inflight.has(key)) return blocked('in-flight')
  const intent = pendingE2Intent(userId, vehicleId)
  if (intent === null || intent === 'corrupt' || intent.state !== 'UNKNOWN') return null
  const next: E2Intent = { ...intent, state: 'SUBMITTING', prior_uncertain: true }
  if (!store(key, next)) return blocked('storage')
  return dispatch(key, next)
}

/** Settlement against the authoritative vehicle history: a stored row of this
 * vehicle carries this exact request id. A CONFLICT is never settled; an
 * intent in flight is not judged. Returns true when the intent was removed. */
export function settleE2Intent(userId: string | null, vehicleId: string, history: E2VehicleHistory): boolean {
  if (!userId || history.vehicle_id !== vehicleId) return false
  const key = e2IntentKey(userId, vehicleId)
  if (inflight.has(key)) return false
  const intent = pendingE2Intent(userId, vehicleId)
  if (intent === null || intent === 'corrupt' || intent.state === 'CONFLICT') return false
  if (!history.records.some((r) => r.request_id === intent.request_id)) return false
  remove(key)
  emit()
  return true
}

function snapshot(userId: string | null, vehicleId: string): string {
  if (!userId) return ''
  const key = e2IntentKey(userId, vehicleId)
  let raw: string | null = null
  try {
    raw = window.localStorage.getItem(key)
  } catch {
    raw = null
  }
  return `${inflight.has(key) ? 'F' : '-'}${raw ?? ''}`
}

export function useE2Intent(userId: string | null, vehicleId: string): { intent: E2Intent | 'corrupt' | null; inFlight: boolean } {
  const raw = useSyncExternalStore(subscribeE2Intents, () => snapshot(userId, vehicleId))
  return useMemo(
    () => ({ intent: pendingE2Intent(userId, vehicleId), inFlight: raw.startsWith('F') }),
    // `raw` is the change signal of the stored intent and the in-flight flag.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [raw, userId, vehicleId],
  )
}

// ---------------------------------------------------------------------------
// Panel messages and the write hook
// ---------------------------------------------------------------------------

export type E2Message = {
  tone: 'success' | 'warning' | 'error'
  text: string
  requestId?: string | null
  reload?: boolean
  warnings?: E2Warning[]
}

export function e2ResultMessage(result: E2WriteResult): E2Message | null {
  switch (result.kind) {
    case 'applied':
      return { tone: 'success', text: 'บันทึกเรียบร้อยแล้ว', warnings: result.warnings }
    case 'no-op':
      return {
        tone: 'success',
        text: result.existingEventId
          ? `มีการมอบหมายเดียวกันอยู่แล้ว (${result.existingEventId}) ไม่มีการบันทึกซ้ำ`
          : 'ข้อมูลเป็นค่านี้อยู่แล้ว ไม่มีการเปลี่ยนแปลง',
      }
    case 'refused':
      return { tone: 'error', text: result.message }
    case 'stale':
      return { tone: 'warning', text: result.message, reload: true }
    case 'conflict':
      return { tone: 'error', text: result.message, requestId: result.requestId }
    case 'unknown':
      return { tone: 'warning', text: result.message, requestId: result.requestId }
    case 'settlement-required':
      return { tone: 'warning', text: result.message, requestId: result.requestId }
    case 'blocked':
      return { tone: 'error', text: result.message }
  }
}

/** Results after which the panel re-reads its authoritative data. */
export function e2ShouldReload(result: E2WriteResult): boolean {
  return ['applied', 'no-op', 'stale', 'settlement-required'].includes(result.kind)
}

/** The write state of one vehicle panel: intent, message, dialog error,
 * settlement and send / resend. A refusal stays in the open dialog. */
export function useE2Writes(userId: string | null, vehicleId: string) {
  const { intent, inFlight } = useE2Intent(userId, vehicleId)
  const [message, setMessage] = useState<E2Message | null>(null)
  const [dialogError, setDialogError] = useState<{ text: string; overlap: E2OverlapDetails | null } | null>(null)

  const settle = useCallback((history: E2VehicleHistory) => {
    if (settleE2Intent(userId, vehicleId, history)) setMessage({ tone: 'success', text: E2_SETTLED_TEXT })
  }, [userId, vehicleId])

  const finish = useCallback((result: E2WriteResult | null, reload: () => void, inDialog: boolean) => {
    if (result === null) return null
    if (inDialog && (result.kind === 'refused' || result.kind === 'blocked')) {
      setDialogError({ text: result.message, overlap: result.kind === 'refused' ? result.overlap : null })
      return result
    }
    setMessage(e2ResultMessage(result))
    if (e2ShouldReload(result)) reload()
    return result
  }, [])

  const submit = useCallback(async (operation: string, body: Record<string, unknown>, path: string, reload: () => void) => {
    setDialogError(null)
    setMessage(null)
    return finish(await startE2Write({ userId, vehicleId, path, operation, body }), reload, true)
  }, [userId, vehicleId, finish])

  const resend = useCallback(async (reload: () => void) => {
    setMessage(null)
    return finish(await resendE2Write(userId, vehicleId), reload, false)
  }, [userId, vehicleId, finish])

  return { intent, inFlight, message, setMessage, dialogError, setDialogError, settle, submit, resend }
}

// ---------------------------------------------------------------------------
// Request bodies of the five operations (the dialog's form state → the exact
// backend schema; `operational_driver_assignment_schemas.py`, extra="forbid")
// ---------------------------------------------------------------------------

export type E2ReviseVariant = 'STATE' | 'SPLIT' | 'EXCLUDE' | 'VOID'

export interface E2Form {
  driverId: string
  mode: E2Mode | ''
  startDate: string
  endDate: string
  shiftStart: string
  shiftEnd: string
  shiftOffset: '0' | '1' | ''
  handover: boolean
  predecessorId: string
  reviseVariant: E2ReviseVariant
  splitFrom: string
  excludeDates: string[]
  dates: string[]
  earlyMode: 'NOW' | 'AFTER_DATE' | ''
  earlyDate: string
  reason: string
}

export function emptyE2Form(): E2Form {
  return {
    driverId: '', mode: '', startDate: '', endDate: '', shiftStart: '', shiftEnd: '', shiftOffset: '', handover: false,
    predecessorId: '', reviseVariant: 'STATE', splitFrom: '', excludeDates: [], dates: [], earlyMode: '', earlyDate: '',
    reason: '',
  }
}

/** The form prefilled with the target's CURRENT state (REVISE only edits it). */
export function formFromState(target: E2AssignmentState | null): E2Form {
  const form = emptyE2Form()
  const s = target?.state
  if (!s) return form
  return {
    ...form,
    driverId: s.assigned_driver_id ?? '',
    mode: (E2_MODES as readonly string[]).includes(s.mode ?? '') ? (s.mode as E2Mode) : '',
    startDate: s.start_date ?? '',
    endDate: s.end_date ?? '',
    shiftStart: s.shift_start_time ?? '',
    shiftEnd: s.shift_end_time ?? '',
    shiftOffset: s.shift_end_day_offset === '0' || s.shift_end_day_offset === '1' ? s.shift_end_day_offset : '',
  }
}

type Built = { body: Record<string, unknown> } | { error: string }

const isShift = (mode: E2Mode | '') => mode !== '' && E2_SHIFT_MODES.includes(mode)
const uniqueSorted = (dates: readonly string[]) => [...new Set(dates)].sort()

function shiftOf(form: E2Form): { start_time: string; end_time: string; end_day_offset: number } | string {
  if (!isHhMm(form.shiftStart) || !isHhMm(form.shiftEnd)) return 'กรุณาระบุเวลาเริ่มและเวลาสิ้นสุดของกะ (HH:MM)'
  if (form.shiftOffset === '') return 'กรุณาเลือกว่ากะสิ้นสุดในวันเดียวกันหรือวันถัดไป'
  return { start_time: form.shiftStart, end_time: form.shiftEnd, end_day_offset: Number(form.shiftOffset) }
}

function reasonError(form: E2Form, required: boolean): string | null {
  if (form.reason.length > E2_MAX_REASON_LENGTH) return `เหตุผลยาวได้ไม่เกิน ${E2_MAX_REASON_LENGTH} ตัวอักษร`
  if (required && form.reason.trim() === '') return 'กรุณาระบุเหตุผล'
  return null
}

/**
 * The exact request body of one operation (pure; exported for tests). Only
 * the fields of that operation's backend schema are sent (`extra="forbid"`).
 */
export function buildE2Body(
  operation: E2Operation,
  form: E2Form,
  target: E2AssignmentState | null,
  assignments: readonly E2AssignmentState[],
  today: string,
): Built {
  if (operation === 'CREATE') {
    if (form.driverId.trim() === '') return { error: 'กรุณาเลือกผู้ขับ (ระบบไม่เลือกให้)' }
    if (form.mode === '') return { error: 'กรุณาเลือกรูปแบบการมอบหมาย' }
    if (!isIsoDate(form.startDate) || !isIsoDate(form.endDate)) return { error: 'กรุณาระบุวันที่เริ่มต้นและวันที่สิ้นสุด' }
    const body: Record<string, unknown> = {
      operation, driver_id: form.driverId, mode: form.mode, start_date: form.startDate, end_date: form.endDate,
    }
    if (isShift(form.mode)) {
      const shift = shiftOf(form)
      if (typeof shift === 'string') return { error: shift }
      body.shift = shift
    }
    if (form.handover) {
      const pred = assignments.find((a) => a.event.event_id === form.predecessorId)
      if (!pred) return { error: 'กรุณาเลือกการมอบหมายก่อนหน้าที่จะส่งต่อ' }
      body.handover = { predecessor_event_id: pred.event.event_id, expected_revision_no: pred.event.revision_no }
    }
    // A2-5.4: a back-dated create needs a reason; a same-day create does not.
    const err = reasonError(form, form.startDate < today)
    if (err) return { error: err }
    if (form.reason.trim() !== '') body.reason_th = form.reason
    return { body }
  }

  if (!target) return { error: 'กรุณาเลือกการมอบหมาย' }
  const base: Record<string, unknown> = {
    operation, event_id: target.event.event_id, expected_revision_no: target.event.revision_no,
  }
  const err = reasonError(form, true)
  if (err) return { error: err }

  if (operation === 'CANCEL') return { body: { ...base, reason_th: form.reason } }

  if (operation === 'EARLY_END') {
    if (form.earlyMode === 'NOW') return { body: { ...base, end: { mode: 'NOW' }, reason_th: form.reason } }
    if (form.earlyMode === 'AFTER_DATE') {
      if (!isIsoDate(form.earlyDate)) return { error: 'กรุณาระบุวันที่สุดท้ายของการมอบหมาย' }
      return { body: { ...base, end: { mode: 'AFTER_DATE', date: form.earlyDate }, reason_th: form.reason } }
    }
    return { error: 'กรุณาเลือกเวลาสิ้นสุด' }
  }

  if (operation === 'SUBSTITUTE') {
    if (form.dates.length === 0 || !form.dates.every(isIsoDate)) return { error: 'กรุณาเพิ่มวันที่ของวัน/กะที่ให้ผู้ขับแทน' }
    if (form.driverId.trim() === '') return { error: 'กรุณาเลือกผู้ขับแทน (ระบบไม่เลือกให้)' }
    return { body: { ...base, dates: uniqueSorted(form.dates), driver_id: form.driverId, reason_th: form.reason } }
  }

  // REVISE
  if (form.reviseVariant === 'VOID') return { body: { ...base, reason_th: form.reason, void_elapsed: true } }
  const state = target.state
  const mode = (state?.mode ?? '') as E2Mode | ''
  if (!state || mode === '') return { error: 'อ่านสถานะปัจจุบันของการมอบหมายนี้ไม่ได้' }
  const current = formFromState(target)
  const pick = form.reviseVariant === 'STATE' ? form : current
  if (pick.driverId.trim() === '') return { error: 'กรุณาเลือกผู้ขับ' }
  if (!isIsoDate(pick.startDate) || !isIsoDate(pick.endDate)) return { error: 'กรุณาระบุวันที่เริ่มต้นและวันที่สิ้นสุด' }
  const body: Record<string, unknown> = {
    ...base, reason_th: form.reason, driver_id: pick.driverId, start_date: pick.startDate, end_date: pick.endDate,
  }
  if (isShift(mode)) {
    // SPLIT sends the NEW applied times; STATE the edited ones; EXCLUDE the current ones.
    const shift = shiftOf(form.reviseVariant === 'EXCLUDE' ? current : form)
    if (typeof shift === 'string') return { error: shift }
    body.shift = shift
  }
  if (form.reviseVariant === 'SPLIT') {
    if (!isShift(mode)) return { error: 'แยกช่วงเวลากะได้เฉพาะการมอบหมายแบบกะ' }
    if (!isIsoDate(form.splitFrom)) return { error: 'กรุณาระบุวันที่เริ่มใช้เวลากะใหม่' }
    body.split_from_date = form.splitFrom
  }
  if (form.reviseVariant === 'EXCLUDE') {
    if (form.excludeDates.length === 0 || !form.excludeDates.every(isIsoDate)) return { error: 'กรุณาเพิ่มวันที่ที่ต้องการตัดออก' }
    body.exclude_dates = uniqueSorted(form.excludeDates)
  }
  return { body }
}
