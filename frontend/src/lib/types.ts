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

/** Workshop equipment status vocabulary (decision C02, extended by the
 * Core Demo Fixes EQUIPMENT STATUS CHANGE approval with RETIRED).
 * Distinct from Vehicle's `OperationalStatus`; do not add vehicle-only
 * values here. */
export type EquipmentOperationalStatus =
  | 'READY'
  | 'IN_USE'
  | 'MAINTENANCE'
  | 'OUT_OF_SERVICE'
  | 'RETIRED'

export interface EquipmentStatusHistoryEntry {
  history_id: string
  equipment_id: string
  status: EquipmentOperationalStatus
  changed_at: string
  changed_by: string | null
  reason: string | null
}

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
  /** Core Demo Fixes, PM WORKFLOW REDESIGN section A. `null` means
   * SOURCE-DATA-REQUIRED — no authoritative model->plan mapping exists. */
  assigned_pm_plan_id: string | null
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
  machine_state_snapshot_id: string | null
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
  /** Core Demo Fix: when this reading was actually observed — may be
   * earlier than the snapshot's own `recorded_at` when carried forward
   * automatically. `null` alongside `value: null` means UNKNOWN. */
  observed_at: string | null
}

export interface MeterSnapshot {
  meter_snapshot_id: string
  asset_type: AssetType
  asset_id: string
  readings: MeterReading[]
  recorded_at: string
  recorded_by: string | null
  /** Core Demo Fix: `true` for the automatic machine-state snapshot
   * mechanism; `false` for a manually-entered reading. */
  is_automatic: boolean
  latitude: number | null
  longitude: number | null
  gps_observed_at: string | null
  source_note: string | null
}

/** Core Demo Fix: read-only preview of an asset's current backend-derived
 * state — never persisted. Used to display values read-only instead of a
 * manual counter/GPS entry form (APPROVED CORE RULE). */
export interface CurrentMachineState {
  asset_type: AssetType
  asset_id: string
  readings: MeterReading[]
  latitude: number | null
  longitude: number | null
  gps_observed_at: string | null
  note: string
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
  part_id: string | null
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

/** Phase 5 — PM/Repair actual part action (baseline "PM/Repair actual
 * actions"). Descriptive metadata only on an actual-usage record; does
 * NOT itself install/remove/transfer a PartInstance — that is done
 * explicitly via the part-instance endpoints. */
export type PartActionType = 'CONSUMED' | 'INSTALLED' | 'REMOVED' | 'SERVICED'

export interface PmUsedPartInput {
  part_description: string
  quantity?: number | null
  unit?: string | null
  part_id?: string | null
  part_instance_id?: string | null
  action?: PartActionType | null
}

export interface PmUsedPart {
  pm_used_part_id: string
  pm_work_result_id: string
  part_description: string
  quantity: number | null
  unit: string | null
  part_id: string | null
  part_instance_id: string | null
  action: PartActionType | null
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
  opened_snapshot_id: string | null
  closed_snapshot_id: string | null
  /** Core Demo Fixes, PM WORKFLOW REDESIGN section C/D — the working set
   * of task IDs currently in scope for this PM occurrence. */
  scope_task_ids: string[]
  scope_approved_at: string | null
  scope_approved_by: string | null
  /** Core Demo Fixes Delta section B — structurally symmetric with
   * Repair's own assignment fields; references user_account.user_id. */
  primary_technician: string | null
  collaborators: string[]
}

export interface PmScopeAddition {
  pm_work_order_id: string
  pm_task_id: string
  added_by: string | null
  added_at: string
  reason: string
}

export interface PmWorkOrderDetail {
  work_order: PmWorkOrder
  results: PmWorkResult[]
  scope_additions: PmScopeAddition[]
}

/** Core Demo Fixes Delta (REV03), section D/H — Store/Inventory
 * integration boundary (`material_request` / `material_request_line`
 * sheets). Never implies a warehouse/stock or approval workflow exists;
 * `request_status` is a plain, unconstrained string. */
export type RequisitionSourceType = 'PM' | 'REPAIR'

export interface MaterialRequest {
  material_request_id: string
  source_type: RequisitionSourceType
  source_work_order_id: string
  vehicle_id: string | null
  request_status: string
  created_at: string
  created_by: string | null
  approved_at: string | null
  approved_by: string | null
  issued_at: string | null
  issued_by: string | null
  closed_at: string | null
  note: string | null
}

export interface RequisitionLine {
  requisition_line_id: string
  material_request_id: string
  source_task_revision_id: string | null
  part_id: string | null
  part_instance_id: string | null
  part_code_snapshot: string | null
  part_description: string
  requested_quantity: number | null
  unit: string | null
  approved_quantity: number | null
  issued_quantity: number | null
  used_quantity: number | null
  returned_quantity: number | null
  line_source: string | null
  created_at: string
  created_by: string | null
}

export interface MaterialRequestDetail {
  request: MaterialRequest
  lines: RequisitionLine[]
}

/** Core Demo Fixes Delta section E — the GPS/location half of the shared
 * automatic machine-state snapshot mechanism (`location_snapshot` sheet),
 * complementing `MeterSnapshot` (counters). Immutable, backend-derived;
 * `null` fields mean honestly-unknown, never a fabricated `0, 0`. */
export interface LocationSnapshot {
  location_snapshot_id: string
  event_type: string
  event_id: string
  vehicle_id: string | null
  device_id: string | null
  latitude: number | null
  longitude: number | null
  altitude_m: number | null
  accuracy_m: number | null
  gps_time: string | null
  received_at: string | null
  snapshot_at: string
  gps_valid: boolean
  source: string | null
  note: string | null
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
  primary_technician: string | null
  collaborators: string[]
}

/** Phase 4 — Repair. Mirrors backend/app/api/v1/repair_schemas.py. Repair
 * is a separate domain from PM (never merged into a PM work order). */
export type RepairSourceType =
  | 'MANUAL'
  | 'INSPECTION_RESULT'
  | 'FINDING'
  | 'PM_RESULT'
  | 'ALERT'
  | 'REPAIR_REQUEST'

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
  closed_snapshot_id: string | null
  primary_technician: string | null
  collaborators: string[]
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
  part_id: string | null
  part_instance_id: string | null
  action: PartActionType | null
  recorded_by: string | null
  recorded_at: string
}

export interface RepairDetail {
  repair: Repair
  actions: RepairAction[]
  parts: RepairPart[]
  /** Core Demo Fixes Delta section H — derived "งานรออะไหล่" indicator
   * (True when this repair has a non-terminal MaterialRequest). Only
   * populated on GET /repairs/{id}; `null`/absent elsewhere. */
  awaiting_parts?: boolean | null
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
  primary_technician: string | null
  collaborators: string[]
  symptom: string | null
}

/** Phase 5 — Parts / Lifetime / Transfer. Mirrors
 * backend/app/api/v1/part_schemas.py, part_instance_schemas.py,
 * position_lifetime_schemas.py, lifetime_rule_schemas.py.
 *
 * G01 (real lifetime rules), G02 (warning windows), G03 (position code
 * master), G04 (overhaul reset rules), G05 (part instance status
 * transitions), and G06 (usage adjustment approval) all remain
 * unresolved (OPEN_DECISIONS_REGISTER_EN.txt) — nothing here computes a
 * due/remaining value, invents a position-code vocabulary, or allows an
 * arbitrary correction of prior/accumulated usage. */

export type TrackingMode = 'NONE' | 'CONSUMABLE' | 'POSITION_LIFETIME' | 'INSTANCE_TRACKED'

export interface PartMaster {
  part_id: string
  part_code: string
  name: string
  specification: string | null
  manufacturer: string | null
  part_number: string | null
  tracking_mode: TrackingMode
  category: string | null
  is_active: boolean
  metadata: Record<string, string>
  created_at: string
  updated_at: string
}

export type PartSetItemRequirement = 'REQUIRED' | 'OPTIONAL' | 'ALTERNATIVE'

export interface PartSet {
  part_set_id: string
  set_code: string
  name: string
  created_at: string
  updated_at: string
}

export interface PartSetItem {
  part_set_item_id: string
  revision_id: string
  part_id: string
  requirement: PartSetItemRequirement
  quantity: number | null
  unit: string | null
  note: string | null
}

export interface PartSetRevision {
  revision_id: string
  part_set_id: string
  revision_number: number
  effective_date: string
  created_at: string
}

export interface PartSetRevisionDetail {
  part_set: PartSet
  revision: PartSetRevision
  items: PartSetItem[]
}

/** G05: PARTIALLY FROZEN — known states only, no transition matrix. */
export type PartInstanceStatus =
  | 'INSTALLED'
  | 'REMOVED'
  | 'IN_REPAIR'
  | 'READY_FOR_INSTALL'
  | 'STOCK'
  | 'SCRAPPED'

/** Historical prior-usage quality state (baseline "PRIOR USAGE /
 * MID-LIFE ENROLLMENT"). UNKNOWN must never be displayed/treated as 0. */
export type PriorUsageQuality = 'KNOWN' | 'PARTIAL' | 'UNKNOWN'

export interface PriorUsage {
  quality: PriorUsageQuality
  value: number | null
  note: string | null
}

export interface PriorUsageInput {
  quality: PriorUsageQuality
  value?: number | null
  note?: string | null
}

export interface PartInstance {
  part_instance_id: string
  part_id: string
  serial_number: string | null
  status: PartInstanceStatus
  prior_usage: PriorUsage
  current_lifecycle_id: string
  note: string | null
  created_at: string
  updated_at: string
}

export type LifecycleStartReason = 'ENROLLMENT' | 'OVERHAUL'

export interface PartLifecycle {
  lifecycle_id: string
  part_instance_id: string
  cycle_number: number
  start_reason: LifecycleStartReason
  started_at: string
  started_by: string | null
  started_note: string | null
  ended_at: string | null
}

export type InstallationSegmentStatus = 'ACTIVE' | 'CLOSED'

export interface InstallationSegment {
  segment_id: string
  part_instance_id: string
  lifecycle_id: string
  asset_type: AssetType
  asset_id: string
  position_code: string | null
  status: InstallationSegmentStatus
  installed_at: string
  installed_by: string | null
  baseline_meter_snapshot_id: string | null
  install_note: string | null
  removed_at: string | null
  removed_by: string | null
  removal_meter_snapshot_id: string | null
  removal_reason: string | null
}

export interface PartInstanceDetail {
  instance: PartInstance
  lifecycles: PartLifecycle[]
  segments: InstallationSegment[]
}

export interface PositionLifetimeRecord {
  position_lifetime_id: string
  asset_type: AssetType
  asset_id: string
  position_code: string
  part_id: string | null
  lifetime_rule_id: string | null
  baseline_meter_snapshot_id: string | null
  prior_usage: PriorUsage
  started_at: string
  started_by: string | null
  note: string | null
}

export type LifetimeTriggerType = 'ENGINE_HOUR' | 'PTO_HOUR' | 'ODOMETER' | 'CYCLE' | 'CALENDAR'

export type LifetimeRuleScope = 'MODEL' | 'VEHICLE'

export interface LifetimeRule {
  lifetime_rule_id: string
  part_id: string
  scope: LifetimeRuleScope
  model_id: string | null
  vehicle_id: string | null
  trigger_type: LifetimeTriggerType
  component_role: ComponentRole | null
  first_due_value: number | null
  interval_value: number | null
  warning_window_value: number | null
  note: string | null
  created_at: string
}

/** Core Demo Fixes Delta REV05 section 10 — drives nav/action visibility
 * from the actor's actual capabilities instead of a hard-coded role list.
 * Backend authorization (`app.domain.authz.require_capability`) remains
 * authoritative regardless of what the frontend shows/hides. */
export interface MeResponse {
  user_id: string | null
  roles: string[]
  capabilities: string[]
}

/** Core Demo Fixes Delta REV05 section 3 — a reported problem waiting
 * for Maintenance review, never a Repair Work Order on its own. */
export interface RepairRequest {
  repair_request_id: string
  vehicle_id: string
  reported_at: string
  reported_by_user_id: string | null
  reporter_type: string | null
  reporter_driver_id: string | null
  reporter_name_snapshot_th: string | null
  report_channel: string | null
  symptom_th: string | null
  priority: string | null
  request_status: string
  reviewed_by_user_id: string | null
  reviewed_at: string | null
  repair_id: string | null
  converted_at: string | null
  note_th: string | null
  meter_snapshot_id: string | null
  /** Core Demo Fixes Delta REV06 section 15 — the originating Finding/PM
   * Work Result this request preserves provenance from, when any
   * (decoded server-side; `null` for an ordinary freeform report). */
  source_type: string | null
  source_id: string | null
}

export interface SubmitRepairRequestResponse {
  request: RepairRequest
  meter_snapshot_id: string | null
}
