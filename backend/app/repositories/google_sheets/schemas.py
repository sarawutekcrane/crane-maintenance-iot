"""Declared Google Sheets tab/header schema for Phase 2 domain tables.

Per docs/00_LOCAL_DEVELOPMENT_AND_NO_SERVER_SETUP_EN.txt section 7:
columns are mapped by header name, never by row position, and the tab
must be validated before writes. These declarations exist now so the
real implementation (added once local Google credentials are available —
see docs/claude-prompts/web-api/02_PHASE2_VEHICLE_MODEL_EQUIPMENT_QR_EN.txt
scope item 14) has an agreed-upon shape to validate against, matching the
prototype spreadsheet.

CORE DEMO FIXES DELTA (REV03 ALIGNMENT): the live prototype Google Sheet
was prepared independently with its own tab names, which take precedence
over this module's original Phase 2-5 guesses. Tab names below were
corrected to match the live sheet exactly (`tab_name=` values only —
domain code and field names are unchanged; columns are still mapped by
header name, not by matching some internal Python identifier). Do not
reintroduce the old plural/guessed names. Sheets outside the delta's
explicit list (checklist/part-set/lifecycle detail tables) were not
renamed — no live name was given for them, so guessing one would violate
"do not invent"; B01 (exact sheet schema version) remains TBD-BLOCKING for
those until confirmed.
"""
from __future__ import annotations

from app.repositories.google_sheets.client import SheetTabSchema

VEHICLE_MODEL_SHEET = SheetTabSchema(
    # Live sheet name: model_master (Core Demo Fixes Delta).
    tab_name="model_master",
    required_headers=(
        "model_id",
        "model_code",
        "model_name",
        "brand",
        "description",
        "component_roles",
        "created_at",
        "updated_at",
        # PM WORKFLOW REDESIGN section A / Delta section I: the prototype's
        # one column for "a model's exactly one assigned PM plan" — maps to
        # domain field VehicleModel.assigned_pm_plan_id. `None`/blank means
        # SOURCE-DATA-REQUIRED; never inferred.
        "default_plan_code",
    ),
)

VEHICLE_SHEET = SheetTabSchema(
    # Live sheet name: vehicle_master (Core Demo Fixes Delta).
    tab_name="vehicle_master",
    required_headers=(
        "vehicle_id",
        "machine_no",
        "model_id",
        "serial_number",
        "operational_status",
        "created_at",
        "updated_at",
    ),
)

VEHICLE_COMPONENT_SHEET = SheetTabSchema(
    # Live sheet name: vehicle_component (Core Demo Fixes Delta).
    tab_name="vehicle_component",
    required_headers=("component_id", "vehicle_id", "component_role", "label"),
)

VEHICLE_STATUS_HISTORY_SHEET = SheetTabSchema(
    tab_name="vehicle_status_history",
    required_headers=("history_id", "vehicle_id", "status", "changed_at", "changed_by", "note"),
)

EQUIPMENT_SHEET = SheetTabSchema(
    # Live sheet name: equipment_master (Core Demo Fixes Delta section 7).
    # Column names differ from the domain model's own field names — mapped
    # by header name, never by position:
    #   equipment_name_th   <- Equipment.name
    #   equipment_type      <- Equipment.category
    #   serial_no           <- Equipment.serial_number
    #   equipment_status    <- Equipment.operational_status (READY / IN_USE /
    #                          MAINTENANCE / OUT_OF_SERVICE / RETIRED — RETIRED
    #                          added by the EQUIPMENT STATUS CHANGE approval;
    #                          a vocabulary separate from Vehicle's
    #                          OperationalStatus, C02)
    #   brand / model_name / active_status / company_start_date
    #                       <- no current domain equivalent; not fabricated,
    #                          left for a future phase once needed
    tab_name="equipment_master",
    required_headers=(
        "equipment_id",
        "equipment_code",
        "equipment_name_th",
        "equipment_type",
        "brand",
        "model_name",
        "serial_no",
        "equipment_status",
        "active_status",
        "company_start_date",
        "note_th",
    ),
)

EQUIPMENT_STATUS_HISTORY_SHEET = SheetTabSchema(
    # Live sheet name matches already: equipment_status_history.
    # Column names differ from the domain model's own field names:
    #   status_history_id  <- EquipmentStatusHistoryEntry.history_id
    #   status_code        <- EquipmentStatusHistoryEntry.status
    #   start_at           <- EquipmentStatusHistoryEntry.changed_at
    #   reason_th          <- EquipmentStatusHistoryEntry.reason
    #   changed_by_user_id <- EquipmentStatusHistoryEntry.changed_by
    #                          (references user_account.user_id, never a
    #                          separate technician master — Delta section G)
    #   end_at / source_type / source_id
    #                       <- no current domain equivalent; not fabricated
    tab_name="equipment_status_history",
    required_headers=(
        "status_history_id",
        "equipment_id",
        "status_code",
        "start_at",
        "end_at",
        "reason_th",
        "changed_by_user_id",
        "source_type",
        "source_id",
    ),
)

# ---------------------------------------------------------------------------
# Inspection / checklist (Phase 3). Declared shape only — see
# GoogleSheetsRepository, which raises a controlled RepositoryError/
# NotImplementedError for these tabs until real credentials/schema
# validation are available, the same pattern established in Phase 2.
# ---------------------------------------------------------------------------

CHECKLIST_MASTER_SHEET = SheetTabSchema(
    tab_name="checklist_masters",
    required_headers=("checklist_id", "asset_type", "code", "name", "created_at", "updated_at"),
)

CHECKLIST_REVISION_SHEET = SheetTabSchema(
    tab_name="checklist_revisions",
    required_headers=(
        "revision_id",
        "checklist_id",
        "revision_number",
        "effective_date",
        "created_at",
    ),
)

CHECKLIST_ITEM_SHEET = SheetTabSchema(
    tab_name="checklist_items",
    required_headers=(
        "item_id",
        "revision_id",
        "sequence",
        "title",
        "inspection_point",
        "method",
        "standard",
        "instruction",
        "frequency",
        "reference_image_attachment_id",
        "required_photo_on_fail",
        "required_remark_on_fail",
        "is_critical",
    ),
)

ATTACHMENT_SHEET = SheetTabSchema(
    # Live sheet name: attachment (Core Demo Fixes Delta).
    # `source_type`/`source_id` added by Delta REV05 section 4 (additive —
    # every purpose predating REV05 leaves both blank and keeps linking
    # back to its owner via that owner's own attachment_ids field).
    tab_name="attachment",
    required_headers=(
        "attachment_id",
        "purpose",
        "storage_ref",
        "filename",
        "content_type",
        "size_bytes",
        "uploaded_at",
        "uploaded_by",
        "source_type",
        "source_id",
    ),
)

INSPECTION_SHEET = SheetTabSchema(
    # Live sheet name: inspection_header (Core Demo Fixes Delta).
    tab_name="inspection_header",
    required_headers=(
        "inspection_id",
        "asset_type",
        "asset_id",
        "checklist_id",
        "revision_id",
        "revision_number",
        "submitted_at",
        "inspector_user_id",
        "overall_remark",
        "machine_state_snapshot_id",
    ),
)

INSPECTION_ITEM_RESULT_SHEET = SheetTabSchema(
    # Live sheet name: inspection_result (Core Demo Fixes Delta).
    tab_name="inspection_result",
    required_headers=(
        "result_id",
        "inspection_id",
        "item_id",
        "sequence",
        "title",
        "inspection_point",
        "method",
        "standard",
        "instruction",
        "is_critical",
        "result",
        "remark",
        "evidence_attachment_ids",
    ),
)

INSPECTION_FINDING_SHEET = SheetTabSchema(
    tab_name="inspection_findings",
    required_headers=(
        "finding_id",
        "inspection_id",
        "result_id",
        "asset_type",
        "asset_id",
        "item_title",
        "is_critical",
        "status",
        "created_at",
    ),
)

# ---------------------------------------------------------------------------
# PM / Repair (Phase 4). Declared shape only — same controlled-error pattern
# as Phase 2/3 (GoogleSheetsRepository raises RepositoryError/
# NotImplementedError until real credentials/schema validation exist).
# ---------------------------------------------------------------------------

PM_PLAN_SHEET = SheetTabSchema(
    # Live sheet name: maintenance_plan (Core Demo Fixes Delta).
    tab_name="maintenance_plan",
    required_headers=(
        "pm_plan_id",
        "plan_code",
        "asset_type",
        "name",
        "model_ids",
        "created_at",
        "updated_at",
    ),
)

PM_TASK_REVISION_SHEET = SheetTabSchema(
    tab_name="pm_task_revisions",
    required_headers=(
        "revision_id",
        "pm_plan_id",
        "revision_number",
        "effective_date",
        "source_revision_note",
        "created_at",
    ),
)

PM_TASK_SHEET = SheetTabSchema(
    # Live sheet name: pm_task_master (Core Demo Fixes Delta).
    tab_name="pm_task_master",
    required_headers=(
        "pm_task_id",
        "revision_id",
        "sequence",
        "group",
        "description",
        "trigger_type",
        "interval_value",
        "interval_unit",
    ),
)

PM_TASK_PART_SHEET = SheetTabSchema(
    # Live sheet name: pm_task_part (Core Demo Fixes Delta) — the
    # authoritative source for PM standard parts; PmService.approve_scope
    # reads this (via PmTaskPart) to auto-generate material_request_line
    # rows, never a fabricated task-part mapping (Delta section D/F).
    tab_name="pm_task_part",
    required_headers=("pm_task_part_id", "pm_task_id", "part_description", "quantity", "unit"),
)

PM_WORK_ORDER_SHEET = SheetTabSchema(
    # Live sheet name: pm_work_order (Core Demo Fixes Delta).
    #
    # SCHEMA FIX (Google Sheets repository completion pass): the original
    # declaration had no column for `PmWorkOrder.opened_snapshot_id` /
    # `closed_snapshot_id` (the Core Demo Fix automatic machine-state
    # snapshot IDs, already surfaced in the API response schema —
    # `app.api.v1.pm_schemas`) even though the structurally-symmetric
    # `REPAIR_SHEET` already carries the equivalent `meter_snapshot_id`/
    # `closed_snapshot_id` columns. Implementing `create_pm_work_order`/
    # `close_pm_work_order` without these two columns would silently drop
    # data the domain contract requires round-tripping — the smallest
    # justified fix is adding the two columns here, mirroring
    # `REPAIR_SHEET`'s own precedent. This tab is not part of
    # `GoogleSheetsRepository._CORE_SCHEMAS`, so current readiness
    # (`GET /api/v1/readiness`) is unaffected; the live sheet's
    # `pm_work_order` tab needs these two columns added before this
    # repository mode is exercised against it for real PM work.
    tab_name="pm_work_order",
    required_headers=(
        "pm_work_order_id",
        "asset_type",
        "asset_id",
        "pm_plan_id",
        "revision_id",
        "due_reason",
        "status",
        "opened_at",
        "opened_by",
        "closed_at",
        "closed_by",
        "note",
        "opened_snapshot_id",
        "closed_snapshot_id",
    ),
)

PM_WORK_RESULT_SHEET = SheetTabSchema(
    # Live sheet name: pm_work_result (Core Demo Fixes Delta).
    tab_name="pm_work_result",
    required_headers=(
        "pm_work_result_id",
        "pm_work_order_id",
        "pm_task_id",
        "revision_id",
        "sequence",
        "task_description",
        "completed",
        "meter_snapshot_id",
        "remark",
        "evidence_attachment_ids",
        "performed_by",
        "performed_at",
    ),
)

PM_USED_PART_SHEET = SheetTabSchema(
    # Live sheet name: pm_used_part (Core Demo Fixes Delta).
    #
    # SCHEMA FIX (Google Sheets repository completion pass): the original
    # declaration had no columns for `PmUsedPart.part_id` /
    # `part_instance_id` / `action` — the same additive Phase 5 fields
    # `REPAIR_PART_SHEET` already declares for the structurally-identical
    # `RepairPart.part_id`/`part_instance_id`/`action`. Without these
    # columns a PM task result's actual-part links to a real Part
    # Master/Instance would be silently dropped on every write. Smallest
    # justified fix: add the same three columns here, mirroring
    # `REPAIR_PART_SHEET`. Not part of `_CORE_SCHEMAS`, so current
    # readiness is unaffected; the live `pm_used_part` tab needs these
    # three columns added before this repository mode is exercised
    # against it for real PM work with part linkage.
    tab_name="pm_used_part",
    required_headers=(
        "pm_used_part_id",
        "pm_work_result_id",
        "part_description",
        "quantity",
        "unit",
        "part_id",
        "part_instance_id",
        "action",
        "recorded_by",
        "recorded_at",
    ),
)

METER_SNAPSHOT_SHEET = SheetTabSchema(
    # Live sheet name: meter_snapshot (Core Demo Fixes Delta) — the
    # counter half of the shared automatic machine-state snapshot
    # mechanism; guardrails §9: meter_snapshot is historical capture,
    # current_counter is current state (see CURRENT_COUNTER_SHEET below).
    tab_name="meter_snapshot",
    required_headers=(
        "meter_snapshot_id",
        "asset_type",
        "asset_id",
        "recorded_at",
        "recorded_by",
        "is_automatic",
        "source_note",
    ),
)

# Read-only reference sheet already established by guardrails §9
# ("current_counter is current state") and confirmed present in the live
# sheet by the Core Demo Fixes Delta's "existing sheets that must be
# reused" list. No domain code in this repository currently writes a live
# "current counter" (no IoT/device ingestion exists yet — see
# app.domain.meter_service.MeterService.capture_current_state, which
# derives its carried-forward value from `meter_snapshot` history
# instead). Declared here only so a future phase that does implement live
# counter ingestion targets the correct existing tab, never a new one.
# Full column list is SOURCE-DATA-REQUIRED (not given by the Delta).
CURRENT_COUNTER_SHEET = SheetTabSchema(
    tab_name="current_counter",
    required_headers=("vehicle_id", "component_id", "counter_type", "value"),
)

# Web/API Phase 6 Batch 4B (Latest Location Projection): the original 5
# columns (guardrails §9's "latest_location is current location") are
# preserved byte-for-byte in name/order; source_device_id/
# source_component_id are appended so VehicleEventService can record
# which raw vehicle_event most recently won the projection (see
# app.domain.vehicle_event_service.VehicleEventService.
# _project_latest_location, the one and only writer of this sheet).
#
# IMPORTANT: this declaration describes the *target* schema Batch 4B
# code expects — same pattern as VEHICLE_EVENT_SHEET's Batch 4A note.
# The live spreadsheet still has only the original 5 headers; the
# 2-column append is a separate, explicitly-authorized migration
# performed after independent review. Until that migration runs,
# GoogleSheetsRepository schema validation against the live sheet will
# honestly report a schema mismatch rather than silently proceeding.
LATEST_LOCATION_SHEET = SheetTabSchema(
    tab_name="latest_location",
    required_headers=(
        "vehicle_id",
        "latitude",
        "longitude",
        "gps_time",
        "received_at",
        "source_device_id",
        "source_component_id",
    ),
)

METER_READING_SHEET = SheetTabSchema(
    tab_name="meter_readings",
    required_headers=("meter_snapshot_id", "component_id", "counter_type", "value"),
)

REPAIR_SHEET = SheetTabSchema(
    # Live sheet name: repair_order (Core Demo Fixes Delta). One real
    # repair occurrence = one row here = one Repair ID; a later occurrence
    # always gets a new row/ID, never reusing a closed one.
    tab_name="repair_order",
    required_headers=(
        "repair_id",
        "asset_type",
        "asset_id",
        "source_type",
        "source_id",
        "category",
        "symptom",
        "meter_snapshot_id",
        "closed_snapshot_id",
        "status",
        "opened_at",
        "opened_by",
        "closed_at",
        "closed_by",
        "close_note",
        "primary_technician",
        "collaborators",
    ),
)

REPAIR_ACTION_SHEET = SheetTabSchema(
    # Live sheet name: repair_action (Core Demo Fixes Delta).
    tab_name="repair_action",
    required_headers=(
        "repair_action_id",
        "repair_id",
        "action_text",
        "actor",
        "created_at",
        "attachment_ids",
    ),
)

REPAIR_PART_SHEET = SheetTabSchema(
    # Live sheet name: repair_part (Core Demo Fixes Delta).
    tab_name="repair_part",
    required_headers=(
        "repair_part_id",
        "repair_id",
        "part_description",
        "quantity",
        "unit",
        "part_id",
        "part_instance_id",
        "action",
        "recorded_by",
        "recorded_at",
    ),
)

# ---------------------------------------------------------------------------
# Part / Lifetime / Transfer (Phase 5). Declared shape only — same
# controlled-error pattern as every prior phase.
# ---------------------------------------------------------------------------

PART_MASTER_SHEET = SheetTabSchema(
    # Live sheet name: part_master (Core Demo Fixes Delta).
    tab_name="part_master",
    required_headers=(
        "part_id",
        "part_code",
        "name",
        "specification",
        "manufacturer",
        "part_number",
        "tracking_mode",
        "category",
        "is_active",
        "metadata",
        "created_at",
        "updated_at",
    ),
)

PART_SET_SHEET = SheetTabSchema(
    tab_name="part_sets",
    required_headers=("part_set_id", "set_code", "name", "created_at", "updated_at"),
)

PART_SET_REVISION_SHEET = SheetTabSchema(
    tab_name="part_set_revisions",
    required_headers=("revision_id", "part_set_id", "revision_number", "effective_date", "created_at"),
)

PART_SET_ITEM_SHEET = SheetTabSchema(
    tab_name="part_set_items",
    required_headers=(
        "part_set_item_id",
        "revision_id",
        "part_id",
        "requirement",
        "quantity",
        "unit",
        "note",
    ),
)

PART_INSTANCE_SHEET = SheetTabSchema(
    tab_name="part_instances",
    required_headers=(
        "part_instance_id",
        "part_id",
        "serial_number",
        "status",
        "prior_usage_quality",
        "prior_usage_value",
        "prior_usage_note",
        "current_lifecycle_id",
        "note",
        "created_at",
        "updated_at",
    ),
)

PART_LIFECYCLE_SHEET = SheetTabSchema(
    tab_name="part_lifecycles",
    required_headers=(
        "lifecycle_id",
        "part_instance_id",
        "cycle_number",
        "start_reason",
        "started_at",
        "started_by",
        "started_note",
        "ended_at",
    ),
)

INSTALLATION_SEGMENT_SHEET = SheetTabSchema(
    tab_name="installation_segments",
    required_headers=(
        "segment_id",
        "part_instance_id",
        "lifecycle_id",
        "asset_type",
        "asset_id",
        "position_code",
        "status",
        "installed_at",
        "installed_by",
        "baseline_meter_snapshot_id",
        "install_note",
        "removed_at",
        "removed_by",
        "removal_meter_snapshot_id",
        "removal_reason",
    ),
)

POSITION_LIFETIME_SHEET = SheetTabSchema(
    tab_name="position_lifetime_records",
    required_headers=(
        "position_lifetime_id",
        "asset_type",
        "asset_id",
        "position_code",
        "part_id",
        "lifetime_rule_id",
        "baseline_meter_snapshot_id",
        "prior_usage_quality",
        "prior_usage_value",
        "prior_usage_note",
        "started_at",
        "started_by",
        "note",
    ),
)

LIFETIME_RULE_SHEET = SheetTabSchema(
    tab_name="lifetime_rules",
    required_headers=(
        "lifetime_rule_id",
        "part_id",
        "scope",
        "model_id",
        "vehicle_id",
        "trigger_type",
        "component_role",
        "first_due_value",
        "interval_value",
        "warning_window_value",
        "note",
        "created_at",
    ),
)

# ---------------------------------------------------------------------------
# CORE DEMO FIXES DELTA (REV03 ALIGNMENT) — new sheets already present in
# the live prototype Google Sheet. Exact names/columns below are copied
# verbatim from the Delta prompt; do not rename or restructure them.
# ---------------------------------------------------------------------------

REPAIR_ASSIGNMENT_SHEET = SheetTabSchema(
    tab_name="repair_assignment",
    required_headers=(
        "repair_assignment_id",
        "repair_id",
        "user_id",
        "assignment_role",
        "assigned_at",
        "assigned_by_user_id",
        "ended_at",
        "active_status",
        "note_th",
    ),
)

PM_WORK_ASSIGNMENT_SHEET = SheetTabSchema(
    tab_name="pm_work_assignment",
    required_headers=(
        "pm_assignment_id",
        "pm_work_order_id",
        "user_id",
        "assignment_role",
        "assigned_at",
        "assigned_by_user_id",
        "ended_at",
        "active_status",
        "note_th",
    ),
)

# ---------------------------------------------------------------------------
# Web/API Phase 6 Batch 1 — Driver / Operator master + vehicle<->driver
# assignment history. LIVE GOOGLE SHEETS SCHEMA — VERIFIED: these two tabs
# were independently confirmed to already exist in the live "MAINTENANCE"
# spreadsheet, with exactly the headers below (present, but with no
# production rows yet). These are EXISTING live tabs — never renamed,
# never duplicated, no column added beyond what was verified.
# ---------------------------------------------------------------------------

DRIVER_MASTER_SHEET = SheetTabSchema(
    tab_name="driver_master",
    required_headers=(
        "driver_id",
        "driver_name_th",
        "phone",
        "license_no",
        "license_expiry_date",
        "active_status",
        "note_th",
    ),
)

VEHICLE_DRIVER_SHEET = SheetTabSchema(
    tab_name="vehicle_driver",
    required_headers=(
        "assignment_id",
        "vehicle_id",
        "driver_id",
        "start_at",
        "end_at",
        "is_primary",
        "assignment_status",
        "changed_by_user_id",
        "note_th",
    ),
)

PM_WORK_SCOPE_SHEET = SheetTabSchema(
    # Backs app.domain.pm.PmWorkOrder.scope_task_ids / scope_approved_at /
    # scope_approved_by and app.domain.pm.PmScopeAdditionAudit. Column
    # correspondence (mapped by header name):
    #   pm_scope_id            <- one row per in-scope PmTask
    #   plan_code              <- PmPlan.plan_code
    #   plan_version           <- PmTaskRevision.revision_number
    #   group_code             <- PmTask.group (never cross-plan — a task's
    #                             own revision belongs to exactly one plan)
    #   scope_source           <- "DUE" (in scope_task_ids at open time) or
    #                             "MANUAL" (present in scope_additions)
    #   due_basis              <- PmWorkOrder.due_reason
    #   added_by_user_id/added_at/add_reason_th
    #                          <- PmScopeAdditionAudit.added_by/added_at/reason
    #                             (only for scope_source=MANUAL rows)
    #   approved_by_user_id/approved_at
    #                          <- PmWorkOrder.scope_approved_by/scope_approved_at
    #   scope_status           <- derived "OPEN" | "APPROVED"
    #   completed_at/completion_snapshot_event_id
    #                          <- derived from the task's own PmWorkResult
    #                             (performed_at / meter_snapshot_id)
    #
    # SCHEMA FIX (Google Sheets repository completion pass): the original
    # declaration documented "one row per in-scope PmTask" but had no
    # column actually identifying *which* PmTask a row is for — only
    # `group_code` (PmTask.group), which is not unique per task and is not
    # the identifier `PmService`/`PmScopeAdditionAudit` operate on
    # (`pm_task_id`). Without a `pm_task_id` column, `PmWorkOrder.
    # scope_task_ids` and per-task scope membership could not be
    # reconstructed at all — implementation was genuinely impossible, not
    # merely inconvenient. Smallest justified fix: add `pm_task_id`. Not
    # part of `_CORE_SCHEMAS`, so current readiness is unaffected; the live
    # `pm_work_scope` tab needs this column added before this repository
    # mode is exercised against it for real PM scope/approval work.
    tab_name="pm_work_scope",
    required_headers=(
        "pm_scope_id",
        "pm_work_order_id",
        "pm_task_id",
        "plan_code",
        "plan_version",
        "group_code",
        "scope_source",
        "due_basis",
        "added_by_user_id",
        "added_at",
        "add_reason_th",
        "approved_by_user_id",
        "approved_at",
        "scope_status",
        "completed_at",
        "completion_snapshot_event_id",
        "note_th",
    ),
)

MATERIAL_REQUEST_SHEET = SheetTabSchema(
    # Header row for app.domain.requisition.MaterialRequest — Store/
    # Inventory integration boundary (Delta section D). request_status is
    # a plain, unconstrained string (default "OPEN"); no Store approval/
    # transition lifecycle is invented here.
    tab_name="material_request",
    required_headers=(
        "material_request_id",
        "source_type",
        "source_work_order_id",
        "vehicle_id",
        "request_status",
        "created_at",
        "created_by_user_id",
        "approved_at",
        "approved_by_user_id",
        "issued_at",
        "issued_by_user_id",
        "closed_at",
        "note_th",
    ),
)

MATERIAL_REQUEST_LINE_SHEET = SheetTabSchema(
    # Header row for app.domain.requisition.RequisitionLine, extended with
    # material_request_id (the header this line belongs to) and
    # source_task_revision_id (the PmTaskRevision a PM-sourced line came
    # from). requested/approved/issued/used/returned quantities remain
    # separate columns; future-managed ones stay nullable/blank rather than
    # defaulted.
    tab_name="material_request_line",
    required_headers=(
        "material_request_line_id",
        "material_request_id",
        "source_task_revision_id",
        "part_id",
        "part_instance_id",
        "part_code_snapshot",
        "part_name_snapshot_th",
        "requested_qty",
        "approved_qty",
        "issued_qty",
        "used_qty",
        "returned_qty",
        "unit",
        "line_source",
        "note_th",
    ),
)

REPAIR_REQUEST_SHEET = SheetTabSchema(
    # Header row for app.domain.repair_request.RepairRequest (Core Demo
    # Fixes Delta REV05 section 3). Exact columns copied verbatim from the
    # Delta prompt — do not rename/restructure/add columns here.
    tab_name="repair_request",
    required_headers=(
        "repair_request_id",
        "vehicle_id",
        "reported_at",
        "reported_by_user_id",
        "reporter_type",
        "reporter_driver_id",
        "reporter_name_snapshot_th",
        "report_channel",
        "symptom_th",
        "priority",
        "request_status",
        "reviewed_by_user_id",
        "reviewed_at",
        "repair_id",
        "converted_at",
        "note_th",
    ),
)

LOCATION_SNAPSHOT_SHEET = SheetTabSchema(
    # Header row for app.domain.location_snapshot.LocationSnapshot — the
    # GPS/location half of the shared automatic machine-state snapshot
    # mechanism, complementing METER_SNAPSHOT_SHEET (counters). Immutable,
    # backend-derived from LATEST_LOCATION_SHEET (always null/unknown in
    # this branch — no live GPS source exists in Phases 1-5). Preserves the
    # source GPS timestamp (gps_time) separately from received_at and
    # snapshot_at so a stale reading is never presented as current.
    tab_name="location_snapshot",
    required_headers=(
        "location_snapshot_id",
        "event_type",
        "event_id",
        "vehicle_id",
        "device_id",
        "latitude",
        "longitude",
        "altitude_m",
        "accuracy_m",
        "gps_time",
        "received_at",
        "snapshot_at",
        "gps_valid",
        "source",
        "note_th",
    ),
)

# ---------------------------------------------------------------------------
# Web/API Phase 6 Batch 2A — Vehicle Certificate create/list/get/history
# foundation. LIVE GOOGLE SHEETS SCHEMA — VERIFIED: this tab was
# independently confirmed to already exist in the live "MAINTENANCE"
# spreadsheet, with exactly the headers below (present, but with no
# production rows yet). This is an EXISTING live tab — never renamed, never
# duplicated, no column added beyond what was verified. Renewal/replacement
# lifecycle columns (`replaced_by_certificate_id`) exist in the schema but
# are never written by Batch 2A code (see
# `app.domain.vehicle_certificate` module docstring).
# ---------------------------------------------------------------------------

VEHICLE_CERTIFICATE_SHEET = SheetTabSchema(
    tab_name="vehicle_certificate",
    required_headers=(
        "certificate_id",
        "vehicle_id",
        "certificate_type_code",
        "certificate_type_name_th",
        "document_no",
        "issue_date",
        "expiry_date",
        "alert_lead_days",
        "certificate_status",
        "replaced_by_certificate_id",
        "storage_ref",
        "created_by_user_id",
        "created_at",
        "note_th",
    ),
)

# ---------------------------------------------------------------------------
# Web/API Phase 6 Batch 3A — Model Document create/list/get/history
# foundation. LIVE GOOGLE SHEETS SCHEMA — VERIFIED: this tab was
# independently confirmed to already exist in the live "MAINTENANCE"
# spreadsheet, with exactly the headers below (present, but with no
# production rows yet). This is an EXISTING live tab — never renamed, never
# duplicated, no column added beyond what was verified. Revision/
# replacement lifecycle columns (`replaced_by_document_id`) exist in the
# schema but are never written by Batch 3A code (see
# `app.domain.model_document` module docstring).
# ---------------------------------------------------------------------------

MODEL_DOCUMENT_SHEET = SheetTabSchema(
    tab_name="model_document",
    required_headers=(
        "model_document_id",
        "model_id",
        "document_type",
        "document_name_th",
        "version",
        "effective_from",
        "effective_to",
        "storage_ref",
        "file_status",
        "active_status",
        "replaced_by_document_id",
        "note_th",
    ),
)

# ---------------------------------------------------------------------------
# Web/API Phase 6 Batch 4A (Raw Vehicle Event Foundation + Idempotent Device
# Event Ingestion). Live tab `vehicle_event` already exists with 13 verified
# headers (event_id..note_th below); the Batch 4A frozen contract appends
# exactly 4 more at the end (device_event_id, sequence, created_offline,
# time_quality) — the existing 13 are preserved byte-for-byte in name and
# order, nothing renamed, nothing reordered, nothing else invented.
#
# IMPORTANT: this declaration describes the *target* schema the Batch 4A
# code expects. The live spreadsheet itself is NOT migrated by this batch
# — that 4-column append is a separate, explicitly-authorized migration
# performed after independent review (see the Batch 4A task's execution
# rules: "Do not create migrations that directly modify the live
# spreadsheet"). Until that migration runs, GoogleSheetsRepository schema
# validation against the live sheet will honestly report a schema mismatch
# (missing the 4 new headers) rather than silently falling back to
# anything — this is the intended, correct behavior for this state, not a
# bug to work around here.
# ---------------------------------------------------------------------------

VEHICLE_EVENT_SHEET = SheetTabSchema(
    tab_name="vehicle_event",
    required_headers=(
        "event_id",
        "vehicle_id",
        "device_id",
        "component_id",
        "event_type",
        "event_time",
        "fuel_level_value",
        "fuel_level_unit",
        "latitude",
        "longitude",
        "gps_valid",
        "received_at",
        "note_th",
        "device_event_id",
        "sequence",
        "created_offline",
        "time_quality",
    ),
)
