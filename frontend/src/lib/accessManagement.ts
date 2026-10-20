import { apiGet, apiPost, apiPostWithRequestId, type ApiResult } from './apiClient'

/**
 * Access Management (Owner-approved Mock implementation) — the client side of
 * `/api/v1/access/*`. Every permission is stored per employee; a department
 * selection is a bulk operation over the employees eligible right now, never a
 * baseline a later employee inherits. The server derives the actor, the scope
 * and every count again on each request: nothing here is an access control.
 */

export interface AccessDelegation {
  delegation_id: string
  delegate_personnel_id: string
  delegate_name: string
  department_id: string
  department_name_th: string
  capabilities: string[]
  granted_by_personnel_id: string
  granted_at: string
  reason_th: string
  revoked: boolean
  revoked_at: string | null
  revoked_by_personnel_id: string | null
  revoke_reason_th: string | null
  effective: boolean
}

export interface AccessMe {
  personnel_id: string | null
  name: string
  is_root: boolean
  recovery: boolean
  revision: number
  root_holder_personnel_id: string | null
  delegations: AccessDelegation[]
  capabilities: string[]
}

export interface CatalogCapability {
  code: string
  label_th: string
  effect_th: string
  /** D7: acts system-wide; only the Maintenance Department Manager grants it, never delegable. */
  sensitive: boolean
}

export interface CatalogCategory {
  code: string
  label_th: string
  note_th: string | null
  capabilities: CatalogCapability[]
}

export interface AccessDepartment {
  department_id: string
  department_name_th: string
  is_active: boolean
  employee_count: number
  grantable: string[]
}

export interface AccessEmployee {
  personnel_id: string
  name: string
  position: string
  position_key: string
  active: boolean
  is_self: boolean
  is_root: boolean
  /** Why this actor may not change this employee (server-derived), or null. */
  exclusion: ExclusionReason | null
  capabilities: string[]
}

export type ExclusionReason = 'INACTIVE' | 'SELF_NOT_EDITABLE' | 'ROOT_PROTECTED'

export const EXCLUSION_LABELS: Record<string, string> = {
  INACTIVE: 'ไม่อยู่ในสถานะใช้งาน',
  SELF_NOT_EDITABLE: 'ผู้รับมอบอำนาจแก้ไขสิทธิ์ของตนเองไม่ได้',
  ROOT_PROTECTED: 'สิทธิ์ของผู้จัดการแผนกซ่อมบำรุงจัดการได้โดยผู้จัดการเท่านั้น',
}

export interface ExcludedEmployee {
  personnel_id: string
  name: string
  reason: ExclusionReason
}

export interface AccessEmployees {
  department_id: string
  revision: number
  grantable: string[]
  positions: { key: string; label: string }[]
  employees: AccessEmployee[]
  active_employee_count: number
  capability_counts: Record<string, number>
}

export type AccessTarget =
  | { kind: 'EMPLOYEE'; personnel_id: string }
  | { kind: 'DEPARTMENT'; department_id: string }

export interface CapabilityChangeSummary {
  capability: string
  action: 'GRANT' | 'REVOKE'
  changed: number
  unchanged: number
}

export interface GrantPlan {
  target_kind: 'EMPLOYEE' | 'DEPARTMENT'
  department_id: string | null
  /** D1: every current employee of the department (or the one employee). */
  eligible_count: number
  target_count: number
  /** D1: never silently dropped — each with the server's reason. */
  excluded: ExcludedEmployee[]
  target_personnel_ids: string[]
  skipped_personnel_ids: string[]
  per_capability: CapabilityChangeSummary[]
  revision: number
}

export interface GrantResult extends Omit<GrantPlan, 'revision'> {
  replayed: boolean
  batch_id: string
  revision?: number
}

export interface RootAppointment {
  personnel_id: string
  name: string
  appointed_at: string
  mode: 'BOOTSTRAP' | 'HANDOVER' | 'RECOVERY' | string | null
  actor_personnel_id: string | null
  actor_user_id: string | null
  actor_name_snapshot: string | null
  reason_th: string
}

export interface RootView {
  position_th: string
  holder: { personnel_id: string; name: string } | null
  valid: boolean
  revision: number
  appointments: RootAppointment[]
}

export interface AccessAuditEntry {
  event_id: string
  kind: string
  personnel_id: string
  capability: string
  delegation_id: string
  department_id: string
  capabilities: string
  actor_personnel_id: string
  actor_user_id: string
  actor_name_snapshot: string
  recorded_at: string
  reason_th: string
  batch_id: string
  target_kind: string
  target_name: string
}

const enc = encodeURIComponent

export const accessApi = {
  me: (): Promise<ApiResult<AccessMe>> => apiGet('/access/me'),
  catalog: (): Promise<ApiResult<{ categories: CatalogCategory[] }>> => apiGet('/access/catalog'),
  departments: (): Promise<ApiResult<AccessDepartment[]>> => apiGet('/access/departments'),
  employees: (departmentId: string): Promise<ApiResult<AccessEmployees>> =>
    apiGet(`/access/employees?department_id=${enc(departmentId)}`),
  preview: (target: AccessTarget, changes: Record<string, boolean>, expectedRevision: number): Promise<ApiResult<GrantPlan>> =>
    apiPost('/access/grants/preview', { target, changes, expected_revision: expectedRevision }),
  apply: (
    target: AccessTarget,
    changes: Record<string, boolean>,
    reason: string,
    expectedRevision: number,
    requestId: string,
  ): Promise<ApiResult<GrantResult>> =>
    apiPostWithRequestId('/access/grants', { target, changes, reason_th: reason, expected_revision: expectedRevision }, requestId),
  delegations: (): Promise<ApiResult<AccessDelegation[]>> => apiGet('/access/delegations'),
  delegate: (
    body: { delegate_personnel_id: string; department_id: string; capabilities: string[]; reason_th: string; expected_revision: number },
    requestId: string,
  ): Promise<ApiResult<AccessDelegation & { replayed: boolean }>> => apiPostWithRequestId('/access/delegations', body, requestId),
  revokeDelegation: (
    delegationId: string,
    reason: string,
    expectedRevision: number,
    requestId: string,
  ): Promise<ApiResult<AccessDelegation & { replayed: boolean }>> =>
    apiPostWithRequestId(`/access/delegations/${enc(delegationId)}/revocation`, { reason_th: reason, expected_revision: expectedRevision }, requestId),
  root: (): Promise<ApiResult<RootView>> => apiGet('/access/root'),
  appointRoot: (personnelId: string, reason: string, expectedRevision: number, requestId: string): Promise<ApiResult<RootView>> =>
    apiPostWithRequestId('/access/root/appointment', { personnel_id: personnelId, reason_th: reason, expected_revision: expectedRevision }, requestId),
  audit: (filter: { personnelId?: string; departmentId?: string }): Promise<ApiResult<AccessAuditEntry[]>> => {
    const params = new URLSearchParams()
    if (filter.personnelId) params.set('personnel_id', filter.personnelId)
    if (filter.departmentId) params.set('department_id', filter.departmentId)
    const query = params.toString()
    return apiGet(`/access/audit${query ? `?${query}` : ''}`)
  },
}

export const ALL_EMPLOYEES = '__ALL__'

/** D1: the employees a department-wide change actually reaches — every current
 * employee this actor may change (the server re-derives and lists the rest). */
export function bulkEligible(employees: AccessEmployee[]): AccessEmployee[] {
  return employees.filter((e) => e.exclusion === null)
}

/** The current employees the department-wide change will NOT reach, with reasons. */
export function bulkExcluded(employees: AccessEmployee[]): AccessEmployee[] {
  return employees.filter((e) => e.exclusion !== null)
}

/** The position filter narrows the individual list only; it never narrows a bulk change. */
export function employeesForPosition(employees: AccessEmployee[], positionKey: string): AccessEmployee[] {
  return positionKey ? employees.filter((e) => e.position_key === positionKey) : employees
}

export type SwitchView =
  | { kind: 'ON' }
  | { kind: 'OFF' }
  | { kind: 'MIXED'; holders: number; total: number }

/** The displayed state of one switch: a touched switch shows the draft, an
 * untouched department switch shows the current counts (mixed = "x of n"). */
export function switchView(
  capability: string,
  draft: Record<string, boolean>,
  target: { kind: 'EMPLOYEE'; employee: AccessEmployee } | { kind: 'DEPARTMENT'; eligible: AccessEmployee[] },
): SwitchView {
  if (capability in draft) return { kind: draft[capability] ? 'ON' : 'OFF' }
  if (target.kind === 'EMPLOYEE') return { kind: target.employee.capabilities.includes(capability) ? 'ON' : 'OFF' }
  const total = target.eligible.length
  const holders = target.eligible.filter((e) => e.capabilities.includes(capability)).length
  if (total > 0 && holders === total) return { kind: 'ON' }
  if (holders === 0) return { kind: 'OFF' }
  return { kind: 'MIXED', holders, total }
}

/** Holders among the employees a bulk change would reach. */
export function holderCount(capability: string, eligible: AccessEmployee[]): number {
  return eligible.filter((e) => e.capabilities.includes(capability)).length
}

/** Toggle a switch: an individual switch set back to its stored value is no
 * longer a change; a department switch stays touched (the server reports how
 * many employees actually change). */
export function toggleDraft(
  draft: Record<string, boolean>,
  capability: string,
  view: SwitchView,
  stored: boolean | null,
): Record<string, boolean> {
  const next = { ...draft }
  const value = view.kind !== 'ON'
  if (stored !== null && value === stored) delete next[capability]
  else next[capability] = value
  return next
}

export const AUDIT_KIND_LABELS: Record<string, string> = {
  GRANT: 'ให้สิทธิ์',
  REVOKE: 'ถอนสิทธิ์',
  GRANT_BATCH: 'บันทึกการเปลี่ยนสิทธิ์ (ทั้งชุด)',
  DELEGATION_GRANT: 'มอบอำนาจจัดการสิทธิ์',
  DELEGATION_REVOKE: 'ยกเลิกการมอบอำนาจ',
  ROOT_APPOINTMENT: 'แต่งตั้งผู้จัดการแผนกซ่อมบำรุง',
  DEPARTMENT_MOVEMENT_PERMISSIONS_RESET: 'ย้ายแผนก — สิทธิ์เดิมทั้งหมดสิ้นสุด',
  DEPARTMENT_TRANSFER_PERMISSIONS_RESET: 'ย้ายแผนก — สิทธิ์เดิมทั้งหมดสิ้นสุด',
  DEPARTMENT_INSERTION_PERMISSIONS_RESET: 'บันทึกประวัติแผนกย้อนหลัง — สิทธิ์เดิมทั้งหมดสิ้นสุด',
  DEPARTMENT_CORRECTION_PERMISSIONS_RESET: 'แก้ไขประวัติแผนก — สิทธิ์เดิมทั้งหมดสิ้นสุด (ไม่คืนสิทธิ์อัตโนมัติ)',
  DEPARTMENT_CANCELLATION_PERMISSIONS_RESET: 'ยกเลิกการย้ายแผนก — สิทธิ์เดิมไม่คืนอัตโนมัติ ต้องให้สิทธิ์ใหม่',
}

export const ROOT_MODE_LABELS: Record<string, string> = {
  BOOTSTRAP: 'ตั้งค่าเริ่มต้นของระบบทดสอบ',
  HANDOVER: 'ส่งมอบตำแหน่ง',
  RECOVERY: 'กู้คืนทางเทคนิค (ไม่มีผู้ดำรงตำแหน่งที่ถูกต้อง)',
}
