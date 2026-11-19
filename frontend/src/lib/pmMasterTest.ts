/**
 * R8 PRE-UAT SG-PM (Owner Consolidated Source Expansion Gate 2026-11-18) — client for the PM Master
 * TEST profile routes. They exist only when the backend runs with PM_MASTER_TEST_PROFILE=true (Mock +
 * Access Management + non-production); otherwise every call answers 404 and the UI shows nothing / "not
 * enabled". Every write carries a client X-Request-Id (the Master's replay contract). TEST data only.
 */
import { apiGet, type ApiResult } from './apiClient'
import { preuatSend } from './masterRecords'
import type { PmWorkOrderDetail, VehiclePmDue } from './types'

const BASE = '/pm-master-test'

export interface PmMasterTestSet {
  set_key: string
  model_variant: string
  section: string
  meter_type: string
  interval_value: number | null
  interval_unit: string
  independent_group: string
  items: { item_key: string; task_text: string }[]
}

export interface PmMasterTestRevision {
  revision_id: string
  plan_code: string
  revision_number: number
  source_digest: string
  sets: PmMasterTestSet[]
}

export interface PmMasterTestStatus {
  note_th: string
  plan_code: string
  source_file: string
  latest_preview_id: string | null
  head_revision: PmMasterTestRevision | null
  assignments: { vehicle_id: string; assembly: string; state: string; plan_code: string | null; version: number }[]
  variant_approvals: { model_id: string; plan_code: string; model_variant: string; state: string; version: number }[]
}

export interface PmMasterTestLedgerEntry {
  entry_id: string
  action: string
  issue: string
  row_or_key: string
  plan_scope: string[]
  resolved: boolean
}

export interface PmMasterTestPreview {
  preview_id: string
  source_file: string
  source_digest: string
  registered_by: string
  ledger: PmMasterTestLedgerEntry[]
  mapping_candidates: { source_row: string; vehicle_ref: string; plan_code: string; plan_model: string; status: string }[]
}

export const getPmMasterTestStatus = (): Promise<ApiResult<PmMasterTestStatus>> => apiGet(`${BASE}/status`)

export const getPmMasterTestPreview = (previewId: string): Promise<ApiResult<PmMasterTestPreview>> =>
  apiGet(`${BASE}/previews/${encodeURIComponent(previewId)}`)

export const registerPmMasterTestPreview = (reason: string, requestId: string) =>
  preuatSend<PmMasterTestPreview>(`${BASE}/previews`, 'POST', { reason }, requestId)

export const resolvePmMasterTestReview = (previewId: string, body: {
  expected_source_digest: string; entry_id: string; outcome: string; evidence: string; values?: Record<string, string>
}, requestId: string) =>
  preuatSend<{ resolution_id: string; preview: PmMasterTestPreview }>(
    `${BASE}/previews/${encodeURIComponent(previewId)}/reviews`, 'POST', body, requestId)

export const publishPmMasterTest = (body: {
  preview_id: string; expected_source_digest: string; expected_revision: number; reason: string
}, requestId: string) =>
  preuatSend<{ replayed: boolean; revision: PmMasterTestRevision }>(`${BASE}/publications`, 'POST', body, requestId)

export const approvePmMasterTestVariant = (body: {
  model_id: string; model_variant: string; expected_version: number; preview_id: string;
  expected_source_digest: string; source_rows: string[]; evidence: string; reason: string
}, requestId: string) => preuatSend<{ state: string; version: number }>(`${BASE}/variant-approvals`, 'POST', body,
  requestId)

export const assignPmMasterTest = (body: {
  vehicle_id: string; assembly: string; plan_code: string | null; expected_version: number; reason: string
}, requestId: string) => preuatSend<{ state: string; version: number }>(`${BASE}/assignments`, 'POST', body,
  requestId)

export const getPmMasterTestVehicleDue = (vehicleId: string): Promise<ApiResult<VehiclePmDue>> =>
  apiGet(`${BASE}/vehicles/${encodeURIComponent(vehicleId)}/due`)

export const openPmMasterTestWorkOrder = (vehicleId: string, body: {
  revision_number: number; selected_set_keys: string[]; note?: string
}, requestId: string) =>
  preuatSend<PmWorkOrderDetail>(`${BASE}/vehicles/${encodeURIComponent(vehicleId)}/work-orders`, 'POST', body,
    requestId)

/** Meter choices for a REVIEW meter decision (from the Master's own vocabulary). */
export const METER_DECISIONS: { value: string; label: string; meter_type: string; driving_component: string }[] = [
  { value: 'CARRIER', label: 'ชั่วโมงเครื่องยนต์ตัวรถ (CARRIER_ENGINE)', meter_type: 'ENGINE_HOUR',
    driving_component: 'CARRIER_ENGINE' },
  { value: 'CRANE', label: 'ชั่วโมงเครื่องยนต์เครน (CRANE_ENGINE)', meter_type: 'ENGINE_HOUR',
    driving_component: 'CRANE_ENGINE' },
]
