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
