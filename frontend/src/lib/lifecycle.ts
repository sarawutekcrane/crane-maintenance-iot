/**
 * R2 Batch R2e — personnel / department lifecycle requests (deactivate,
 * reactivate, reconcile) with the same request-intent discipline as the
 * registry mutations (`registryPending.ts`), kept in its own module so the
 * accepted registry bookkeeping is not touched:
 *
 * - An intent (request id + exact body) is stored BEFORE the request is sent,
 *   under `crane.lifecyclePending.v1:<userId>:<entity>:<id>` (localStorage;
 *   page memory when storage is unavailable).
 * - A response removes the intent only when its outcome is PROVEN: a 200, or a
 *   refusal the backend raises before any write (403/404/409/422, a rejected
 *   history write), or a recorded event whose state write failed (the history
 *   then shows MISMATCH and an explicit reconciliation finishes it).
 * - Review fix R2: `409 <ENTITY>_LIFECYCLE_MISMATCH` is its own outcome
 *   (`mismatch`), never success, replay or stale. On a same-id resend after an
 *   unknown outcome it proves the earlier event was recorded while the record's
 *   state was not; the intent is cleared and the UI moves to the explicit
 *   reconciliation. A `replayed` 200 (only returned while the record is
 *   consistent) stays a proven completed replay.
 * - Anything else (other 5xx, an unknown history-write outcome, a transport
 *   failure or timeout) KEEPS the intent as UNKNOWN: neither success nor
 *   failure is claimed.
 * - No automatic retry and no new request id: a resend is an explicit user
 *   action with the SAME request id and the SAME stored body.
 *
 * localStorage is not a security boundary; the backend stays authoritative.
 */
import { apiMutation, type MutationResponse } from './apiClient'
import { describeErrorCode } from './labels'

export type LifecycleEntity = 'personnel' | 'departments'
export type LifecycleOperation = 'deactivations' | 'reactivations' | 'lifecycle-reconciliations'

export interface LifecycleIntent {
  requestId: string
  operation: LifecycleOperation
  body: Record<string, unknown>
  createdAt: string
}

export type LifecycleResult =
  | { kind: 'changed' | 'no-op' | 'replayed' }
  | { kind: 'stale'; code: string; message: string }
  | { kind: 'mismatch'; code: string; message: string }
  | { kind: 'refused'; code: string; message: string; status: number; requestId: string | null }
  | { kind: 'recorded-state-pending'; message: string; requestId: string | null }
  | { kind: 'unknown'; message: string; requestId: string }

const memory = new Map<string, string>()

function key(userId: string | null, entity: LifecycleEntity, id: string): string {
  return `crane.lifecyclePending.v1:${userId ?? 'anonymous'}:${entity}:${id}`
}

function read(storageKey: string): string | null {
  try {
    return window.localStorage.getItem(storageKey)
  } catch {
    return memory.get(storageKey) ?? null
  }
}

function write(storageKey: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(storageKey)
    else window.localStorage.setItem(storageKey, value)
  } catch {
    if (value === null) memory.delete(storageKey)
    else memory.set(storageKey, value)
  }
}

export function pendingLifecycleIntent(
  userId: string | null,
  entity: LifecycleEntity,
  id: string,
): LifecycleIntent | null {
  const raw = read(key(userId, entity, id))
  if (!raw) return null
  try {
    return JSON.parse(raw) as LifecycleIntent
  } catch {
    return null
  }
}

export function dismissLifecycleIntent(userId: string | null, entity: LifecycleEntity, id: string): void {
  write(key(userId, entity, id), null)
}

function newRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  // RFC 4122 v4 fallback (test environments without crypto.randomUUID).
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16)
  })
}

export const MISMATCH_MESSAGE =
  'พบว่าประวัติการเปลี่ยนสถานะถูกบันทึกแล้ว แต่สถานะข้อมูลหลักยังไม่ตรงกัน กรุณาตรวจสอบข้อมูลล่าสุดและซิงก์สถานะให้ตรงกับประวัติ'

const UNKNOWN_MESSAGE =
  'ไม่ทราบผลการบันทึก (อาจบันทึกแล้วหรือยังไม่บันทึก) ระบบไม่ได้ส่งซ้ำอัตโนมัติ กรุณาโหลดข้อมูลล่าสุดเพื่อตรวจสอบ หรือกด "ส่งคำขอเดิมอีกครั้ง"'

function errorOf(json: unknown): { code: string; details: Record<string, unknown> } | null {
  if (typeof json !== 'object' || json === null || !('error' in json)) return null
  const error = (json as { error?: { code?: unknown; details?: unknown } }).error
  if (!error || typeof error.code !== 'string') return null
  const details = typeof error.details === 'object' && error.details !== null ? error.details : {}
  return { code: error.code, details: details as Record<string, unknown> }
}

/** Classify one response. Exported for unit tests. */
export function classifyLifecycleResponse(response: MutationResponse, requestId: string): LifecycleResult {
  if (response.kind === 'transport') return { kind: 'unknown', message: UNKNOWN_MESSAGE, requestId }
  const { status, json } = response
  if (status === 200 && typeof json === 'object' && json !== null) {
    const body = json as { changed?: unknown; replayed?: unknown }
    if (body.replayed === true) return { kind: 'replayed' }
    if (body.changed === true) return { kind: 'changed' }
    if (body.changed === false) return { kind: 'no-op' }
  }
  const error = errorOf(json)
  if (error && [403, 404, 409, 422].includes(status)) {
    const message = describeErrorCode(error.code)
    if (status === 409 && error.code.endsWith('_LIFECYCLE_STALE')) return { kind: 'stale', code: error.code, message }
    if (status === 409 && error.code.endsWith('_LIFECYCLE_MISMATCH')) {
      return { kind: 'mismatch', code: error.code, message: MISMATCH_MESSAGE }
    }
    return { kind: 'refused', code: error.code, message, status, requestId: response.headerRequestId }
  }
  if (error && status === 503 && error.code.endsWith('_LIFECYCLE_HISTORY_WRITE_FAILED')
      && error.details.history_write_outcome === 'rejected') {
    return {
      kind: 'refused',
      code: error.code,
      message: 'ระบบบันทึกประวัติไม่สำเร็จ ข้อมูลยังไม่ถูกเปลี่ยน',
      status,
      requestId: response.headerRequestId,
    }
  }
  if (error && status === 503 && error.code.endsWith('_LIFECYCLE_STATE_WRITE_FAILED')
      && error.details.event_recorded === true) {
    return {
      kind: 'recorded-state-pending',
      message:
        'บันทึกประวัติแล้ว แต่ปรับสถานะของข้อมูลหลักไม่สำเร็จ สถานะจึงยังไม่ตรงกับประวัติ กรุณาโหลดข้อมูลล่าสุดแล้ว "ซิงก์สถานะให้ตรงกับประวัติล่าสุด"',
      requestId: response.headerRequestId,
    }
  }
  return { kind: 'unknown', message: UNKNOWN_MESSAGE, requestId }
}

async function send(
  userId: string | null,
  entity: LifecycleEntity,
  id: string,
  intent: LifecycleIntent,
): Promise<LifecycleResult> {
  const response = await apiMutation(
    `/${entity}/${encodeURIComponent(id)}/${intent.operation}`,
    'POST',
    intent.body,
    { requestId: intent.requestId },
  )
  const result = classifyLifecycleResponse(response, intent.requestId)
  if (result.kind !== 'unknown') dismissLifecycleIntent(userId, entity, id)
  return result
}

/** A NEW user intent: a new request id, stored before sending. */
export async function startLifecycleAction(
  userId: string | null,
  entity: LifecycleEntity,
  id: string,
  operation: LifecycleOperation,
  body: Record<string, unknown>,
): Promise<LifecycleResult> {
  const intent: LifecycleIntent = { requestId: newRequestId(), operation, body, createdAt: new Date().toISOString() }
  write(key(userId, entity, id), JSON.stringify(intent))
  return send(userId, entity, id, intent)
}

/** The explicit resend of the stored intent: SAME request id, SAME body. */
export async function resendLifecycleAction(
  userId: string | null,
  entity: LifecycleEntity,
  id: string,
): Promise<LifecycleResult | null> {
  const intent = pendingLifecycleIntent(userId, entity, id)
  return intent ? send(userId, entity, id, intent) : null
}
