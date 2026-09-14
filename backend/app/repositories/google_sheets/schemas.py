"""Declared Google Sheets tab/header schema for Phase 2 domain tables.

Per docs/00_LOCAL_DEVELOPMENT_AND_NO_SERVER_SETUP_EN.txt section 7:
columns are mapped by header name, never by row position, and the tab
must be validated before writes. These declarations exist now so the
real implementation (added once local Google credentials are available —
see docs/claude-prompts/web-api/02_PHASE2_VEHICLE_MODEL_EQUIPMENT_QR_EN.txt
scope item 14) has an agreed-upon shape to validate against, matching the
prototype spreadsheet.
"""
from __future__ import annotations

from app.repositories.google_sheets.client import SheetTabSchema

VEHICLE_MODEL_SHEET = SheetTabSchema(
    tab_name="vehicle_models",
    required_headers=(
        "model_id",
        "model_code",
        "model_name",
        "brand",
        "description",
        "component_roles",
        "created_at",
        "updated_at",
    ),
)

VEHICLE_SHEET = SheetTabSchema(
    tab_name="vehicles",
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
    tab_name="vehicle_components",
    required_headers=("component_id", "vehicle_id", "component_role", "label"),
)

VEHICLE_STATUS_HISTORY_SHEET = SheetTabSchema(
    tab_name="vehicle_status_history",
    required_headers=("history_id", "vehicle_id", "status", "changed_at", "changed_by", "note"),
)

EQUIPMENT_SHEET = SheetTabSchema(
    tab_name="equipment",
    # "operational_status" values are EquipmentOperationalStatus codes
    # (READY / IN_USE / MAINTENANCE / OUT_OF_SERVICE / RETIRED — RETIRED
    # added by the Core Demo Fixes EQUIPMENT STATUS CHANGE approval) — a
    # vocabulary separate from the vehicle sheet's Vehicle OperationalStatus
    # codes (see app.domain.equipment.EquipmentOperationalStatus, C02).
    required_headers=(
        "equipment_id",
        "equipment_code",
        "name",
        "category",
        "serial_number",
        "location",
        "operational_status",
        "created_at",
        "updated_at",
    ),
)

EQUIPMENT_STATUS_HISTORY_SHEET = SheetTabSchema(
    tab_name="equipment_status_history",
    required_headers=("history_id", "equipment_id", "status", "changed_at", "changed_by", "reason"),
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
    tab_name="attachments",
    required_headers=(
        "attachment_id",
        "purpose",
        "storage_ref",
        "filename",
        "content_type",
        "size_bytes",
        "uploaded_at",
        "uploaded_by",
    ),
)

INSPECTION_SHEET = SheetTabSchema(
    tab_name="inspections",
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
    ),
)

INSPECTION_ITEM_RESULT_SHEET = SheetTabSchema(
    tab_name="inspection_item_results",
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
    tab_name="pm_plans",
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
    tab_name="pm_tasks",
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
    tab_name="pm_task_parts",
    required_headers=("pm_task_part_id", "pm_task_id", "part_description", "quantity", "unit"),
)

PM_WORK_ORDER_SHEET = SheetTabSchema(
    tab_name="pm_work_orders",
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
    ),
)

PM_WORK_RESULT_SHEET = SheetTabSchema(
    tab_name="pm_work_results",
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
    tab_name="pm_used_parts",
    required_headers=(
        "pm_used_part_id",
        "pm_work_result_id",
        "part_description",
        "quantity",
        "unit",
        "recorded_by",
        "recorded_at",
    ),
)

METER_SNAPSHOT_SHEET = SheetTabSchema(
    tab_name="meter_snapshots",
    required_headers=("meter_snapshot_id", "asset_type", "asset_id", "recorded_at", "recorded_by"),
)

METER_READING_SHEET = SheetTabSchema(
    tab_name="meter_readings",
    required_headers=("meter_snapshot_id", "component_id", "counter_type", "value"),
)

REPAIR_SHEET = SheetTabSchema(
    tab_name="repairs",
    required_headers=(
        "repair_id",
        "asset_type",
        "asset_id",
        "source_type",
        "source_id",
        "category",
        "symptom",
        "meter_snapshot_id",
        "status",
        "opened_at",
        "opened_by",
        "closed_at",
        "closed_by",
        "close_note",
    ),
)

REPAIR_ACTION_SHEET = SheetTabSchema(
    tab_name="repair_actions",
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
    tab_name="repair_parts",
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
    tab_name="part_masters",
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

REQUISITION_LINE_SHEET = SheetTabSchema(
    tab_name="requisition_lines",
    required_headers=(
        "requisition_line_id",
        "work_order_reference",
        "source_type",
        "part_id",
        "part_instance_id",
        "part_description",
        "requested_quantity",
        "unit",
        "approved_quantity",
        "issued_quantity",
        "used_quantity",
        "returned_quantity",
        "created_at",
        "created_by",
    ),
)
