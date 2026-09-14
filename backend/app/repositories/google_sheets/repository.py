"""Google Sheets-backed repository (base adapter).

Implements the same `Repository` interface as `MockRepository`. The
domain/service layer must not know or care which one is active; only
`app.dependencies` (composition root) decides based on `DATA_REPOSITORY`.

Per scope item 14 of the Phase 2 prompt ("Implement repository mappings
first in MockRepository, then GoogleSheetsRepository when local Google
credentials are available"): the domain-entity methods below are wired to
the declared tab schemas (`app.repositories.google_sheets.schemas`) but
raise a controlled `RepositoryError` until real
`GOOGLE_SHEET_ID`/`GOOGLE_APPLICATION_CREDENTIALS` are configured on the
developer's machine, and `NotImplementedError` beyond that point — the
same pattern `validate_schema` already used in Phase 1. This keeps the
Repository contract honest: the interface is fully implemented, but the
Google Sheets I/O itself is completed once it can actually be exercised
against the prototype spreadsheet (this sandboxed environment has no
Google credentials or network path to test it).
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.config import Settings
from app.domain.assignment import PmAssignmentHistoryEntry, RepairAssignmentHistoryEntry
from app.domain.asset import AssetType
from app.domain.attachment import Attachment, AttachmentPurpose
from app.domain.checklist import ChecklistRevisionDetail
from app.domain.common import OperationalStatus, PageParams
from app.domain.equipment import (
    Equipment,
    EquipmentCategory,
    EquipmentOperationalStatus,
    EquipmentStatusHistoryEntry,
)
from app.domain.inspection import (
    FindingStatus,
    InspectionDetail,
    InspectionFinding,
    InspectionItemResult,
    InspectionSummary,
    NewInspectionItemInput,
)
from app.domain.lifetime_rule import LifetimeRule, LifetimeRuleScope, LifetimeTriggerType
from app.domain.location_snapshot import LocationSnapshot
from app.domain.meter import CounterType, MeterReading, MeterSnapshot
from app.domain.part import PartActionType, PartMaster, PartSet, PartSetRevisionDetail, TrackingMode
from app.domain.part_instance import (
    InstallationSegment,
    LifecycleStartReason,
    PartInstanceDetail,
    PartInstanceStatus,
    PriorUsage,
)
from app.domain.pm import (
    PmPlan,
    PmScopeAdditionAudit,
    PmTaskRevisionDetail,
    PmTriggerType,
    PmWorkOrder,
    PmWorkOrderDetail,
    PmWorkOrderStatus,
    PmWorkOrderSummary,
    PmWorkResult,
)
from app.domain.position_lifetime import PositionLifetimeRecord
from app.domain.requisition import (
    MaterialRequest,
    MaterialRequestDetail,
    RequisitionLine,
    RequisitionSourceType,
)
from app.domain.repair import Repair, RepairDetail, RepairSourceType, RepairStatus, RepairSummary
from app.domain.repair_request import (
    REPAIR_REQUEST_STATUS_CONVERTED,
    REPAIR_REQUEST_STATUS_PENDING,
    RepairRequest,
)
from app.domain.vehicle import Vehicle, VehicleComponent, VehicleStatusHistoryEntry
from app.domain.vehicle_model import ComponentRole, VehicleModel
from app.repositories.base import Repository, RepositoryError
from app.repositories.google_sheets.client import GoogleSheetsClient
from app.repositories.google_sheets import schemas


def _epoch() -> datetime:
    """Fallback for a `created_at`/`updated_at`-style column that is
    unexpectedly blank in a live row — never fabricates "now" as a stand-
    in for a real historical timestamp."""
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


class GoogleSheetsRepository(Repository):
    def __init__(self, settings: Settings) -> None:
        self._client = GoogleSheetsClient(settings)

    @property
    def mode(self) -> str:
        return "google_sheets"

    # Every tab this delta gave real (non-stubbed) read/write I/O — see
    # `_require_configured`'s docstring. Readiness validates exactly these,
    # naming the first missing/mismatched sheet/header rather than a
    # generic failure (REV05 section 11D). Never auto-creates/renames a
    # live sheet.
    _CORE_SCHEMAS = (
        schemas.VEHICLE_SHEET,
        schemas.VEHICLE_MODEL_SHEET,
        schemas.PM_PLAN_SHEET,
        schemas.EQUIPMENT_SHEET,
        schemas.EQUIPMENT_STATUS_HISTORY_SHEET,
        schemas.METER_SNAPSHOT_SHEET,
        schemas.METER_READING_SHEET,
        schemas.LOCATION_SNAPSHOT_SHEET,
        schemas.ATTACHMENT_SHEET,
        schemas.REPAIR_REQUEST_SHEET,
        schemas.MATERIAL_REQUEST_SHEET,
        schemas.MATERIAL_REQUEST_LINE_SHEET,
    )

    async def check_ready(self) -> tuple[bool, str | None]:
        connected, reason = await self._client.verify_connectivity()
        if not connected:
            return False, reason
        for schema in self._CORE_SCHEMAS:
            ok, schema_reason = await self._client.validate_schema(schema)
            if not ok:
                return False, schema_reason
        return True, None

    def _require_configured(self, entity: str) -> None:
        """Still-stubbed methods only (REV05 section 11E lists which Core
        paths got real I/O this delta — everything else stays this
        controlled, honest stub rather than claiming support it doesn't
        have yet)."""
        self._ensure_configured(entity)
        raise NotImplementedError(
            f"Google Sheets read/write for '{entity}' (tab schema declared in "
            "app.repositories.google_sheets.schemas) is not implemented yet — "
            "see docs/phase-results/core-demo-fixes-result.md REV05 section for "
            "exactly which Core paths this delta gave real Google Sheets I/O."
        )

    def _ensure_configured(self, entity: str) -> None:
        """Real (non-stubbed) methods call this instead of
        `_require_configured` — raises the same clear, controlled error
        when unconfigured, but otherwise actually performs the I/O rather
        than always raising `NotImplementedError`."""
        if not self._client.is_configured:
            raise RepositoryError(
                f"Cannot read/write '{entity}': GOOGLE_SHEET_ID / "
                "GOOGLE_APPLICATION_CREDENTIALS are not configured. See "
                "docs/claude-prompts/web-api/00_LOCAL_DEVELOPMENT_AND_NO_SERVER_SETUP_EN.txt "
                "section 6 to connect a local Google Sheets prototype."
            )

    @staticmethod
    def _next_id(rows: list[dict], id_column: str, prefix: str) -> str:
        """`PREFIX-NNNN` convention (zero-padded to at least 4 digits,
        widening if the sheet already has 10,000+ rows for this prefix) —
        the same stable opaque ID shape `MockRepository` uses. Computed
        from the current max suffix rather than a process-local counter,
        since a real sheet must survive backend restarts."""
        max_seq = 0
        for row in rows:
            value = str(row.get(id_column, ""))
            if value.startswith(f"{prefix}-"):
                suffix = value[len(prefix) + 1 :]
                if suffix.isdigit():
                    max_seq = max(max_seq, int(suffix))
        width = max(4, len(str(max_seq + 1)))
        return f"{prefix}-{max_seq + 1:0{width}d}"

    @staticmethod
    def _parse_datetime(value: str) -> "datetime | None":
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _parse_float(value: object) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_bool(value: object) -> bool:
        return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}

    # ---- Vehicle model ----

    async def list_vehicle_models(
        self, q: str | None, params: PageParams
    ) -> tuple[list[VehicleModel], int]:
        self._require_configured(schemas.VEHICLE_MODEL_SHEET.tab_name)

    async def get_vehicle_model(self, model_id: str) -> VehicleModel | None:
        self._ensure_configured(schemas.VEHICLE_MODEL_SHEET.tab_name)
        found = await self._client.find_row(schemas.VEHICLE_MODEL_SHEET, "model_id", model_id)
        if found is None:
            return None
        _, row = found
        assigned_pm_plan_id = await self._resolve_plan_id_by_code(row.get("default_plan_code", ""))
        component_roles_raw = str(row.get("component_roles", ""))
        return VehicleModel(
            model_id=row["model_id"],
            model_code=row.get("model_code", ""),
            model_name=row.get("model_name", ""),
            brand=row.get("brand") or None,
            description=row.get("description") or None,
            component_roles=[
                ComponentRole(value.strip())
                for value in component_roles_raw.split(",")
                if value.strip()
            ],
            created_at=self._parse_datetime(row.get("created_at", "")) or _epoch(),
            updated_at=self._parse_datetime(row.get("updated_at", "")) or _epoch(),
            assigned_pm_plan_id=assigned_pm_plan_id,
        )

    async def _resolve_plan_id_by_code(self, plan_code: str) -> str | None:
        """`model_master.default_plan_code` stores a `plan_code` (e.g.
        "PLAN1"), but the domain field `VehicleModel.assigned_pm_plan_id`
        wants the plan's own `pm_plan_id` (e.g. "PMP-0001") — resolved by
        a lookup against `maintenance_plan`, never guessed/duplicated."""
        if not plan_code:
            return None
        found = await self._client.find_row(schemas.PM_PLAN_SHEET, "plan_code", plan_code)
        return found[1]["pm_plan_id"] if found else None

    # ---- Vehicle ----

    async def list_vehicles(
        self,
        q: str | None,
        operational_status: OperationalStatus | None,
        model_id: str | None,
        params: PageParams,
    ) -> tuple[list[Vehicle], int]:
        self._require_configured(schemas.VEHICLE_SHEET.tab_name)

    async def get_vehicle(self, vehicle_id: str) -> Vehicle | None:
        self._ensure_configured(schemas.VEHICLE_SHEET.tab_name)
        found = await self._client.find_row(schemas.VEHICLE_SHEET, "vehicle_id", vehicle_id)
        if found is None:
            return None
        _, row = found
        return Vehicle(
            vehicle_id=row["vehicle_id"],
            machine_no=row.get("machine_no", ""),
            model_id=row.get("model_id", ""),
            serial_number=row.get("serial_number") or None,
            operational_status=OperationalStatus(row.get("operational_status") or "READY"),
            created_at=self._parse_datetime(row.get("created_at", "")) or _epoch(),
            updated_at=self._parse_datetime(row.get("updated_at", "")) or _epoch(),
        )

    async def update_vehicle_machine_no(self, vehicle_id: str, machine_no: str) -> Vehicle:
        self._require_configured(schemas.VEHICLE_SHEET.tab_name)

    async def list_vehicle_components(self, vehicle_id: str) -> list[VehicleComponent]:
        self._require_configured(schemas.VEHICLE_COMPONENT_SHEET.tab_name)

    async def list_vehicle_status_history(
        self, vehicle_id: str
    ) -> list[VehicleStatusHistoryEntry]:
        self._require_configured(schemas.VEHICLE_STATUS_HISTORY_SHEET.tab_name)

    async def change_vehicle_status(
        self,
        vehicle_id: str,
        new_status: OperationalStatus,
        changed_by: str | None,
        note: str | None,
    ) -> VehicleStatusHistoryEntry:
        self._require_configured(schemas.VEHICLE_STATUS_HISTORY_SHEET.tab_name)

    # ---- Workshop equipment ----

    async def list_equipment(
        self, q: str | None, category: EquipmentCategory | None, params: PageParams
    ) -> tuple[list[Equipment], int]:
        self._require_configured(schemas.EQUIPMENT_SHEET.tab_name)

    def _equipment_from_row(self, row: dict) -> Equipment:
        try:
            category = EquipmentCategory(row.get("equipment_type", ""))
        except ValueError as exc:
            raise RepositoryError(
                f"equipment_master row '{row.get('equipment_id')}' has "
                f"equipment_type='{row.get('equipment_type')}', which is not one of the "
                f"approved EquipmentCategory values — fix the live row rather than guessing"
            ) from exc
        try:
            status = EquipmentOperationalStatus(row.get("equipment_status", ""))
        except ValueError as exc:
            raise RepositoryError(
                f"equipment_master row '{row.get('equipment_id')}' has "
                f"equipment_status='{row.get('equipment_status')}', which is not one of the "
                f"approved EquipmentOperationalStatus values"
            ) from exc
        return Equipment(
            equipment_id=row["equipment_id"],
            equipment_code=row.get("equipment_code", ""),
            name=row.get("equipment_name_th", ""),
            category=category,
            serial_number=row.get("serial_no") or None,
            location=None,  # no column reserved for this in the live sheet
            operational_status=status,
            created_at=self._parse_datetime(row.get("company_start_date", "")) or _epoch(),
            updated_at=_epoch(),  # equipment_master has no updated_at column
        )

    async def get_equipment(self, equipment_id: str) -> Equipment | None:
        self._ensure_configured(schemas.EQUIPMENT_SHEET.tab_name)
        found = await self._client.find_row(schemas.EQUIPMENT_SHEET, "equipment_id", equipment_id)
        return self._equipment_from_row(found[1]) if found else None

    async def change_equipment_status(
        self,
        equipment_id: str,
        status: EquipmentOperationalStatus,
        reason: str | None,
        changed_by: str | None,
    ) -> Equipment:
        self._ensure_configured(schemas.EQUIPMENT_STATUS_HISTORY_SHEET.tab_name)
        found = await self._client.find_row(schemas.EQUIPMENT_SHEET, "equipment_id", equipment_id)
        if found is None:
            raise RepositoryError(f"Equipment '{equipment_id}' was not found")
        row_number, row = found
        updated_row = dict(row)
        updated_row["equipment_status"] = status.value
        await self._client.update_row(schemas.EQUIPMENT_SHEET, row_number, updated_row)

        history_rows = await self._client.read_rows(schemas.EQUIPMENT_STATUS_HISTORY_SHEET)
        history_id = self._next_id(history_rows, "status_history_id", "ESTH")
        now = datetime.now(timezone.utc)
        await self._client.append_row(
            schemas.EQUIPMENT_STATUS_HISTORY_SHEET,
            {
                "status_history_id": history_id,
                "equipment_id": equipment_id,
                "status_code": status.value,
                "start_at": now.isoformat(),
                "end_at": "",
                "reason_th": reason or "",
                "changed_by_user_id": changed_by or "",
                "source_type": "",
                "source_id": "",
            },
        )
        return self._equipment_from_row(updated_row)

    async def list_equipment_status_history(
        self, equipment_id: str
    ) -> list[EquipmentStatusHistoryEntry]:
        self._ensure_configured(schemas.EQUIPMENT_STATUS_HISTORY_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.EQUIPMENT_STATUS_HISTORY_SHEET)
        entries = [
            EquipmentStatusHistoryEntry(
                history_id=row["status_history_id"],
                equipment_id=row["equipment_id"],
                status=EquipmentOperationalStatus(row["status_code"]),
                changed_at=self._parse_datetime(row.get("start_at", "")) or _epoch(),
                changed_by=row.get("changed_by_user_id") or None,
                reason=row.get("reason_th") or None,
            )
            for row in rows
            if row.get("equipment_id") == equipment_id
        ]
        entries.sort(key=lambda e: e.changed_at)
        return entries

    # ---- Checklist / inspection (Phase 3) ----

    async def get_active_checklist_revision(
        self, asset_type: AssetType
    ) -> ChecklistRevisionDetail | None:
        self._require_configured(schemas.CHECKLIST_REVISION_SHEET.tab_name)

    async def get_checklist_revision(
        self, checklist_id: str, revision_id: str
    ) -> ChecklistRevisionDetail | None:
        self._require_configured(schemas.CHECKLIST_REVISION_SHEET.tab_name)

    def _attachment_from_row(self, row: dict) -> Attachment:
        return Attachment(
            attachment_id=row["attachment_id"],
            purpose=AttachmentPurpose(row.get("purpose") or "REPAIR_EVIDENCE"),
            storage_ref=row.get("storage_ref", ""),
            filename=row.get("filename", ""),
            content_type=row.get("content_type", ""),
            size_bytes=int(self._parse_float(row.get("size_bytes")) or 0),
            uploaded_at=self._parse_datetime(row.get("uploaded_at", "")) or _epoch(),
            uploaded_by=row.get("uploaded_by") or None,
            source_type=row.get("source_type") or None,
            source_id=row.get("source_id") or None,
        )

    async def create_attachment(
        self,
        purpose: AttachmentPurpose,
        storage_ref: str,
        filename: str,
        content_type: str,
        size_bytes: int,
        uploaded_by: str | None,
        source_type: str | None = None,
        source_id: str | None = None,
    ) -> Attachment:
        self._ensure_configured(schemas.ATTACHMENT_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.ATTACHMENT_SHEET)
        attachment_id = self._next_id(rows, "attachment_id", "ATT")
        uploaded_at = datetime.now(timezone.utc)
        await self._client.append_row(
            schemas.ATTACHMENT_SHEET,
            {
                "attachment_id": attachment_id,
                "purpose": purpose.value,
                "storage_ref": storage_ref,
                "filename": filename,
                "content_type": content_type,
                "size_bytes": size_bytes,
                "uploaded_at": uploaded_at.isoformat(),
                "uploaded_by": uploaded_by or "",
                "source_type": source_type or "",
                "source_id": source_id or "",
            },
        )
        return Attachment(
            attachment_id=attachment_id,
            purpose=purpose,
            storage_ref=storage_ref,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            uploaded_at=uploaded_at,
            uploaded_by=uploaded_by,
            source_type=source_type,
            source_id=source_id,
        )

    async def get_attachment(self, attachment_id: str) -> Attachment | None:
        self._ensure_configured(schemas.ATTACHMENT_SHEET.tab_name)
        found = await self._client.find_row(schemas.ATTACHMENT_SHEET, "attachment_id", attachment_id)
        return self._attachment_from_row(found[1]) if found else None

    async def list_attachments_for_source(
        self, source_type: str, source_id: str
    ) -> list[Attachment]:
        self._ensure_configured(schemas.ATTACHMENT_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.ATTACHMENT_SHEET)
        matches = [
            self._attachment_from_row(row)
            for row in rows
            if row.get("source_type") == source_type and row.get("source_id") == source_id
        ]
        matches.sort(key=lambda a: a.uploaded_at)
        return matches

    async def create_inspection(
        self,
        asset_type: AssetType,
        asset_id: str,
        checklist_id: str,
        revision_id: str,
        revision_number: int,
        inspector_user_id: str | None,
        overall_remark: str | None,
        items: list[NewInspectionItemInput],
        machine_state_snapshot_id: str | None = None,
    ) -> InspectionDetail:
        self._require_configured(schemas.INSPECTION_SHEET.tab_name)

    async def get_inspection(self, inspection_id: str) -> InspectionDetail | None:
        self._require_configured(schemas.INSPECTION_SHEET.tab_name)

    async def list_inspections(
        self,
        asset_type: AssetType | None,
        asset_id: str | None,
        params: PageParams,
    ) -> tuple[list[InspectionSummary], int]:
        self._require_configured(schemas.INSPECTION_SHEET.tab_name)

    async def find_inspection_finding(self, finding_id: str) -> InspectionFinding | None:
        self._require_configured(schemas.INSPECTION_FINDING_SHEET.tab_name)

    async def find_inspection_result(self, result_id: str) -> InspectionItemResult | None:
        self._require_configured(schemas.INSPECTION_ITEM_RESULT_SHEET.tab_name)

    async def list_inspection_findings(
        self,
        asset_type: AssetType | None,
        asset_id: str | None,
        status: FindingStatus | None,
    ) -> list[InspectionFinding]:
        self._require_configured(schemas.INSPECTION_FINDING_SHEET.tab_name)

    # ---- PM plan / task revision (Phase 4) ----

    async def list_pm_plans(self, asset_type: AssetType | None, model_id: str | None) -> list[PmPlan]:
        self._require_configured(schemas.PM_PLAN_SHEET.tab_name)

    async def get_pm_plan(self, pm_plan_id: str) -> PmPlan | None:
        self._ensure_configured(schemas.PM_PLAN_SHEET.tab_name)
        found = await self._client.find_row(schemas.PM_PLAN_SHEET, "pm_plan_id", pm_plan_id)
        if found is None:
            return None
        _, row = found
        model_ids_raw = str(row.get("model_ids", ""))
        return PmPlan(
            pm_plan_id=row["pm_plan_id"],
            plan_code=row.get("plan_code", ""),
            asset_type=AssetType(row.get("asset_type") or "VEHICLE"),
            name=row.get("name", ""),
            model_ids=[v.strip() for v in model_ids_raw.split(",") if v.strip()],
            created_at=self._parse_datetime(row.get("created_at", "")) or _epoch(),
            updated_at=self._parse_datetime(row.get("updated_at", "")) or _epoch(),
        )

    async def get_active_pm_task_revision(self, pm_plan_id: str) -> PmTaskRevisionDetail | None:
        self._require_configured(schemas.PM_TASK_REVISION_SHEET.tab_name)

    async def get_pm_task_revision(
        self, pm_plan_id: str, revision_id: str
    ) -> PmTaskRevisionDetail | None:
        self._require_configured(schemas.PM_TASK_REVISION_SHEET.tab_name)

    # ---- PM work order / work result (Phase 4) ----

    async def create_pm_work_order(
        self,
        asset_type: AssetType,
        asset_id: str,
        pm_plan_id: str,
        revision_id: str,
        due_reason: PmTriggerType | None,
        opened_by: str | None,
        note: str | None,
        opened_snapshot_id: str | None = None,
        scope_task_ids: list[str] | None = None,
    ) -> PmWorkOrder:
        self._require_configured(schemas.PM_WORK_ORDER_SHEET.tab_name)

    async def add_pm_scope_task(
        self,
        pm_work_order_id: str,
        pm_task_id: str,
        added_by: str | None,
        reason: str,
    ) -> PmScopeAdditionAudit:
        # Core Demo Fixes Delta section C: scope rows (due + manually-added
        # groups) persist through pm_work_scope, not the pm_work_order
        # header sheet.
        self._require_configured(schemas.PM_WORK_SCOPE_SHEET.tab_name)

    async def approve_pm_scope(
        self, pm_work_order_id: str, approved_by: str | None
    ) -> PmWorkOrder:
        self._require_configured(schemas.PM_WORK_SCOPE_SHEET.tab_name)

    async def assign_pm_work_order(
        self,
        pm_work_order_id: str,
        primary_technician: str | None,
        collaborators: list[str],
        assigned_by: str | None = None,
    ) -> PmWorkOrder:
        self._require_configured(schemas.PM_WORK_ASSIGNMENT_SHEET.tab_name)

    async def list_pm_work_order_assignment_history(
        self, pm_work_order_id: str
    ) -> list[PmAssignmentHistoryEntry]:
        self._require_configured(schemas.PM_WORK_ASSIGNMENT_SHEET.tab_name)

    async def get_pm_work_order(self, pm_work_order_id: str) -> PmWorkOrderDetail | None:
        self._require_configured(schemas.PM_WORK_ORDER_SHEET.tab_name)

    async def list_pm_work_orders(
        self,
        asset_type: AssetType | None,
        asset_id: str | None,
        params: PageParams,
        status: PmWorkOrderStatus | None = None,
    ) -> tuple[list[PmWorkOrderSummary], int]:
        self._require_configured(schemas.PM_WORK_ORDER_SHEET.tab_name)

    async def get_last_closed_pm_work_order(
        self, asset_type: AssetType, asset_id: str, pm_plan_id: str
    ) -> PmWorkOrderDetail | None:
        self._require_configured(schemas.PM_WORK_ORDER_SHEET.tab_name)

    async def close_pm_work_order(
        self,
        pm_work_order_id: str,
        closed_by: str | None,
        note: str | None,
        closed_snapshot_id: str | None = None,
    ) -> PmWorkOrder:
        self._require_configured(schemas.PM_WORK_ORDER_SHEET.tab_name)

    async def create_pm_work_result(
        self,
        pm_work_order_id: str,
        pm_task_id: str,
        revision_id: str,
        sequence: int,
        task_description: str,
        completed: bool,
        meter_snapshot_id: str | None,
        remark: str | None,
        used_parts: list[dict],
        evidence_attachment_ids: list[str],
        performed_by: str | None,
    ) -> PmWorkResult:
        self._require_configured(schemas.PM_WORK_RESULT_SHEET.tab_name)

    async def find_pm_work_result(self, pm_work_result_id: str) -> PmWorkResult | None:
        self._require_configured(schemas.PM_WORK_RESULT_SHEET.tab_name)

    # ---- Meter snapshot (Phase 4) ----

    async def create_meter_snapshot(
        self,
        asset_type: AssetType,
        asset_id: str,
        readings: list[MeterReading],
        recorded_by: str | None,
        is_automatic: bool = False,
        latitude: float | None = None,
        longitude: float | None = None,
        gps_observed_at=None,
        source_note: str | None = None,
    ) -> MeterSnapshot:
        self._ensure_configured(schemas.METER_SNAPSHOT_SHEET.tab_name)
        snapshot_rows = await self._client.read_rows(schemas.METER_SNAPSHOT_SHEET)
        meter_snapshot_id = self._next_id(snapshot_rows, "meter_snapshot_id", "MSNAP")
        recorded_at = datetime.now(timezone.utc)
        await self._client.append_row(
            schemas.METER_SNAPSHOT_SHEET,
            {
                "meter_snapshot_id": meter_snapshot_id,
                "asset_type": asset_type.value,
                "asset_id": asset_id,
                "recorded_at": recorded_at.isoformat(),
                "recorded_by": recorded_by or "",
                "is_automatic": is_automatic,
                "source_note": source_note or "",
            },
        )
        for reading in readings:
            await self._client.append_row(
                schemas.METER_READING_SHEET,
                {
                    "meter_snapshot_id": meter_snapshot_id,
                    "component_id": reading.component_id or "",
                    "counter_type": reading.counter_type.value,
                    "value": reading.value,
                },
            )
        return MeterSnapshot(
            meter_snapshot_id=meter_snapshot_id,
            asset_type=asset_type,
            asset_id=asset_id,
            readings=[r.model_copy(deep=True) for r in readings],
            recorded_at=recorded_at,
            recorded_by=recorded_by,
            is_automatic=is_automatic,
            latitude=latitude,
            longitude=longitude,
            gps_observed_at=gps_observed_at,
            source_note=source_note,
        )

    def _meter_snapshot_from_row(
        self, row: dict, reading_rows: list[dict]
    ) -> MeterSnapshot:
        readings = [
            MeterReading(
                component_id=r.get("component_id") or None,
                counter_type=CounterType(r["counter_type"]),
                value=self._parse_float(r.get("value")),
                observed_at=None,  # meter_readings has no observed_at column
            )
            for r in reading_rows
            if r.get("meter_snapshot_id") == row["meter_snapshot_id"]
        ]
        return MeterSnapshot(
            meter_snapshot_id=row["meter_snapshot_id"],
            asset_type=AssetType(row.get("asset_type") or "VEHICLE"),
            asset_id=row.get("asset_id", ""),
            readings=readings,
            recorded_at=self._parse_datetime(row.get("recorded_at", "")) or _epoch(),
            recorded_by=row.get("recorded_by") or None,
            is_automatic=self._parse_bool(row.get("is_automatic")),
            source_note=row.get("source_note") or None,
        )

    async def get_meter_snapshot(self, meter_snapshot_id: str) -> MeterSnapshot | None:
        self._ensure_configured(schemas.METER_SNAPSHOT_SHEET.tab_name)
        found = await self._client.find_row(
            schemas.METER_SNAPSHOT_SHEET, "meter_snapshot_id", meter_snapshot_id
        )
        if found is None:
            return None
        reading_rows = await self._client.read_rows(schemas.METER_READING_SHEET)
        return self._meter_snapshot_from_row(found[1], reading_rows)

    async def list_meter_snapshots_for_asset(
        self, asset_type: AssetType, asset_id: str
    ) -> list[MeterSnapshot]:
        self._ensure_configured(schemas.METER_SNAPSHOT_SHEET.tab_name)
        snapshot_rows = await self._client.read_rows(schemas.METER_SNAPSHOT_SHEET)
        reading_rows = await self._client.read_rows(schemas.METER_READING_SHEET)
        matches = [
            row
            for row in snapshot_rows
            if row.get("asset_type") == asset_type.value and row.get("asset_id") == asset_id
        ]
        return [self._meter_snapshot_from_row(row, reading_rows) for row in matches]

    # ---- Repair (Phase 4) ----

    async def create_repair(
        self,
        asset_type: AssetType,
        asset_id: str,
        source_type: RepairSourceType,
        source_id: str | None,
        category: str | None,
        symptom: str | None,
        meter_snapshot_id: str | None,
        opened_by: str | None,
        primary_technician: str | None = None,
        collaborators: list[str] | None = None,
    ) -> Repair:
        self._require_configured(schemas.REPAIR_SHEET.tab_name)

    async def get_repair(self, repair_id: str) -> RepairDetail | None:
        self._require_configured(schemas.REPAIR_SHEET.tab_name)

    async def list_repairs(
        self,
        asset_type: AssetType | None,
        asset_id: str | None,
        status: RepairStatus | None,
        params: PageParams,
        assigned_to: str | None = None,
        unassigned_only: bool = False,
    ) -> tuple[list[RepairSummary], int]:
        self._require_configured(schemas.REPAIR_SHEET.tab_name)

    async def assign_repair(
        self,
        repair_id: str,
        primary_technician: str | None,
        collaborators: list[str],
        assigned_by: str | None = None,
    ) -> Repair:
        # Core Demo Fixes Delta section A: assignment persists as append-
        # only history through repair_assignment (one PRIMARY row plus zero
        # or more COLLABORATOR rows, technician referencing
        # user_account.user_id) — the repair_order header's own
        # primary_technician/collaborators columns stay in sync for direct
        # reads, but repair_assignment is authoritative for history.
        self._require_configured(schemas.REPAIR_ASSIGNMENT_SHEET.tab_name)

    async def list_repair_assignment_history(
        self, repair_id: str
    ) -> list[RepairAssignmentHistoryEntry]:
        self._require_configured(schemas.REPAIR_ASSIGNMENT_SHEET.tab_name)

    # ---- Repair Request (Core Demo Fixes Delta REV05 section 3) ----

    def _repair_request_from_row(self, row: dict) -> RepairRequest:
        return RepairRequest(
            repair_request_id=row["repair_request_id"],
            vehicle_id=row.get("vehicle_id", ""),
            reported_at=self._parse_datetime(row.get("reported_at", "")) or _epoch(),
            reported_by_user_id=row.get("reported_by_user_id") or None,
            reporter_type=row.get("reporter_type") or None,
            reporter_driver_id=row.get("reporter_driver_id") or None,
            reporter_name_snapshot_th=row.get("reporter_name_snapshot_th") or None,
            report_channel=row.get("report_channel") or None,
            symptom_th=row.get("symptom_th") or None,
            priority=row.get("priority") or None,
            request_status=row.get("request_status") or REPAIR_REQUEST_STATUS_PENDING,
            reviewed_by_user_id=row.get("reviewed_by_user_id") or None,
            reviewed_at=self._parse_datetime(row.get("reviewed_at", "")),
            repair_id=row.get("repair_id") or None,
            converted_at=self._parse_datetime(row.get("converted_at", "")),
            note_th=row.get("note_th") or None,
            # `meter_snapshot_id` is domain-only — the live `repair_request`
            # sheet has no reserved column for it (see
            # app.domain.repair_request.RepairRequest.meter_snapshot_id).
            meter_snapshot_id=None,
        )

    async def create_repair_request(
        self,
        vehicle_id: str,
        reported_by_user_id: str | None,
        reporter_type: str | None,
        reporter_driver_id: str | None,
        reporter_name_snapshot_th: str | None,
        report_channel: str | None,
        symptom_th: str | None,
        priority: str | None,
        note_th: str | None,
        meter_snapshot_id: str | None = None,
    ) -> RepairRequest:
        self._ensure_configured(schemas.REPAIR_REQUEST_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.REPAIR_REQUEST_SHEET)
        repair_request_id = self._next_id(rows, "repair_request_id", "RRQ")
        reported_at = datetime.now(timezone.utc)
        await self._client.append_row(
            schemas.REPAIR_REQUEST_SHEET,
            {
                "repair_request_id": repair_request_id,
                "vehicle_id": vehicle_id,
                "reported_at": reported_at.isoformat(),
                "reported_by_user_id": reported_by_user_id or "",
                "reporter_type": reporter_type or "",
                "reporter_driver_id": reporter_driver_id or "",
                "reporter_name_snapshot_th": reporter_name_snapshot_th or "",
                "report_channel": report_channel or "",
                "symptom_th": symptom_th or "",
                "priority": priority or "",
                "request_status": REPAIR_REQUEST_STATUS_PENDING,
                "reviewed_by_user_id": "",
                "reviewed_at": "",
                "repair_id": "",
                "converted_at": "",
                "note_th": note_th or "",
            },
        )
        return RepairRequest(
            repair_request_id=repair_request_id,
            vehicle_id=vehicle_id,
            reported_at=reported_at,
            reported_by_user_id=reported_by_user_id,
            reporter_type=reporter_type,
            reporter_driver_id=reporter_driver_id,
            reporter_name_snapshot_th=reporter_name_snapshot_th,
            report_channel=report_channel,
            symptom_th=symptom_th,
            priority=priority,
            request_status=REPAIR_REQUEST_STATUS_PENDING,
            note_th=note_th,
            meter_snapshot_id=meter_snapshot_id,
        )

    async def get_repair_request(self, repair_request_id: str) -> RepairRequest | None:
        self._ensure_configured(schemas.REPAIR_REQUEST_SHEET.tab_name)
        found = await self._client.find_row(
            schemas.REPAIR_REQUEST_SHEET, "repair_request_id", repair_request_id
        )
        return self._repair_request_from_row(found[1]) if found else None

    async def list_pending_repair_requests(
        self, params: PageParams
    ) -> tuple[list[RepairRequest], int]:
        self._ensure_configured(schemas.REPAIR_REQUEST_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.REPAIR_REQUEST_SHEET)
        pending = [
            self._repair_request_from_row(row)
            for row in rows
            if (row.get("request_status") or REPAIR_REQUEST_STATUS_PENDING)
            == REPAIR_REQUEST_STATUS_PENDING
        ]
        pending.sort(key=lambda r: r.reported_at)
        start = (params.page - 1) * params.page_size
        page = pending[start : start + params.page_size]
        return page, len(pending)

    async def mark_repair_request_converted(
        self,
        repair_request_id: str,
        repair_id: str,
        reviewed_by_user_id: str | None,
    ) -> RepairRequest:
        self._ensure_configured(schemas.REPAIR_REQUEST_SHEET.tab_name)
        found = await self._client.find_row(
            schemas.REPAIR_REQUEST_SHEET, "repair_request_id", repair_request_id
        )
        if found is None:
            raise RepositoryError(f"Repair request '{repair_request_id}' was not found")
        row_number, row = found
        now = datetime.now(timezone.utc)
        updated_row = dict(row)
        updated_row.update(
            {
                "request_status": REPAIR_REQUEST_STATUS_CONVERTED,
                "reviewed_by_user_id": reviewed_by_user_id or "",
                "reviewed_at": now.isoformat(),
                "repair_id": repair_id,
                "converted_at": now.isoformat(),
            }
        )
        await self._client.update_row(schemas.REPAIR_REQUEST_SHEET, row_number, updated_row)
        return self._repair_request_from_row(updated_row)

    async def add_repair_action(
        self,
        repair_id: str,
        action_text: str,
        actor: str | None,
        attachment_ids: list[str],
    ) -> None:
        self._require_configured(schemas.REPAIR_ACTION_SHEET.tab_name)

    async def add_repair_part(
        self,
        repair_id: str,
        part_description: str,
        quantity: float | None,
        unit: str | None,
        recorded_by: str | None,
        part_id: str | None = None,
        part_instance_id: str | None = None,
        action: PartActionType | None = None,
    ) -> None:
        self._require_configured(schemas.REPAIR_PART_SHEET.tab_name)

    async def close_repair(
        self,
        repair_id: str,
        closed_by: str | None,
        close_note: str | None,
        closed_snapshot_id: str | None = None,
    ) -> Repair:
        self._require_configured(schemas.REPAIR_SHEET.tab_name)

    # ---- Part Master / Part Set (Phase 5) ----

    async def create_part_master(
        self,
        part_code: str,
        name: str,
        specification: str | None,
        manufacturer: str | None,
        part_number: str | None,
        tracking_mode: TrackingMode,
        category: str | None,
        metadata: dict[str, str],
    ) -> PartMaster:
        self._require_configured(schemas.PART_MASTER_SHEET.tab_name)

    async def get_part_master(self, part_id: str) -> PartMaster | None:
        self._require_configured(schemas.PART_MASTER_SHEET.tab_name)

    async def list_part_masters(
        self, q: str | None, tracking_mode: TrackingMode | None, params: PageParams
    ) -> tuple[list[PartMaster], int]:
        self._require_configured(schemas.PART_MASTER_SHEET.tab_name)

    async def create_part_set(self, set_code: str, name: str) -> PartSet:
        self._require_configured(schemas.PART_SET_SHEET.tab_name)

    async def get_part_set(self, part_set_id: str) -> PartSet | None:
        self._require_configured(schemas.PART_SET_SHEET.tab_name)

    async def create_part_set_revision(
        self, part_set_id: str, effective_date, items: list[dict]
    ) -> PartSetRevisionDetail:
        self._require_configured(schemas.PART_SET_REVISION_SHEET.tab_name)

    async def get_active_part_set_revision(self, part_set_id: str) -> PartSetRevisionDetail | None:
        self._require_configured(schemas.PART_SET_REVISION_SHEET.tab_name)

    async def get_part_set_revision(
        self, part_set_id: str, revision_id: str
    ) -> PartSetRevisionDetail | None:
        self._require_configured(schemas.PART_SET_REVISION_SHEET.tab_name)

    # ---- Part Instance / lifecycle / installation segment (Phase 5) ----

    async def create_part_instance(
        self,
        part_id: str,
        serial_number: str | None,
        prior_usage: PriorUsage,
        note: str | None,
        created_by: str | None,
    ) -> PartInstanceDetail:
        self._require_configured(schemas.PART_INSTANCE_SHEET.tab_name)

    async def get_part_instance(self, part_instance_id: str) -> PartInstanceDetail | None:
        self._require_configured(schemas.PART_INSTANCE_SHEET.tab_name)

    async def list_part_instances(
        self, part_id: str | None, status: PartInstanceStatus | None, params: PageParams
    ) -> tuple[list[PartInstanceDetail], int]:
        self._require_configured(schemas.PART_INSTANCE_SHEET.tab_name)

    async def update_part_instance_status(
        self, part_instance_id: str, status: PartInstanceStatus
    ) -> None:
        self._require_configured(schemas.PART_INSTANCE_SHEET.tab_name)

    async def create_installation_segment(
        self,
        part_instance_id: str,
        lifecycle_id: str,
        asset_type: AssetType,
        asset_id: str,
        position_code: str | None,
        installed_by: str | None,
        baseline_meter_snapshot_id: str | None,
        install_note: str | None,
    ) -> InstallationSegment:
        self._require_configured(schemas.INSTALLATION_SEGMENT_SHEET.tab_name)

    async def close_installation_segment(
        self,
        segment_id: str,
        removed_by: str | None,
        removal_meter_snapshot_id: str | None,
        removal_reason: str | None,
    ) -> InstallationSegment:
        self._require_configured(schemas.INSTALLATION_SEGMENT_SHEET.tab_name)

    async def start_new_part_lifecycle(
        self,
        part_instance_id: str,
        start_reason: LifecycleStartReason,
        started_note: str | None,
        started_by: str | None,
    ) -> None:
        self._require_configured(schemas.PART_LIFECYCLE_SHEET.tab_name)

    # ---- Position lifetime (Phase 5) ----

    async def create_position_lifetime(
        self,
        asset_type: AssetType,
        asset_id: str,
        position_code: str,
        part_id: str | None,
        lifetime_rule_id: str | None,
        baseline_meter_snapshot_id: str | None,
        prior_usage: PriorUsage,
        started_by: str | None,
        note: str | None,
    ) -> PositionLifetimeRecord:
        self._require_configured(schemas.POSITION_LIFETIME_SHEET.tab_name)

    async def get_position_lifetime(
        self, position_lifetime_id: str
    ) -> PositionLifetimeRecord | None:
        self._require_configured(schemas.POSITION_LIFETIME_SHEET.tab_name)

    async def list_position_lifetime_for_asset(
        self, asset_type: AssetType, asset_id: str
    ) -> list[PositionLifetimeRecord]:
        self._require_configured(schemas.POSITION_LIFETIME_SHEET.tab_name)

    # ---- Lifetime rule (Phase 5) ----

    async def create_lifetime_rule(
        self,
        part_id: str,
        scope: LifetimeRuleScope,
        model_id: str | None,
        vehicle_id: str | None,
        trigger_type: LifetimeTriggerType,
        component_role: ComponentRole | None,
        first_due_value: float | None,
        interval_value: float | None,
        warning_window_value: float | None,
        note: str | None,
    ) -> LifetimeRule:
        self._require_configured(schemas.LIFETIME_RULE_SHEET.tab_name)

    async def get_lifetime_rule(self, lifetime_rule_id: str) -> LifetimeRule | None:
        self._require_configured(schemas.LIFETIME_RULE_SHEET.tab_name)

    async def list_lifetime_rules_for_part(self, part_id: str) -> list[LifetimeRule]:
        self._require_configured(schemas.LIFETIME_RULE_SHEET.tab_name)

    # ---- Location snapshot (Core Demo Fixes Delta section E) ----

    def _location_snapshot_from_row(self, row: dict) -> LocationSnapshot:
        return LocationSnapshot(
            location_snapshot_id=row["location_snapshot_id"],
            event_type=row.get("event_type", ""),
            event_id=row.get("event_id", ""),
            vehicle_id=row.get("vehicle_id") or None,
            device_id=row.get("device_id") or None,
            latitude=self._parse_float(row.get("latitude")),
            longitude=self._parse_float(row.get("longitude")),
            altitude_m=self._parse_float(row.get("altitude_m")),
            accuracy_m=self._parse_float(row.get("accuracy_m")),
            gps_time=self._parse_datetime(row.get("gps_time", "")),
            received_at=self._parse_datetime(row.get("received_at", "")),
            snapshot_at=self._parse_datetime(row.get("snapshot_at", "")) or _epoch(),
            gps_valid=self._parse_bool(row.get("gps_valid")),
            source=row.get("source") or None,
            note=row.get("note_th") or None,
        )

    async def create_location_snapshot(
        self,
        event_type: str,
        event_id: str,
        vehicle_id: str | None,
        device_id: str | None,
        latitude: float | None,
        longitude: float | None,
        altitude_m: float | None,
        accuracy_m: float | None,
        gps_time,
        received_at,
        gps_valid: bool,
        source: str | None,
    ) -> LocationSnapshot:
        self._ensure_configured(schemas.LOCATION_SNAPSHOT_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.LOCATION_SNAPSHOT_SHEET)
        location_snapshot_id = self._next_id(rows, "location_snapshot_id", "LOCSNAP")
        snapshot_at = datetime.now(timezone.utc)
        await self._client.append_row(
            schemas.LOCATION_SNAPSHOT_SHEET,
            {
                "location_snapshot_id": location_snapshot_id,
                "event_type": event_type,
                "event_id": event_id,
                "vehicle_id": vehicle_id or "",
                "device_id": device_id or "",
                "latitude": latitude,
                "longitude": longitude,
                "altitude_m": altitude_m,
                "accuracy_m": accuracy_m,
                "gps_time": gps_time.isoformat() if gps_time else "",
                "received_at": received_at.isoformat() if received_at else "",
                "snapshot_at": snapshot_at.isoformat(),
                "gps_valid": gps_valid,
                "source": source or "",
                "note_th": "",
            },
        )
        return LocationSnapshot(
            location_snapshot_id=location_snapshot_id,
            event_type=event_type,
            event_id=event_id,
            vehicle_id=vehicle_id,
            device_id=device_id,
            latitude=latitude,
            longitude=longitude,
            altitude_m=altitude_m,
            accuracy_m=accuracy_m,
            gps_time=gps_time,
            received_at=received_at,
            snapshot_at=snapshot_at,
            gps_valid=gps_valid,
            source=source,
        )

    async def get_location_snapshot(self, location_snapshot_id: str) -> LocationSnapshot | None:
        self._ensure_configured(schemas.LOCATION_SNAPSHOT_SHEET.tab_name)
        found = await self._client.find_row(
            schemas.LOCATION_SNAPSHOT_SHEET, "location_snapshot_id", location_snapshot_id
        )
        return self._location_snapshot_from_row(found[1]) if found else None

    async def list_location_snapshots_for_event(self, event_id: str) -> list[LocationSnapshot]:
        self._ensure_configured(schemas.LOCATION_SNAPSHOT_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.LOCATION_SNAPSHOT_SHEET)
        matches = [row for row in rows if row.get("event_id") == event_id]
        return [self._location_snapshot_from_row(row) for row in matches]

    # ---- Material request (Core Demo Fixes Delta, Store/Inventory boundary) ----

    def _material_request_from_row(self, row: dict) -> MaterialRequest:
        return MaterialRequest(
            material_request_id=row["material_request_id"],
            source_type=RequisitionSourceType(row.get("source_type") or "REPAIR"),
            source_work_order_id=row.get("source_work_order_id", ""),
            vehicle_id=row.get("vehicle_id") or None,
            request_status=row.get("request_status") or "OPEN",
            created_at=self._parse_datetime(row.get("created_at", "")) or _epoch(),
            created_by=row.get("created_by_user_id") or None,
            approved_at=self._parse_datetime(row.get("approved_at", "")),
            approved_by=row.get("approved_by_user_id") or None,
            issued_at=self._parse_datetime(row.get("issued_at", "")),
            issued_by=row.get("issued_by_user_id") or None,
            closed_at=self._parse_datetime(row.get("closed_at", "")),
            note=row.get("note_th") or None,
        )

    async def create_material_request(
        self,
        source_type: RequisitionSourceType,
        source_work_order_id: str,
        vehicle_id: str | None,
        created_by: str | None,
        note: str | None = None,
    ) -> MaterialRequest:
        self._ensure_configured(schemas.MATERIAL_REQUEST_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.MATERIAL_REQUEST_SHEET)
        material_request_id = self._next_id(rows, "material_request_id", "MREQ")
        created_at = datetime.now(timezone.utc)
        await self._client.append_row(
            schemas.MATERIAL_REQUEST_SHEET,
            {
                "material_request_id": material_request_id,
                "source_type": source_type.value,
                "source_work_order_id": source_work_order_id,
                "vehicle_id": vehicle_id or "",
                "request_status": "OPEN",
                "created_at": created_at.isoformat(),
                "created_by_user_id": created_by or "",
                "approved_at": "",
                "approved_by_user_id": "",
                "issued_at": "",
                "issued_by_user_id": "",
                "closed_at": "",
                "note_th": note or "",
            },
        )
        return MaterialRequest(
            material_request_id=material_request_id,
            source_type=source_type,
            source_work_order_id=source_work_order_id,
            vehicle_id=vehicle_id,
            created_at=created_at,
            created_by=created_by,
            note=note,
        )

    async def get_material_request(self, material_request_id: str) -> MaterialRequestDetail | None:
        self._ensure_configured(schemas.MATERIAL_REQUEST_SHEET.tab_name)
        found = await self._client.find_row(
            schemas.MATERIAL_REQUEST_SHEET, "material_request_id", material_request_id
        )
        if found is None:
            return None
        line_rows = await self._client.read_rows(schemas.MATERIAL_REQUEST_LINE_SHEET)
        lines = [
            self._requisition_line_from_row(row)
            for row in line_rows
            if row.get("material_request_id") == material_request_id
        ]
        return MaterialRequestDetail(
            request=self._material_request_from_row(found[1]), lines=lines
        )

    async def list_material_requests_for_work_order(
        self, source_work_order_id: str
    ) -> list[MaterialRequest]:
        self._ensure_configured(schemas.MATERIAL_REQUEST_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.MATERIAL_REQUEST_SHEET)
        matches = [
            self._material_request_from_row(row)
            for row in rows
            if row.get("source_work_order_id") == source_work_order_id
        ]
        matches.sort(key=lambda r: r.created_at)
        return matches

    def _requisition_line_from_row(self, row: dict) -> RequisitionLine:
        return RequisitionLine(
            requisition_line_id=row["material_request_line_id"],
            material_request_id=row.get("material_request_id", ""),
            source_task_revision_id=row.get("source_task_revision_id") or None,
            part_id=row.get("part_id") or None,
            part_instance_id=row.get("part_instance_id") or None,
            part_code_snapshot=row.get("part_code_snapshot") or None,
            part_description=row.get("part_name_snapshot_th", ""),
            requested_quantity=self._parse_float(row.get("requested_qty")),
            unit=row.get("unit") or None,
            approved_quantity=self._parse_float(row.get("approved_qty")),
            issued_quantity=self._parse_float(row.get("issued_qty")),
            used_quantity=self._parse_float(row.get("used_qty")),
            returned_quantity=self._parse_float(row.get("returned_qty")),
            line_source=row.get("line_source") or None,
            created_at=self._parse_datetime(row.get("created_at", "")) or _epoch(),
            created_by=None,  # material_request_line has no created_by column
        )

    async def create_requisition_line(
        self,
        material_request_id: str,
        part_id: str | None,
        part_instance_id: str | None,
        part_code_snapshot: str | None,
        part_description: str,
        requested_quantity: float | None,
        unit: str | None,
        source_task_revision_id: str | None,
        line_source: str | None,
        created_by: str | None,
    ) -> RequisitionLine:
        self._ensure_configured(schemas.MATERIAL_REQUEST_LINE_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.MATERIAL_REQUEST_LINE_SHEET)
        line_id = self._next_id(rows, "material_request_line_id", "MREQL")
        created_at = datetime.now(timezone.utc)
        await self._client.append_row(
            schemas.MATERIAL_REQUEST_LINE_SHEET,
            {
                "material_request_line_id": line_id,
                "material_request_id": material_request_id,
                "source_task_revision_id": source_task_revision_id or "",
                "part_id": part_id or "",
                "part_instance_id": part_instance_id or "",
                "part_code_snapshot": part_code_snapshot or "",
                "part_name_snapshot_th": part_description,
                "requested_qty": requested_quantity,
                "approved_qty": "",
                "issued_qty": "",
                "used_qty": "",
                "returned_qty": "",
                "unit": unit or "",
                "line_source": line_source or "",
                "note_th": "",
            },
        )
        return RequisitionLine(
            requisition_line_id=line_id,
            material_request_id=material_request_id,
            source_task_revision_id=source_task_revision_id,
            part_id=part_id,
            part_instance_id=part_instance_id,
            part_code_snapshot=part_code_snapshot,
            part_description=part_description,
            requested_quantity=requested_quantity,
            unit=unit,
            line_source=line_source,
            created_at=created_at,
            created_by=created_by,
        )

    async def list_requisition_lines_for_work_order(
        self, work_order_reference: str
    ) -> list[RequisitionLine]:
        self._ensure_configured(schemas.MATERIAL_REQUEST_LINE_SHEET.tab_name)
        request_rows = await self._client.read_rows(schemas.MATERIAL_REQUEST_SHEET)
        request_ids = {
            row["material_request_id"]
            for row in request_rows
            if row.get("source_work_order_id") == work_order_reference
        }
        line_rows = await self._client.read_rows(schemas.MATERIAL_REQUEST_LINE_SHEET)
        return [
            self._requisition_line_from_row(row)
            for row in line_rows
            if row.get("material_request_id") in request_ids
        ]
