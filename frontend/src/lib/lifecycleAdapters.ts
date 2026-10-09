/**
 * R2 Batch R2e — entity adapters of the lifecycle panel. Personnel states are
 * ACTIVE / INACTIVE (the R2c-1 read stays raw text: blank or any other value is
 * shown as unknown, never as active). Department states are the frozen
 * is_active boolean.
 */
import type { LifecycleAdapter, LifecycleStateKey } from '../components/LifecyclePanel'
import { CAN_MANAGE_DEPARTMENT, CAN_MANAGE_PERSONNEL } from './capabilityNames'
import type { DepartmentLifecycleHistory, Personnel, PersonnelLifecycleHistory } from './types'

export const UNKNOWN_STATUS_LABEL = 'ไม่ทราบสถานะ'

/** The display name of a personnel record (never substituted with an id). */
export function personnelName(p: Personnel): string {
  const name = [p.first_name, p.last_name].filter(Boolean).join(' ')
  return name || 'ไม่มีชื่อในข้อมูล'
}

/** A personnel `active_status` raw value for display; unknown is never "active". */
export function personnelStatusLabel(raw: string | null | undefined): string {
  if (raw === 'ACTIVE') return 'ใช้งาน'
  if (raw === 'INACTIVE') return 'ปิดใช้งาน'
  if (raw === null || raw === undefined || !raw.trim()) return UNKNOWN_STATUS_LABEL
  return `${UNKNOWN_STATUS_LABEL} (ค่าในข้อมูล: ${raw})`
}

export function departmentStatusLabel(isActive: boolean | null | undefined): string {
  if (isActive === true) return 'ใช้งาน'
  if (isActive === false) return 'ปิดใช้งาน'
  return UNKNOWN_STATUS_LABEL
}

function personnelKey(raw: string | null | undefined): LifecycleStateKey {
  return raw === 'ACTIVE' || raw === 'INACTIVE' ? raw : 'UNKNOWN'
}

function departmentKey(value: boolean | null | undefined): LifecycleStateKey {
  if (value === true) return 'ACTIVE'
  if (value === false) return 'INACTIVE'
  return 'UNKNOWN'
}

const stateLabel = (state: LifecycleStateKey) =>
  state === 'ACTIVE' ? 'ใช้งาน' : state === 'INACTIVE' ? 'ปิดใช้งาน' : UNKNOWN_STATUS_LABEL

export const personnelLifecycleAdapter: LifecycleAdapter = {
  entity: 'personnel',
  entityLabel: 'บุคลากร',
  capability: CAN_MANAGE_PERSONNEL,
  normalize: (json) => {
    const history = json as PersonnelLifecycleHistory
    return {
      current: personnelKey(history.current_state),
      currentRaw: history.current_state,
      consistency: history.lifecycle_consistency,
      events: history.events.map((e) => ({
        id: e.lifecycle_event_id, kind: e.event_kind, previous: personnelKey(e.previous_state),
        next: personnelKey(e.new_state), recordedAt: e.recorded_at, recordedBy: e.recorded_by, reason: e.reason_th,
      })),
    }
  },
  expectedBody: (current) => ({ expected_active_status: current }),
  stateLabel: (state, raw) => (state === 'UNKNOWN' && raw !== undefined ? personnelStatusLabel(raw) : stateLabel(state)),
  dialogNote:
    'การปิดใช้งานข้อมูลบุคลากรไม่ใช่การปิดบัญชีผู้ใช้งาน ไม่เปลี่ยนสิทธิ์ ไม่ปิดการเข้าสู่ระบบ และไม่เปลี่ยนข้อมูลช่าง คนขับ หรืองานที่มอบหมาย',
}

export const departmentLifecycleAdapter: LifecycleAdapter = {
  entity: 'departments',
  entityLabel: 'แผนก',
  capability: CAN_MANAGE_DEPARTMENT,
  normalize: (json) => {
    const history = json as DepartmentLifecycleHistory
    return {
      current: departmentKey(history.current_state),
      currentRaw: null,
      consistency: history.lifecycle_consistency,
      events: history.events.map((e) => ({
        id: e.lifecycle_event_id, kind: e.event_kind, previous: departmentKey(e.previous_state),
        next: departmentKey(e.new_state), recordedAt: e.recorded_at, recordedBy: e.recorded_by, reason: e.reason_th,
      })),
    }
  },
  expectedBody: (current) => ({ expected_is_active: current === 'ACTIVE' }),
  stateLabel: (state) => stateLabel(state),
  dialogNote: 'การปิดใช้งานแผนกไม่เปลี่ยนข้อมูลบุคลากรใด ๆ',
}
