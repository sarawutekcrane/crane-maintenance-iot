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
    # (READY / IN_USE / MAINTENANCE / OUT_OF_SERVICE) — a vocabulary
    # separate from the vehicle sheet's Vehicle OperationalStatus codes
    # (see app.domain.equipment.EquipmentOperationalStatus, decision C02).
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
