/**
 * R8 PRE-UAT Whole-Web Completion (Owner source approval Rev 1) — the shared PRE-UAT write
 * helper and the TEST master record client (Mock/TEST only; the backend enforces every rule).
 *
 * `preuatSend` sends the client X-Request-Id through the existing `apiMutation`
 * (never retried automatically). `useRetainedRequestId` keeps ONE id per intent until a
 * definitive answer, so a resend after a timeout replays the original result on the server
 * instead of writing twice. The id changes only after success or after the user edits the
 * form (a new intent).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, apiGet, apiMutation, type ApiResult } from './apiClient'
import { useCapabilities } from './capabilities'
import { newR2RequestId } from './r2HistoryWrites'
import type { MasterEntityPath, MasterRecordList, MasterRecordOutcome } from './types'

export async function preuatSend<T>(path: string, method: 'POST' | 'PATCH', body: unknown,
  requestId: string): Promise<ApiResult<T>> {
  const response = await apiMutation(path, method, body, { requestId })
  if (response.kind === 'transport') return { ok: false, error: response.error }
  if (response.status >= 200 && response.status < 300) return { ok: true, data: response.json as T }
  const json = response.json as { error?: { code: string; message: string; details?: Record<string, unknown> } }
  if (json && typeof json === 'object' && json.error && typeof json.error.code === 'string') {
    return { ok: false, error: new ApiError(response.status, json as never) }
  }
  return { ok: false, error: new Error(`HTTP ${response.status}`) }
}

export function useRetainedRequestId() {
  const ref = useRef<string | null>(null)
  const current = useCallback((): string | null => {
    if (!ref.current) ref.current = newR2RequestId()
    return ref.current
  }, [])
  const reset = useCallback(() => {
    ref.current = null
  }, [])
  return { current, reset }
}

export interface MasterFieldDef {
  name: string
  label: string
  required?: boolean
  choices?: { value: string; label: string }[]
  multi?: boolean
  editable?: boolean
}

export const MASTER_FIELDS: Record<MasterEntityPath, MasterFieldDef[]> = {
  vehicles: [
    { name: 'machine_no', label: 'หมายเลขเครื่องจักร', required: true },
    { name: 'model_id', label: 'รหัสรุ่น', required: true },
    { name: 'serial_number', label: 'หมายเลขซีเรียล' },
    { name: 'operational_status', label: 'สถานะ', required: true, choices: [
      { value: 'READY', label: 'พร้อมใช้งาน' }, { value: 'WORKING', label: 'ใช้งานอยู่' },
      { value: 'MAINTENANCE', label: 'ซ่อมบำรุง' }, { value: 'OUT_OF_SERVICE', label: 'หยุดใช้งาน' },
      { value: 'LONG_TERM_PARKING', label: 'จอดระยะยาว' }] },
  ],
  models: [
    { name: 'model_code', label: 'รหัสรุ่น (code)', required: true },
    { name: 'model_name', label: 'ชื่อรุ่น', required: true, editable: true },
    { name: 'brand', label: 'ยี่ห้อ', editable: true },
    { name: 'description', label: 'รายละเอียด', editable: true },
    { name: 'component_roles', label: 'ส่วนประกอบ', required: true, multi: true, choices: [
      { value: 'CARRIER_ENGINE', label: 'เครื่องยนต์ช่วงล่าง' }, { value: 'CRANE_ENGINE', label: 'เครื่องยนต์ชุดเครน' },
      { value: 'PTO', label: 'PTO' }, { value: 'VEHICLE', label: 'ตัวรถ' }] },
  ],
  equipment: [
    { name: 'equipment_code', label: 'รหัสเครื่องมือ', required: true },
    { name: 'name', label: 'ชื่อ', required: true, editable: true },
    { name: 'category', label: 'ประเภท', required: true, choices: [
      'LATHE', 'MILLING', 'AIR_COMPRESSOR', 'WELDING', 'PRESS', 'DRILL_PRESS', 'GRINDER', 'FORKLIFT', 'OTHER',
    ].map((v) => ({ value: v, label: v })) },
    { name: 'serial_number', label: 'หมายเลขซีเรียล', editable: true },
    { name: 'location', label: 'ที่ตั้ง', editable: true },
    { name: 'operational_status', label: 'สถานะ', required: true, choices: [
      { value: 'READY', label: 'พร้อมใช้งาน' }, { value: 'IN_USE', label: 'ใช้งานอยู่' },
      { value: 'MAINTENANCE', label: 'ซ่อมบำรุง' }, { value: 'OUT_OF_SERVICE', label: 'หยุดใช้งาน' },
      { value: 'RETIRED', label: 'ปลดระวาง' }] },
  ],
  branches: [{ name: 'branch_name', label: 'ชื่อสาขา', required: true, editable: true }],
  departments: [{ name: 'department_name_th', label: 'ชื่อแผนก', required: true, editable: true }],
  personnel: [
    { name: 'first_name', label: 'ชื่อ', required: true, editable: true },
    { name: 'last_name', label: 'นามสกุล', required: true, editable: true },
    { name: 'position', label: 'ตำแหน่ง', editable: true },
  ],
  technicians: [
    { name: 'first_name', label: 'ชื่อ', required: true, editable: true },
    { name: 'last_name', label: 'นามสกุล', required: true, editable: true },
  ],
}

export const MASTER_ENTITY_LABEL: Record<MasterEntityPath, string> = {
  vehicles: 'รถ', models: 'รุ่นรถ', equipment: 'เครื่องมือ', branches: 'สาขา', departments: 'แผนก',
  personnel: 'บุคลากร', technicians: 'ช่าง',
}

export const MASTER_ID_COLUMN: Record<MasterEntityPath, string> = {
  vehicles: 'vehicle_id', models: 'model_id', equipment: 'equipment_id', branches: 'branch_id',
  departments: 'department_id', personnel: 'personnel_id', technicians: 'technician_id',
}

export function listMasterRecords(entity: MasterEntityPath): Promise<ApiResult<MasterRecordList>> {
  return apiGet<MasterRecordList>(`/master-records/${entity}`)
}

export function saveMasterRecord(entity: MasterEntityPath, recordId: string | null, body: Record<string, unknown>,
  requestId: string): Promise<ApiResult<MasterRecordOutcome>> {
  return recordId
    ? preuatSend<MasterRecordOutcome>(`/master-records/${entity}/${encodeURIComponent(recordId)}`, 'PATCH', body,
      requestId)
    : preuatSend<MasterRecordOutcome>(`/master-records/${entity}`, 'POST', body, requestId)
}

/**
 * PG-5 P-A: whether a control guarded by a per-employee TEST grant should be shown. In Access
 * Management mode only a holder of `capability` sees it (the backend D6 policy re-checks every write);
 * outside it (`/access/me` answers 409 ACCESS_MANAGEMENT_NOT_ENABLED) the control is unchanged and the
 * existing development-mode rules apply on the server. Hidden while unknown (fail-closed). UX only.
 */
export function useTestGrantControlVisible(capability: string): boolean {
  const { hasCapability, loading } = useCapabilities()
  const [mode, setMode] = useState<'AM' | 'LEGACY' | 'UNKNOWN'>('UNKNOWN')
  useEffect(() => {
    let live = true
    void apiGet<unknown>('/access/me').then((r) => {
      if (!live) return
      if (r.ok) setMode('AM')
      else if (r.error instanceof ApiError && r.error.code === 'ACCESS_MANAGEMENT_NOT_ENABLED') setMode('LEGACY')
      else setMode('AM') // any other answer: treat as Access Management (fail-closed)
    })
    return () => { live = false }
  }, [])
  if (mode === 'LEGACY') return true
  return mode === 'AM' && !loading && hasCapability(capability)
}
