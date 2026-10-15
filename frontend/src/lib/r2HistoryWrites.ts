/**
 * R2 Batch R2-C2a — request intents of the five R2f history-write families
 * (Personnel↔Technician / Account / Driver links, equipment caretaker events,
 * permanent responsible-driver events). Its own module: the accepted
 * `lifecycle.ts`, `registryPending.ts` and `technicianV2.ts` are untouched.
 *
 * Owner safety correction C2a-2 (strict, family-aware outcomes):
 * - An intent (UUID v4 from `crypto.getRandomValues`, the exact path and the
 *   exact serialized body) is written to localStorage and read back BEFORE the
 *   request is sent, under `crane.r2HistoryPending.v1:<userId>:<family>:<entity>`.
 *   No user id, no secure random source or no working storage → the write is
 *   refused here (fail closed); an untracked mutation is never sent.
 * - At most one unresolved intent per user / family / entity, and one request
 *   in flight per key.
 * - Default outcome: KEEP as UNKNOWN. A first attempt is removed only for a
 *   correlated (body `request_id` and, when present, the `X-Request-Id`
 *   header equal the intent's id), shape-validated success, or a refusal whose
 *   (status, code) is on the family's explicit pre-write list — every code on
 *   it is raised by the backend before its single history append (W1), see
 *   the PRE_WRITE / POST_REPLAY tables below with their source references.
 * - 409 REQUEST_ID_REUSED → KEEP as CONFLICT. W1 failure → removed only when
 *   `history_write_outcome` is exactly "rejected"; otherwise KEEP. A link
 *   projection (W2) failure with the event recorded → KEEP as RECORDED until
 *   the link history shows the request (the history then offers Reconcile).
 * - Once an intent has been uncertain, no response removes it (as in
 *   `registryPending.ts`): a success or replay keeps it for SETTLEMENT against
 *   the authoritative read (link history: the event carrying this request id;
 *   caretaker / responsibility timeline: a returned record id). A refusal or a
 *   no-op of a resend proves nothing about the earlier attempt, even when it is
 *   raised after the backend's request-id replay lookup: the backend holds no
 *   write lock and looks the id up in a history snapshot read before it checks,
 *   so an earlier attempt still running on the server may append after that
 *   read. Such an intent stays UNKNOWN (fail closed) until a settlement.
 * - A CONFLICT (REQUEST_ID_REUSED) intent is never resent and never settled:
 *   the id is recorded with a different body, and no read shows which body.
 *   It needs an authorized investigation (the panel says so).
 * - Never an automatic retry and never a new id: a resend is an explicit user
 *   action with the SAME id, path and stored body.
 *
 * localStorage is not a security boundary; the backend stays authoritative.
 */
import { useCallback, useMemo, useState, useSyncExternalStore } from 'react'
import { apiMutation, type MutationResponse } from './apiClient'
import { describeErrorCode } from './labels'
import { CONSISTENCIES, CURRENT_STATUSES, isObj, LINK_KINDS, TIMELINE_STATUSES, type LinkHistory, type LinkKind, type TimelinePeriod } from './r2History'

export type R2Family = 'technician-link' | 'account-link' | 'driver-link' | 'caretaker' | 'responsibility'
export type R2IntentState = 'SUBMITTING' | 'UNKNOWN' | 'CONFLICT' | 'RECORDED'

export interface R2Intent {
  v: 1
  family: R2Family
  entity_id: string
  request_id: string
  /** The API path under /api/v1, exactly as first sent. */
  path: string
  /** The body exactly as first sent (`body_json` is its serialization). */
  body: Record<string, unknown>
  body_json: string
  /** A display label of the operation (e.g. LINK, TRANSFER, RECONCILE). */
  operation: string
  created_at: string
  state: R2IntentState
  /** True once any attempt's outcome was not proven. */
  prior_uncertain: boolean
  /** Record ids proven by a correlated success / replay, for settlement. */
  record_ids: string[]
}

export type R2BlockedReason = 'no-user' | 'crypto' | 'storage' | 'pending' | 'in-flight'

export type R2WriteResult =
  | { kind: 'applied'; recordIds: string[]; body: Record<string, unknown> }
  | { kind: 'no-op' }
  | { kind: 'refused'; status: number; code: string; message: string; details: Record<string, unknown> | null }
  | { kind: 'stale'; code: string; message: string }
  | { kind: 'mismatch'; code: string; message: string }
  | { kind: 'recorded-projection-pending'; recordId: string; message: string }
  | { kind: 'conflict'; code: string; message: string; requestId: string }
  | { kind: 'unknown'; requestId: string; message: string; refused?: { status: number; code: string } }
  | { kind: 'settlement-required'; requestId: string; recordIds: string[]; message: string }
  | { kind: 'blocked'; reason: R2BlockedReason; message: string }

// ---------------------------------------------------------------------------
// Family contracts. Every (status, code) below is raised by the backend before
// its W1 history append; POST_REPLAY ones are raised only after the request-id
// replay lookup (same id + same body → replay; different body → REUSED). Both
// lists confirm a zero-write of a FIRST attempt only; neither proves anything
// about an earlier uncertain attempt (see the header).
// Sources: backend/app/domain/personnel_link.py (change / reconcile),
// equipment_caretaker.py (record_event / _correct / _check_new_caretaker),
// crane_driver_responsibility.py (record_event / _correct / _check_new_driver),
// effective_time.py, request_id_dependency.py, registry_write_support.py.
// ---------------------------------------------------------------------------

const pair = (status: number, code: string) => `${status}:${code}`

const COMMON_PRE_WRITE = [
  pair(403, 'HTTP_ERROR'),
  pair(422, 'REQUEST_ID_REQUIRED'),
  pair(422, 'VALIDATION_ERROR'),
  pair(422, 'REASON_REQUIRED'),
  pair(503, 'REGISTRY_DATA_CONTEXT_NOT_CONFIGURED'),
]

const EFFECTIVE_CODES = [
  'EFFECTIVE_MODE_NOT_ALLOWED', 'EFFECTIVE_MODE_INVALID', 'EFFECTIVE_TIME_OFFSET_REQUIRED',
  'EFFECTIVE_TIME_PRECISION', 'FUTURE_EFFECTIVE_NOT_ALLOWED', 'EFFECTIVE_TIME_OUT_OF_RANGE',
].map((code) => pair(422, code))

interface FamilySpec {
  w1: string
  /** Link families only: the W2 projection failure. */
  w2: string | null
  stale: string
  /** Link families only. */
  mismatch: string | null
  /** Record ids of a validated `changed: true` body, or null when malformed. */
  applied: (json: Record<string, unknown>) => string[] | null
  preWrite: ReadonlySet<string>
}

const nonEmpty = (v: unknown): v is string => typeof v === 'string' && v.length > 0
const strOrNull = (v: unknown) => v === null || typeof v === 'string'

function linkFamily(kind: LinkKind): FamilySpec {
  const { label: L, targetLabel: T, targetReadPrefix: TR, idField: f } = LINK_KINDS[kind]
  const postReplay = [
    pair(409, `${T}_ID_AMBIGUOUS`), pair(422, `${T}_SCOPE_UNPROVEN`), pair(422, `${T}_NOT_FOUND`),
    pair(409, `${T}_ALREADY_LINKED`), pair(409, `${L}_STALE`), pair(409, `${L}_RELINK_REQUIRED`),
    pair(409, `${L}_LINK_REQUIRED`), pair(409, `${L}_RECONCILIATION_NOT_REQUIRED`),
    pair(409, `${L}_RELATED_REQUEST_INVALID`),
  ]
  return {
    w1: `${L}_HISTORY_WRITE_FAILED`,
    w2: `${L}_PROJECTION_WRITE_FAILED`,
    stale: `${L}_STALE`,
    mismatch: `${L}_MISMATCH`,
    applied: (json) =>
      nonEmpty(json.link_event_id) && strOrNull(json[`previous_${f}`]) && strOrNull(json[`new_${f}`])
        && (CONSISTENCIES as readonly unknown[]).includes(json.relationship_consistency_after)
        ? [json.link_event_id] : null,
    preWrite: new Set([
      ...COMMON_PRE_WRITE,
      pair(422, `${L}_TARGET_NOT_ALLOWED`), pair(422, `${L}_TARGET_REQUIRED`),
      pair(404, 'PERSONNEL_NOT_FOUND'), pair(409, 'PERSONNEL_ID_AMBIGUOUS'),
      pair(503, 'PERSONNEL_MASTER_READ_FAILED'), pair(503, `${L}_HISTORY_READ_FAILED`), pair(503, `${TR}_READ_FAILED`),
      ...postReplay,
    ]),
  }
}

const timelineApplied = (json: Record<string, unknown>): string[] | null =>
  nonEmpty(json.record_id) && nonEmpty(json.event_id)
    && (TIMELINE_STATUSES as readonly unknown[]).includes(json.timeline_status_after)
    && (CURRENT_STATUSES as readonly unknown[]).includes(json.current_status)
    ? [json.record_id] : null

const CARETAKER_POST_REPLAY = [
  pair(409, 'CARETAKER_HISTORY_STALE'), pair(404, 'CARETAKER_EVENT_NOT_FOUND'), pair(409, 'CARETAKER_EVENT_CANCELLED'),
  pair(409, 'CARETAKER_TIMELINE_AMBIGUOUS'), pair(409, 'CARETAKER_EVENT_SAME_INSTANT'),
  pair(409, 'CARETAKER_INSERTION_NOT_HISTORICAL'), pair(409, 'CARETAKER_EVENT_NOT_LATEST'),
  pair(409, 'CARETAKER_END_WITHOUT_CARETAKER'), pair(422, 'CARETAKER_CORRECTION_CHANGES_EVENT_NATURE'),
  pair(409, 'TECHNICIAN_ID_AMBIGUOUS'), pair(422, 'TECHNICIAN_SCOPE_UNPROVEN'), pair(422, 'TECHNICIAN_NOT_FOUND'),
  pair(422, 'TECHNICIAN_NOT_ACTIVE'), pair(422, 'TECHNICIAN_PERSONNEL_UNRESOLVED'),
  pair(409, 'TECHNICIAN_PERSONNEL_AMBIGUOUS'), pair(422, 'PERSONNEL_NOT_ACTIVE'),
]

const RESPONSIBILITY_POST_REPLAY = [
  pair(409, 'DRIVER_RESPONSIBILITY_HISTORY_STALE'), pair(404, 'DRIVER_RESPONSIBILITY_EVENT_NOT_FOUND'),
  pair(409, 'DRIVER_RESPONSIBILITY_EVENT_CANCELLED'), pair(409, 'DRIVER_RESPONSIBILITY_TIMELINE_AMBIGUOUS'),
  pair(409, 'DRIVER_RESPONSIBILITY_EVENT_SAME_INSTANT'), pair(409, 'DRIVER_RESPONSIBILITY_EVENT_NOT_LATEST'),
  pair(409, 'DRIVER_RESPONSIBILITY_INSERTION_NOT_HISTORICAL'), pair(409, 'DRIVER_RESPONSIBILITY_END_WITHOUT_DRIVER'),
  pair(422, 'DRIVER_RESPONSIBILITY_CORRECTION_CHANGES_EVENT_NATURE'), pair(409, 'DRIVER_ID_AMBIGUOUS'),
  pair(422, 'DRIVER_SCOPE_UNPROVEN'), pair(422, 'DRIVER_NOT_FOUND'), pair(422, 'DRIVER_NOT_ACTIVE'),
  pair(409, 'DRIVER_PERSONNEL_AMBIGUOUS'), pair(422, 'PERSONNEL_NOT_ACTIVE'),
]

export const FAMILIES: Record<R2Family, FamilySpec> = {
  'technician-link': linkFamily('technician'),
  'account-link': linkFamily('account'),
  'driver-link': linkFamily('driver'),
  caretaker: {
    w1: 'CARETAKER_HISTORY_WRITE_FAILED',
    w2: null,
    stale: 'CARETAKER_HISTORY_STALE',
    mismatch: null,
    applied: timelineApplied,
    preWrite: new Set([
      ...COMMON_PRE_WRITE, ...EFFECTIVE_CODES,
      pair(404, 'EQUIPMENT_NOT_FOUND'), pair(409, 'EQUIPMENT_ID_AMBIGUOUS'), pair(422, 'EQUIPMENT_SCOPE_UNPROVEN'),
      pair(422, 'CARETAKER_TECHNICIAN_REQUIRED'), pair(422, 'CARETAKER_OPERATION_INVALID'),
      pair(503, 'EQUIPMENT_MASTER_READ_FAILED'), pair(503, 'EQUIPMENT_CARETAKER_HISTORY_READ_FAILED'),
      pair(503, 'TECHNICIAN_MASTER_READ_FAILED'), pair(503, 'PERSONNEL_MASTER_READ_FAILED'),
      ...CARETAKER_POST_REPLAY,
    ]),
  },
  responsibility: {
    w1: 'DRIVER_RESPONSIBILITY_HISTORY_WRITE_FAILED',
    w2: null,
    stale: 'DRIVER_RESPONSIBILITY_HISTORY_STALE',
    mismatch: null,
    applied: timelineApplied,
    preWrite: new Set([
      ...COMMON_PRE_WRITE, ...EFFECTIVE_CODES,
      pair(404, 'VEHICLE_NOT_FOUND'), pair(409, 'VEHICLE_ID_AMBIGUOUS'), pair(422, 'VEHICLE_SCOPE_UNPROVEN'),
      pair(422, 'DRIVER_RESPONSIBILITY_DRIVER_REQUIRED'), pair(422, 'DRIVER_RESPONSIBILITY_OPERATION_INVALID'),
      pair(503, 'VEHICLE_MASTER_READ_FAILED'), pair(503, 'DRIVER_MASTER_READ_FAILED'),
      pair(503, 'CRANE_DRIVER_RESPONSIBILITY_HISTORY_READ_FAILED'), pair(503, 'PERSONNEL_MASTER_READ_FAILED'),
      ...RESPONSIBILITY_POST_REPLAY,
    ]),
  },
}

// ---------------------------------------------------------------------------
// Messages
// ---------------------------------------------------------------------------

export const UNKNOWN_MESSAGE =
  'ไม่ทราบผลการบันทึก (อาจบันทึกแล้วหรือยังไม่บันทึก) ระบบไม่ได้ส่งซ้ำอัตโนมัติ กรุณาโหลดข้อมูลล่าสุดเพื่อตรวจสอบ หรือกด "ส่งคำขอเดิมอีกครั้ง"'
export const SETTLEMENT_MESSAGE = 'ระบบตอบรับคำขอนี้แล้ว กำลังตรวจสอบกับประวัติล่าสุดก่อนปิดรายการค้าง'
export const CONFLICT_MESSAGE =
  'รหัสคำขอนี้ถูกใช้กับข้อมูลอื่นแล้ว ระบบไม่ได้บันทึกคำขอนี้ซ้ำ รายการค้างนี้ต้องตรวจสอบก่อนบันทึกรายการใหม่'
export const CONFLICT_ESCALATION =
  'ระบบยืนยันผลของคำขอนี้จากหน้าจอนี้ไม่ได้ และจะไม่ส่งคำขอใหม่แทน กรุณาแจ้งผู้ดูแลระบบพร้อมรหัสคำขอนี้เพื่อตรวจสอบ'
export const PROJECTION_MESSAGE =
  'บันทึกประวัติแล้ว แต่ปรับข้อมูลความเชื่อมโยงปัจจุบันไม่สำเร็จ ข้อมูลปัจจุบันจึงยังไม่ตรงกับประวัติ กรุณาโหลดข้อมูลล่าสุดแล้วใช้ "ปรับข้อมูลให้ตรงกับประวัติ"'
export const RESEND_REFUSED_MESSAGE =
  'การส่งคำขอเดิมอีกครั้งถูกปฏิเสธ แต่การปฏิเสธนี้ไม่ได้ยืนยันว่าคำขอครั้งก่อนไม่ได้ถูกบันทึก รายการค้างจึงยังคงอยู่: '

const BLOCKED_MESSAGES: Record<R2BlockedReason, string> = {
  'no-user': 'ยังระบุผู้ใช้งานไม่ได้ จึงยังบันทึกไม่ได้ กรุณาโหลดหน้านี้ใหม่',
  crypto: 'เบราว์เซอร์นี้สร้างรหัสคำขอที่ปลอดภัยไม่ได้ จึงไม่ส่งคำขอ',
  storage: 'บันทึกรายการคำขอไว้ในเบราว์เซอร์ไม่ได้ จึงไม่ส่งคำขอ (เพื่อไม่ให้เกิดคำขอที่ติดตามผลไม่ได้)',
  pending: 'ยังมีคำขอเดิมที่ยังไม่ทราบผลหรือรอตรวจสอบ ต้องจัดการคำขอนั้นก่อน',
  'in-flight': 'กำลังส่งคำขออยู่ กรุณารอผลก่อน',
}

// ---------------------------------------------------------------------------
// Request id and storage
// ---------------------------------------------------------------------------

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

/** A UUID v4 from `crypto.getRandomValues`, or null (never Math.random). */
export function newR2RequestId(): string | null {
  try {
    if (typeof crypto === 'undefined' || typeof crypto.getRandomValues !== 'function') return null
    const bytes = new Uint8Array(16)
    crypto.getRandomValues(bytes)
    bytes[6] = (bytes[6] & 0x0f) | 0x40
    bytes[8] = (bytes[8] & 0x3f) | 0x80
    const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
    const id = `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
    return UUID_V4.test(id) ? id : null
  } catch {
    return null
  }
}

export const STORAGE_PREFIX = 'crane.r2HistoryPending.v1'

export function r2IntentKey(userId: string, family: R2Family, entityId: string): string {
  return `${STORAGE_PREFIX}:${userId}:${family}:${entityId}`
}

const inflight = new Set<string>()
const listeners = new Set<() => void>()

/** Panels re-render on any intent change (this page). */
export function subscribeR2Intents(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function emit(): void {
  for (const listener of listeners) listener()
}

function store(key: string, intent: R2Intent): boolean {
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
    // Nothing else to do: the intent simply stays visible.
  }
}

function isIntent(v: unknown): v is R2Intent {
  return isObj(v) && v.v === 1 && typeof v.family === 'string' && v.family in FAMILIES && typeof v.entity_id === 'string'
    && typeof v.request_id === 'string' && UUID_V4.test(v.request_id) && typeof v.path === 'string'
    && isObj(v.body) && typeof v.body_json === 'string' && JSON.stringify(v.body) === v.body_json
    && typeof v.operation === 'string' && typeof v.created_at === 'string'
    && ['SUBMITTING', 'UNKNOWN', 'CONFLICT', 'RECORDED'].includes(v.state as string)
    && typeof v.prior_uncertain === 'boolean' && Array.isArray(v.record_ids) && v.record_ids.every((r) => typeof r === 'string')
}

/** The stored intent. An unparseable entry is reported as `corrupt` (it still
 * blocks new writes: nothing is assumed about it). A SUBMITTING intent with
 * no request in flight on this page is shown as UNKNOWN. */
export function pendingR2Intent(
  userId: string | null, family: R2Family, entityId: string,
): R2Intent | 'corrupt' | null {
  if (!userId) return null
  const key = r2IntentKey(userId, family, entityId)
  let raw: string | null
  try {
    raw = window.localStorage.getItem(key)
  } catch {
    return null
  }
  if (raw === null) return null
  try {
    const parsed: unknown = JSON.parse(raw)
    if (!isIntent(parsed) || parsed.family !== family || parsed.entity_id !== entityId) return 'corrupt'
    return parsed.state === 'SUBMITTING' && !inflight.has(key) ? { ...parsed, state: 'UNKNOWN' } : parsed
  } catch {
    return 'corrupt'
  }
}

export function isR2InFlight(userId: string | null, family: R2Family, entityId: string): boolean {
  return !!userId && inflight.has(r2IntentKey(userId, family, entityId))
}

// ---------------------------------------------------------------------------
// Classification
// ---------------------------------------------------------------------------

export interface R2Classification {
  action: 'REMOVE' | 'KEEP'
  state?: R2IntentState
  recordIds?: string[]
  result: R2WriteResult
}

function errorEnvelope(json: unknown): { code: string; requestId: unknown; details: Record<string, unknown> | null } | null {
  if (!isObj(json) || !isObj(json.error) || typeof json.error.code !== 'string') return null
  return {
    code: json.error.code,
    requestId: json.error.request_id,
    details: isObj(json.error.details) ? json.error.details : null,
  }
}

/** The outcome of ONE response for the intent (pure; exported for tests). */
export function classifyR2Response(
  response: MutationResponse,
  intent: Pick<R2Intent, 'family' | 'request_id' | 'prior_uncertain'>,
): R2Classification {
  const rid = intent.request_id
  const spec = FAMILIES[intent.family]
  const unknown = (refused?: { status: number; code: string }): R2Classification => ({
    action: 'KEEP', state: 'UNKNOWN',
    result: {
      kind: 'unknown', requestId: rid,
      message: refused ? `${RESEND_REFUSED_MESSAGE}${describeErrorCode(refused.code)}` : UNKNOWN_MESSAGE,
      ...(refused ? { refused } : {}),
    },
  })
  const settle = (recordIds: string[]): R2Classification => ({
    action: 'KEEP', state: 'UNKNOWN', recordIds,
    result: { kind: 'settlement-required', requestId: rid, recordIds, message: SETTLEMENT_MESSAGE },
  })
  if (response.kind !== 'http') return unknown()
  if (response.headerRequestId !== null && response.headerRequestId !== rid) return unknown()
  const { status, json } = response
  if (!isObj(json)) return unknown()

  if (status === 200) {
    if (json.request_id !== rid) return unknown()
    if ('replayed' in json) {
      const ids = json.record_ids
      const valid = json.replayed === true && Array.isArray(ids) && ids.length > 0 && ids.every(nonEmpty)
      // A replay proves the request was recorded; settle it against the history.
      return valid ? settle(ids as string[]) : unknown()
    }
    // A no-op of a resend proves nothing about the earlier attempt (header).
    if (json.changed === false) return intent.prior_uncertain ? unknown() : { action: 'REMOVE', result: { kind: 'no-op' } }
    if (json.changed === true) {
      const recordIds = spec.applied(json)
      if (recordIds === null) return unknown()
      if (intent.prior_uncertain) return settle(recordIds)
      return { action: 'REMOVE', recordIds, result: { kind: 'applied', recordIds, body: json } }
    }
    return unknown()
  }

  const error = errorEnvelope(json)
  if (error === null || error.requestId !== rid) return unknown()
  const { code, details } = error
  const message = describeErrorCode(code)
  if (status === 409 && code === 'REQUEST_ID_REUSED') {
    return { action: 'KEEP', state: 'CONFLICT', result: { kind: 'conflict', code, message: CONFLICT_MESSAGE, requestId: rid } }
  }
  if (status === 503 && code === spec.w1) {
    if (details?.history_write_outcome === 'rejected' && !intent.prior_uncertain) {
      return { action: 'REMOVE', result: { kind: 'refused', status, code, message, details } }
    }
    return unknown(details?.history_write_outcome === 'rejected' ? { status, code } : undefined)
  }
  if (spec.w2 !== null && status === 503 && code === spec.w2) {
    if (details?.event_recorded === true && nonEmpty(details.record_id)) {
      return {
        action: 'KEEP', state: 'RECORDED', recordIds: [details.record_id],
        result: { kind: 'recorded-projection-pending', recordId: details.record_id, message: PROJECTION_MESSAGE },
      }
    }
    return unknown()
  }
  if (intent.prior_uncertain) {
    // No refusal of a resend proves the earlier attempt was not recorded (not
    // even one raised after the replay lookup, see the header; MISMATCH may be
    // the earlier attempt's own recorded event): the intent is kept.
    return unknown(spec.preWrite.has(pair(status, code)) ? { status, code } : undefined)
  }
  if (spec.mismatch !== null && status === 409 && code === spec.mismatch) {
    return { action: 'REMOVE', result: { kind: 'mismatch', code, message } }
  }
  if (!spec.preWrite.has(pair(status, code))) return unknown()
  if (status === 409 && code === spec.stale) return { action: 'REMOVE', result: { kind: 'stale', code, message } }
  return { action: 'REMOVE', result: { kind: 'refused', status, code, message, details } }
}

// ---------------------------------------------------------------------------
// Send / resend / settle
// ---------------------------------------------------------------------------

async function dispatch(key: string, intent: R2Intent): Promise<R2WriteResult> {
  inflight.add(key)
  emit()
  let response: MutationResponse
  try {
    response = await apiMutation(intent.path, 'POST', JSON.parse(intent.body_json), { requestId: intent.request_id })
  } finally {
    inflight.delete(key)
  }
  const outcome = classifyR2Response(response, intent)
  if (outcome.action === 'REMOVE') {
    remove(key)
  } else {
    const next: R2Intent = {
      ...intent,
      state: outcome.state ?? 'UNKNOWN',
      prior_uncertain: intent.prior_uncertain || outcome.result.kind === 'unknown' || outcome.state === 'UNKNOWN',
      record_ids: outcome.recordIds ?? intent.record_ids,
    }
    store(key, next)
  }
  emit()
  return outcome.result
}

function blocked(reason: R2BlockedReason): R2WriteResult {
  return { kind: 'blocked', reason, message: BLOCKED_MESSAGES[reason] }
}

export interface R2WriteRequest {
  userId: string | null
  family: R2Family
  entityId: string
  path: string
  operation: string
  body: Record<string, unknown>
}

/** A NEW user intent: a new id, stored (and read back) before sending. */
export async function startR2Write(request: R2WriteRequest): Promise<R2WriteResult> {
  const { userId, family, entityId } = request
  if (!userId) return blocked('no-user')
  const key = r2IntentKey(userId, family, entityId)
  if (inflight.has(key)) return blocked('in-flight')
  if (pendingR2Intent(userId, family, entityId) !== null) return blocked('pending')
  const requestId = newR2RequestId()
  if (requestId === null) return blocked('crypto')
  const intent: R2Intent = {
    v: 1, family, entity_id: entityId, request_id: requestId, path: request.path, body: request.body,
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

/** The explicit resend of the stored intent: SAME id, path and body. Only an
 * UNKNOWN intent can be resent; a resend is always after an uncertainty. */
export async function resendR2Write(userId: string | null, family: R2Family, entityId: string): Promise<R2WriteResult | null> {
  if (!userId) return blocked('no-user')
  const key = r2IntentKey(userId, family, entityId)
  if (inflight.has(key)) return blocked('in-flight')
  const intent = pendingR2Intent(userId, family, entityId)
  if (intent === null || intent === 'corrupt' || intent.state !== 'UNKNOWN') return null
  const next: R2Intent = { ...intent, state: 'SUBMITTING', prior_uncertain: true }
  if (!store(key, next)) return blocked('storage')
  return dispatch(key, next)
}

export type R2Settlement = { kind: 'settled'; mismatch: boolean } | null

/** Settlement against the authoritative read. Link families: the history holds
 * an event carrying this request id. Timelines: a period carries a record id
 * proven by a correlated response. Otherwise (and always for a CONFLICT)
 * nothing changes. */
export function settleR2Intent(
  userId: string | null,
  family: R2Family,
  entityId: string,
  evidence: { kind: 'link'; history: LinkHistory } | { kind: 'timeline'; events: readonly TimelinePeriod[] },
): R2Settlement {
  if (!userId) return null
  const key = r2IntentKey(userId, family, entityId)
  if (inflight.has(key)) return null
  const intent = pendingR2Intent(userId, family, entityId)
  // A CONFLICT is never settled: a history entry with this id may carry another body.
  if (intent === null || intent === 'corrupt' || intent.state === 'CONFLICT') return null
  let settled = false
  let mismatch = false
  if (evidence.kind === 'link') {
    settled = evidence.history.events.some((e) => e.request_id === intent.request_id)
    mismatch = settled && evidence.history.consistency === 'MISMATCH'
  } else if (intent.record_ids.length > 0) {
    settled = evidence.events.some((e) => intent.record_ids.includes(e.head_record_id) || intent.record_ids.includes(e.event_id))
  }
  if (!settled) return null
  remove(key)
  emit()
  return { kind: 'settled', mismatch }
}

function snapshot(userId: string | null, family: R2Family, entityId: string): string {
  if (!userId) return ''
  const key = r2IntentKey(userId, family, entityId)
  let raw: string | null = null
  try {
    raw = window.localStorage.getItem(key)
  } catch {
    raw = null
  }
  return `${inflight.has(key) ? 'F' : '-'}${raw ?? ''}`
}

/** The pending intent of one entity / family and whether a request is in
 * flight, re-rendered on every change made on this page. */
export function useR2Intent(userId: string | null, family: R2Family, entityId: string): {
  intent: R2Intent | 'corrupt' | null
  inFlight: boolean
} {
  const raw = useSyncExternalStore(subscribeR2Intents, () => snapshot(userId, family, entityId))
  return useMemo(
    () => ({ intent: pendingR2Intent(userId, family, entityId), inFlight: raw.startsWith('F') }),
    // `raw` is the change signal of the stored intent and the in-flight flag.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [raw, userId, family, entityId],
  )
}

// ---------------------------------------------------------------------------
// Panel messages and the shared write hook
// ---------------------------------------------------------------------------

export type R2Message = {
  tone: 'success' | 'warning' | 'error'
  text: string
  requestId?: string | null
  reload?: boolean
}

/** The message of one write result (null = nothing to show). */
export function r2ResultMessage(result: R2WriteResult): R2Message | null {
  switch (result.kind) {
    case 'applied':
      return { tone: 'success', text: 'บันทึกเรียบร้อยแล้ว' }
    case 'no-op':
      return { tone: 'success', text: 'ข้อมูลเป็นค่านี้อยู่แล้ว ไม่มีการเปลี่ยนแปลง' }
    case 'refused':
      return { tone: 'error', text: result.message }
    case 'stale':
      return { tone: 'warning', text: result.message, reload: true }
    case 'mismatch':
      return { tone: 'error', text: result.message, reload: true }
    case 'recorded-projection-pending':
      return { tone: 'error', text: result.message, reload: true }
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
export function r2ShouldReload(result: R2WriteResult): boolean {
  return ['applied', 'no-op', 'stale', 'mismatch', 'recorded-projection-pending', 'settlement-required']
    .includes(result.kind)
}

export const SETTLED_TEXT = 'ตรวจสอบกับประวัติล่าสุดแล้ว: คำขอเดิมถูกบันทึกแล้ว'
export const SETTLED_MISMATCH_TEXT =
  'ตรวจสอบกับประวัติล่าสุดแล้ว: คำขอเดิมถูกบันทึกแล้ว แต่ข้อมูลปัจจุบันยังไม่ตรงกับประวัติ ต้องปรับข้อมูลให้ตรงกับประวัติ'

export type R2Evidence = { kind: 'link'; history: LinkHistory } | { kind: 'timeline'; events: readonly TimelinePeriod[] }

/** The write state of one panel (one family / entity): the pending intent,
 * the panel message, the dialog error, settlement and send / resend. Only a
 * confirmed or settlement-relevant outcome re-reads the authoritative data. */
export function useR2Writes(userId: string | null, family: R2Family, entityId: string) {
  const { intent, inFlight } = useR2Intent(userId, family, entityId)
  const [message, setMessage] = useState<R2Message | null>(null)
  const [dialogError, setDialogError] = useState<string | null>(null)

  const settle = useCallback((evidence: R2Evidence) => {
    const settled = settleR2Intent(userId, family, entityId, evidence)
    if (settled) setMessage({ tone: settled.mismatch ? 'error' : 'success', text: settled.mismatch ? SETTLED_MISMATCH_TEXT : SETTLED_TEXT })
  }, [userId, family, entityId])

  const finish = useCallback((result: R2WriteResult | null, reload: () => void, inDialog: boolean) => {
    if (result === null) return null
    if (inDialog && (result.kind === 'refused' || result.kind === 'blocked')) {
      setDialogError(result.message)
      return result
    }
    setMessage(r2ResultMessage(result))
    if (r2ShouldReload(result)) reload()
    return result
  }, [])

  const submit = useCallback(async (path: string, operation: string, body: Record<string, unknown>, reload: () => void) => {
    setDialogError(null)
    setMessage(null)
    return finish(await startR2Write({ userId, family, entityId, path, operation, body }), reload, true)
  }, [userId, family, entityId, finish])

  const resend = useCallback(async (reload: () => void) => {
    setMessage(null)
    return finish(await resendR2Write(userId, family, entityId), reload, false)
  }, [userId, family, entityId, finish])

  return { intent, inFlight, message, setMessage, dialogError, setDialogError, settle, submit, resend }
}
