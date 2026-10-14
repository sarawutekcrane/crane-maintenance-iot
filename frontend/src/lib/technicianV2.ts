/**
 * R2 Batch R2f-h4 B4 — Technician V2 frontend support (C1 Amendment A1-§25).
 *
 * Read side: the scope-aware technician picker (`GET /technicians`), the V2
 * assignment read (`GET /{job}/technician-assignments`), V2 My Work
 * (`GET /my-work`) and the U1 waiting queues (`GET /{kind}/v2-waiting-assignment`).
 * The server decides scope, eligibility (BOTH-ACTIVE) and authorization; nothing
 * here filters by scope, invents a search parameter or re-validates a technician.
 *
 * Write side (`POST /{job}/technician-assignments`) follows the R2e
 * request-intent discipline (`lifecycle.ts`), kept in its own module:
 *
 * - The intent (request id + exact body, including `expected_current`) is
 *   stored BEFORE sending, under
 *   `crane.technicianAssignmentPending.v1:<userId>:<kind>:<jobId>`
 *   (localStorage; page memory when storage is unavailable).
 * - The intent is removed only when the outcome is PROVEN: a 200 (changed /
 *   no-op / replayed), `409 TECHNICIAN_ASSIGNMENT_STALE` (nothing written —
 *   reload and reconfirm), any refusal the backend raises before writing
 *   (403 / 404 / 409 / 422, the listed pre-write 500 / 503 codes), or
 *   `503 TECHNICIAN_ASSIGNMENT_WRITE_FAILED {write_outcome: "rejected"}`.
 * - Anything else (a transport failure or timeout, `write_outcome: "unknown"`,
 *   an unlisted 5xx) KEEPS the intent as UNKNOWN: neither success nor failure
 *   is claimed. There is no automatic retry and no new request id: a resend is
 *   an explicit user action with the SAME request id and the SAME stored body.
 *
 * R2 Batch R2f-h4 B6 (owner D2): the whole-assignment withdrawal
 * (`POST /{job}/technician-assignment-withdrawals`, body `{expected_current, reason_th?}`)
 * uses the SAME intent store and classification. The stored intent records its
 * `operation` so an explicit resend goes to the endpoint it was created for; an
 * intent stored before B6 (no `operation`) is an assignment.
 *
 * localStorage is not a security boundary; the backend stays authoritative.
 */
import { ApiError, apiGet, apiMutation, type ApiResult, type MutationResponse } from './apiClient'
import { describeErrorCode } from './labels'
import type { Page } from './types'

/** Thai messages for the V2 codes (kept here so the shared label table is unchanged).
 * The code itself is always shown next to the message as well. */
const V2_ERROR_MESSAGES: Record<string, string> = {
  HTTP_ERROR: 'คุณไม่มีสิทธิ์ดำเนินการนี้',
  ASSIGNMENT_MODEL_MISMATCH: 'งานนี้ไม่ได้ใช้รูปแบบการมอบหมายช่าง V2 จึงดำเนินการนี้ไม่ได้',
  ASSIGNMENT_MODEL_DATA_INVALID: 'ข้อมูลรูปแบบการมอบหมายของงานไม่ถูกต้อง ระบบจึงไม่แสดงข้อมูล',
  TECHNICIAN_ASSIGNMENT_STALE: 'ทีมช่างปัจจุบันถูกเปลี่ยนไปแล้ว กรุณาโหลดข้อมูลล่าสุด',
  TECHNICIAN_ASSIGNMENT_ORDER_AMBIGUOUS: 'ระบุทีมช่างปัจจุบันไม่ได้ (มีชุดการมอบหมายที่บันทึกในเวลาเดียวกัน) กรุณาแจ้งผู้ดูแลข้อมูล',
  TECHNICIAN_ASSIGNMENT_SCOPE_MISMATCH: 'งานนี้อยู่นอกขอบเขตข้อมูลของระบบนี้',
  TECHNICIAN_ASSIGNMENT_LIVE_TEST_UNSUPPORTED: 'ไม่รองรับการมอบหมายช่างกับงานทดสอบในระบบจริง',
  TECHNICIAN_ASSIGNMENT_PRIMARY_REQUIRED: 'ต้องเลือกช่างหลัก (PRIMARY) 1 คน',
  TECHNICIAN_ASSIGNMENT_DUPLICATE_ASSIGNEE: 'เลือกช่างซ้ำกัน',
  TECHNICIAN_ASSIGNMENT_DATA_INVALID: 'ข้อมูลการมอบหมายช่างไม่ถูกต้อง ระบบจึงไม่แสดงข้อมูล กรุณาแจ้งผู้ดูแลข้อมูล',
  TECHNICIAN_ASSIGNMENT_JOB_DATA_INVALID: 'ข้อมูลใบงานบางรายการไม่ถูกต้อง ระบบจึงไม่แสดงคิวงาน กรุณาแจ้งผู้ดูแลข้อมูล',
  TECHNICIAN_ASSIGNMENT_SCHEMA_INVALID: 'โครงสร้างข้อมูลการมอบหมายช่างไม่ถูกต้อง',
  TECHNICIAN_ASSIGNMENT_JOB_SCHEMA_INVALID: 'โครงสร้างข้อมูลใบงานไม่ถูกต้อง',
  TECHNICIAN_ASSIGNMENT_JOB_CLOSED: 'งานนี้ปิดแล้ว จึงเปลี่ยนแปลงการมอบหมายช่างไม่ได้',
  LEGACY_ASSIGNMENT_RETIRED: 'การมอบหมายช่างแบบเดิมถูกยกเลิกแล้ว กรุณาใช้การมอบหมายช่าง V2',
  TECHNICIAN_ASSIGNMENT_WRITE_FAILED: 'บันทึกการมอบหมายช่างไม่สำเร็จ',
  TECHNICIAN_NOT_FOUND: 'ไม่พบรหัสช่างนี้',
  TECHNICIAN_SCOPE_UNPROVEN: 'ยืนยันไม่ได้ว่าช่างนี้อยู่ในขอบเขตข้อมูลเดียวกับงาน',
  TECHNICIAN_NOT_ACTIVE: 'ช่างนี้ไม่ได้อยู่ในสถานะใช้งาน',
  TECHNICIAN_PERSONNEL_UNRESOLVED: 'ช่างนี้ยังไม่ได้เชื่อมกับข้อมูลบุคลากร',
  PERSONNEL_NOT_ACTIVE: 'บุคลากรของช่างนี้ไม่ได้อยู่ในสถานะใช้งาน',
  TECHNICIAN_ID_AMBIGUOUS: 'รหัสช่างนี้ซ้ำกันในข้อมูลหลัก',
  TECHNICIAN_PERSONNEL_AMBIGUOUS: 'ช่างนี้เชื่อมกับบุคลากรมากกว่าหนึ่งรายการ',
  TECHNICIAN_MASTER_DATA_INVALID: 'ข้อมูลหลักของช่างไม่ถูกต้อง กรุณาแจ้งผู้ดูแลข้อมูล',
  TECHNICIAN_MASTER_SCHEMA_INVALID: 'โครงสร้างข้อมูลหลักของช่างไม่ถูกต้อง',
  REQUEST_ID_REUSED: 'รหัสคำขอนี้ถูกใช้กับการเปลี่ยนแปลงอื่นแล้ว ระบบจึงไม่ได้บันทึก',
  REASON_REQUIRED: 'เหตุผล (ถ้าระบุ) ต้องไม่ว่างและไม่ยาวเกินกำหนด',
  VALIDATION_ERROR: 'ข้อมูลที่ส่งไม่ถูกต้อง',
}

export function describeV2Error(code: string | null | undefined): string {
  return (code && V2_ERROR_MESSAGES[code]) || describeErrorCode(code ?? undefined)
}

export type WorkKind = 'REPAIR' | 'PM'

export interface TechnicianSummary {
  technician_id: string
  first_name: string | null
  last_name: string | null
  active_status: string | null
}

export interface AssignmentSet {
  assignment_set_id: string
  assigned_at: string
  assigned_by_user_id: string
  primary_technician_id: string
  collaborator_technician_ids: string[]
  reason_th: string | null
  record_ids: string[]
}

/** One recorded whole-assignment withdrawal (B6 D2; immutable history). */
export interface AssignmentWithdrawal {
  withdrawal_id: string
  withdrawn_at: string
  withdrawn_by_user_id: string
  reason_th: string | null
  record_ids: string[]
}

export interface TechnicianAssignments {
  job_id: string
  assignment_model: 'TECHNICIAN_V2'
  /** NONE also after a withdrawal: the job then has no current set. */
  status: 'NONE' | 'VALID' | 'AMBIGUOUS'
  current: AssignmentSet | null
  sets: AssignmentSet[]
  /** Absent on a pre-B6 backend response; treated as no withdrawals. */
  withdrawals?: AssignmentWithdrawal[]
}

export interface ExpectedSet {
  primary_technician_id: string
  collaborator_technician_ids: string[]
}

export interface AssignmentBody {
  primary_technician_id: string
  collaborator_technician_ids: string[]
  /** REQUIRED by the backend: null means "I expect no current set". */
  expected_current: ExpectedSet | null
  reason_th?: string
}

/** B6 D2: the withdrawal body. `expected_current` is REQUIRED and never null
 * (a withdrawal always names the exact current set it removes). */
export interface WithdrawalBody {
  expected_current: ExpectedSet
  reason_th?: string
}

export type MyWorkResolution =
  | 'RESOLVED'
  | 'UNAUTHENTICATED'
  | 'ACCOUNT_MISSING'
  | 'ACCOUNT_AMBIGUOUS'
  | 'ACCOUNT_SCOPE_UNPROVEN'
  | 'PERSONNEL_UNLINKED'
  | 'PERSONNEL_AMBIGUOUS'
  | 'PERSONNEL_SCOPE_MISMATCH'
  | 'TECHNICIAN_UNLINKED'
  | 'TECHNICIAN_MISSING'
  | 'TECHNICIAN_AMBIGUOUS'
  | 'TECHNICIAN_SCOPE_UNPROVEN'

export interface MyWorkItem {
  work_type: WorkKind
  job_id: string
  asset_type: string
  asset_id: string
  status: string
  opened_at: string
  assignment_role: 'PRIMARY' | 'COLLABORATOR'
  assignment_set_id: string
  assigned_at: string
}

export interface MyWorkResponse {
  resolution: MyWorkResolution | string
  technician_id: string | null
  items: MyWorkItem[] | null
}

export type WaitingStatus = 'NONE' | 'AMBIGUOUS' | 'DATA_INVALID'

export interface WaitingItem {
  work_type: WorkKind
  job_id: string
  asset_type: string
  asset_id: string
  status: 'OPEN'
  opened_at: string
  assignment_status: WaitingStatus | string
  issues: Record<string, number>
}

export interface WaitingQueueResponse extends Page<WaitingItem> {
  data_context: string
}

/** The persisted job marker exposed on the Repair / PM detail responses (B1). */
export type AssignmentModelSignal = 'LEGACY' | 'TECHNICIAN_V2' | 'INVALID'

/** Fail closed: anything other than the two exact known values is INVALID. */
export function assignmentModelOf(value: unknown): AssignmentModelSignal {
  return value === 'LEGACY' || value === 'TECHNICIAN_V2' ? value : 'INVALID'
}

const JOB_API_PATH: Record<WorkKind, string> = { REPAIR: '/repairs', PM: '/pm/work-orders' }

export function jobApiPath(kind: WorkKind, jobId: string): string {
  return `${JOB_API_PATH[kind]}/${encodeURIComponent(jobId)}`
}

/** The canonical detail route of a job (B5 navigation cutover: the job detail
 * pages host the V2 assignment area; the B4 `/v2/...` paths only redirect here). */
export function jobDetailRoute(kind: WorkKind, jobId: string): string {
  return kind === 'REPAIR' ? `/repairs/${encodeURIComponent(jobId)}` : `/pm/work-orders/${encodeURIComponent(jobId)}`
}

export function waitingQueuePath(kind: WorkKind): string {
  return `${JOB_API_PATH[kind]}/v2-waiting-assignment`
}

/** A technician's display name, separate from (never a substitute for) the id. */
export function technicianName(technician: TechnicianSummary | undefined): string | null {
  if (!technician) return null
  const name = [technician.first_name, technician.last_name].filter((part) => part && part.trim()).join(' ')
  return name || null
}

export const TECHNICIAN_PAGE_SIZE = 200
/** A bound on the picker's page walk (200 × 50 = 10 000 rows) so a misbehaving
 * total can never loop forever; exceeding it is an error, never a partial list. */
export const TECHNICIAN_MAX_PAGES = 50

/**
 * Every technician the server returns for its own scope, walking the existing
 * `page` / `page_size` parameters only. Any failed page fails the whole read
 * (never a partial picker).
 */
export async function fetchAllTechnicians(): Promise<ApiResult<TechnicianSummary[]>> {
  const all: TechnicianSummary[] = []
  for (let page = 1; page <= TECHNICIAN_MAX_PAGES; page += 1) {
    const result = await apiGet<Page<TechnicianSummary>>(`/technicians?page=${page}&page_size=${TECHNICIAN_PAGE_SIZE}`)
    if (!result.ok) return result
    all.push(...result.data.items)
    if (result.data.items.length === 0 || all.length >= result.data.total_items) return { ok: true, data: all }
  }
  return { ok: false, error: new Error('TECHNICIAN_LIST_TOO_LARGE') }
}

export interface SelectionProblem {
  code: 'PRIMARY_REQUIRED' | 'DUPLICATE_ASSIGNEE' | 'PRIMARY_AS_COLLABORATOR' | 'UNKNOWN_TECHNICIAN'
  message: string
}

/**
 * Client-side usability checks only (the backend re-validates everything):
 * exactly one PRIMARY, no duplicate, the PRIMARY never also a COLLABORATOR, and
 * every id one of the stable ids the picker listed (never free text).
 */
export function selectionProblem(
  primary: string,
  collaborators: string[],
  listedIds: ReadonlySet<string>,
): SelectionProblem | null {
  if (!primary) return { code: 'PRIMARY_REQUIRED', message: 'กรุณาเลือกช่างหลัก (PRIMARY) 1 คน' }
  if (new Set(collaborators).size !== collaborators.length) {
    return { code: 'DUPLICATE_ASSIGNEE', message: 'เลือกช่างร่วมซ้ำกัน กรุณาตรวจสอบ' }
  }
  if (collaborators.includes(primary)) {
    return { code: 'PRIMARY_AS_COLLABORATOR', message: 'ช่างหลักต้องไม่ถูกเลือกเป็นช่างร่วมด้วย' }
  }
  if (![primary, ...collaborators].every((id) => listedIds.has(id))) {
    return { code: 'UNKNOWN_TECHNICIAN', message: 'มีรหัสช่างที่ไม่อยู่ในรายการของระบบ กรุณาโหลดรายชื่อช่างใหม่' }
  }
  return null
}

/** The exact current set, as the body's `expected_current` (null = no current set). */
export function expectedCurrentOf(current: AssignmentSet | null): ExpectedSet | null {
  return current
    ? { primary_technician_id: current.primary_technician_id, collaborator_technician_ids: [...current.collaborator_technician_ids] }
    : null
}

export function buildAssignmentBody(
  primary: string,
  collaborators: string[],
  current: AssignmentSet | null,
  reason: string,
): AssignmentBody {
  const body: AssignmentBody = {
    primary_technician_id: primary,
    collaborator_technician_ids: [...collaborators],
    expected_current: expectedCurrentOf(current),
  }
  if (reason.trim()) body.reason_th = reason.trim()
  return body
}

export function buildWithdrawalBody(current: AssignmentSet, reason: string): WithdrawalBody {
  const body: WithdrawalBody = { expected_current: expectedCurrentOf(current) as ExpectedSet }
  if (reason.trim()) body.reason_th = reason.trim()
  return body
}

// ---- request intent (R2e pattern) -------------------------------------------------------------

export type AssignmentOperation = 'assign' | 'withdraw'

export type AssignmentIntent =
  | { operation?: 'assign'; requestId: string; body: AssignmentBody; createdAt: string }
  | { operation: 'withdraw'; requestId: string; body: WithdrawalBody; createdAt: string }

/** The operation of a stored intent (pre-B6 intents carry none: an assignment). */
export function intentOperation(intent: AssignmentIntent): AssignmentOperation {
  return intent.operation === 'withdraw' ? 'withdraw' : 'assign'
}

export type AssignmentResult =
  | { kind: 'changed' | 'no-op' | 'replayed' | 'withdrawn' }
  | { kind: 'stale'; code: string; message: string }
  | { kind: 'refused'; code: string; message: string; status: number; requestId: string | null }
  | { kind: 'unknown'; message: string; requestId: string }

const memory = new Map<string, string>()

function key(userId: string | null, kind: WorkKind, jobId: string): string {
  return `crane.technicianAssignmentPending.v1:${userId ?? 'anonymous'}:${kind}:${jobId}`
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

export function pendingAssignmentIntent(userId: string | null, kind: WorkKind, jobId: string): AssignmentIntent | null {
  const raw = read(key(userId, kind, jobId))
  if (!raw) return null
  try {
    return JSON.parse(raw) as AssignmentIntent
  } catch {
    return null
  }
}

export function dismissAssignmentIntent(userId: string | null, kind: WorkKind, jobId: string): void {
  write(key(userId, kind, jobId), null)
}

function newRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  // RFC 4122 v4 fallback (test environments without crypto.randomUUID).
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16)
  })
}

export const STALE_MESSAGE =
  'ทีมช่างปัจจุบันถูกเปลี่ยนไปแล้วโดยผู้อื่น ระบบไม่ได้บันทึกการเปลี่ยนแปลงนี้ กรุณาโหลดข้อมูลล่าสุดแล้วยืนยันการเลือกอีกครั้ง'

export const UNKNOWN_MESSAGE =
  'ไม่ทราบผลการบันทึก (อาจบันทึกแล้วหรือยังไม่บันทึก) ระบบไม่ได้ส่งซ้ำอัตโนมัติ กรุณาโหลดข้อมูลล่าสุดเพื่อตรวจสอบ หรือกด "ส่งคำขอเดิมอีกครั้ง"'

/**
 * 500 / 503 codes the V2 assignment route raises BEFORE any write (route
 * contract `technician_assignment_routes._RESPONSES`; the only write-time error
 * is TECHNICIAN_ASSIGNMENT_WRITE_FAILED). An unlisted 5xx stays UNKNOWN.
 */
const PRE_WRITE_SERVER_CODES = new Set([
  'ASSIGNMENT_MODEL_DATA_INVALID',
  'TECHNICIAN_ASSIGNMENT_JOB_DATA_INVALID',
  'TECHNICIAN_ASSIGNMENT_JOB_SCHEMA_INVALID',
  'TECHNICIAN_ASSIGNMENT_SCHEMA_INVALID',
  'TECHNICIAN_ASSIGNMENT_DATA_INVALID',
  'TECHNICIAN_MASTER_SCHEMA_INVALID',
  'TECHNICIAN_MASTER_DATA_INVALID',
  'PERSONNEL_MASTER_SCHEMA_INVALID',
  'PERSONNEL_MASTER_DATA_INVALID',
  'REGISTRY_DATA_CONTEXT_NOT_CONFIGURED',
])

function errorOf(json: unknown): { code: string; details: Record<string, unknown> } | null {
  if (typeof json !== 'object' || json === null || !('error' in json)) return null
  const error = (json as { error?: { code?: unknown; details?: unknown } }).error
  if (!error || typeof error.code !== 'string') return null
  const details = typeof error.details === 'object' && error.details !== null ? error.details : {}
  return { code: error.code, details: details as Record<string, unknown> }
}

/** Classify one response. Exported for unit tests. */
export function classifyAssignmentResponse(response: MutationResponse, requestId: string): AssignmentResult {
  if (response.kind === 'transport') return { kind: 'unknown', message: UNKNOWN_MESSAGE, requestId }
  const { status, json } = response
  if (status === 200 && typeof json === 'object' && json !== null) {
    const body = json as { changed?: unknown; replayed?: unknown; withdrawn?: unknown }
    if (body.replayed === true) return { kind: 'replayed' }
    if (body.changed === true && body.withdrawn === true) return { kind: 'withdrawn' }
    if (body.changed === true) return { kind: 'changed' }
    if (body.changed === false) return { kind: 'no-op' }
  }
  const error = errorOf(json)
  if (!error) return { kind: 'unknown', message: UNKNOWN_MESSAGE, requestId }
  const refused = (message: string): AssignmentResult => ({
    kind: 'refused', code: error.code, message, status, requestId: response.headerRequestId,
  })
  if (status === 409 && error.code === 'TECHNICIAN_ASSIGNMENT_STALE') {
    return { kind: 'stale', code: error.code, message: STALE_MESSAGE }
  }
  if ([403, 404, 409, 422].includes(status)) return refused(describeV2Error(error.code))
  if ((status === 500 || status === 503) && PRE_WRITE_SERVER_CODES.has(error.code)) {
    return refused(describeV2Error(error.code))
  }
  if (status === 503 && error.code.endsWith('_READ_FAILED')) return refused(describeV2Error(error.code))
  if (status === 503 && error.code === 'TECHNICIAN_ASSIGNMENT_WRITE_FAILED' && error.details.write_outcome === 'rejected') {
    return refused('ระบบบันทึกข้อมูลไม่สำเร็จ ข้อมูลการมอบหมายยังไม่ถูกเปลี่ยน')
  }
  return { kind: 'unknown', message: UNKNOWN_MESSAGE, requestId }
}

async function send(userId: string | null, kind: WorkKind, jobId: string, intent: AssignmentIntent): Promise<AssignmentResult> {
  const endpoint = intentOperation(intent) === 'withdraw' ? 'technician-assignment-withdrawals' : 'technician-assignments'
  const response = await apiMutation(`${jobApiPath(kind, jobId)}/${endpoint}`, 'POST', intent.body, {
    requestId: intent.requestId,
  })
  const result = classifyAssignmentResponse(response, intent.requestId)
  if (result.kind !== 'unknown') dismissAssignmentIntent(userId, kind, jobId)
  return result
}

/** A NEW user intent: a new request id, stored before sending. */
export async function startAssignment(
  userId: string | null,
  kind: WorkKind,
  jobId: string,
  body: AssignmentBody,
): Promise<AssignmentResult> {
  const intent: AssignmentIntent = { operation: 'assign', requestId: newRequestId(), body, createdAt: new Date().toISOString() }
  write(key(userId, kind, jobId), JSON.stringify(intent))
  return send(userId, kind, jobId, intent)
}

/** B6 D2: a NEW whole-assignment withdrawal intent (new request id, stored before sending). */
export async function startWithdrawal(
  userId: string | null,
  kind: WorkKind,
  jobId: string,
  body: WithdrawalBody,
): Promise<AssignmentResult> {
  const intent: AssignmentIntent = { operation: 'withdraw', requestId: newRequestId(), body, createdAt: new Date().toISOString() }
  write(key(userId, kind, jobId), JSON.stringify(intent))
  return send(userId, kind, jobId, intent)
}

/** The explicit resend of the stored intent: SAME request id, SAME body. */
export async function resendAssignment(userId: string | null, kind: WorkKind, jobId: string): Promise<AssignmentResult | null> {
  const intent = pendingAssignmentIntent(userId, kind, jobId)
  return intent ? send(userId, kind, jobId, intent) : null
}

/** A failed read as the facts `ErrorState` shows (message, code, request id). */
export interface ReadFailure {
  message: string
  code: string | null
  requestId: string | null
  status: number | null
}

export function readFailure(error: ApiError | Error): ReadFailure {
  if (error instanceof ApiError) {
    return { message: describeV2Error(error.code), code: error.code, requestId: error.requestId ?? null, status: error.status }
  }
  return { message: 'เชื่อมต่อระบบไม่สำเร็จ กรุณาลองใหม่อีกครั้ง', code: null, requestId: null, status: null }
}
