/**
 * Phase 7 Batch 7O2b — registry operation bookkeeping (contract Final Rev2
 * §10.3-§10.4, as replaced by the Outcome Classification Addendum A.1-A.3).
 *
 * Page-level (module) state, NOT component state: every response is applied
 * here whatever view is mounted; a view only re-renders from it.
 *
 * - An intent is written BEFORE the request is sent, under
 *   `crane.registryPending.v1:<userId>:<vehicleId>` (localStorage; page memory
 *   when storage is unavailable).
 * - Default outcome: KEEP, state UNKNOWN. A response removes the intent only
 *   when it is a validated, correlated, allowlisted outcome of a FIRST attempt
 *   (`classifyResponse`). Once an intent has been uncertain, no response
 *   removes it; only history settlement (own record found AND history
 *   CONSISTENT) or an explicit acknowledgement does.
 * - No automatic resend. A resend is an explicit user action with the SAME
 *   request id and the SAME stored body.
 * - Limits: 5 intents per user per vehicle (oldest evicted); 14-day expiry at
 *   load; 60-second client timeout (apiMutation). localStorage is not a
 *   security boundary: keys separate users of one browser for display only.
 *
 * Phase 7 Batch 7O2c adds the five responsible-branch operations under the
 * SAME key. Settlement is family-scoped: a registration-history read judges
 * only registration intents, a branch-history read only branch intents.
 * A branch 200 with `projection_write: NOT_DETERMINED` (the history is still
 * ambiguous; the vehicle record was left unchanged) is KEPT as
 * RECORDED_PROJECTION_PENDING, never reported as a completed change.
 */
import { apiMutation, type MutationResponse } from './apiClient'
import allowlistData from './registryOutcomeAllowlist.json'
import type { BranchHistory, RegistrationHistory } from './types'

export type RegistrationOperation = 'registration' | 'registration_reconcile'
export type BranchOperation = 'transfer' | 'insertion' | 'correction' | 'cancellation' | 'reconcile'
export type RegistryOperation = RegistrationOperation | BranchOperation
export type RegistryFamily = 'registration' | 'branch'
export type IntentState = 'SUBMITTING' | 'UNKNOWN' | 'UNCONFIRMED' | 'RECORDED_PROJECTION_PENDING' | 'CONFLICT'

export interface PendingIntent {
  request_id: string
  operation: RegistryOperation
  vehicle_id: string
  /** Correction / cancellation: the target event (part of the path and of the replay identity). */
  event_id?: string | null
  /** The request body exactly as sent (a resend sends it unchanged). */
  body: Record<string, unknown>
  submitted_at: string
  state: IntentState
  page_instance: string
  route_epoch: number
  /** True once the intent has been in any KEEP state: no later response may remove it. */
  prior_uncertain: boolean
}

export const STORAGE_PREFIX = 'crane.registryPending.v1'
export const PENDING_LIMIT = 5
export const PENDING_TTL_MS = 14 * 24 * 60 * 60 * 1000
export const UNKNOWN_TEXT = 'ยังไม่ทราบผลการบันทึก — ระบบจะตรวจสอบจากประวัติ'
export const MEMORY_ONLY_TEXT = 'คำเตือนนี้จะหายเมื่อออกจากหน้า'

const STATE_RANK: Record<IntentState, number> = {
  CONFLICT: 4,
  RECORDED_PROJECTION_PENDING: 3,
  UNKNOWN: 2,
  UNCONFIRMED: 2,
  SUBMITTING: 1,
}
const REGISTRATION_OPERATIONS: readonly RegistryOperation[] = ['registration', 'registration_reconcile']
const BRANCH_OPERATIONS: readonly RegistryOperation[] = ['transfer', 'insertion', 'correction', 'cancellation', 'reconcile']
const REGISTRY_OPERATIONS: readonly RegistryOperation[] = [...REGISTRATION_OPERATIONS, ...BRANCH_OPERATIONS]

export function operationFamily(operation: RegistryOperation): RegistryFamily {
  return BRANCH_OPERATIONS.includes(operation) ? 'branch' : 'registration'
}

export function storageKey(userId: string, vehicleId: string): string {
  return `${STORAGE_PREFIX}:${userId}:${vehicleId}`
}

// ---------------------------------------------------------------------------
// Outcome classification (Addendum A.2). The allowlist is the shared table
// (registryOutcomeAllowlist.json), checked against the backend's table by
// backend/tests/test_registration_write_batch7o2b.py.
// ---------------------------------------------------------------------------

function buildAllowlist(): Record<RegistryOperation, ReadonlySet<string>> {
  const data = allowlistData as unknown as Record<string, unknown>
  const table = {} as Record<RegistryOperation, ReadonlySet<string>>
  for (const op of REGISTRY_OPERATIONS) {
    const pairs = data[op]
    table[op] = new Set(
      Array.isArray(pairs)
        ? pairs
            .filter((p): p is [number, string] => Array.isArray(p) && typeof p[0] === 'number' && typeof p[1] === 'string')
            .map(([status, code]) => `${status}:${code}`)
        : [],
    )
  }
  return table
}

export const ZERO_WRITE_ALLOWLIST = buildAllowlist()

export function isAllowlisted(operation: string, status: number, code: string): boolean {
  const set = (ZERO_WRITE_ALLOWLIST as Record<string, ReadonlySet<string> | undefined>)[operation]
  return set !== undefined && set.has(`${status}:${code}`)
}

export type ConfirmedNotice = 'CONFIRMED_APPLIED' | 'CONFIRMED_NO_OP' | 'CONFIRMED_ZERO_WRITE'

export interface Classification {
  action: 'REMOVE' | 'KEEP'
  /** KEEP: the new intent state. */
  state?: IntentState
  /** REMOVE: why the outcome is known. */
  notice?: ConfirmedNotice
  /** A correlated error envelope's code and details, for the inline message. */
  errorCode?: string
  errorDetails?: Record<string, unknown> | null
  /** A correlated, validated 200 body. */
  body?: Record<string, unknown>
  /** KEEP after prior uncertainty: this response was a proven refusal of the resend. */
  refused?: boolean
}

type Obj = Record<string, unknown>
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v)
const nonEmpty = (v: unknown): v is string => typeof v === 'string' && v.length > 0

/** The W1 (history append) and W2 (vehicle record) failure codes of each family. */
const WRITE_FAILED: Record<RegistryFamily, { w1: string; w2: string }> = {
  registration: { w1: 'REGISTRATION_HISTORY_WRITE_FAILED', w2: 'VEHICLE_MASTER_WRITE_FAILED' },
  branch: { w1: 'BRANCH_HISTORY_WRITE_FAILED', w2: 'BRANCH_PROJECTION_WRITE_FAILED' },
}

/** Addendum A.2. Default KEEP UNKNOWN; REMOVE only for a validated,
 * correlated, allowlisted outcome of a first attempt. */
export function classifyResponse(
  response: MutationResponse,
  intent: Pick<PendingIntent, 'request_id' | 'operation' | 'prior_uncertain'>,
): Classification {
  const unknown: Classification = { action: 'KEEP', state: 'UNKNOWN' }
  // After prior uncertainty nothing is removed; a proven refusal of the resend
  // is still reported (`refused`) so the UI can show it beside the banner.
  const removeOr = (notice: ConfirmedNotice, extra: Partial<Classification> = {}): Classification =>
    intent.prior_uncertain
      ? { ...unknown, ...extra, ...(notice === 'CONFIRMED_ZERO_WRITE' ? { refused: true } : {}) }
      : { action: 'REMOVE', notice, ...extra }
  if (response.kind !== 'http') return unknown
  if (!(REGISTRY_OPERATIONS as readonly string[]).includes(intent.operation)) return unknown
  const { status, json } = response
  const rid = intent.request_id
  const family = operationFamily(intent.operation)
  if (!isObj(json)) return unknown // non-JSON, empty, proxy page

  if (status === 200) {
    if (response.headerRequestId !== rid || json.request_id !== rid) return unknown
    if (json.replayed === true) return { ...unknown, body: json } // record proven; settle by history
    if (json.changed === false && !('replayed' in json)) return removeOr('CONFIRMED_NO_OP', { body: json })
    if (json.changed === true && family === 'branch') {
      if (!nonEmpty(json.record_id)) return unknown
      // Recorded, but the history is still ambiguous and the vehicle record was
      // deliberately left unchanged: not a completed change.
      if (json.projection_write === 'NOT_DETERMINED') return { action: 'KEEP', state: 'RECORDED_PROJECTION_PENDING', body: json }
      if (json.projection_write !== 'WRITTEN' && json.projection_write !== 'NOT_NEEDED') return unknown
      return removeOr('CONFIRMED_APPLIED', { body: json })
    }
    if (json.changed === true) {
      const change = json.change
      const changeId = isObj(change) ? change.change_id : undefined
      if (!nonEmpty(changeId) || (json.master_write !== 'WRITTEN' && json.master_write !== 'NOT_NEEDED')) return unknown
      return removeOr('CONFIRMED_APPLIED', { body: json })
    }
    return unknown
  }

  const error = json.error
  if (!isObj(error) || typeof error.code !== 'string' || error.request_id !== rid) return unknown
  const code = error.code
  const details = isObj(error.details) ? error.details : null
  const coded = { errorCode: code, errorDetails: details }
  if (status === 409 && code === 'REQUEST_ID_REUSED') return { action: 'KEEP', state: 'CONFLICT', ...coded }
  const { w1, w2 } = WRITE_FAILED[family]
  if (status === 503 && code === w1) {
    if (details?.history_write_outcome === 'rejected') return removeOr('CONFIRMED_ZERO_WRITE', coded)
    return { ...unknown, ...coded }
  }
  if (status === 503 && code === w2) {
    const recorded =
      family === 'branch'
        ? details?.event_recorded === true && nonEmpty(details.record_id)
        : details?.history_recorded === true && nonEmpty(details.change_id)
    if (recorded) {
      return { action: 'KEEP', state: 'RECORDED_PROJECTION_PENDING', ...coded }
    }
    return { ...unknown, ...coded }
  }
  if (isAllowlisted(intent.operation, status, code)) return removeOr('CONFIRMED_ZERO_WRITE', coded)
  return { ...unknown, ...coded } // INTERNAL_ERROR, unknown codes, wrong status or operation
}

export function bannerState(intents: readonly PendingIntent[]): IntentState | null {
  let best: IntentState | null = null
  for (const intent of intents) {
    if (best === null || STATE_RANK[intent.state] > STATE_RANK[best]) best = intent.state
  }
  return best
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export type SettlementIntent = 'RECORDED' | 'RECORDED_LATER_CHANGED'

export interface SettlementNotice {
  request_id: string
  operation: RegistryOperation
  intent: SettlementIntent
}

export interface ResponseResult {
  classification: Classification
  /** False when the intent was already gone (settled in another tab, acknowledged). */
  found: boolean
}

function newPageInstance(): string {
  return newRequestId()
}

/** A UUIDv4 for X-Request-Id; does not depend on crypto.randomUUID (not
 * available outside secure contexts). */
export function newRequestId(): string {
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

function isIntent(value: unknown): value is PendingIntent {
  return (
    isObj(value) &&
    nonEmpty(value.request_id) &&
    (REGISTRY_OPERATIONS as readonly unknown[]).includes(value.operation) &&
    typeof value.vehicle_id === 'string' &&
    isObj(value.body) &&
    typeof value.submitted_at === 'string' &&
    typeof value.state === 'string' &&
    value.state in STATE_RANK &&
    (value.event_id === undefined || value.event_id === null || typeof value.event_id === 'string')
  )
}

export class PendingStore {
  readonly pageInstance: string
  private readonly memory = new Map<string, PendingIntent[]>()
  private readonly inflight = new Set<string>()
  private readonly listeners = new Set<() => void>()
  private readonly lastReads = new Map<string, RegistrationHistory>()
  private readonly lastBranchReads = new Map<string, BranchHistory>()
  private readonly lastNotices = new Map<string, SettlementNotice[]>()
  private memoryOnly = false
  private version = 0
  private readonly getStorage: () => Storage | null
  private readonly now: () => number

  constructor(getStorage: () => Storage | null, now: () => number = Date.now, pageInstance: string = newPageInstance()) {
    this.getStorage = getStorage
    this.now = now
    this.pageInstance = pageInstance
  }

  /** True when intents live only in this page's memory (storage failed). */
  get isMemoryOnly(): boolean {
    return this.memoryOnly
  }

  /** Changes whenever anything this store holds changes (for re-rendering). */
  get snapshotVersion(): number {
    return this.version
  }

  isInflight(requestId: string): boolean {
    return this.inflight.has(requestId)
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  /** Another tab changed storage: re-render (settlement is idempotent by request id). */
  notifyExternalChange(): void {
    this.emit()
  }

  private emit(): void {
    this.version += 1
    for (const listener of this.listeners) listener()
  }

  private storage(): Storage | null {
    if (this.memoryOnly) return null
    try {
      return this.getStorage()
    } catch {
      this.memoryOnly = true
      return null
    }
  }

  private read(key: string): PendingIntent[] {
    if (!this.memoryOnly) {
      const storage = this.storage()
      if (storage) {
        try {
          const raw = storage.getItem(key)
          const parsed: unknown = raw ? JSON.parse(raw) : []
          return Array.isArray(parsed) ? parsed.filter(isIntent) : []
        } catch {
          this.memoryOnly = true
        }
      } else {
        this.memoryOnly = true
      }
    }
    return (this.memory.get(key) ?? []).map((i) => ({ ...i }))
  }

  private write(key: string, intents: PendingIntent[]): void {
    this.memory.set(key, intents.map((i) => ({ ...i })))
    if (!this.memoryOnly) {
      const storage = this.storage()
      try {
        if (!storage) throw new Error('no storage')
        if (intents.length === 0) storage.removeItem(key)
        else storage.setItem(key, JSON.stringify(intents))
      } catch {
        this.memoryOnly = true // keep the copy in memory; the banner discloses it
      }
    }
  }

  private fresh(intents: PendingIntent[]): PendingIntent[] {
    const cutoff = this.now() - PENDING_TTL_MS
    return intents.filter((i) => {
      const at = Date.parse(i.submitted_at)
      return Number.isFinite(at) && at > cutoff
    })
  }

  /** The intents of one user and vehicle, oldest first; expired ones are dropped here (at load).
   * `family` limits the list to one family's operations. */
  list(userId: string, vehicleId: string, family?: RegistryFamily): PendingIntent[] {
    const key = storageKey(userId, vehicleId)
    const all = this.read(key)
    const kept = this.fresh(all)
    if (kept.length !== all.length) this.write(key, kept)
    return kept
      .filter((i) => family === undefined || operationFamily(i.operation) === family)
      .map((i) => ({ ...i, body: { ...i.body } }))
  }

  /** Persist a new intent BEFORE dispatch (state SUBMITTING). Evicts the oldest beyond the limit. */
  add(userId: string, intent: PendingIntent): void {
    const key = storageKey(userId, intent.vehicle_id)
    const next = [...this.fresh(this.read(key)), { ...intent, body: { ...intent.body } }]
    this.write(key, next.slice(-PENDING_LIMIT))
    this.emit()
  }

  private mutate(userId: string, vehicleId: string, change: (intents: PendingIntent[]) => PendingIntent[]): void {
    const key = storageKey(userId, vehicleId)
    this.write(key, change(this.read(key)))
    this.emit()
  }

  markInflight(requestId: string, inflight: boolean): void {
    if (inflight) this.inflight.add(requestId)
    else this.inflight.delete(requestId)
    this.emit()
  }

  /** Bookkeeping for one response: always applied, whatever view is mounted.
   * `operation` is the operation of the intent that SENT the request; it is
   * used when that intent is already gone (settled or acknowledged, e.g. in
   * another tab), so the response is still classified by its own operation's
   * rules. A missing intent is never recreated. */
  applyResponse(
    userId: string,
    vehicleId: string,
    requestId: string,
    operation: RegistryOperation,
    response: MutationResponse,
  ): ResponseResult {
    const key = storageKey(userId, vehicleId)
    const intents = this.read(key)
    const intent = intents.find((i) => i.request_id === requestId)
    if (!intent) {
      // Classified for the message only, as an uncertain attempt: it can remove
      // nothing, and nothing is written back.
      return {
        classification: classifyResponse(response, { request_id: requestId, operation, prior_uncertain: true }),
        found: false,
      }
    }
    const classification = classifyResponse(response, intent)
    if (classification.action === 'REMOVE') {
      this.write(key, intents.filter((i) => i.request_id !== requestId))
    } else {
      this.write(
        key,
        intents.map((i) =>
          i.request_id === requestId ? { ...i, state: classification.state ?? 'UNKNOWN', prior_uncertain: true } : i,
        ),
      )
    }
    this.emit()
    return { classification, found: true }
  }

  /**
   * §10.4 settlement on a registration-history read of this vehicle. `history`
   * null = the read failed: nothing changes (an error is never evidence).
   * Intents in flight on THIS page are not judged. Only registration intents
   * are judged (family-scoped).
   */
  settle(userId: string, vehicleId: string, history: RegistrationHistory | null): SettlementNotice[] {
    if (history === null) return []
    this.lastReads.delete(vehicleId)
    return this.settleFamily(userId, vehicleId, 'registration', history.items.map((i) => i.request_id), history.consistency)
  }

  /**
   * 7O2c settlement on a branch-history read: only branch intents are judged.
   * Own record (by `request_id` only; `related_request_id` settles nothing)
   * not found → UNCONFIRMED; found with PROJECTION_MISMATCH or UNDETERMINED →
   * RECORDED_PROJECTION_PENDING; found with CONSISTENT → removed with a notice.
   */
  settleBranch(userId: string, vehicleId: string, history: BranchHistory | null): SettlementNotice[] {
    if (history === null) return []
    this.lastBranchReads.delete(vehicleId)
    return this.settleFamily(userId, vehicleId, 'branch', history.records.map((r) => r.request_id), history.consistency)
  }

  private settleFamily(
    userId: string,
    vehicleId: string,
    family: RegistryFamily,
    requestIds: readonly string[],
    consistency: string,
  ): SettlementNotice[] {
    const notices: SettlementNotice[] = []
    this.mutate(userId, vehicleId, (intents) =>
      this.fresh(intents).flatMap((intent) => {
        if (operationFamily(intent.operation) !== family) return [intent]
        if (this.inflight.has(intent.request_id) || intent.state === 'CONFLICT') return [intent]
        const position = requestIds.lastIndexOf(intent.request_id)
        if (position < 0) return [{ ...intent, state: 'UNCONFIRMED' as const, prior_uncertain: true }]
        if (consistency !== 'CONSISTENT') {
          return [{ ...intent, state: 'RECORDED_PROJECTION_PENDING' as const, prior_uncertain: true }]
        }
        notices.push({
          request_id: intent.request_id,
          operation: intent.operation,
          intent: position < requestIds.length - 1 ? 'RECORDED_LATER_CHANGED' : 'RECORDED',
        })
        return []
      }),
    )
    this.lastNotices.set(`${family}|${storageKey(userId, vehicleId)}`, notices)
    this.emit()
    return notices
  }

  /** Keep the latest successful history read of a vehicle for a user that is
   * not known yet (e.g. /me still loading); `settleLatest` judges it later. */
  rememberRead(vehicleId: string, history: RegistrationHistory): void {
    this.lastReads.set(vehicleId, history)
  }

  /** As `rememberRead`, for a branch-history read. */
  rememberBranchRead(vehicleId: string, history: BranchHistory): void {
    this.lastBranchReads.set(vehicleId, history)
  }

  /** Settle against the reads kept by `rememberRead` / `rememberBranchRead` (used once, then dropped). */
  settleLatest(userId: string, vehicleId: string): SettlementNotice[] {
    const history = this.lastReads.get(vehicleId)
    const branch = this.lastBranchReads.get(vehicleId)
    return [
      ...(history ? this.settle(userId, vehicleId, history) : []),
      ...(branch ? this.settleBranch(userId, vehicleId, branch) : []),
    ]
  }

  /** The notices of the latest settlement of this user, vehicle and family. */
  notices(userId: string, vehicleId: string, family: RegistryFamily = 'registration'): SettlementNotice[] {
    return this.lastNotices.get(`${family}|${storageKey(userId, vehicleId)}`) ?? []
  }

  /** "รับทราบ": removes the client intent only; nothing on the server changes. */
  acknowledge(userId: string, vehicleId: string, requestId: string): void {
    this.mutate(userId, vehicleId, (intents) => intents.filter((i) => i.request_id !== requestId))
  }

  /** The stored intent for an explicit same-id resend (UNKNOWN / UNCONFIRMED only). */
  resendable(userId: string, vehicleId: string, requestId: string): PendingIntent | null {
    const intent = this.list(userId, vehicleId).find((i) => i.request_id === requestId)
    if (!intent || this.inflight.has(requestId)) return null
    return intent.state === 'UNKNOWN' || intent.state === 'UNCONFIRMED' || (intent.state === 'SUBMITTING' && intent.prior_uncertain)
      ? intent
      : null
  }

  /** Mark a resend as submitting; its prior uncertainty is kept. */
  markResending(userId: string, vehicleId: string, requestId: string): void {
    this.mutate(userId, vehicleId, (intents) =>
      intents.map((i) => (i.request_id === requestId ? { ...i, state: 'SUBMITTING' as const, prior_uncertain: true } : i)),
    )
  }
}

function browserStorage(): Storage | null {
  return typeof window === 'undefined' ? null : window.localStorage
}

/** The page-level store used by the registration editor. */
export const registryPendingStore = new PendingStore(browserStorage)

if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event) => {
    if (event.key === null || event.key.startsWith(`${STORAGE_PREFIX}:`)) registryPendingStore.notifyExternalChange()
  })
}

// ---------------------------------------------------------------------------
// Dispatch
// ---------------------------------------------------------------------------

export function mutationPath(
  operation: RegistryOperation,
  vehicleId: string,
  eventId?: string | null,
): { path: string; method: 'PATCH' | 'POST' } {
  const id = encodeURIComponent(vehicleId)
  const event = encodeURIComponent(eventId ?? '')
  switch (operation) {
    case 'registration':
      return { path: `/vehicles/${id}/registration`, method: 'PATCH' }
    case 'registration_reconcile':
      return { path: `/vehicles/${id}/registration-history/reconciliations`, method: 'POST' }
    case 'transfer':
      return { path: `/vehicles/${id}/branch-transfers`, method: 'POST' }
    case 'insertion':
      return { path: `/vehicles/${id}/branch-history/insertions`, method: 'POST' }
    case 'correction':
      return { path: `/vehicles/${id}/branch-history/events/${event}/corrections`, method: 'POST' }
    case 'cancellation':
      return { path: `/vehicles/${id}/branch-history/events/${event}/cancellations`, method: 'POST' }
    case 'reconcile':
      return { path: `/vehicles/${id}/branch-projection/reconciliations`, method: 'POST' }
  }
}

async function dispatch(store: PendingStore, userId: string, intent: PendingIntent): Promise<ResponseResult> {
  const { path, method } = mutationPath(intent.operation, intent.vehicle_id, intent.event_id)
  store.markInflight(intent.request_id, true)
  let response: MutationResponse
  try {
    response = await apiMutation(path, method, intent.body, { requestId: intent.request_id })
  } finally {
    store.markInflight(intent.request_id, false)
  }
  return store.applyResponse(userId, intent.vehicle_id, intent.request_id, intent.operation, response)
}

/** A new user intent: a fresh request id, persisted BEFORE the request is sent. */
export async function submitRegistryIntent(
  store: PendingStore,
  args: {
    userId: string
    vehicleId: string
    operation: RegistryOperation
    body: Record<string, unknown>
    routeEpoch: number
    eventId?: string | null
  },
): Promise<ResponseResult & { requestId: string }> {
  const intent: PendingIntent = {
    request_id: newRequestId(),
    operation: args.operation,
    vehicle_id: args.vehicleId,
    ...(args.eventId ? { event_id: args.eventId } : {}),
    body: { ...args.body },
    submitted_at: new Date(Date.now()).toISOString(),
    state: 'SUBMITTING',
    page_instance: store.pageInstance,
    route_epoch: args.routeEpoch,
    prior_uncertain: false,
  }
  store.add(args.userId, intent)
  const result = await dispatch(store, args.userId, intent)
  return { ...result, requestId: intent.request_id }
}

/** Explicit "ส่งคำขอเดิมอีกครั้ง": the same request id and the same stored body. */
export async function resendRegistryIntent(
  store: PendingStore,
  userId: string,
  vehicleId: string,
  requestId: string,
): Promise<ResponseResult | null> {
  const intent = store.resendable(userId, vehicleId, requestId)
  if (!intent) return null
  store.markResending(userId, vehicleId, requestId)
  return dispatch(store, userId, { ...intent, prior_uncertain: true })
}
