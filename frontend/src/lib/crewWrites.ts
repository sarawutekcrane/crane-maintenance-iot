/**
 * R8 early workstream — request intents of the crew assignment write route
 * (`POST /vehicles/{id}/crew-assignment-operations`; Owner source approval
 * 2026-11-18, OD-3 / OD-4). Its own module; the accepted E2 client is untouched.
 *
 * Backend contract (crew_assignment.py): 403 -> 422 REQUEST_ID_REQUIRED -> body ->
 * 501 / 503 context -> 409 REAL refusal -> both histories read -> REPLAY (same id +
 * same body -> the original result; a different body -> 409 REQUEST_ID_REUSED) ->
 * rules -> person-axis conflicts -> ONE two-stream guarded append. After the append
 * the only outcomes are success, CREW_CONCURRENT_CHANGE (nothing written) and 503
 * CREW_HISTORY_WRITE_FAILED {history_write_outcome}.
 *
 * Client rules (no duplicate submission, no lost response):
 * - the intent (UUID v4 request id + exact body) is stored BEFORE sending under
 *   `crane.crewPending.v1:<userId>:<vehicleId>`; without a user id, a secure random
 *   source or working storage nothing is sent;
 * - one unresolved intent per user / vehicle, one request in flight;
 * - a definitive answer (2xx, or a refusal the server raises before writing,
 *   including CREW_CONCURRENT_CHANGE) settles and removes the intent;
 * - a transport failure, a timeout or CREW_HISTORY_WRITE_FAILED keeps it as UNKNOWN:
 *   the user resends with the SAME id and body, and the server replays the original
 *   result if the first attempt had landed (never a second row);
 * - 409 REQUEST_ID_REUSED is kept as CONFLICT (never resent automatically).
 * localStorage is not a security boundary; the backend enforces everything.
 */
import { useCallback, useState } from 'react'
import { apiMutation, type MutationResponse } from './apiClient'
import { describeCrewErrorCode } from './labels'
import { newR2RequestId } from './r2HistoryWrites'

export type CrewIntentState = 'UNKNOWN' | 'CONFLICT'

export interface CrewIntent {
  v: 1
  vehicle_id: string
  request_id: string
  body_json: string
  operation: string
  state: CrewIntentState
}

export type CrewSubmitResult =
  | { kind: 'success'; changed: boolean; replayed: boolean; warnings: string[] }
  | { kind: 'refused'; code: string | undefined; message: string; details: Record<string, unknown> | null }
  | { kind: 'unknown'; message: string }
  | { kind: 'blocked'; message: string }

const PREFIX = 'crane.crewPending.v1'

export function crewPendingKey(userId: string, vehicleId: string): string {
  return `${PREFIX}:${userId}:${vehicleId}`
}

export function readCrewIntent(userId: string | null, vehicleId: string): CrewIntent | null {
  if (!userId) return null
  try {
    const raw = window.localStorage.getItem(crewPendingKey(userId, vehicleId))
    if (!raw) return null
    const parsed = JSON.parse(raw) as CrewIntent
    return parsed && parsed.v === 1 && typeof parsed.request_id === 'string' ? parsed : null
  } catch {
    return null
  }
}

function writeIntent(userId: string, intent: CrewIntent): boolean {
  try {
    const key = crewPendingKey(userId, intent.vehicle_id)
    window.localStorage.setItem(key, JSON.stringify(intent))
    return window.localStorage.getItem(key) === JSON.stringify(intent)
  } catch {
    return false
  }
}

function clearIntent(userId: string, vehicleId: string): void {
  try {
    window.localStorage.removeItem(crewPendingKey(userId, vehicleId))
  } catch {
    /* nothing to clear */
  }
}

function errorOf(json: unknown): { code?: string; details: Record<string, unknown> | null } {
  if (json && typeof json === 'object' && 'error' in json) {
    const error = (json as { error?: { code?: unknown; details?: unknown } }).error
    const code = typeof error?.code === 'string' ? error.code : undefined
    const details = error?.details && typeof error.details === 'object' ? (error.details as Record<string, unknown>) : null
    return { code, details }
  }
  return { details: null }
}

/** Classify one HTTP outcome (pure; exported for tests). */
export function classifyCrewResponse(response: MutationResponse): CrewSubmitResult {
  if (response.kind === 'transport') {
    return { kind: 'unknown', message: 'ไม่ทราบผล (การเชื่อมต่อขัดข้อง) — กด “ส่งคำขอเดิมอีกครั้ง” เพื่อตรวจผล' }
  }
  if (response.status >= 200 && response.status < 300) {
    const json = (response.json ?? {}) as { changed?: unknown; replayed?: unknown; warnings?: unknown }
    const warnings = Array.isArray(json.warnings)
      ? json.warnings.map((w) => (w && typeof w === 'object' ? String((w as { code?: unknown }).code ?? '') : ''))
      : []
    return { kind: 'success', changed: json.changed === true, replayed: json.replayed === true, warnings }
  }
  const { code, details } = errorOf(response.json)
  if (code === 'CREW_HISTORY_WRITE_FAILED' && details?.history_write_outcome !== 'rejected') {
    return { kind: 'unknown', message: describeCrewErrorCode(code) }
  }
  if (response.status >= 500 && code !== 'CREW_HISTORY_WRITE_FAILED' && response.status !== 501) {
    return { kind: 'unknown', message: 'ไม่ทราบผล (เซิร์ฟเวอร์ขัดข้อง) — กด “ส่งคำขอเดิมอีกครั้ง” เพื่อตรวจผล' }
  }
  return { kind: 'refused', code, message: describeCrewErrorCode(code), details }
}

export function useCrewWrites(vehicleId: string, userId: string | null) {
  const [intent, setIntent] = useState<CrewIntent | null>(() => readCrewIntent(userId, vehicleId))
  const [inFlight, setInFlight] = useState(false)
  // The user id arrives after /me loads: re-read the stored intent for this user and vehicle
  // (adjusted during render when the key changes, not in an effect).
  const intentKey = `${userId ?? ''}:${vehicleId}`
  const [readKey, setReadKey] = useState(intentKey)
  if (readKey !== intentKey) {
    setReadKey(intentKey)
    setIntent(readCrewIntent(userId, vehicleId))
  }

  const send = useCallback(
    async (stored: CrewIntent): Promise<CrewSubmitResult> => {
      if (!userId) return { kind: 'blocked', message: 'ยังไม่ทราบตัวผู้ใช้ จึงไม่ส่งคำขอ' }
      setInFlight(true)
      const response = await apiMutation(
        `/vehicles/${encodeURIComponent(vehicleId)}/crew-assignment-operations`,
        'POST',
        JSON.parse(stored.body_json),
        { requestId: stored.request_id },
      )
      setInFlight(false)
      const result = classifyCrewResponse(response)
      if (result.kind === 'success' || (result.kind === 'refused' && result.code !== 'REQUEST_ID_REUSED')) {
        clearIntent(userId, vehicleId)
        setIntent(null)
      } else if (result.kind === 'refused') {
        const conflict = { ...stored, state: 'CONFLICT' as const }
        writeIntent(userId, conflict)
        setIntent(conflict)
      } else {
        const unknown = { ...stored, state: 'UNKNOWN' as const }
        writeIntent(userId, unknown)
        setIntent(unknown)
      }
      return result
    },
    [userId, vehicleId],
  )

  /** A NEW intent: refused while another one is unresolved or in flight. */
  const submit = useCallback(
    async (body: Record<string, unknown>): Promise<CrewSubmitResult> => {
      if (!userId) return { kind: 'blocked', message: 'ยังไม่ทราบตัวผู้ใช้ จึงไม่ส่งคำขอ' }
      if (inFlight) return { kind: 'blocked', message: 'กำลังส่งคำขออยู่ กรุณารอ' }
      if (readCrewIntent(userId, vehicleId)) {
        return { kind: 'blocked', message: 'มีคำขอเดิมที่ยังไม่ทราบผล กรุณาส่งคำขอเดิมอีกครั้งก่อน' }
      }
      const requestId = newR2RequestId()
      if (!requestId) return { kind: 'blocked', message: 'เบราว์เซอร์ไม่รองรับการสร้างรหัสคำขอที่ปลอดภัย' }
      const stored: CrewIntent = {
        v: 1,
        vehicle_id: vehicleId,
        request_id: requestId,
        body_json: JSON.stringify(body),
        operation: String(body.operation ?? ''),
        state: 'UNKNOWN',
      }
      if (!writeIntent(userId, stored)) return { kind: 'blocked', message: 'บันทึกคำขอในเบราว์เซอร์ไม่ได้ จึงไม่ส่ง' }
      return send(stored)
    },
    [userId, vehicleId, inFlight, send],
  )

  /** Resend the stored intent with the SAME request id and body. */
  const resend = useCallback(async (): Promise<CrewSubmitResult> => {
    const stored = readCrewIntent(userId, vehicleId)
    if (!stored || stored.state === 'CONFLICT') {
      return { kind: 'blocked', message: 'ไม่มีคำขอเดิมที่ส่งซ้ำได้' }
    }
    return send(stored)
  }, [userId, vehicleId, send])

  return { intent, inFlight, submit, resend }
}
