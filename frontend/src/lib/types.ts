/** Mirrors backend/app/api/v1/vehicle_schemas.py and equipment_schemas.py. */

/** Vehicle-only. Workshop equipment uses `EquipmentOperationalStatus`
 * instead — a separate vocabulary approved as the resolution of
 * OPEN_DECISIONS_REGISTER_EN.txt decision C02; do not reuse this type
 * for equipment. */
export type OperationalStatus =
  | 'WORKING'
  | 'READY'
  | 'MAINTENANCE'
  | 'OUT_OF_SERVICE'
  | 'LONG_TERM_PARKING'

/** Workshop equipment status vocabulary (decision C02). Distinct from
 * Vehicle's `OperationalStatus`; do not add vehicle-only values here. */
export type EquipmentOperationalStatus = 'READY' | 'IN_USE' | 'MAINTENANCE' | 'OUT_OF_SERVICE'

export type ComponentRole = 'CARRIER_ENGINE' | 'CRANE_ENGINE' | 'PTO' | 'VEHICLE'

export type EquipmentCategory =
  | 'LATHE'
  | 'MILLING'
  | 'AIR_COMPRESSOR'
  | 'WELDING'
  | 'PRESS'
  | 'DRILL_PRESS'
  | 'GRINDER'
  | 'FORKLIFT'
  | 'OTHER'

export interface Page<T> {
  items: T[]
  page: number
  page_size: number
  total_items: number
}

export interface VehicleModel {
  model_id: string
  model_code: string
  model_name: string
  brand: string | null
  description: string | null
  component_roles: ComponentRole[]
  created_at: string
  updated_at: string
}

export interface Vehicle {
  vehicle_id: string
  machine_no: string
  model_id: string
  serial_number: string | null
  operational_status: OperationalStatus
  created_at: string
  updated_at: string
}

export interface VehicleComponent {
  component_id: string
  vehicle_id: string
  component_role: ComponentRole
  label: string
}

export interface VehicleStatusHistoryEntry {
  history_id: string
  vehicle_id: string
  status: OperationalStatus
  changed_at: string
  changed_by: string | null
  note: string | null
}

export interface VehicleDetail {
  vehicle: Vehicle
  model: VehicleModel | null
  components: VehicleComponent[]
}

export interface ChangeVehicleStatusResult {
  vehicle: Vehicle
  history_entry: VehicleStatusHistoryEntry
}

export interface Equipment {
  equipment_id: string
  equipment_code: string
  name: string
  category: EquipmentCategory
  serial_number: string | null
  location: string | null
  operational_status: EquipmentOperationalStatus
  created_at: string
  updated_at: string
}

/** Phase 3 — inspection / checklist. Mirrors
 * backend/app/api/v1/inspection_schemas.py. */

export type AssetType = 'VEHICLE' | 'EQUIPMENT'

/** Stable English result codes (backend/app/domain/checklist.py). Thai
 * labels live in `lib/labels.ts` — never hard-code Thai text for these
 * codes anywhere else. */
export type InspectionResultValue = 'PASS' | 'FAIL' | 'NA'

export interface AttachmentInfo {
  attachment_id: string
  purpose: string
  filename: string
  content_type: string
  size_bytes: number
  uploaded_at: string
  uploaded_by: string | null
  url: string
}

export interface ChecklistItem {
  item_id: string
  revision_id: string
  sequence: number
  title: string
  inspection_point: string | null
  method: string | null
  standard: string | null
  instruction: string | null
  frequency: string | null
  required_photo_on_fail: boolean
  /** CORRECTION (post-Phase-3 verification): per-item, source-data-driven
   * flag, defaults to `false` — a FAIL requiring a remark is never a
   * global, unconditional rule. Mirrors `required_photo_on_fail`. */
  required_remark_on_fail: boolean
  is_critical: boolean
  /** Master guidance image — separate from the evidence photo captured
   * during an actual inspection (see `InspectionItemResult.evidence`). */
  reference_image: AttachmentInfo | null
}

export interface ChecklistMasterInfo {
  checklist_id: string
  asset_type: AssetType
  code: string
  name: string
}

export interface ChecklistRevisionInfo {
  revision_id: string
  checklist_id: string
  revision_number: number
  effective_date: string
  created_at: string
}

export interface ChecklistRevisionDetail {
  checklist: ChecklistMasterInfo
  revision: ChecklistRevisionInfo
  items: ChecklistItem[]
}

export interface SubmitInspectionItem {
  item_id: string
  result: InspectionResultValue
  remark?: string | null
  evidence_attachment_ids?: string[]
}

export interface SubmitInspectionRequest {
  asset_type: AssetType
  asset_id: string
  overall_remark?: string | null
  items: SubmitInspectionItem[]
}

export interface InspectionItemResult {
  result_id: string
  inspection_id: string
  item_id: string
  sequence: number
  title: string
  inspection_point: string | null
  method: string | null
  standard: string | null
  instruction: string | null
  is_critical: boolean
  result: InspectionResultValue
  remark: string | null
  /** Evidence photos captured for this result — separate from the
   * checklist item's `reference_image`. */
  evidence: AttachmentInfo[]
}

export interface InspectionFinding {
  finding_id: string
  inspection_id: string
  result_id: string
  asset_type: AssetType
  asset_id: string
  item_title: string
  is_critical: boolean
  status: string
  created_at: string
}

export interface InspectionHeader {
  inspection_id: string
  asset_type: AssetType
  asset_id: string
  checklist_id: string
  revision_id: string
  revision_number: number
  submitted_at: string
  inspector_user_id: string | null
  overall_remark: string | null
}

export interface InspectionDetail {
  header: InspectionHeader
  items: InspectionItemResult[]
  findings: InspectionFinding[]
}

export interface InspectionSummary {
  inspection_id: string
  asset_type: AssetType
  asset_id: string
  checklist_id: string
  revision_number: number
  submitted_at: string
  inspector_user_id: string | null
  pass_count: number
  fail_count: number
  na_count: number
  has_fail: boolean
}
