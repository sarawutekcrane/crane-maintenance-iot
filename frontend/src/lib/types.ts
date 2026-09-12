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

/** Phase 4 — meter/counter snapshot. Mirrors
 * backend/app/api/v1/meter_schemas.py. Guardrails §10 frozen concept:
 * vehicle_id -> component_id -> counter_type -> value. `value: null` means
 * UNKNOWN and must never be displayed/treated as 0. */
export type CounterType = 'ENGINE_HOUR' | 'PTO_HOUR' | 'ODOMETER'

export interface MeterReadingInput {
  component_id?: string | null
  counter_type: CounterType
  value: number | null
}

export interface MeterReading {
  component_id: string | null
  counter_type: CounterType
  value: number | null
}

export interface MeterSnapshot {
  meter_snapshot_id: string
  asset_type: AssetType
  asset_id: string
  readings: MeterReading[]
  recorded_at: string
  recorded_by: string | null
}

/** Phase 4 — PM (preventive maintenance). Mirrors
 * backend/app/api/v1/pm_schemas.py. PLAN2/PLAN3/PLAN4 are not fabricated
 * (OPEN_DECISIONS_REGISTER_EN.txt E05) — only plans the backend actually
 * returns should ever be rendered. */
export type PmTriggerType = 'ENGINE_HOUR' | 'PTO_HOUR' | 'ODOMETER' | 'CALENDAR'

export type PmWorkOrderStatus = 'OPEN' | 'CLOSED'

export interface PmTaskPart {
  pm_task_part_id: string
  pm_task_id: string
  part_description: string
  quantity: number | null
  unit: string | null
}

export interface PmTask {
  pm_task_id: string
  revision_id: string
  sequence: number
  group: string | null
  description: string
  trigger_type: PmTriggerType | null
  interval_value: number | null
  interval_unit: string | null
  standard_parts: PmTaskPart[]
}

export interface PmPlan {
  pm_plan_id: string
  plan_code: string
  asset_type: AssetType
  name: string
  model_ids: string[]
}

export interface PmTaskRevision {
  revision_id: string
  pm_plan_id: string
  revision_number: number
  effective_date: string
  source_revision_note: string | null
  created_at: string
}

export interface PmTaskRevisionDetail {
  plan: PmPlan
  revision: PmTaskRevision
  tasks: PmTask[]
}

/** `due_status` is always `"UNKNOWN"` in Phase 4 (E02/E03/E04 unresolved)
 * — never compute a due/remaining value from `last_completed_*` on the
 * frontend; display `due_status_note` as-is. */
export interface PmPlanStatus {
  plan: PmPlan
  active_revision: PmTaskRevision | null
  last_completed_work_order_id: string | null
  last_completed_at: string | null
  last_completed_meter_snapshot_id: string | null
  due_status: string
  due_status_note: string
}

export interface PmUsedPartInput {
  part_description: string
  quantity?: number | null
  unit?: string | null
}

export interface PmUsedPart {
  pm_used_part_id: string
  pm_work_result_id: string
  part_description: string
  quantity: number | null
  unit: string | null
  recorded_by: string | null
  recorded_at: string
}

export interface PmWorkResult {
  pm_work_result_id: string
  pm_work_order_id: string
  pm_task_id: string
  revision_id: string
  sequence: number
  task_description: string
  completed: boolean
  meter_snapshot_id: string | null
  remark: string | null
  used_parts: PmUsedPart[]
  evidence_attachment_ids: string[]
  performed_by: string | null
  performed_at: string
}

export interface PmWorkOrder {
  pm_work_order_id: string
  asset_type: AssetType
  asset_id: string
  pm_plan_id: string
  revision_id: string
  due_reason: PmTriggerType | null
  status: PmWorkOrderStatus
  opened_at: string
  opened_by: string | null
  closed_at: string | null
  closed_by: string | null
  note: string | null
}

export interface PmWorkOrderDetail {
  work_order: PmWorkOrder
  results: PmWorkResult[]
}

export interface PmWorkOrderSummary {
  pm_work_order_id: string
  asset_type: AssetType
  asset_id: string
  pm_plan_id: string
  revision_id: string
  status: PmWorkOrderStatus
  opened_at: string
  closed_at: string | null
  result_count: number
}

/** Phase 4 — Repair. Mirrors backend/app/api/v1/repair_schemas.py. Repair
 * is a separate domain from PM (never merged into a PM work order). */
export type RepairSourceType = 'MANUAL' | 'INSPECTION_RESULT' | 'FINDING' | 'PM_RESULT' | 'ALERT'

export type RepairStatus = 'OPEN' | 'CLOSED'

export interface Repair {
  repair_id: string
  asset_type: AssetType
  asset_id: string
  source_type: RepairSourceType
  source_id: string | null
  category: string | null
  symptom: string | null
  meter_snapshot_id: string | null
  status: RepairStatus
  opened_at: string
  opened_by: string | null
  closed_at: string | null
  closed_by: string | null
  close_note: string | null
}

export interface RepairAction {
  repair_action_id: string
  repair_id: string
  action_text: string
  actor: string | null
  created_at: string
  attachment_ids: string[]
}

export interface RepairPart {
  repair_part_id: string
  repair_id: string
  part_description: string
  quantity: number | null
  unit: string | null
  recorded_by: string | null
  recorded_at: string
}

export interface RepairDetail {
  repair: Repair
  actions: RepairAction[]
  parts: RepairPart[]
}

export interface RepairSummary {
  repair_id: string
  asset_type: AssetType
  asset_id: string
  source_type: RepairSourceType
  source_id: string | null
  status: RepairStatus
  opened_at: string
  closed_at: string | null
  action_count: number
}
