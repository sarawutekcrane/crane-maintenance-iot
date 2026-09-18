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

import json
from datetime import date, datetime, timezone

from app.config import Settings
from app.domain.assignment import (
    AssignmentRole,
    PmAssignmentHistoryEntry,
    RepairAssignmentHistoryEntry,
    active_primary_and_collaborators,
)
from app.domain.asset import AssetType
from app.domain.attachment import Attachment, AttachmentPurpose
from app.domain.checklist import (
    ChecklistItem,
    ChecklistMaster,
    ChecklistRevision,
    ChecklistRevisionDetail,
    InspectionResultValue,
)
from app.domain.common import OperationalStatus, PageParams
from app.domain.driver import Driver, VehicleDriverAssignment
from app.domain.vehicle_certificate import CertificateStatus, VehicleCertificate
from app.domain.model_document import ModelDocument
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
    InspectionHeader,
    InspectionItemResult,
    InspectionSummary,
    NewInspectionItemInput,
)
from app.domain.lifetime_rule import LifetimeRule, LifetimeRuleScope, LifetimeTriggerType
from app.domain.location_snapshot import CurrentLocation, LocationSnapshot
from app.domain.meter import CounterType, CurrentCounterReading, MeterReading, MeterSnapshot
from app.domain.part import (
    PartActionType,
    PartMaster,
    PartSet,
    PartSetItem,
    PartSetItemRequirement,
    PartSetRevision,
    PartSetRevisionDetail,
    TrackingMode,
)
from app.domain.part_instance import (
    InstallationSegment,
    InstallationSegmentStatus,
    LifecycleStartReason,
    PartInstance,
    PartInstanceDetail,
    PartInstanceStatus,
    PartLifecycle,
    PriorUsage,
    PriorUsageQuality,
)
from app.domain.pm import (
    PmPlan,
    PmScopeAdditionAudit,
    PmTask,
    PmTaskPart,
    PmTaskRevision,
    PmTaskRevisionDetail,
    PmTriggerType,
    PmUsedPart,
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
from app.domain.repair import (
    Repair,
    RepairAction,
    RepairDetail,
    RepairPart,
    RepairSourceType,
    RepairStatus,
    RepairSummary,
)
from app.domain.repair_request import (
    REPAIR_REQUEST_STATUS_CONVERTED,
    REPAIR_REQUEST_STATUS_PENDING,
    RepairRequest,
    decode_meter_snapshot_link,
    decode_provenance_note,
    encode_meter_snapshot_link,
)
from app.domain.vehicle import Vehicle, VehicleComponent, VehicleStatusHistoryEntry
from app.domain.vehicle_model import ComponentRole, VehicleModel
from app.repositories.base import (
    Repository,
    RepositoryError,
    RepositoryFeatureNotImplementedError,
)
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
        # Web/API Phase 6 Batch 1 — verified live tabs, real I/O below.
        schemas.DRIVER_MASTER_SHEET,
        schemas.VEHICLE_DRIVER_SHEET,
        # Web/API Phase 6 Batch 2A — verified live tab, real I/O below.
        schemas.VEHICLE_CERTIFICATE_SHEET,
        # Web/API Phase 6 Batch 3A — verified live tab, real I/O below.
        schemas.MODEL_DOCUMENT_SHEET,
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
        have yet).

        F3 cross-phase integration fix: raises the explicit
        `RepositoryFeatureNotImplementedError` (never a bare
        `NotImplementedError`) so `app.errors` can surface this as a
        distinct, user-safe `FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE` API
        error instead of a generic `INTERNAL_ERROR` — this is a known,
        intentional gap, not an unexpected programming defect."""
        self._ensure_configured(entity)
        raise RepositoryFeatureNotImplementedError(entity)

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
    def _parse_date(value: object) -> "date | None":
        if not value:
            return None
        try:
            return date.fromisoformat(str(value))
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

    def _vehicle_model_from_row(
        self, row: dict, plan_id_by_code: dict[str, str]
    ) -> VehicleModel:
        component_roles_raw = str(row.get("component_roles", ""))
        plan_code = row.get("default_plan_code", "")
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
            assigned_pm_plan_id=plan_id_by_code.get(plan_code) if plan_code else None,
        )

    async def _plan_id_by_code_map(self) -> dict[str, str]:
        plan_rows = await self._client.read_rows(schemas.PM_PLAN_SHEET)
        return {
            row["plan_code"]: row["pm_plan_id"]
            for row in plan_rows
            if row.get("plan_code") and row.get("pm_plan_id")
        }

    async def list_vehicle_models(
        self, q: str | None, params: PageParams
    ) -> tuple[list[VehicleModel], int]:
        self._ensure_configured(schemas.VEHICLE_MODEL_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.VEHICLE_MODEL_SHEET)
        plan_id_by_code = await self._plan_id_by_code_map()
        models = [self._vehicle_model_from_row(row, plan_id_by_code) for row in rows]
        if q:
            needle = q.strip().lower()
            models = [
                m
                for m in models
                if needle in m.model_code.lower() or needle in m.model_name.lower()
            ]
        models.sort(key=lambda m: m.model_id)
        start = (params.page - 1) * params.page_size
        page = models[start : start + params.page_size]
        return page, len(models)

    async def get_vehicle_model(self, model_id: str) -> VehicleModel | None:
        self._ensure_configured(schemas.VEHICLE_MODEL_SHEET.tab_name)
        found = await self._client.find_row(schemas.VEHICLE_MODEL_SHEET, "model_id", model_id)
        if found is None:
            return None
        _, row = found
        plan_id_by_code = await self._plan_id_by_code_map()
        return self._vehicle_model_from_row(row, plan_id_by_code)

    # ---- Vehicle ----

    def _vehicle_from_row(self, row: dict) -> Vehicle:
        return Vehicle(
            vehicle_id=row["vehicle_id"],
            machine_no=row.get("machine_no", ""),
            model_id=row.get("model_id", ""),
            serial_number=row.get("serial_number") or None,
            operational_status=OperationalStatus(row.get("operational_status") or "READY"),
            created_at=self._parse_datetime(row.get("created_at", "")) or _epoch(),
            updated_at=self._parse_datetime(row.get("updated_at", "")) or _epoch(),
        )

    async def list_vehicles(
        self,
        q: str | None,
        operational_status: OperationalStatus | None,
        model_id: str | None,
        params: PageParams,
    ) -> tuple[list[Vehicle], int]:
        self._ensure_configured(schemas.VEHICLE_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.VEHICLE_SHEET)
        vehicles = [self._vehicle_from_row(row) for row in rows]
        if q:
            needle = q.strip().lower()
            vehicles = [
                v
                for v in vehicles
                if needle in v.machine_no.lower() or needle in v.vehicle_id.lower()
            ]
        if operational_status is not None:
            vehicles = [v for v in vehicles if v.operational_status == operational_status]
        if model_id is not None:
            vehicles = [v for v in vehicles if v.model_id == model_id]
        vehicles.sort(key=lambda v: v.vehicle_id)
        start = (params.page - 1) * params.page_size
        page = vehicles[start : start + params.page_size]
        return page, len(vehicles)

    async def get_vehicle(self, vehicle_id: str) -> Vehicle | None:
        self._ensure_configured(schemas.VEHICLE_SHEET.tab_name)
        found = await self._client.find_row(schemas.VEHICLE_SHEET, "vehicle_id", vehicle_id)
        if found is None:
            return None
        return self._vehicle_from_row(found[1])

    async def update_vehicle_machine_no(self, vehicle_id: str, machine_no: str) -> Vehicle:
        self._ensure_configured(schemas.VEHICLE_SHEET.tab_name)
        found = await self._client.find_row(schemas.VEHICLE_SHEET, "vehicle_id", vehicle_id)
        if found is None:
            raise RepositoryError(f"Vehicle '{vehicle_id}' was not found")
        row_number, row = found
        updated_row = dict(row)
        updated_row["machine_no"] = machine_no
        updated_row["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self._client.update_row(schemas.VEHICLE_SHEET, row_number, updated_row)
        return self._vehicle_from_row(updated_row)

    async def list_vehicle_components(self, vehicle_id: str) -> list[VehicleComponent]:
        # REV06 section 9/10 (P0): required for `MeterService
        # .capture_current_state`'s carry-forward read on every VEHICLE
        # Repair/RepairRequest automatic snapshot (CORE-G01) — without a
        # real read here, `POST /repair-requests` itself 500s in
        # google_sheets mode before the conversion path is even reached.
        self._ensure_configured(schemas.VEHICLE_COMPONENT_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.VEHICLE_COMPONENT_SHEET)
        return [
            VehicleComponent(
                component_id=row["component_id"],
                vehicle_id=row.get("vehicle_id", ""),
                component_role=ComponentRole(row.get("component_role") or "CARRIER_ENGINE"),
                label=row.get("label", ""),
            )
            for row in rows
            if row.get("vehicle_id") == vehicle_id
        ]

    def _vehicle_status_history_from_row(self, row: dict) -> VehicleStatusHistoryEntry:
        return VehicleStatusHistoryEntry(
            history_id=row["history_id"],
            vehicle_id=row.get("vehicle_id", ""),
            status=OperationalStatus(row.get("status") or "READY"),
            changed_at=self._parse_datetime(row.get("changed_at", "")) or _epoch(),
            changed_by=row.get("changed_by") or None,
            note=row.get("note") or None,
        )

    async def list_vehicle_status_history(
        self, vehicle_id: str
    ) -> list[VehicleStatusHistoryEntry]:
        self._ensure_configured(schemas.VEHICLE_STATUS_HISTORY_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.VEHICLE_STATUS_HISTORY_SHEET)
        entries = [
            self._vehicle_status_history_from_row(row)
            for row in rows
            if row.get("vehicle_id") == vehicle_id
        ]
        entries.sort(key=lambda e: e.changed_at, reverse=True)
        return entries

    async def change_vehicle_status(
        self,
        vehicle_id: str,
        new_status: OperationalStatus,
        changed_by: str | None,
        note: str | None,
    ) -> VehicleStatusHistoryEntry:
        self._ensure_configured(schemas.VEHICLE_STATUS_HISTORY_SHEET.tab_name)
        found = await self._client.find_row(schemas.VEHICLE_SHEET, "vehicle_id", vehicle_id)
        if found is None:
            raise RepositoryError(f"Vehicle '{vehicle_id}' was not found")
        row_number, row = found
        updated_row = dict(row)
        updated_row["operational_status"] = new_status.value
        now = datetime.now(timezone.utc)
        updated_row["updated_at"] = now.isoformat()
        await self._client.update_row(schemas.VEHICLE_SHEET, row_number, updated_row)

        history_rows = await self._client.read_rows(schemas.VEHICLE_STATUS_HISTORY_SHEET)
        history_id = self._next_id(history_rows, "history_id", "STH")
        await self._client.append_row(
            schemas.VEHICLE_STATUS_HISTORY_SHEET,
            {
                "history_id": history_id,
                "vehicle_id": vehicle_id,
                "status": new_status.value,
                "changed_at": now.isoformat(),
                "changed_by": changed_by or "",
                "note": note or "",
            },
        )
        return VehicleStatusHistoryEntry(
            history_id=history_id,
            vehicle_id=vehicle_id,
            status=new_status,
            changed_at=now,
            changed_by=changed_by,
            note=note,
        )

    # ---- Workshop equipment ----

    async def list_equipment(
        self, q: str | None, category: EquipmentCategory | None, params: PageParams
    ) -> tuple[list[Equipment], int]:
        self._ensure_configured(schemas.EQUIPMENT_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.EQUIPMENT_SHEET)
        items = [self._equipment_from_row(row) for row in rows]
        if q:
            needle = q.strip().lower()
            items = [
                e
                for e in items
                if needle in e.name.lower() or needle in e.equipment_code.lower()
            ]
        if category is not None:
            items = [e for e in items if e.category == category]
        items.sort(key=lambda e: e.equipment_id)
        start = (params.page - 1) * params.page_size
        page = items[start : start + params.page_size]
        return page, len(items)

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

    def _checklist_item_from_row(self, row: dict) -> ChecklistItem:
        return ChecklistItem(
            item_id=row["item_id"],
            revision_id=row.get("revision_id", ""),
            sequence=int(self._parse_float(row.get("sequence")) or 0),
            title=row.get("title", ""),
            inspection_point=row.get("inspection_point") or None,
            method=row.get("method") or None,
            standard=row.get("standard") or None,
            instruction=row.get("instruction") or None,
            frequency=row.get("frequency") or None,
            reference_image_attachment_id=row.get("reference_image_attachment_id") or None,
            required_photo_on_fail=self._parse_bool(row.get("required_photo_on_fail")),
            required_remark_on_fail=self._parse_bool(row.get("required_remark_on_fail")),
            is_critical=self._parse_bool(row.get("is_critical")),
        )

    async def _checklist_revision_detail(
        self, checklist_row: dict, revision_row: dict
    ) -> ChecklistRevisionDetail:
        checklist = ChecklistMaster(
            checklist_id=checklist_row["checklist_id"],
            asset_type=AssetType(checklist_row.get("asset_type") or "VEHICLE"),
            code=checklist_row.get("code", ""),
            name=checklist_row.get("name", ""),
            created_at=self._parse_datetime(checklist_row.get("created_at", "")) or _epoch(),
            updated_at=self._parse_datetime(checklist_row.get("updated_at", "")) or _epoch(),
        )
        revision = ChecklistRevision(
            revision_id=revision_row["revision_id"],
            checklist_id=revision_row.get("checklist_id", ""),
            revision_number=int(self._parse_float(revision_row.get("revision_number")) or 0),
            effective_date=self._parse_date(revision_row.get("effective_date", "")) or _epoch().date(),
            created_at=self._parse_datetime(revision_row.get("created_at", "")) or _epoch(),
        )
        item_rows = await self._client.read_rows(schemas.CHECKLIST_ITEM_SHEET)
        items = [
            self._checklist_item_from_row(row)
            for row in item_rows
            if row.get("revision_id") == revision.revision_id
        ]
        items.sort(key=lambda i: i.sequence)
        return ChecklistRevisionDetail(checklist=checklist, revision=revision, items=items)

    async def get_active_checklist_revision(
        self, asset_type: AssetType
    ) -> ChecklistRevisionDetail | None:
        self._ensure_configured(schemas.CHECKLIST_REVISION_SHEET.tab_name)
        checklist_rows = await self._client.read_rows(schemas.CHECKLIST_MASTER_SHEET)
        checklist_row = next(
            (row for row in checklist_rows if row.get("asset_type") == asset_type.value), None
        )
        if checklist_row is None:
            return None
        revision_rows = await self._client.read_rows(schemas.CHECKLIST_REVISION_SHEET)
        today = datetime.now(timezone.utc).date()
        candidates = [
            row
            for row in revision_rows
            if row.get("checklist_id") == checklist_row["checklist_id"]
            and self._parse_date(row.get("effective_date", "")) is not None
            and self._parse_date(row.get("effective_date", "")) <= today
        ]
        if not candidates:
            return None
        latest = max(
            candidates,
            key=lambda row: (
                self._parse_date(row.get("effective_date", "")),
                int(self._parse_float(row.get("revision_number")) or 0),
            ),
        )
        return await self._checklist_revision_detail(checklist_row, latest)

    async def get_checklist_revision(
        self, checklist_id: str, revision_id: str
    ) -> ChecklistRevisionDetail | None:
        self._ensure_configured(schemas.CHECKLIST_REVISION_SHEET.tab_name)
        found = await self._client.find_row(
            schemas.CHECKLIST_REVISION_SHEET, "revision_id", revision_id
        )
        if found is None or found[1].get("checklist_id") != checklist_id:
            return None
        checklist_found = await self._client.find_row(
            schemas.CHECKLIST_MASTER_SHEET, "checklist_id", checklist_id
        )
        if checklist_found is None:
            return None
        return await self._checklist_revision_detail(checklist_found[1], found[1])

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

    def _inspection_header_from_row(self, row: dict) -> InspectionHeader:
        return InspectionHeader(
            inspection_id=row["inspection_id"],
            asset_type=AssetType(row.get("asset_type") or "VEHICLE"),
            asset_id=row.get("asset_id", ""),
            checklist_id=row.get("checklist_id", ""),
            revision_id=row.get("revision_id", ""),
            revision_number=int(self._parse_float(row.get("revision_number")) or 0),
            submitted_at=self._parse_datetime(row.get("submitted_at", "")) or _epoch(),
            inspector_user_id=row.get("inspector_user_id") or None,
            overall_remark=row.get("overall_remark") or None,
            machine_state_snapshot_id=row.get("machine_state_snapshot_id") or None,
        )

    def _inspection_item_result_from_row(self, row: dict) -> InspectionItemResult:
        evidence_raw = str(row.get("evidence_attachment_ids", ""))
        return InspectionItemResult(
            result_id=row["result_id"],
            inspection_id=row.get("inspection_id", ""),
            item_id=row.get("item_id", ""),
            sequence=int(self._parse_float(row.get("sequence")) or 0),
            title=row.get("title", ""),
            inspection_point=row.get("inspection_point") or None,
            method=row.get("method") or None,
            standard=row.get("standard") or None,
            instruction=row.get("instruction") or None,
            is_critical=self._parse_bool(row.get("is_critical")),
            result=InspectionResultValue(row.get("result") or "NA"),
            remark=row.get("remark") or None,
            evidence_attachment_ids=[v.strip() for v in evidence_raw.split(",") if v.strip()],
        )

    def _inspection_finding_from_row(self, row: dict) -> InspectionFinding:
        return InspectionFinding(
            finding_id=row["finding_id"],
            inspection_id=row.get("inspection_id", ""),
            result_id=row.get("result_id", ""),
            asset_type=AssetType(row.get("asset_type") or "VEHICLE"),
            asset_id=row.get("asset_id", ""),
            item_title=row.get("item_title", ""),
            is_critical=self._parse_bool(row.get("is_critical")),
            status=FindingStatus(row.get("status") or "OPEN"),
            created_at=self._parse_datetime(row.get("created_at", "")) or _epoch(),
        )

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
        self._ensure_configured(schemas.INSPECTION_SHEET.tab_name)
        header_rows = await self._client.read_rows(schemas.INSPECTION_SHEET)
        inspection_id = self._next_id(header_rows, "inspection_id", "INS")
        submitted_at = datetime.now(timezone.utc)
        header = InspectionHeader(
            inspection_id=inspection_id,
            asset_type=asset_type,
            asset_id=asset_id,
            checklist_id=checklist_id,
            revision_id=revision_id,
            revision_number=revision_number,
            submitted_at=submitted_at,
            inspector_user_id=inspector_user_id,
            overall_remark=overall_remark,
            machine_state_snapshot_id=machine_state_snapshot_id,
        )
        await self._client.append_row(
            schemas.INSPECTION_SHEET,
            {
                "inspection_id": inspection_id,
                "asset_type": asset_type.value,
                "asset_id": asset_id,
                "checklist_id": checklist_id,
                "revision_id": revision_id,
                "revision_number": revision_number,
                "submitted_at": submitted_at.isoformat(),
                "inspector_user_id": inspector_user_id or "",
                "overall_remark": overall_remark or "",
                "machine_state_snapshot_id": machine_state_snapshot_id or "",
            },
        )

        result_rows = await self._client.read_rows(schemas.INSPECTION_ITEM_RESULT_SHEET)
        finding_rows = await self._client.read_rows(schemas.INSPECTION_FINDING_SHEET)
        item_results: list[InspectionItemResult] = []
        findings: list[InspectionFinding] = []
        pending_result_rows: list[dict[str, object]] = []
        pending_finding_rows: list[dict[str, object]] = []
        for item_input in items:
            result_id = self._next_id(result_rows, "result_id", "RES")
            result = InspectionItemResult(
                result_id=result_id,
                inspection_id=inspection_id,
                item_id=item_input.item_id,
                sequence=item_input.sequence,
                title=item_input.title,
                inspection_point=item_input.inspection_point,
                method=item_input.method,
                standard=item_input.standard,
                instruction=item_input.instruction,
                is_critical=item_input.is_critical,
                result=item_input.result,
                remark=item_input.remark,
                evidence_attachment_ids=list(item_input.evidence_attachment_ids),
            )
            pending_result_rows.append(
                {
                    "result_id": result_id,
                    "inspection_id": inspection_id,
                    "item_id": result.item_id,
                    "sequence": result.sequence,
                    "title": result.title,
                    "inspection_point": result.inspection_point or "",
                    "method": result.method or "",
                    "standard": result.standard or "",
                    "instruction": result.instruction or "",
                    "is_critical": result.is_critical,
                    "result": result.result.value,
                    "remark": result.remark or "",
                    "evidence_attachment_ids": ",".join(result.evidence_attachment_ids),
                }
            )
            result_rows.append({"result_id": result_id})
            item_results.append(result)

            if item_input.result == InspectionResultValue.FAIL:
                finding_id = self._next_id(finding_rows, "finding_id", "FND")
                finding = InspectionFinding(
                    finding_id=finding_id,
                    inspection_id=inspection_id,
                    result_id=result_id,
                    asset_type=asset_type,
                    asset_id=asset_id,
                    item_title=item_input.title,
                    is_critical=item_input.is_critical,
                    status=FindingStatus.OPEN,
                    created_at=submitted_at,
                )
                pending_finding_rows.append(
                    {
                        "finding_id": finding_id,
                        "inspection_id": inspection_id,
                        "result_id": result_id,
                        "asset_type": asset_type.value,
                        "asset_id": asset_id,
                        "item_title": finding.item_title,
                        "is_critical": finding.is_critical,
                        "status": finding.status.value,
                        "created_at": submitted_at.isoformat(),
                    }
                )
                finding_rows.append({"finding_id": finding_id})
                findings.append(finding)

        # Every result row (and every finding row) belongs to one logical
        # write per sheet — see `GoogleSheetsClient.append_rows` for why
        # this must never be split back into one `append_row` call per
        # item (REV07 live UAT defect, section 15: that pattern silently
        # dropped all but the last submitted result row).
        await self._client.append_rows(schemas.INSPECTION_ITEM_RESULT_SHEET, pending_result_rows)
        await self._client.append_rows(schemas.INSPECTION_FINDING_SHEET, pending_finding_rows)

        return InspectionDetail(header=header, items=item_results, findings=findings)

    async def get_inspection(self, inspection_id: str) -> InspectionDetail | None:
        self._ensure_configured(schemas.INSPECTION_SHEET.tab_name)
        found = await self._client.find_row(schemas.INSPECTION_SHEET, "inspection_id", inspection_id)
        if found is None:
            return None
        header = self._inspection_header_from_row(found[1])
        result_rows = await self._client.read_rows(schemas.INSPECTION_ITEM_RESULT_SHEET)
        items = [
            self._inspection_item_result_from_row(row)
            for row in result_rows
            if row.get("inspection_id") == inspection_id
        ]
        finding_rows = await self._client.read_rows(schemas.INSPECTION_FINDING_SHEET)
        findings = [
            self._inspection_finding_from_row(row)
            for row in finding_rows
            if row.get("inspection_id") == inspection_id
        ]
        return InspectionDetail(header=header, items=items, findings=findings)

    async def list_inspections(
        self,
        asset_type: AssetType | None,
        asset_id: str | None,
        params: PageParams,
    ) -> tuple[list[InspectionSummary], int]:
        self._ensure_configured(schemas.INSPECTION_SHEET.tab_name)
        header_rows = await self._client.read_rows(schemas.INSPECTION_SHEET)
        headers = [self._inspection_header_from_row(row) for row in header_rows]
        if asset_type is not None:
            headers = [h for h in headers if h.asset_type == asset_type]
        if asset_id is not None:
            headers = [h for h in headers if h.asset_id == asset_id]
        headers.sort(key=lambda h: h.submitted_at, reverse=True)

        result_rows = await self._client.read_rows(schemas.INSPECTION_ITEM_RESULT_SHEET)
        items_by_inspection: dict[str, list[InspectionItemResult]] = {}
        for row in result_rows:
            inspection_id = row.get("inspection_id")
            if inspection_id:
                items_by_inspection.setdefault(inspection_id, []).append(
                    self._inspection_item_result_from_row(row)
                )

        summaries = [
            InspectionSummary(
                inspection_id=h.inspection_id,
                asset_type=h.asset_type,
                asset_id=h.asset_id,
                checklist_id=h.checklist_id,
                revision_number=h.revision_number,
                submitted_at=h.submitted_at,
                inspector_user_id=h.inspector_user_id,
                pass_count=sum(
                    1
                    for i in items_by_inspection.get(h.inspection_id, [])
                    if i.result == InspectionResultValue.PASS
                ),
                fail_count=sum(
                    1
                    for i in items_by_inspection.get(h.inspection_id, [])
                    if i.result == InspectionResultValue.FAIL
                ),
                na_count=sum(
                    1
                    for i in items_by_inspection.get(h.inspection_id, [])
                    if i.result == InspectionResultValue.NA
                ),
                has_fail=any(
                    i.result == InspectionResultValue.FAIL
                    for i in items_by_inspection.get(h.inspection_id, [])
                ),
            )
            for h in headers
        ]
        start = (params.page - 1) * params.page_size
        page = summaries[start : start + params.page_size]
        return page, len(summaries)

    async def find_inspection_finding(self, finding_id: str) -> InspectionFinding | None:
        self._ensure_configured(schemas.INSPECTION_FINDING_SHEET.tab_name)
        found = await self._client.find_row(
            schemas.INSPECTION_FINDING_SHEET, "finding_id", finding_id
        )
        return self._inspection_finding_from_row(found[1]) if found else None

    async def find_inspection_result(self, result_id: str) -> InspectionItemResult | None:
        self._ensure_configured(schemas.INSPECTION_ITEM_RESULT_SHEET.tab_name)
        found = await self._client.find_row(
            schemas.INSPECTION_ITEM_RESULT_SHEET, "result_id", result_id
        )
        return self._inspection_item_result_from_row(found[1]) if found else None

    async def list_inspection_findings(
        self,
        asset_type: AssetType | None,
        asset_id: str | None,
        status: FindingStatus | None,
    ) -> list[InspectionFinding]:
        self._ensure_configured(schemas.INSPECTION_FINDING_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.INSPECTION_FINDING_SHEET)
        findings = [self._inspection_finding_from_row(row) for row in rows]
        if asset_type is not None:
            findings = [f for f in findings if f.asset_type == asset_type]
        if asset_id is not None:
            findings = [f for f in findings if f.asset_id == asset_id]
        if status is not None:
            findings = [f for f in findings if f.status == status]
        findings.sort(key=lambda f: f.created_at, reverse=True)
        return findings

    # ---- PM plan / task revision (Phase 4) ----

    def _pm_plan_from_row(self, row: dict) -> PmPlan:
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

    async def list_pm_plans(self, asset_type: AssetType | None, model_id: str | None) -> list[PmPlan]:
        self._ensure_configured(schemas.PM_PLAN_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.PM_PLAN_SHEET)
        plans = [self._pm_plan_from_row(row) for row in rows]
        if asset_type is not None:
            plans = [p for p in plans if p.asset_type == asset_type]
        if model_id is not None:
            plans = [p for p in plans if not p.model_ids or model_id in p.model_ids]
        plans.sort(key=lambda p: p.pm_plan_id)
        return plans

    async def get_pm_plan(self, pm_plan_id: str) -> PmPlan | None:
        self._ensure_configured(schemas.PM_PLAN_SHEET.tab_name)
        found = await self._client.find_row(schemas.PM_PLAN_SHEET, "pm_plan_id", pm_plan_id)
        return self._pm_plan_from_row(found[1]) if found else None

    def _pm_task_part_from_row(self, row: dict) -> PmTaskPart:
        return PmTaskPart(
            pm_task_part_id=row["pm_task_part_id"],
            pm_task_id=row.get("pm_task_id", ""),
            part_description=row.get("part_description", ""),
            quantity=self._parse_float(row.get("quantity")),
            unit=row.get("unit") or None,
            part_id=row.get("part_id") or None,
        )

    async def _pm_task_revision_detail(
        self, plan: PmPlan, revision_row: dict
    ) -> PmTaskRevisionDetail:
        revision = PmTaskRevision(
            revision_id=revision_row["revision_id"],
            pm_plan_id=revision_row.get("pm_plan_id", ""),
            revision_number=int(self._parse_float(revision_row.get("revision_number")) or 0),
            effective_date=self._parse_date(revision_row.get("effective_date", "")) or _epoch().date(),
            source_revision_note=revision_row.get("source_revision_note") or None,
            created_at=self._parse_datetime(revision_row.get("created_at", "")) or _epoch(),
        )
        task_rows = await self._client.read_rows(schemas.PM_TASK_SHEET)
        task_part_rows = await self._client.read_rows(schemas.PM_TASK_PART_SHEET)
        tasks: list[PmTask] = []
        for row in task_rows:
            if row.get("revision_id") != revision.revision_id:
                continue
            standard_parts = [
                self._pm_task_part_from_row(p)
                for p in task_part_rows
                if p.get("pm_task_id") == row["pm_task_id"]
            ]
            tasks.append(
                PmTask(
                    pm_task_id=row["pm_task_id"],
                    revision_id=row.get("revision_id", ""),
                    sequence=int(self._parse_float(row.get("sequence")) or 0),
                    group=row.get("group") or None,
                    description=row.get("description", ""),
                    trigger_type=PmTriggerType(row["trigger_type"]) if row.get("trigger_type") else None,
                    interval_value=self._parse_float(row.get("interval_value")),
                    interval_unit=row.get("interval_unit") or None,
                    standard_parts=standard_parts,
                )
            )
        tasks.sort(key=lambda t: t.sequence)
        return PmTaskRevisionDetail(plan=plan, revision=revision, tasks=tasks)

    async def get_active_pm_task_revision(self, pm_plan_id: str) -> PmTaskRevisionDetail | None:
        self._ensure_configured(schemas.PM_TASK_REVISION_SHEET.tab_name)
        plan = await self.get_pm_plan(pm_plan_id)
        if plan is None:
            return None
        revision_rows = await self._client.read_rows(schemas.PM_TASK_REVISION_SHEET)
        today = datetime.now(timezone.utc).date()
        candidates = [
            row
            for row in revision_rows
            if row.get("pm_plan_id") == pm_plan_id
            and self._parse_date(row.get("effective_date", "")) is not None
            and self._parse_date(row.get("effective_date", "")) <= today
        ]
        if not candidates:
            return None
        latest = max(
            candidates,
            key=lambda row: (
                self._parse_date(row.get("effective_date", "")),
                int(self._parse_float(row.get("revision_number")) or 0),
            ),
        )
        return await self._pm_task_revision_detail(plan, latest)

    async def get_pm_task_revision(
        self, pm_plan_id: str, revision_id: str
    ) -> PmTaskRevisionDetail | None:
        self._ensure_configured(schemas.PM_TASK_REVISION_SHEET.tab_name)
        found = await self._client.find_row(schemas.PM_TASK_REVISION_SHEET, "revision_id", revision_id)
        if found is None or found[1].get("pm_plan_id") != pm_plan_id:
            return None
        plan = await self.get_pm_plan(pm_plan_id)
        if plan is None:
            return None
        return await self._pm_task_revision_detail(plan, found[1])

    # ---- PM work order / work result (Phase 4) ----

    def _pm_assignment_from_row(self, row: dict) -> PmAssignmentHistoryEntry:
        return PmAssignmentHistoryEntry(
            pm_assignment_id=row["pm_assignment_id"],
            pm_work_order_id=row.get("pm_work_order_id", ""),
            user_id=row.get("user_id", ""),
            assignment_role=AssignmentRole(row.get("assignment_role") or "PRIMARY"),
            assigned_at=self._parse_datetime(row.get("assigned_at", "")) or _epoch(),
            assigned_by_user_id=row.get("assigned_by_user_id") or None,
            ended_at=self._parse_datetime(row.get("ended_at", "")),
            active_status=self._parse_bool(row.get("active_status", "TRUE")),
            note=row.get("note_th") or None,
        )

    def _pm_scope_addition_from_row(self, row: dict) -> PmScopeAdditionAudit:
        return PmScopeAdditionAudit(
            pm_work_order_id=row.get("pm_work_order_id", ""),
            pm_task_id=row.get("pm_task_id", ""),
            added_by=row.get("added_by_user_id") or None,
            added_at=self._parse_datetime(row.get("added_at", "")) or _epoch(),
            reason=row.get("add_reason_th", ""),
        )

    def _pm_work_order_row_to_domain(
        self,
        row: dict,
        scope_rows: list[dict],
        primary_technician: str | None,
        collaborators: list[str],
    ) -> PmWorkOrder:
        scope_task_ids = [r["pm_task_id"] for r in scope_rows if r.get("pm_task_id")]
        scope_approved_at: datetime | None = None
        scope_approved_by: str | None = None
        for r in scope_rows:
            if r.get("approved_at"):
                scope_approved_at = self._parse_datetime(r.get("approved_at", ""))
                scope_approved_by = r.get("approved_by_user_id") or None
                break
        return PmWorkOrder(
            pm_work_order_id=row["pm_work_order_id"],
            asset_type=AssetType(row.get("asset_type") or "VEHICLE"),
            asset_id=row.get("asset_id", ""),
            pm_plan_id=row.get("pm_plan_id", ""),
            revision_id=row.get("revision_id", ""),
            due_reason=PmTriggerType(row["due_reason"]) if row.get("due_reason") else None,
            status=PmWorkOrderStatus(row.get("status") or "OPEN"),
            opened_at=self._parse_datetime(row.get("opened_at", "")) or _epoch(),
            opened_by=row.get("opened_by") or None,
            closed_at=self._parse_datetime(row.get("closed_at", "")),
            closed_by=row.get("closed_by") or None,
            note=row.get("note") or None,
            opened_snapshot_id=row.get("opened_snapshot_id") or None,
            closed_snapshot_id=row.get("closed_snapshot_id") or None,
            scope_task_ids=scope_task_ids,
            scope_approved_at=scope_approved_at,
            scope_approved_by=scope_approved_by,
            primary_technician=primary_technician,
            collaborators=collaborators,
        )

    async def _load_pm_work_order(self, row: dict) -> PmWorkOrder:
        pm_work_order_id = row["pm_work_order_id"]
        scope_rows_all = await self._client.read_rows(schemas.PM_WORK_SCOPE_SHEET)
        scope_rows = [r for r in scope_rows_all if r.get("pm_work_order_id") == pm_work_order_id]
        assignment_rows_all = await self._client.read_rows(schemas.PM_WORK_ASSIGNMENT_SHEET)
        assignment_entries = [
            self._pm_assignment_from_row(r)
            for r in assignment_rows_all
            if r.get("pm_work_order_id") == pm_work_order_id
        ]
        primary, collaborators = active_primary_and_collaborators(assignment_entries)
        return self._pm_work_order_row_to_domain(row, scope_rows, primary, collaborators)

    def _pm_used_part_from_row(self, row: dict) -> PmUsedPart:
        return PmUsedPart(
            pm_used_part_id=row["pm_used_part_id"],
            pm_work_result_id=row.get("pm_work_result_id", ""),
            part_description=row.get("part_description", ""),
            quantity=self._parse_float(row.get("quantity")),
            unit=row.get("unit") or None,
            part_id=row.get("part_id") or None,
            part_instance_id=row.get("part_instance_id") or None,
            action=PartActionType(row["action"]) if row.get("action") else None,
            recorded_by=row.get("recorded_by") or None,
            recorded_at=self._parse_datetime(row.get("recorded_at", "")) or _epoch(),
        )

    def _pm_work_result_from_row(self, row: dict, used_part_rows: list[dict]) -> PmWorkResult:
        evidence_raw = str(row.get("evidence_attachment_ids", ""))
        used_parts = [
            self._pm_used_part_from_row(r)
            for r in used_part_rows
            if r.get("pm_work_result_id") == row["pm_work_result_id"]
        ]
        return PmWorkResult(
            pm_work_result_id=row["pm_work_result_id"],
            pm_work_order_id=row.get("pm_work_order_id", ""),
            pm_task_id=row.get("pm_task_id", ""),
            revision_id=row.get("revision_id", ""),
            sequence=int(self._parse_float(row.get("sequence")) or 0),
            task_description=row.get("task_description", ""),
            completed=self._parse_bool(row.get("completed")),
            meter_snapshot_id=row.get("meter_snapshot_id") or None,
            remark=row.get("remark") or None,
            used_parts=used_parts,
            evidence_attachment_ids=[v.strip() for v in evidence_raw.split(",") if v.strip()],
            performed_by=row.get("performed_by") or None,
            performed_at=self._parse_datetime(row.get("performed_at", "")) or _epoch(),
        )

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
        self._ensure_configured(schemas.PM_WORK_ORDER_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.PM_WORK_ORDER_SHEET)
        pm_work_order_id = self._next_id(rows, "pm_work_order_id", "PMWO")
        opened_at = datetime.now(timezone.utc)
        await self._client.append_row(
            schemas.PM_WORK_ORDER_SHEET,
            {
                "pm_work_order_id": pm_work_order_id,
                "asset_type": asset_type.value,
                "asset_id": asset_id,
                "pm_plan_id": pm_plan_id,
                "revision_id": revision_id,
                "due_reason": due_reason.value if due_reason else "",
                "status": PmWorkOrderStatus.OPEN.value,
                "opened_at": opened_at.isoformat(),
                "opened_by": opened_by or "",
                "closed_at": "",
                "closed_by": "",
                "note": note or "",
                "opened_snapshot_id": opened_snapshot_id or "",
                "closed_snapshot_id": "",
            },
        )

        scope_task_ids = list(scope_task_ids) if scope_task_ids else []
        if scope_task_ids:
            plan = await self.get_pm_plan(pm_plan_id)
            plan_code = plan.plan_code if plan else ""
            revision_found = await self._client.find_row(
                schemas.PM_TASK_REVISION_SHEET, "revision_id", revision_id
            )
            plan_version = revision_found[1].get("revision_number", "") if revision_found else ""
            task_rows = await self._client.read_rows(schemas.PM_TASK_SHEET)
            group_by_task_id = {r["pm_task_id"]: r.get("group", "") for r in task_rows}
            scope_rows = await self._client.read_rows(schemas.PM_WORK_SCOPE_SHEET)
            for task_id in scope_task_ids:
                pm_scope_id = self._next_id(scope_rows, "pm_scope_id", "PMSCP")
                new_row = {
                    "pm_scope_id": pm_scope_id,
                    "pm_work_order_id": pm_work_order_id,
                    "pm_task_id": task_id,
                    "plan_code": plan_code,
                    "plan_version": plan_version,
                    "group_code": group_by_task_id.get(task_id, ""),
                    "scope_source": "DUE",
                    "due_basis": due_reason.value if due_reason else "",
                    "added_by_user_id": "",
                    "added_at": "",
                    "add_reason_th": "",
                    "approved_by_user_id": "",
                    "approved_at": "",
                    "scope_status": "OPEN",
                    "completed_at": "",
                    "completion_snapshot_event_id": "",
                    "note_th": "",
                }
                await self._client.append_row(schemas.PM_WORK_SCOPE_SHEET, new_row)
                scope_rows.append(new_row)

        return PmWorkOrder(
            pm_work_order_id=pm_work_order_id,
            asset_type=asset_type,
            asset_id=asset_id,
            pm_plan_id=pm_plan_id,
            revision_id=revision_id,
            due_reason=due_reason,
            status=PmWorkOrderStatus.OPEN,
            opened_at=opened_at,
            opened_by=opened_by,
            note=note,
            opened_snapshot_id=opened_snapshot_id,
            scope_task_ids=scope_task_ids,
            primary_technician=None,
            collaborators=[],
        )

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
        self._ensure_configured(schemas.PM_WORK_SCOPE_SHEET.tab_name)
        found = await self._client.find_row(schemas.PM_WORK_ORDER_SHEET, "pm_work_order_id", pm_work_order_id)
        if found is None:
            raise RepositoryError(f"PM work order '{pm_work_order_id}' was not found")
        _, wo_row = found
        plan = await self.get_pm_plan(wo_row.get("pm_plan_id", ""))
        plan_code = plan.plan_code if plan else ""
        revision_found = await self._client.find_row(
            schemas.PM_TASK_REVISION_SHEET, "revision_id", wo_row.get("revision_id", "")
        )
        plan_version = revision_found[1].get("revision_number", "") if revision_found else ""
        task_found = await self._client.find_row(schemas.PM_TASK_SHEET, "pm_task_id", pm_task_id)
        group_code = task_found[1].get("group", "") if task_found else ""

        scope_rows = await self._client.read_rows(schemas.PM_WORK_SCOPE_SHEET)
        pm_scope_id = self._next_id(scope_rows, "pm_scope_id", "PMSCP")
        added_at = datetime.now(timezone.utc)
        await self._client.append_row(
            schemas.PM_WORK_SCOPE_SHEET,
            {
                "pm_scope_id": pm_scope_id,
                "pm_work_order_id": pm_work_order_id,
                "pm_task_id": pm_task_id,
                "plan_code": plan_code,
                "plan_version": plan_version,
                "group_code": group_code,
                "scope_source": "MANUAL",
                "due_basis": "",
                "added_by_user_id": added_by or "",
                "added_at": added_at.isoformat(),
                "add_reason_th": reason,
                "approved_by_user_id": "",
                "approved_at": "",
                "scope_status": "OPEN",
                "completed_at": "",
                "completion_snapshot_event_id": "",
                "note_th": "",
            },
        )
        return PmScopeAdditionAudit(
            pm_work_order_id=pm_work_order_id,
            pm_task_id=pm_task_id,
            added_by=added_by,
            added_at=added_at,
            reason=reason,
        )

    async def approve_pm_scope(
        self, pm_work_order_id: str, approved_by: str | None
    ) -> PmWorkOrder:
        self._ensure_configured(schemas.PM_WORK_SCOPE_SHEET.tab_name)
        found = await self._client.find_row(schemas.PM_WORK_ORDER_SHEET, "pm_work_order_id", pm_work_order_id)
        if found is None:
            raise RepositoryError(f"PM work order '{pm_work_order_id}' was not found")
        _, wo_row = found
        scope_rows = await self._client.read_rows(schemas.PM_WORK_SCOPE_SHEET)
        now = datetime.now(timezone.utc)
        for index, row in enumerate(scope_rows):
            if row.get("pm_work_order_id") != pm_work_order_id:
                continue
            updated = dict(row)
            updated["approved_by_user_id"] = approved_by or ""
            updated["approved_at"] = now.isoformat()
            updated["scope_status"] = "APPROVED"
            await self._client.update_row(schemas.PM_WORK_SCOPE_SHEET, index + 2, updated)
        return await self._load_pm_work_order(wo_row)

    async def assign_pm_work_order(
        self,
        pm_work_order_id: str,
        primary_technician: str | None,
        collaborators: list[str],
        assigned_by: str | None = None,
    ) -> PmWorkOrder:
        self._ensure_configured(schemas.PM_WORK_ASSIGNMENT_SHEET.tab_name)
        found = await self._client.find_row(schemas.PM_WORK_ORDER_SHEET, "pm_work_order_id", pm_work_order_id)
        if found is None:
            raise RepositoryError(f"PM work order '{pm_work_order_id}' was not found")
        _, wo_row = found
        now = datetime.now(timezone.utc)
        collaborators = list(collaborators) if collaborators else []

        new_assignments: list[tuple[str, AssignmentRole]] = []
        if primary_technician:
            new_assignments.append((primary_technician, AssignmentRole.PRIMARY))
        for collaborator in collaborators:
            new_assignments.append((collaborator, AssignmentRole.COLLABORATOR))
        new_keys = set(new_assignments)

        history_rows = await self._client.read_rows(schemas.PM_WORK_ASSIGNMENT_SHEET)
        for index, hrow in enumerate(history_rows):
            if hrow.get("pm_work_order_id") != pm_work_order_id:
                continue
            if not self._parse_bool(hrow.get("active_status", "TRUE")):
                continue
            key = (hrow.get("user_id", ""), AssignmentRole(hrow.get("assignment_role") or "PRIMARY"))
            if key in new_keys:
                continue
            ended_row = dict(hrow)
            ended_row["active_status"] = "FALSE"
            ended_row["ended_at"] = now.isoformat()
            await self._client.update_row(schemas.PM_WORK_ASSIGNMENT_SHEET, index + 2, ended_row)
            history_rows[index] = ended_row

        already_active = {
            (hrow.get("user_id", ""), AssignmentRole(hrow.get("assignment_role") or "PRIMARY"))
            for hrow in history_rows
            if hrow.get("pm_work_order_id") == pm_work_order_id
            and self._parse_bool(hrow.get("active_status", "TRUE"))
        }
        for user_id, role in new_assignments:
            if (user_id, role) in already_active:
                continue
            assignment_id = self._next_id(history_rows, "pm_assignment_id", "PASG")
            new_row = {
                "pm_assignment_id": assignment_id,
                "pm_work_order_id": pm_work_order_id,
                "user_id": user_id,
                "assignment_role": role.value,
                "assigned_at": now.isoformat(),
                "assigned_by_user_id": assigned_by or "",
                "ended_at": "",
                "active_status": "TRUE",
                "note_th": "",
            }
            await self._client.append_row(schemas.PM_WORK_ASSIGNMENT_SHEET, new_row)
            history_rows.append(new_row)

        return await self._load_pm_work_order(wo_row)

    async def list_pm_work_order_assignment_history(
        self, pm_work_order_id: str
    ) -> list[PmAssignmentHistoryEntry]:
        self._ensure_configured(schemas.PM_WORK_ASSIGNMENT_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.PM_WORK_ASSIGNMENT_SHEET)
        entries = [
            self._pm_assignment_from_row(r) for r in rows if r.get("pm_work_order_id") == pm_work_order_id
        ]
        entries.sort(key=lambda e: e.assigned_at)
        return entries

    async def get_pm_work_order(self, pm_work_order_id: str) -> PmWorkOrderDetail | None:
        self._ensure_configured(schemas.PM_WORK_ORDER_SHEET.tab_name)
        found = await self._client.find_row(schemas.PM_WORK_ORDER_SHEET, "pm_work_order_id", pm_work_order_id)
        if found is None:
            return None
        _, row = found
        work_order = await self._load_pm_work_order(row)

        scope_rows_all = await self._client.read_rows(schemas.PM_WORK_SCOPE_SHEET)
        scope_rows = [r for r in scope_rows_all if r.get("pm_work_order_id") == pm_work_order_id]
        scope_additions = [
            self._pm_scope_addition_from_row(r) for r in scope_rows if r.get("scope_source") == "MANUAL"
        ]
        scope_additions.sort(key=lambda a: a.added_at)

        result_rows = await self._client.read_rows(schemas.PM_WORK_RESULT_SHEET)
        used_part_rows = await self._client.read_rows(schemas.PM_USED_PART_SHEET)
        results = [
            self._pm_work_result_from_row(r, used_part_rows)
            for r in result_rows
            if r.get("pm_work_order_id") == pm_work_order_id
        ]
        results.sort(key=lambda r: r.sequence)

        return PmWorkOrderDetail(work_order=work_order, results=results, scope_additions=scope_additions)

    async def list_pm_work_orders(
        self,
        asset_type: AssetType | None,
        asset_id: str | None,
        params: PageParams,
        status: PmWorkOrderStatus | None = None,
        assigned_to: str | None = None,
    ) -> tuple[list[PmWorkOrderSummary], int]:
        self._ensure_configured(schemas.PM_WORK_ORDER_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.PM_WORK_ORDER_SHEET)
        if asset_type is not None:
            rows = [r for r in rows if r.get("asset_type") == asset_type.value]
        if asset_id is not None:
            rows = [r for r in rows if r.get("asset_id") == asset_id]
        if status is not None:
            rows = [r for r in rows if r.get("status") == status.value]

        assignment_rows = await self._client.read_rows(schemas.PM_WORK_ASSIGNMENT_SHEET)
        history_by_wo_id: dict[str, list[PmAssignmentHistoryEntry]] = {}
        for hrow in assignment_rows:
            wo_id = hrow.get("pm_work_order_id")
            if wo_id:
                history_by_wo_id.setdefault(wo_id, []).append(self._pm_assignment_from_row(hrow))
        active_by_wo_id = {
            row["pm_work_order_id"]: active_primary_and_collaborators(
                history_by_wo_id.get(row["pm_work_order_id"], [])
            )
            for row in rows
        }
        if assigned_to is not None:
            rows = [
                r
                for r in rows
                if assigned_to == active_by_wo_id[r["pm_work_order_id"]][0]
                or assigned_to in active_by_wo_id[r["pm_work_order_id"]][1]
            ]
        rows.sort(key=lambda r: self._parse_datetime(r.get("opened_at", "")) or _epoch(), reverse=True)

        result_rows = await self._client.read_rows(schemas.PM_WORK_RESULT_SHEET)
        result_counts: dict[str, int] = {}
        for rrow in result_rows:
            wo_id = rrow.get("pm_work_order_id")
            if wo_id:
                result_counts[wo_id] = result_counts.get(wo_id, 0) + 1

        summaries = [
            PmWorkOrderSummary(
                pm_work_order_id=row["pm_work_order_id"],
                asset_type=AssetType(row.get("asset_type") or "VEHICLE"),
                asset_id=row.get("asset_id", ""),
                pm_plan_id=row.get("pm_plan_id", ""),
                revision_id=row.get("revision_id", ""),
                status=PmWorkOrderStatus(row.get("status") or "OPEN"),
                opened_at=self._parse_datetime(row.get("opened_at", "")) or _epoch(),
                closed_at=self._parse_datetime(row.get("closed_at", "")),
                result_count=result_counts.get(row["pm_work_order_id"], 0),
                primary_technician=active_by_wo_id[row["pm_work_order_id"]][0],
                collaborators=list(active_by_wo_id[row["pm_work_order_id"]][1]),
            )
            for row in rows
        ]
        start = (params.page - 1) * params.page_size
        page = summaries[start : start + params.page_size]
        return page, len(summaries)

    async def get_last_closed_pm_work_order(
        self, asset_type: AssetType, asset_id: str, pm_plan_id: str
    ) -> PmWorkOrderDetail | None:
        self._ensure_configured(schemas.PM_WORK_ORDER_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.PM_WORK_ORDER_SHEET)
        candidates = [
            row
            for row in rows
            if row.get("asset_type") == asset_type.value
            and row.get("asset_id") == asset_id
            and row.get("pm_plan_id") == pm_plan_id
            and row.get("status") == PmWorkOrderStatus.CLOSED.value
            and self._parse_datetime(row.get("closed_at", "")) is not None
        ]
        if not candidates:
            return None
        latest = max(candidates, key=lambda r: self._parse_datetime(r.get("closed_at", "")))
        return await self.get_pm_work_order(latest["pm_work_order_id"])

    async def close_pm_work_order(
        self,
        pm_work_order_id: str,
        closed_by: str | None,
        note: str | None,
        closed_snapshot_id: str | None = None,
    ) -> PmWorkOrder:
        self._ensure_configured(schemas.PM_WORK_ORDER_SHEET.tab_name)
        found = await self._client.find_row(schemas.PM_WORK_ORDER_SHEET, "pm_work_order_id", pm_work_order_id)
        if found is None:
            raise RepositoryError(f"PM work order '{pm_work_order_id}' was not found")
        row_number, row = found
        now = datetime.now(timezone.utc)
        updated_row = dict(row)
        updated_row.update(
            {
                "status": PmWorkOrderStatus.CLOSED.value,
                "closed_at": now.isoformat(),
                "closed_by": closed_by or "",
                "note": note if note is not None else row.get("note", ""),
                "closed_snapshot_id": closed_snapshot_id or "",
            }
        )
        await self._client.update_row(schemas.PM_WORK_ORDER_SHEET, row_number, updated_row)

        # Live UAT fix: closing a PM work order must end every currently-
        # active assignment (PRIMARY and collaborators), using this same
        # closure timestamp — pm_work_assignment history is authoritative
        # and must never keep reporting someone as still actively
        # assigned to a CLOSED work order. Non-destructive: end each row
        # in place, never delete it (mirrors close_repair's identical fix
        # and assign_pm_work_order's own ending logic, just with no
        # replacement row appended afterward).
        history_rows = await self._client.read_rows(schemas.PM_WORK_ASSIGNMENT_SHEET)
        for index, hrow in enumerate(history_rows):
            if hrow.get("pm_work_order_id") != pm_work_order_id:
                continue
            if not self._parse_bool(hrow.get("active_status", "TRUE")):
                continue
            ended_row = dict(hrow)
            ended_row["active_status"] = "FALSE"
            ended_row["ended_at"] = now.isoformat()
            await self._client.update_row(schemas.PM_WORK_ASSIGNMENT_SHEET, index + 2, ended_row)

        return await self._load_pm_work_order(updated_row)

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
        self._ensure_configured(schemas.PM_WORK_RESULT_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.PM_WORK_RESULT_SHEET)
        pm_work_result_id = self._next_id(rows, "pm_work_result_id", "PMWR")
        performed_at = datetime.now(timezone.utc)
        await self._client.append_row(
            schemas.PM_WORK_RESULT_SHEET,
            {
                "pm_work_result_id": pm_work_result_id,
                "pm_work_order_id": pm_work_order_id,
                "pm_task_id": pm_task_id,
                "revision_id": revision_id,
                "sequence": sequence,
                "task_description": task_description,
                "completed": completed,
                "meter_snapshot_id": meter_snapshot_id or "",
                "remark": remark or "",
                "evidence_attachment_ids": ",".join(evidence_attachment_ids) if evidence_attachment_ids else "",
                "performed_by": performed_by or "",
                "performed_at": performed_at.isoformat(),
            },
        )

        used_part_rows = await self._client.read_rows(schemas.PM_USED_PART_SHEET)
        built_parts: list[PmUsedPart] = []
        for part in used_parts:
            pm_used_part_id = self._next_id(used_part_rows, "pm_used_part_id", "PMUP")
            action = part.get("action")
            new_row = {
                "pm_used_part_id": pm_used_part_id,
                "pm_work_result_id": pm_work_result_id,
                "part_description": part["part_description"],
                "quantity": part.get("quantity") if part.get("quantity") is not None else "",
                "unit": part.get("unit") or "",
                "part_id": part.get("part_id") or "",
                "part_instance_id": part.get("part_instance_id") or "",
                "action": action.value if action else "",
                "recorded_by": performed_by or "",
                "recorded_at": performed_at.isoformat(),
            }
            await self._client.append_row(schemas.PM_USED_PART_SHEET, new_row)
            used_part_rows.append(new_row)
            built_parts.append(
                PmUsedPart(
                    pm_used_part_id=pm_used_part_id,
                    pm_work_result_id=pm_work_result_id,
                    part_description=part["part_description"],
                    quantity=part.get("quantity"),
                    unit=part.get("unit"),
                    part_id=part.get("part_id"),
                    part_instance_id=part.get("part_instance_id"),
                    action=action,
                    recorded_by=performed_by,
                    recorded_at=performed_at,
                )
            )

        return PmWorkResult(
            pm_work_result_id=pm_work_result_id,
            pm_work_order_id=pm_work_order_id,
            pm_task_id=pm_task_id,
            revision_id=revision_id,
            sequence=sequence,
            task_description=task_description,
            completed=completed,
            meter_snapshot_id=meter_snapshot_id,
            remark=remark,
            used_parts=built_parts,
            evidence_attachment_ids=list(evidence_attachment_ids),
            performed_by=performed_by,
            performed_at=performed_at,
        )

    async def find_pm_work_result(self, pm_work_result_id: str) -> PmWorkResult | None:
        self._ensure_configured(schemas.PM_WORK_RESULT_SHEET.tab_name)
        found = await self._client.find_row(
            schemas.PM_WORK_RESULT_SHEET, "pm_work_result_id", pm_work_result_id
        )
        if found is None:
            return None
        used_part_rows = await self._client.read_rows(schemas.PM_USED_PART_SHEET)
        return self._pm_work_result_from_row(found[1], used_part_rows)

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

    async def list_current_counters(self, vehicle_id: str) -> list[CurrentCounterReading]:
        """REV05: authoritative CURRENT counter state, read fresh from
        `current_counter` — never a value carried forward from
        `meter_snapshot` history. `component_id` blank (ODOMETER,
        vehicle-level) maps to `None`, mirroring `MeterReading`. A row
        with an unrecognized/blank `counter_type` is skipped rather than
        raising — a live sheet's stray row must never break every other
        vehicle's snapshot capture."""
        self._ensure_configured(schemas.CURRENT_COUNTER_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.CURRENT_COUNTER_SHEET)
        readings: list[CurrentCounterReading] = []
        for row in rows:
            if row.get("vehicle_id") != vehicle_id:
                continue
            counter_type_raw = row.get("counter_type")
            try:
                counter_type = CounterType(counter_type_raw)
            except ValueError:
                continue
            readings.append(
                CurrentCounterReading(
                    component_id=row.get("component_id") or None,
                    counter_type=counter_type,
                    value=self._parse_float(row.get("value")),
                )
            )
        return readings

    async def get_current_location(self, vehicle_id: str) -> CurrentLocation | None:
        """REV05: authoritative CURRENT location state, read fresh from
        `latest_location` — never a value carried forward from
        `location_snapshot` history. Only the columns the live sheet
        actually declares (no `altitude_m`/`accuracy_m`/`source`/
        `device_id` here — `latest_location` does not carry them)."""
        self._ensure_configured(schemas.LATEST_LOCATION_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.LATEST_LOCATION_SHEET)
        for row in rows:
            if row.get("vehicle_id") != vehicle_id:
                continue
            return CurrentLocation(
                vehicle_id=vehicle_id,
                latitude=self._parse_float(row.get("latitude")),
                longitude=self._parse_float(row.get("longitude")),
                gps_time=self._parse_datetime(row.get("gps_time", "")),
                received_at=self._parse_datetime(row.get("received_at", "")),
            )
        return None

    # ---- Repair (Core Demo Fixes Delta REV06 section 9/10 — P0: real I/O) ----
    #
    # REV05 left every one of these stubbed, which silently broke the
    # approved `Repair Request -> Maintenance review -> RPR` conversion
    # path in google_sheets mode (RepairRequestService.convert calls
    # RepairService.create_repair, which calls this repository's
    # `create_repair`). REV06 gives the Core Demo subset the conversion
    # path and its resulting UI/API actually exercise real Sheets I/O:
    # create/get/list/assign/action/part/close — using the exact live
    # `repair_order`/`repair_action`/`repair_part`/`repair_assignment`
    # headers already declared in `app.repositories.google_sheets.schemas`
    # (no schema invention needed — every field REV06 needs already has a
    # column). Concurrency/idempotency follows the same documented,
    # non-transactional pattern as `create_repair_request`/
    # `mark_repair_request_converted` above — see
    # `GoogleSheetsClient`'s module docstring section 11F and
    # `RepairRequestService.convert`'s own idempotency re-check, which is
    # what actually prevents a duplicate RPR on a sequential retry; this
    # repository never pretends to add real database transaction
    # semantics on top of that.

    def _repair_from_row(self, row: dict) -> Repair:
        collaborators_raw = str(row.get("collaborators", ""))
        return Repair(
            repair_id=row["repair_id"],
            asset_type=AssetType(row.get("asset_type") or "VEHICLE"),
            asset_id=row.get("asset_id", ""),
            source_type=RepairSourceType(row.get("source_type") or "MANUAL"),
            source_id=row.get("source_id") or None,
            category=row.get("category") or None,
            symptom=row.get("symptom") or None,
            meter_snapshot_id=row.get("meter_snapshot_id") or None,
            status=RepairStatus(row.get("status") or "OPEN"),
            opened_at=self._parse_datetime(row.get("opened_at", "")) or _epoch(),
            opened_by=row.get("opened_by") or None,
            closed_at=self._parse_datetime(row.get("closed_at", "")),
            closed_by=row.get("closed_by") or None,
            close_note=row.get("close_note") or None,
            closed_snapshot_id=row.get("closed_snapshot_id") or None,
            primary_technician=row.get("primary_technician") or None,
            collaborators=[v.strip() for v in collaborators_raw.split(",") if v.strip()],
        )

    def _repair_action_from_row(self, row: dict) -> RepairAction:
        attachment_ids_raw = str(row.get("attachment_ids", ""))
        return RepairAction(
            repair_action_id=row["repair_action_id"],
            repair_id=row.get("repair_id", ""),
            action_text=row.get("action_text", ""),
            actor=row.get("actor") or None,
            created_at=self._parse_datetime(row.get("created_at", "")) or _epoch(),
            attachment_ids=[v.strip() for v in attachment_ids_raw.split(",") if v.strip()],
        )

    def _repair_part_from_row(self, row: dict) -> RepairPart:
        return RepairPart(
            repair_part_id=row["repair_part_id"],
            repair_id=row.get("repair_id", ""),
            part_description=row.get("part_description", ""),
            quantity=self._parse_float(row.get("quantity")),
            unit=row.get("unit") or None,
            part_id=row.get("part_id") or None,
            part_instance_id=row.get("part_instance_id") or None,
            action=PartActionType(row["action"]) if row.get("action") else None,
            recorded_by=row.get("recorded_by") or None,
            recorded_at=self._parse_datetime(row.get("recorded_at", "")) or _epoch(),
        )

    def _repair_assignment_from_row(self, row: dict) -> RepairAssignmentHistoryEntry:
        return RepairAssignmentHistoryEntry(
            repair_assignment_id=row["repair_assignment_id"],
            repair_id=row.get("repair_id", ""),
            user_id=row.get("user_id", ""),
            assignment_role=AssignmentRole(row.get("assignment_role") or "PRIMARY"),
            assigned_at=self._parse_datetime(row.get("assigned_at", "")) or _epoch(),
            assigned_by_user_id=row.get("assigned_by_user_id") or None,
            ended_at=self._parse_datetime(row.get("ended_at", "")),
            active_status=self._parse_bool(row.get("active_status", "TRUE")),
            note=row.get("note_th") or None,
        )

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
        self._ensure_configured(schemas.REPAIR_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.REPAIR_SHEET)
        repair_id = self._next_id(rows, "repair_id", "RPR")
        opened_at = datetime.now(timezone.utc)
        collaborators = list(collaborators) if collaborators else []
        await self._client.append_row(
            schemas.REPAIR_SHEET,
            {
                "repair_id": repair_id,
                "asset_type": asset_type.value,
                "asset_id": asset_id,
                "source_type": source_type.value,
                "source_id": source_id or "",
                "category": category or "",
                "symptom": symptom or "",
                "meter_snapshot_id": meter_snapshot_id or "",
                "closed_snapshot_id": "",
                "status": RepairStatus.OPEN.value,
                "opened_at": opened_at.isoformat(),
                "opened_by": opened_by or "",
                "closed_at": "",
                "closed_by": "",
                "close_note": "",
                "primary_technician": primary_technician or "",
                "collaborators": ",".join(collaborators),
            },
        )
        if primary_technician or collaborators:
            # Keep repair_assignment (the authoritative history) in sync
            # with the header row created above, exactly like a separate
            # `assign_repair` call made right after `POST /repairs`.
            await self.assign_repair(
                repair_id=repair_id,
                primary_technician=primary_technician,
                collaborators=collaborators,
                assigned_by=opened_by,
            )
        return Repair(
            repair_id=repair_id,
            asset_type=asset_type,
            asset_id=asset_id,
            source_type=source_type,
            source_id=source_id,
            category=category,
            symptom=symptom,
            meter_snapshot_id=meter_snapshot_id,
            status=RepairStatus.OPEN,
            opened_at=opened_at,
            opened_by=opened_by,
            primary_technician=primary_technician,
            collaborators=collaborators,
        )

    async def get_repair(self, repair_id: str) -> RepairDetail | None:
        self._ensure_configured(schemas.REPAIR_SHEET.tab_name)
        found = await self._client.find_row(schemas.REPAIR_SHEET, "repair_id", repair_id)
        if found is None:
            return None
        _, row = found
        repair = self._repair_from_row(row)
        action_rows = await self._client.read_rows(schemas.REPAIR_ACTION_SHEET)
        actions = [
            self._repair_action_from_row(r)
            for r in action_rows
            if r.get("repair_id") == repair_id
        ]
        actions.sort(key=lambda a: a.created_at)
        part_rows = await self._client.read_rows(schemas.REPAIR_PART_SHEET)
        parts = [
            self._repair_part_from_row(r) for r in part_rows if r.get("repair_id") == repair_id
        ]
        parts.sort(key=lambda p: p.recorded_at)
        return RepairDetail(repair=repair, actions=actions, parts=parts)

    async def find_repairs_by_source(
        self, source_type: RepairSourceType, source_id: str
    ) -> list[Repair]:
        self._ensure_configured(schemas.REPAIR_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.REPAIR_SHEET)
        return [
            self._repair_from_row(row)
            for row in rows
            if row.get("source_type") == source_type.value and row.get("source_id") == source_id
        ]

    async def list_repairs(
        self,
        asset_type: AssetType | None,
        asset_id: str | None,
        status: RepairStatus | None,
        params: PageParams,
        assigned_to: str | None = None,
        unassigned_only: bool = False,
    ) -> tuple[list[RepairSummary], int]:
        self._ensure_configured(schemas.REPAIR_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.REPAIR_SHEET)
        repairs = [self._repair_from_row(r) for r in rows]
        if asset_type is not None:
            repairs = [r for r in repairs if r.asset_type == asset_type]
        if asset_id is not None:
            repairs = [r for r in repairs if r.asset_id == asset_id]
        if status is not None:
            repairs = [r for r in repairs if r.status == status]
        if assigned_to is not None or unassigned_only:
            # REV06.2 (independent-audit MEDIUM fix): derive "who is
            # currently assigned" from active `repair_assignment` history —
            # never the denormalized `primary_technician`/`collaborators`
            # columns, which can go stale between the two separate writes
            # `assign_repair` makes (Google Sheets has no transactions).
            # One extra full-sheet read here (not one per repair) keeps
            # this at the same cost class as the `action_rows` fetch just
            # below, rather than an N+1 per-repair history fetch.
            assignment_rows = await self._client.read_rows(schemas.REPAIR_ASSIGNMENT_SHEET)
            history_by_repair_id: dict[str, list[RepairAssignmentHistoryEntry]] = {}
            for hrow in assignment_rows:
                rid = hrow.get("repair_id")
                if rid:
                    history_by_repair_id.setdefault(rid, []).append(
                        self._repair_assignment_from_row(hrow)
                    )
            active_by_repair_id = {
                r.repair_id: active_primary_and_collaborators(
                    history_by_repair_id.get(r.repair_id, [])
                )
                for r in repairs
            }
            if assigned_to is not None:
                repairs = [
                    r
                    for r in repairs
                    if assigned_to == active_by_repair_id[r.repair_id][0]
                    or assigned_to in active_by_repair_id[r.repair_id][1]
                ]
            if unassigned_only:
                repairs = [r for r in repairs if active_by_repair_id[r.repair_id][0] is None]
        repairs.sort(key=lambda r: r.opened_at, reverse=True)

        action_rows = await self._client.read_rows(schemas.REPAIR_ACTION_SHEET)
        action_counts: dict[str, int] = {}
        for arow in action_rows:
            rid = arow.get("repair_id")
            if rid:
                action_counts[rid] = action_counts.get(rid, 0) + 1

        summaries = [
            RepairSummary(
                repair_id=r.repair_id,
                asset_type=r.asset_type,
                asset_id=r.asset_id,
                source_type=r.source_type,
                source_id=r.source_id,
                status=r.status,
                opened_at=r.opened_at,
                closed_at=r.closed_at,
                action_count=action_counts.get(r.repair_id, 0),
                primary_technician=r.primary_technician,
                collaborators=list(r.collaborators),
                symptom=r.symptom,
            )
            for r in repairs
        ]
        start = (params.page - 1) * params.page_size
        page = summaries[start : start + params.page_size]
        return page, len(summaries)

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
        self._ensure_configured(schemas.REPAIR_ASSIGNMENT_SHEET.tab_name)
        found = await self._client.find_row(schemas.REPAIR_SHEET, "repair_id", repair_id)
        if found is None:
            raise RepositoryError(f"Repair '{repair_id}' was not found")
        row_number, row = found
        now = datetime.now(timezone.utc)
        collaborators = list(collaborators) if collaborators else []

        new_assignments: list[tuple[str, AssignmentRole]] = []
        if primary_technician:
            new_assignments.append((primary_technician, AssignmentRole.PRIMARY))
        for collaborator in collaborators:
            new_assignments.append((collaborator, AssignmentRole.COLLABORATOR))
        new_keys = set(new_assignments)

        history_rows = await self._client.read_rows(schemas.REPAIR_ASSIGNMENT_SHEET)
        for index, hrow in enumerate(history_rows):
            if hrow.get("repair_id") != repair_id:
                continue
            if not self._parse_bool(hrow.get("active_status", "TRUE")):
                continue
            key = (hrow.get("user_id", ""), AssignmentRole(hrow.get("assignment_role") or "PRIMARY"))
            if key in new_keys:
                continue
            # Non-destructive: end this row in place, never delete it.
            ended_row = dict(hrow)
            ended_row["active_status"] = "FALSE"
            ended_row["ended_at"] = now.isoformat()
            await self._client.update_row(schemas.REPAIR_ASSIGNMENT_SHEET, index + 2, ended_row)
            history_rows[index] = ended_row

        already_active = {
            (hrow.get("user_id", ""), AssignmentRole(hrow.get("assignment_role") or "PRIMARY"))
            for hrow in history_rows
            if hrow.get("repair_id") == repair_id
            and self._parse_bool(hrow.get("active_status", "TRUE"))
        }
        for user_id, role in new_assignments:
            if (user_id, role) in already_active:
                continue
            assignment_id = self._next_id(history_rows, "repair_assignment_id", "RASG")
            new_row = {
                "repair_assignment_id": assignment_id,
                "repair_id": repair_id,
                "user_id": user_id,
                "assignment_role": role.value,
                "assigned_at": now.isoformat(),
                "assigned_by_user_id": assigned_by or "",
                "ended_at": "",
                "active_status": "TRUE",
                "note_th": "",
            }
            await self._client.append_row(schemas.REPAIR_ASSIGNMENT_SHEET, new_row)
            history_rows.append(new_row)

        updated_row = dict(row)
        updated_row.update(
            {
                "primary_technician": primary_technician or "",
                "collaborators": ",".join(collaborators),
            }
        )
        await self._client.update_row(schemas.REPAIR_SHEET, row_number, updated_row)
        return self._repair_from_row(updated_row)

    async def list_repair_assignment_history(
        self, repair_id: str
    ) -> list[RepairAssignmentHistoryEntry]:
        self._ensure_configured(schemas.REPAIR_ASSIGNMENT_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.REPAIR_ASSIGNMENT_SHEET)
        entries = [
            self._repair_assignment_from_row(r) for r in rows if r.get("repair_id") == repair_id
        ]
        entries.sort(key=lambda e: e.assigned_at)
        return entries

    # ---- Repair Request (Core Demo Fixes Delta REV05 section 3) ----

    def _repair_request_from_row(self, row: dict) -> RepairRequest:
        meter_snapshot_id, note_th = decode_meter_snapshot_link(row.get("note_th") or None)
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
            # `note_th` here is still whatever `RepairRequestService`
            # originally built (plain text, or still `[[SRC:...]]`-encoded)
            # — only this repository's own meter-snapshot marker layer has
            # been stripped off; `RepairRequestService._with_decoded_provenance`
            # decodes the rest, unaware this layer ever existed.
            note_th=note_th,
            # `meter_snapshot_id` is domain-only — the live `repair_request`
            # sheet has no reserved column for it (see
            # app.domain.repair_request.RepairRequest.meter_snapshot_id) —
            # persisted/recovered via the protected note_th metadata
            # envelope instead (see `encode_meter_snapshot_link`/
            # `decode_meter_snapshot_link`).
            meter_snapshot_id=meter_snapshot_id,
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
        persisted_note_th = encode_meter_snapshot_link(note_th, meter_snapshot_id)
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
                "note_th": persisted_note_th or "",
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

    async def list_repair_requests_by_reporter(
        self, reported_by_user_id: str, params: PageParams
    ) -> tuple[list[RepairRequest], int]:
        self._ensure_configured(schemas.REPAIR_REQUEST_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.REPAIR_REQUEST_SHEET)
        mine = [
            self._repair_request_from_row(row)
            for row in rows
            if (row.get("reported_by_user_id") or None) == reported_by_user_id
        ]
        mine.sort(key=lambda r: r.reported_at, reverse=True)
        start = (params.page - 1) * params.page_size
        page = mine[start : start + params.page_size]
        return page, len(mine)

    async def list_repair_requests_by_source(
        self, source_type: str, source_id: str
    ) -> list[RepairRequest]:
        self._ensure_configured(schemas.REPAIR_REQUEST_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.REPAIR_REQUEST_SHEET)
        matches = []
        for row in rows:
            # Strip this repository's own meter-snapshot marker layer
            # first (it always sits outermost — see
            # `encode_meter_snapshot_link`) before decoding source
            # provenance from what remains, exactly like
            # `_repair_request_from_row` does.
            _, note_after_snapshot = decode_meter_snapshot_link(row.get("note_th") or None)
            decoded_type, decoded_id, _ = decode_provenance_note(note_after_snapshot)
            if decoded_type == source_type and decoded_id == source_id:
                matches.append(self._repair_request_from_row(row))
        matches.sort(key=lambda r: r.reported_at)
        return matches

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
        self._ensure_configured(schemas.REPAIR_ACTION_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.REPAIR_ACTION_SHEET)
        repair_action_id = self._next_id(rows, "repair_action_id", "RPRA")
        await self._client.append_row(
            schemas.REPAIR_ACTION_SHEET,
            {
                "repair_action_id": repair_action_id,
                "repair_id": repair_id,
                "action_text": action_text,
                "actor": actor or "",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "attachment_ids": ",".join(attachment_ids) if attachment_ids else "",
            },
        )

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
        self._ensure_configured(schemas.REPAIR_PART_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.REPAIR_PART_SHEET)
        repair_part_id = self._next_id(rows, "repair_part_id", "RPRP")
        await self._client.append_row(
            schemas.REPAIR_PART_SHEET,
            {
                "repair_part_id": repair_part_id,
                "repair_id": repair_id,
                "part_description": part_description,
                "quantity": quantity if quantity is not None else "",
                "unit": unit or "",
                "part_id": part_id or "",
                "part_instance_id": part_instance_id or "",
                "action": action.value if action else "",
                "recorded_by": recorded_by or "",
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    async def close_repair(
        self,
        repair_id: str,
        closed_by: str | None,
        close_note: str | None,
        closed_snapshot_id: str | None = None,
    ) -> Repair:
        self._ensure_configured(schemas.REPAIR_SHEET.tab_name)
        found = await self._client.find_row(schemas.REPAIR_SHEET, "repair_id", repair_id)
        if found is None:
            raise RepositoryError(f"Repair '{repair_id}' was not found")
        row_number, row = found
        now = datetime.now(timezone.utc)
        updated_row = dict(row)
        updated_row.update(
            {
                "status": RepairStatus.CLOSED.value,
                "closed_at": now.isoformat(),
                "closed_by": closed_by or "",
                "close_note": close_note or "",
                "closed_snapshot_id": closed_snapshot_id or "",
            }
        )
        await self._client.update_row(schemas.REPAIR_SHEET, row_number, updated_row)

        # Live UAT fix: closing a repair must end every currently-active
        # assignment (PRIMARY and collaborators), using this same closure
        # timestamp — repair_assignment history is authoritative and must
        # never keep reporting someone as still actively assigned to a
        # CLOSED repair. Non-destructive: end each row in place, never
        # delete it (mirrors assign_repair's own ending logic above, just
        # with no replacement row appended afterward). Google Sheets has
        # no real transaction: if this second write fails partway after
        # the status update above already committed, the repair is
        # CLOSED with some assignment rows still showing active until a
        # retry/fix-up — the same non-transactional risk class
        # `assign_repair`'s own two-write pattern (history rows, then the
        # repair_order sync) already accepts elsewhere in this repository.
        history_rows = await self._client.read_rows(schemas.REPAIR_ASSIGNMENT_SHEET)
        for index, hrow in enumerate(history_rows):
            if hrow.get("repair_id") != repair_id:
                continue
            if not self._parse_bool(hrow.get("active_status", "TRUE")):
                continue
            ended_row = dict(hrow)
            ended_row["active_status"] = "FALSE"
            ended_row["ended_at"] = now.isoformat()
            await self._client.update_row(schemas.REPAIR_ASSIGNMENT_SHEET, index + 2, ended_row)

        return self._repair_from_row(updated_row)

    # ---- Part Master / Part Set (Phase 5) ----

    def _part_master_from_row(self, row: dict) -> PartMaster:
        metadata_raw = row.get("metadata") or ""
        try:
            metadata = json.loads(metadata_raw) if metadata_raw else {}
        except ValueError:
            metadata = {}
        return PartMaster(
            part_id=row["part_id"],
            part_code=row.get("part_code", ""),
            name=row.get("name", ""),
            specification=row.get("specification") or None,
            manufacturer=row.get("manufacturer") or None,
            part_number=row.get("part_number") or None,
            tracking_mode=TrackingMode(row.get("tracking_mode") or "NONE"),
            category=row.get("category") or None,
            is_active=self._parse_bool(row.get("is_active", "TRUE")),
            metadata=metadata,
            created_at=self._parse_datetime(row.get("created_at", "")) or _epoch(),
            updated_at=self._parse_datetime(row.get("updated_at", "")) or _epoch(),
        )

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
        self._ensure_configured(schemas.PART_MASTER_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.PART_MASTER_SHEET)
        part_id = self._next_id(rows, "part_id", "PART")
        now = datetime.now(timezone.utc)
        await self._client.append_row(
            schemas.PART_MASTER_SHEET,
            {
                "part_id": part_id,
                "part_code": part_code,
                "name": name,
                "specification": specification or "",
                "manufacturer": manufacturer or "",
                "part_number": part_number or "",
                "tracking_mode": tracking_mode.value,
                "category": category or "",
                "is_active": True,
                "metadata": json.dumps(metadata) if metadata else "",
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            },
        )
        return PartMaster(
            part_id=part_id,
            part_code=part_code,
            name=name,
            specification=specification,
            manufacturer=manufacturer,
            part_number=part_number,
            tracking_mode=tracking_mode,
            category=category,
            is_active=True,
            metadata=dict(metadata),
            created_at=now,
            updated_at=now,
        )

    async def get_part_master(self, part_id: str) -> PartMaster | None:
        self._ensure_configured(schemas.PART_MASTER_SHEET.tab_name)
        found = await self._client.find_row(schemas.PART_MASTER_SHEET, "part_id", part_id)
        return self._part_master_from_row(found[1]) if found else None

    async def list_part_masters(
        self, q: str | None, tracking_mode: TrackingMode | None, params: PageParams
    ) -> tuple[list[PartMaster], int]:
        self._ensure_configured(schemas.PART_MASTER_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.PART_MASTER_SHEET)
        items = [self._part_master_from_row(row) for row in rows]
        if q:
            needle = q.strip().lower()
            items = [
                p
                for p in items
                if needle in p.name.lower()
                or needle in p.part_code.lower()
                or (p.specification and needle in p.specification.lower())
            ]
        if tracking_mode is not None:
            items = [p for p in items if p.tracking_mode == tracking_mode]
        items.sort(key=lambda p: p.part_id)
        start = (params.page - 1) * params.page_size
        page = items[start : start + params.page_size]
        return page, len(items)

    def _part_set_from_row(self, row: dict) -> PartSet:
        return PartSet(
            part_set_id=row["part_set_id"],
            set_code=row.get("set_code", ""),
            name=row.get("name", ""),
            created_at=self._parse_datetime(row.get("created_at", "")) or _epoch(),
            updated_at=self._parse_datetime(row.get("updated_at", "")) or _epoch(),
        )

    async def create_part_set(self, set_code: str, name: str) -> PartSet:
        self._ensure_configured(schemas.PART_SET_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.PART_SET_SHEET)
        part_set_id = self._next_id(rows, "part_set_id", "PSET")
        now = datetime.now(timezone.utc)
        await self._client.append_row(
            schemas.PART_SET_SHEET,
            {
                "part_set_id": part_set_id,
                "set_code": set_code,
                "name": name,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            },
        )
        return PartSet(part_set_id=part_set_id, set_code=set_code, name=name, created_at=now, updated_at=now)

    async def get_part_set(self, part_set_id: str) -> PartSet | None:
        self._ensure_configured(schemas.PART_SET_SHEET.tab_name)
        found = await self._client.find_row(schemas.PART_SET_SHEET, "part_set_id", part_set_id)
        return self._part_set_from_row(found[1]) if found else None

    def _part_set_item_from_row(self, row: dict) -> PartSetItem:
        return PartSetItem(
            part_set_item_id=row["part_set_item_id"],
            revision_id=row.get("revision_id", ""),
            part_id=row.get("part_id", ""),
            requirement=PartSetItemRequirement(row.get("requirement") or "REQUIRED"),
            quantity=self._parse_float(row.get("quantity")),
            unit=row.get("unit") or None,
            note=row.get("note") or None,
        )

    async def _part_set_revision_detail(
        self, part_set: PartSet, revision_row: dict
    ) -> PartSetRevisionDetail:
        revision = PartSetRevision(
            revision_id=revision_row["revision_id"],
            part_set_id=revision_row.get("part_set_id", ""),
            revision_number=int(self._parse_float(revision_row.get("revision_number")) or 0),
            effective_date=self._parse_date(revision_row.get("effective_date", "")) or _epoch().date(),
            created_at=self._parse_datetime(revision_row.get("created_at", "")) or _epoch(),
        )
        item_rows = await self._client.read_rows(schemas.PART_SET_ITEM_SHEET)
        items = [
            self._part_set_item_from_row(row)
            for row in item_rows
            if row.get("revision_id") == revision.revision_id
        ]
        items.sort(key=lambda i: i.part_set_item_id)
        return PartSetRevisionDetail(part_set=part_set, revision=revision, items=items)

    async def create_part_set_revision(
        self, part_set_id: str, effective_date, items: list[dict]
    ) -> PartSetRevisionDetail:
        self._ensure_configured(schemas.PART_SET_REVISION_SHEET.tab_name)
        part_set = await self.get_part_set(part_set_id)
        if part_set is None:
            raise RepositoryError(f"Part set '{part_set_id}' was not found")
        revision_rows = await self._client.read_rows(schemas.PART_SET_REVISION_SHEET)
        revision_id = self._next_id(revision_rows, "revision_id", "PSREV")
        revision_number = (
            sum(1 for row in revision_rows if row.get("part_set_id") == part_set_id) + 1
        )
        now = datetime.now(timezone.utc)
        await self._client.append_row(
            schemas.PART_SET_REVISION_SHEET,
            {
                "revision_id": revision_id,
                "part_set_id": part_set_id,
                "revision_number": revision_number,
                "effective_date": effective_date.isoformat(),
                "created_at": now.isoformat(),
            },
        )

        item_rows = await self._client.read_rows(schemas.PART_SET_ITEM_SHEET)
        built_items: list[PartSetItem] = []
        for item in items:
            part_set_item_id = self._next_id(item_rows, "part_set_item_id", "PSITEM")
            requirement: PartSetItemRequirement = item["requirement"]
            new_row = {
                "part_set_item_id": part_set_item_id,
                "revision_id": revision_id,
                "part_id": item["part_id"],
                "requirement": requirement.value,
                "quantity": item.get("quantity") if item.get("quantity") is not None else "",
                "unit": item.get("unit") or "",
                "note": item.get("note") or "",
            }
            await self._client.append_row(schemas.PART_SET_ITEM_SHEET, new_row)
            item_rows.append(new_row)
            built_items.append(
                PartSetItem(
                    part_set_item_id=part_set_item_id,
                    revision_id=revision_id,
                    part_id=item["part_id"],
                    requirement=requirement,
                    quantity=item.get("quantity"),
                    unit=item.get("unit"),
                    note=item.get("note"),
                )
            )

        revision = PartSetRevision(
            revision_id=revision_id,
            part_set_id=part_set_id,
            revision_number=revision_number,
            effective_date=effective_date,
            created_at=now,
        )
        return PartSetRevisionDetail(part_set=part_set, revision=revision, items=built_items)

    async def get_active_part_set_revision(self, part_set_id: str) -> PartSetRevisionDetail | None:
        self._ensure_configured(schemas.PART_SET_REVISION_SHEET.tab_name)
        part_set = await self.get_part_set(part_set_id)
        if part_set is None:
            return None
        revision_rows = await self._client.read_rows(schemas.PART_SET_REVISION_SHEET)
        today = datetime.now(timezone.utc).date()
        candidates = [
            row
            for row in revision_rows
            if row.get("part_set_id") == part_set_id
            and self._parse_date(row.get("effective_date", "")) is not None
            and self._parse_date(row.get("effective_date", "")) <= today
        ]
        if not candidates:
            return None
        latest = max(
            candidates,
            key=lambda row: (
                self._parse_date(row.get("effective_date", "")),
                int(self._parse_float(row.get("revision_number")) or 0),
            ),
        )
        return await self._part_set_revision_detail(part_set, latest)

    async def get_part_set_revision(
        self, part_set_id: str, revision_id: str
    ) -> PartSetRevisionDetail | None:
        self._ensure_configured(schemas.PART_SET_REVISION_SHEET.tab_name)
        found = await self._client.find_row(schemas.PART_SET_REVISION_SHEET, "revision_id", revision_id)
        if found is None or found[1].get("part_set_id") != part_set_id:
            return None
        part_set = await self.get_part_set(part_set_id)
        if part_set is None:
            return None
        return await self._part_set_revision_detail(part_set, found[1])

    # ---- Part Instance / lifecycle / installation segment (Phase 5) ----

    def _prior_usage_from_row(self, row: dict) -> PriorUsage:
        return PriorUsage(
            quality=PriorUsageQuality(row.get("prior_usage_quality") or "UNKNOWN"),
            value=self._parse_float(row.get("prior_usage_value")),
            note=row.get("prior_usage_note") or None,
        )

    def _part_lifecycle_from_row(self, row: dict) -> PartLifecycle:
        return PartLifecycle(
            lifecycle_id=row["lifecycle_id"],
            part_instance_id=row.get("part_instance_id", ""),
            cycle_number=int(self._parse_float(row.get("cycle_number")) or 0),
            start_reason=LifecycleStartReason(row.get("start_reason") or "ENROLLMENT"),
            started_at=self._parse_datetime(row.get("started_at", "")) or _epoch(),
            started_by=row.get("started_by") or None,
            started_note=row.get("started_note") or None,
            ended_at=self._parse_datetime(row.get("ended_at", "")),
        )

    def _installation_segment_from_row(self, row: dict) -> InstallationSegment:
        return InstallationSegment(
            segment_id=row["segment_id"],
            part_instance_id=row.get("part_instance_id", ""),
            lifecycle_id=row.get("lifecycle_id", ""),
            asset_type=AssetType(row.get("asset_type") or "VEHICLE"),
            asset_id=row.get("asset_id", ""),
            position_code=row.get("position_code") or None,
            status=InstallationSegmentStatus(row.get("status") or "ACTIVE"),
            installed_at=self._parse_datetime(row.get("installed_at", "")) or _epoch(),
            installed_by=row.get("installed_by") or None,
            baseline_meter_snapshot_id=row.get("baseline_meter_snapshot_id") or None,
            install_note=row.get("install_note") or None,
            removed_at=self._parse_datetime(row.get("removed_at", "")),
            removed_by=row.get("removed_by") or None,
            removal_meter_snapshot_id=row.get("removal_meter_snapshot_id") or None,
            removal_reason=row.get("removal_reason") or None,
        )

    def _part_instance_from_row(self, row: dict) -> PartInstance:
        return PartInstance(
            part_instance_id=row["part_instance_id"],
            part_id=row.get("part_id", ""),
            serial_number=row.get("serial_number") or None,
            status=PartInstanceStatus(row.get("status") or "READY_FOR_INSTALL"),
            prior_usage=self._prior_usage_from_row(row),
            current_lifecycle_id=row.get("current_lifecycle_id", ""),
            note=row.get("note") or None,
            created_at=self._parse_datetime(row.get("created_at", "")) or _epoch(),
            updated_at=self._parse_datetime(row.get("updated_at", "")) or _epoch(),
        )

    async def _part_instance_detail(self, instance_row: dict) -> PartInstanceDetail:
        instance = self._part_instance_from_row(instance_row)
        lifecycle_rows = await self._client.read_rows(schemas.PART_LIFECYCLE_SHEET)
        lifecycles = [
            self._part_lifecycle_from_row(r)
            for r in lifecycle_rows
            if r.get("part_instance_id") == instance.part_instance_id
        ]
        lifecycles.sort(key=lambda lc: lc.cycle_number)
        segment_rows = await self._client.read_rows(schemas.INSTALLATION_SEGMENT_SHEET)
        segments = [
            self._installation_segment_from_row(r)
            for r in segment_rows
            if r.get("part_instance_id") == instance.part_instance_id
        ]
        segments.sort(key=lambda s: s.installed_at)
        return PartInstanceDetail(instance=instance, lifecycles=lifecycles, segments=segments)

    async def create_part_instance(
        self,
        part_id: str,
        serial_number: str | None,
        prior_usage: PriorUsage,
        note: str | None,
        created_by: str | None,
    ) -> PartInstanceDetail:
        self._ensure_configured(schemas.PART_INSTANCE_SHEET.tab_name)
        instance_rows = await self._client.read_rows(schemas.PART_INSTANCE_SHEET)
        instance_id = self._next_id(instance_rows, "part_instance_id", "PINST")
        now = datetime.now(timezone.utc)

        lifecycle_rows = await self._client.read_rows(schemas.PART_LIFECYCLE_SHEET)
        lifecycle_id = self._next_id(lifecycle_rows, "lifecycle_id", "PLC")
        await self._client.append_row(
            schemas.PART_LIFECYCLE_SHEET,
            {
                "lifecycle_id": lifecycle_id,
                "part_instance_id": instance_id,
                "cycle_number": 1,
                "start_reason": LifecycleStartReason.ENROLLMENT.value,
                "started_at": now.isoformat(),
                "started_by": created_by or "",
                "started_note": "",
                "ended_at": "",
            },
        )
        await self._client.append_row(
            schemas.PART_INSTANCE_SHEET,
            {
                "part_instance_id": instance_id,
                "part_id": part_id,
                "serial_number": serial_number or "",
                "status": PartInstanceStatus.READY_FOR_INSTALL.value,
                "prior_usage_quality": prior_usage.quality.value,
                "prior_usage_value": prior_usage.value if prior_usage.value is not None else "",
                "prior_usage_note": prior_usage.note or "",
                "current_lifecycle_id": lifecycle_id,
                "note": note or "",
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            },
        )

        instance = PartInstance(
            part_instance_id=instance_id,
            part_id=part_id,
            serial_number=serial_number,
            status=PartInstanceStatus.READY_FOR_INSTALL,
            prior_usage=prior_usage.model_copy(deep=True),
            current_lifecycle_id=lifecycle_id,
            note=note,
            created_at=now,
            updated_at=now,
        )
        lifecycle = PartLifecycle(
            lifecycle_id=lifecycle_id,
            part_instance_id=instance_id,
            cycle_number=1,
            start_reason=LifecycleStartReason.ENROLLMENT,
            started_at=now,
            started_by=created_by,
            started_note=None,
            ended_at=None,
        )
        return PartInstanceDetail(instance=instance, lifecycles=[lifecycle], segments=[])

    async def get_part_instance(self, part_instance_id: str) -> PartInstanceDetail | None:
        self._ensure_configured(schemas.PART_INSTANCE_SHEET.tab_name)
        found = await self._client.find_row(
            schemas.PART_INSTANCE_SHEET, "part_instance_id", part_instance_id
        )
        if found is None:
            return None
        return await self._part_instance_detail(found[1])

    async def list_part_instances(
        self, part_id: str | None, status: PartInstanceStatus | None, params: PageParams
    ) -> tuple[list[PartInstanceDetail], int]:
        self._ensure_configured(schemas.PART_INSTANCE_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.PART_INSTANCE_SHEET)
        if part_id is not None:
            rows = [r for r in rows if r.get("part_id") == part_id]
        if status is not None:
            rows = [r for r in rows if r.get("status") == status.value]
        rows.sort(key=lambda r: r["part_instance_id"])
        start = (params.page - 1) * params.page_size
        page_rows = rows[start : start + params.page_size]
        details = [await self._part_instance_detail(r) for r in page_rows]
        return details, len(rows)

    async def update_part_instance_status(
        self, part_instance_id: str, status: PartInstanceStatus
    ) -> None:
        self._ensure_configured(schemas.PART_INSTANCE_SHEET.tab_name)
        found = await self._client.find_row(
            schemas.PART_INSTANCE_SHEET, "part_instance_id", part_instance_id
        )
        if found is None:
            raise RepositoryError(f"Part instance '{part_instance_id}' was not found")
        row_number, row = found
        updated_row = dict(row)
        updated_row["status"] = status.value
        updated_row["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self._client.update_row(schemas.PART_INSTANCE_SHEET, row_number, updated_row)

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
        self._ensure_configured(schemas.INSTALLATION_SEGMENT_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.INSTALLATION_SEGMENT_SHEET)
        segment_id = self._next_id(rows, "segment_id", "SEG")
        installed_at = datetime.now(timezone.utc)
        await self._client.append_row(
            schemas.INSTALLATION_SEGMENT_SHEET,
            {
                "segment_id": segment_id,
                "part_instance_id": part_instance_id,
                "lifecycle_id": lifecycle_id,
                "asset_type": asset_type.value,
                "asset_id": asset_id,
                "position_code": position_code or "",
                "status": InstallationSegmentStatus.ACTIVE.value,
                "installed_at": installed_at.isoformat(),
                "installed_by": installed_by or "",
                "baseline_meter_snapshot_id": baseline_meter_snapshot_id or "",
                "install_note": install_note or "",
                "removed_at": "",
                "removed_by": "",
                "removal_meter_snapshot_id": "",
                "removal_reason": "",
            },
        )
        return InstallationSegment(
            segment_id=segment_id,
            part_instance_id=part_instance_id,
            lifecycle_id=lifecycle_id,
            asset_type=asset_type,
            asset_id=asset_id,
            position_code=position_code,
            status=InstallationSegmentStatus.ACTIVE,
            installed_at=installed_at,
            installed_by=installed_by,
            baseline_meter_snapshot_id=baseline_meter_snapshot_id,
            install_note=install_note,
        )

    async def close_installation_segment(
        self,
        segment_id: str,
        removed_by: str | None,
        removal_meter_snapshot_id: str | None,
        removal_reason: str | None,
    ) -> InstallationSegment:
        self._ensure_configured(schemas.INSTALLATION_SEGMENT_SHEET.tab_name)
        found = await self._client.find_row(schemas.INSTALLATION_SEGMENT_SHEET, "segment_id", segment_id)
        if found is None:
            raise RepositoryError(f"Installation segment '{segment_id}' was not found")
        row_number, row = found
        updated_row = dict(row)
        updated_row.update(
            {
                "status": InstallationSegmentStatus.CLOSED.value,
                "removed_at": datetime.now(timezone.utc).isoformat(),
                "removed_by": removed_by or "",
                "removal_meter_snapshot_id": removal_meter_snapshot_id or "",
                "removal_reason": removal_reason or "",
            }
        )
        await self._client.update_row(schemas.INSTALLATION_SEGMENT_SHEET, row_number, updated_row)
        return self._installation_segment_from_row(updated_row)

    async def start_new_part_lifecycle(
        self,
        part_instance_id: str,
        start_reason: LifecycleStartReason,
        started_note: str | None,
        started_by: str | None,
    ) -> None:
        self._ensure_configured(schemas.PART_LIFECYCLE_SHEET.tab_name)
        found = await self._client.find_row(schemas.PART_INSTANCE_SHEET, "part_instance_id", part_instance_id)
        if found is None:
            raise RepositoryError(f"Part instance '{part_instance_id}' was not found")
        instance_row_number, instance_row = found

        lifecycle_rows = await self._client.read_rows(schemas.PART_LIFECYCLE_SHEET)
        current_lifecycle_id = instance_row.get("current_lifecycle_id", "")
        current_found = None
        for index, row in enumerate(lifecycle_rows):
            if row.get("lifecycle_id") == current_lifecycle_id:
                current_found = (index, row)
                break

        now = datetime.now(timezone.utc)
        cycle_number = 1
        if current_found is not None:
            index, current_row = current_found
            ended_row = dict(current_row)
            ended_row["ended_at"] = now.isoformat()
            await self._client.update_row(schemas.PART_LIFECYCLE_SHEET, index + 2, ended_row)
            cycle_number = int(self._parse_float(current_row.get("cycle_number")) or 0) + 1

        new_lifecycle_id = self._next_id(lifecycle_rows, "lifecycle_id", "PLC")
        await self._client.append_row(
            schemas.PART_LIFECYCLE_SHEET,
            {
                "lifecycle_id": new_lifecycle_id,
                "part_instance_id": part_instance_id,
                "cycle_number": cycle_number,
                "start_reason": start_reason.value,
                "started_at": now.isoformat(),
                "started_by": started_by or "",
                "started_note": started_note or "",
                "ended_at": "",
            },
        )

        updated_instance_row = dict(instance_row)
        updated_instance_row["current_lifecycle_id"] = new_lifecycle_id
        updated_instance_row["updated_at"] = now.isoformat()
        await self._client.update_row(schemas.PART_INSTANCE_SHEET, instance_row_number, updated_instance_row)

    # ---- Position lifetime (Phase 5) ----

    def _position_lifetime_from_row(self, row: dict) -> PositionLifetimeRecord:
        return PositionLifetimeRecord(
            position_lifetime_id=row["position_lifetime_id"],
            asset_type=AssetType(row.get("asset_type") or "VEHICLE"),
            asset_id=row.get("asset_id", ""),
            position_code=row.get("position_code", ""),
            part_id=row.get("part_id") or None,
            lifetime_rule_id=row.get("lifetime_rule_id") or None,
            baseline_meter_snapshot_id=row.get("baseline_meter_snapshot_id") or None,
            prior_usage=self._prior_usage_from_row(row),
            started_at=self._parse_datetime(row.get("started_at", "")) or _epoch(),
            started_by=row.get("started_by") or None,
            note=row.get("note") or None,
        )

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
        self._ensure_configured(schemas.POSITION_LIFETIME_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.POSITION_LIFETIME_SHEET)
        position_lifetime_id = self._next_id(rows, "position_lifetime_id", "POSLT")
        started_at = datetime.now(timezone.utc)
        await self._client.append_row(
            schemas.POSITION_LIFETIME_SHEET,
            {
                "position_lifetime_id": position_lifetime_id,
                "asset_type": asset_type.value,
                "asset_id": asset_id,
                "position_code": position_code,
                "part_id": part_id or "",
                "lifetime_rule_id": lifetime_rule_id or "",
                "baseline_meter_snapshot_id": baseline_meter_snapshot_id or "",
                "prior_usage_quality": prior_usage.quality.value,
                "prior_usage_value": prior_usage.value if prior_usage.value is not None else "",
                "prior_usage_note": prior_usage.note or "",
                "started_at": started_at.isoformat(),
                "started_by": started_by or "",
                "note": note or "",
            },
        )
        return PositionLifetimeRecord(
            position_lifetime_id=position_lifetime_id,
            asset_type=asset_type,
            asset_id=asset_id,
            position_code=position_code,
            part_id=part_id,
            lifetime_rule_id=lifetime_rule_id,
            baseline_meter_snapshot_id=baseline_meter_snapshot_id,
            prior_usage=prior_usage.model_copy(deep=True),
            started_at=started_at,
            started_by=started_by,
            note=note,
        )

    async def get_position_lifetime(
        self, position_lifetime_id: str
    ) -> PositionLifetimeRecord | None:
        self._ensure_configured(schemas.POSITION_LIFETIME_SHEET.tab_name)
        found = await self._client.find_row(
            schemas.POSITION_LIFETIME_SHEET, "position_lifetime_id", position_lifetime_id
        )
        return self._position_lifetime_from_row(found[1]) if found else None

    async def list_position_lifetime_for_asset(
        self, asset_type: AssetType, asset_id: str
    ) -> list[PositionLifetimeRecord]:
        self._ensure_configured(schemas.POSITION_LIFETIME_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.POSITION_LIFETIME_SHEET)
        records = [
            self._position_lifetime_from_row(row)
            for row in rows
            if row.get("asset_type") == asset_type.value and row.get("asset_id") == asset_id
        ]
        records.sort(key=lambda r: r.started_at)
        return records

    # ---- Lifetime rule (Phase 5) ----

    def _lifetime_rule_from_row(self, row: dict) -> LifetimeRule:
        return LifetimeRule(
            lifetime_rule_id=row["lifetime_rule_id"],
            part_id=row.get("part_id", ""),
            scope=LifetimeRuleScope(row.get("scope") or "MODEL"),
            model_id=row.get("model_id") or None,
            vehicle_id=row.get("vehicle_id") or None,
            trigger_type=LifetimeTriggerType(row.get("trigger_type") or "CALENDAR"),
            component_role=ComponentRole(row["component_role"]) if row.get("component_role") else None,
            first_due_value=self._parse_float(row.get("first_due_value")),
            interval_value=self._parse_float(row.get("interval_value")),
            warning_window_value=self._parse_float(row.get("warning_window_value")),
            note=row.get("note") or None,
            created_at=self._parse_datetime(row.get("created_at", "")) or _epoch(),
        )

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
        self._ensure_configured(schemas.LIFETIME_RULE_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.LIFETIME_RULE_SHEET)
        lifetime_rule_id = self._next_id(rows, "lifetime_rule_id", "LTR")
        now = datetime.now(timezone.utc)
        await self._client.append_row(
            schemas.LIFETIME_RULE_SHEET,
            {
                "lifetime_rule_id": lifetime_rule_id,
                "part_id": part_id,
                "scope": scope.value,
                "model_id": model_id or "",
                "vehicle_id": vehicle_id or "",
                "trigger_type": trigger_type.value,
                "component_role": component_role.value if component_role else "",
                "first_due_value": first_due_value if first_due_value is not None else "",
                "interval_value": interval_value if interval_value is not None else "",
                "warning_window_value": warning_window_value if warning_window_value is not None else "",
                "note": note or "",
                "created_at": now.isoformat(),
            },
        )
        return LifetimeRule(
            lifetime_rule_id=lifetime_rule_id,
            part_id=part_id,
            scope=scope,
            model_id=model_id,
            vehicle_id=vehicle_id,
            trigger_type=trigger_type,
            component_role=component_role,
            first_due_value=first_due_value,
            interval_value=interval_value,
            warning_window_value=warning_window_value,
            note=note,
            created_at=now,
        )

    async def get_lifetime_rule(self, lifetime_rule_id: str) -> LifetimeRule | None:
        self._ensure_configured(schemas.LIFETIME_RULE_SHEET.tab_name)
        found = await self._client.find_row(schemas.LIFETIME_RULE_SHEET, "lifetime_rule_id", lifetime_rule_id)
        return self._lifetime_rule_from_row(found[1]) if found else None

    async def list_lifetime_rules_for_part(self, part_id: str) -> list[LifetimeRule]:
        self._ensure_configured(schemas.LIFETIME_RULE_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.LIFETIME_RULE_SHEET)
        rules = [self._lifetime_rule_from_row(row) for row in rows if row.get("part_id") == part_id]
        rules.sort(key=lambda r: r.lifetime_rule_id)
        return rules

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

    # ---- Driver / Operator (Web/API Phase 6 Batch 1) ----
    # Real (non-stubbed) read/write against the two verified live tabs
    # (`driver_master`, `vehicle_driver` — see
    # app.repositories.google_sheets.schemas). Mapped by header name only,
    # never row position (guardrails §18).
    #
    # LIVE UAT DEFECT FIX (phone leading-zero loss): the shared
    # GoogleSheetsClient always writes with value_input_option=
    # "USER_ENTERED" (see client.py), which makes the Sheets API parse a
    # plain digit-only cell value the same way a human typing into the UI
    # would — so an opaque textual value that happens to look like a
    # number (e.g. a phone number starting with "0") gets silently
    # coerced into a numeric cell, losing the leading zero. `phone` is
    # documented (app.domain.driver) as an opaque textual value, never a
    # number, so its write must defeat that auto-detection. This is
    # deliberately a field-safe fix at this repository's own row-building
    # layer (`_driver_sheet_write_row`), not a change to
    # GoogleSheetsClient/value_input_option itself: no evidence exists
    # that any other driver_master field, or any other table, has the
    # same numeric-coercion risk, so no global/shared behavior was
    # touched (scope guardrails).
    #
    # FOLLOW-UP FINDING (same investigation, live UAT defect follow-up):
    # gspread's `get_all_records()` performs its own client-side numeric
    # coercion (`numericise_all`) on every column's formatted-value
    # string, independent of how the cell is actually stored server-side.
    # This means even a `phone` cell correctly written as literal text by
    # `_force_text_for_sheet` above would still be converted back into a
    # Python `int` on every subsequent read if it happens to look like a
    # plain number (e.g. "0999999999" -> 999999999), silently re-losing
    # the leading zero the write-side fix just preserved. Every read of
    # `driver_master` below passes `phone` through
    # `_DRIVER_TEXT_ONLY_HEADERS` to `GoogleSheetsClient.read_rows`/
    # `find_row`'s `text_only_headers`, which uses gspread's own
    # `numericise_ignore` mechanism — reusing an existing, established
    # gspread feature rather than inventing a new conversion layer, and
    # touching no field beyond the one already-confirmed `phone` defect.
    _DRIVER_TEXT_ONLY_HEADERS = ("phone",)

    @staticmethod
    def _force_text_for_sheet(value: str) -> str:
        """Prefix with a leading apostrophe — the standard Google Sheets
        input-formatting marker that forces USER_ENTERED to store the
        value as literal text instead of auto-detecting it as a number.
        The apostrophe is never part of the stored cell content: reading
        the cell back through the Sheets API returns the text without
        it."""
        return f"'{value}"

    @classmethod
    def _driver_sheet_write_row(cls, row: dict) -> dict:
        """A copy of `row` suitable for the actual Sheets write. Only
        `phone` is force-texted here — the one field this UAT defect was
        confirmed against; no other driver_master column is modified."""
        written = dict(row)
        if written.get("phone"):
            written["phone"] = cls._force_text_for_sheet(written["phone"])
        return written

    @staticmethod
    def _driver_phone_from_cell(value: object) -> str | None:
        """LIVE UAT DEFECT FIX (read-side robustness): an existing/legacy
        `driver_master` row may already have `phone` stored as a genuine
        Sheets number (e.g. written before this fix existed), which the
        Sheets API can return as a Python `int`/`float` rather than
        `str`. `Driver.phone` is a `str | None` field and pydantic does
        not coerce `int`/`float` to `str`, so passing it through
        unchanged previously raised a validation error and surfaced as
        an HTTP 500 on every subsequent read of that row. This coerces
        defensively to text so reading never crashes — it does NOT
        attempt to reconstruct a leading zero that Sheets may have
        already stripped (that information is genuinely lost; inventing
        it back would be fabricating data), and it never rewrites the
        sheet itself. A `float` that is a whole number (e.g. `999999999.0`,
        which some Sheets numeric reads may produce) is rendered without
        a spurious trailing `.0`."""
        if value is None or value == "":
            return None
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    def _driver_from_row(self, row: dict) -> Driver:
        return Driver(
            driver_id=row["driver_id"],
            driver_name_th=row.get("driver_name_th", ""),
            phone=self._driver_phone_from_cell(row.get("phone")),
            license_no=row.get("license_no") or None,
            license_expiry_date=self._parse_date(row.get("license_expiry_date", "")),
            # NO-GUESSING RULE (app.domain.driver): a plain passthrough
            # string, never coerced against an invented vocabulary.
            active_status=row.get("active_status") or None,
            note_th=row.get("note_th") or None,
        )

    async def create_driver(
        self,
        driver_name_th: str,
        phone: str | None,
        license_no: str | None,
        license_expiry_date: date | None,
        active_status: str | None,
        note_th: str | None,
    ) -> Driver:
        self._ensure_configured(schemas.DRIVER_MASTER_SHEET.tab_name)
        rows = await self._client.read_rows(
            schemas.DRIVER_MASTER_SHEET, text_only_headers=self._DRIVER_TEXT_ONLY_HEADERS
        )
        driver_id = self._next_id(rows, "driver_id", "DRV")
        row = {
            "driver_id": driver_id,
            "driver_name_th": driver_name_th,
            "phone": phone or "",
            "license_no": license_no or "",
            "license_expiry_date": license_expiry_date.isoformat() if license_expiry_date else "",
            "active_status": active_status or "",
            "note_th": note_th or "",
        }
        await self._client.append_row(
            schemas.DRIVER_MASTER_SHEET, self._driver_sheet_write_row(row)
        )
        return self._driver_from_row(row)

    async def get_driver(self, driver_id: str) -> Driver | None:
        self._ensure_configured(schemas.DRIVER_MASTER_SHEET.tab_name)
        found = await self._client.find_row(
            schemas.DRIVER_MASTER_SHEET,
            "driver_id",
            driver_id,
            text_only_headers=self._DRIVER_TEXT_ONLY_HEADERS,
        )
        if found is None:
            return None
        return self._driver_from_row(found[1])

    async def list_drivers(
        self, q: str | None, params: PageParams
    ) -> tuple[list[Driver], int]:
        self._ensure_configured(schemas.DRIVER_MASTER_SHEET.tab_name)
        rows = await self._client.read_rows(
            schemas.DRIVER_MASTER_SHEET, text_only_headers=self._DRIVER_TEXT_ONLY_HEADERS
        )
        drivers = [self._driver_from_row(row) for row in rows]
        if q:
            needle = q.strip().lower()
            drivers = [
                d
                for d in drivers
                if needle in d.driver_name_th.lower()
                or (d.phone and needle in d.phone.lower())
                or (d.license_no and needle in d.license_no.lower())
            ]
        drivers.sort(key=lambda d: d.driver_id)
        start = (params.page - 1) * params.page_size
        page = drivers[start : start + params.page_size]
        return page, len(drivers)

    async def update_driver(
        self,
        driver_id: str,
        driver_name_th: str,
        phone: str | None,
        license_no: str | None,
        license_expiry_date: date | None,
        active_status: str | None,
        note_th: str | None,
    ) -> Driver:
        self._ensure_configured(schemas.DRIVER_MASTER_SHEET.tab_name)
        found = await self._client.find_row(
            schemas.DRIVER_MASTER_SHEET,
            "driver_id",
            driver_id,
            text_only_headers=self._DRIVER_TEXT_ONLY_HEADERS,
        )
        if found is None:
            raise RepositoryError(f"Driver '{driver_id}' was not found")
        row_number, row = found
        updated_row = dict(row)
        updated_row.update(
            {
                "driver_name_th": driver_name_th,
                "phone": phone or "",
                "license_no": license_no or "",
                "license_expiry_date": (
                    license_expiry_date.isoformat() if license_expiry_date else ""
                ),
                "active_status": active_status or "",
                "note_th": note_th or "",
            }
        )
        await self._client.update_row(
            schemas.DRIVER_MASTER_SHEET, row_number, self._driver_sheet_write_row(updated_row)
        )
        return self._driver_from_row(updated_row)

    def _vehicle_driver_assignment_from_row(self, row: dict) -> VehicleDriverAssignment:
        return VehicleDriverAssignment(
            assignment_id=row["assignment_id"],
            vehicle_id=row.get("vehicle_id", ""),
            driver_id=row.get("driver_id", ""),
            start_at=self._parse_datetime(row.get("start_at", "")) or _epoch(),
            end_at=self._parse_datetime(row.get("end_at", "")),
            is_primary=self._parse_bool(row.get("is_primary")),
            # NO-GUESSING RULE (app.domain.driver): a plain passthrough
            # string, never coerced against an invented vocabulary.
            assignment_status=row.get("assignment_status") or None,
            changed_by_user_id=row.get("changed_by_user_id") or None,
            note_th=row.get("note_th") or None,
        )

    async def create_vehicle_driver_assignment(
        self,
        vehicle_id: str,
        driver_id: str,
        start_at: datetime,
        is_primary: bool,
        assignment_status: str | None,
        changed_by_user_id: str | None,
        note_th: str | None,
    ) -> VehicleDriverAssignment:
        self._ensure_configured(schemas.VEHICLE_DRIVER_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.VEHICLE_DRIVER_SHEET)
        assignment_id = self._next_id(rows, "assignment_id", "VDRV")
        row = {
            "assignment_id": assignment_id,
            "vehicle_id": vehicle_id,
            "driver_id": driver_id,
            "start_at": start_at.isoformat(),
            "end_at": "",
            "is_primary": "TRUE" if is_primary else "FALSE",
            "assignment_status": assignment_status or "",
            "changed_by_user_id": changed_by_user_id or "",
            "note_th": note_th or "",
        }
        # Append-only: an existing row is never rewritten/removed here —
        # a caller that wants a prior period closed calls
        # end_vehicle_driver_assignment explicitly/first.
        await self._client.append_row(schemas.VEHICLE_DRIVER_SHEET, row)
        return self._vehicle_driver_assignment_from_row(row)

    async def get_vehicle_driver_assignment(
        self, assignment_id: str
    ) -> VehicleDriverAssignment | None:
        self._ensure_configured(schemas.VEHICLE_DRIVER_SHEET.tab_name)
        found = await self._client.find_row(
            schemas.VEHICLE_DRIVER_SHEET, "assignment_id", assignment_id
        )
        if found is None:
            return None
        return self._vehicle_driver_assignment_from_row(found[1])

    async def end_vehicle_driver_assignment(
        self,
        assignment_id: str,
        end_at: datetime,
        changed_by_user_id: str | None,
    ) -> VehicleDriverAssignment:
        self._ensure_configured(schemas.VEHICLE_DRIVER_SHEET.tab_name)
        found = await self._client.find_row(
            schemas.VEHICLE_DRIVER_SHEET, "assignment_id", assignment_id
        )
        if found is None:
            raise RepositoryError(f"Vehicle driver assignment '{assignment_id}' was not found")
        row_number, row = found
        updated_row = dict(row)
        updated_row["end_at"] = end_at.isoformat()
        updated_row["changed_by_user_id"] = changed_by_user_id or row.get("changed_by_user_id", "")
        await self._client.update_row(schemas.VEHICLE_DRIVER_SHEET, row_number, updated_row)
        return self._vehicle_driver_assignment_from_row(updated_row)

    async def list_vehicle_driver_assignments(
        self, vehicle_id: str
    ) -> list[VehicleDriverAssignment]:
        self._ensure_configured(schemas.VEHICLE_DRIVER_SHEET.tab_name)
        rows = await self._client.read_rows(schemas.VEHICLE_DRIVER_SHEET)
        entries = [
            self._vehicle_driver_assignment_from_row(row)
            for row in rows
            if row.get("vehicle_id") == vehicle_id
        ]
        entries.sort(key=lambda e: e.start_at, reverse=True)
        return entries

    # ---- Vehicle Certificate (Web/API Phase 6 Batch 2A) ----
    #
    # Column correspondence: mapped by header name (verified live tab
    # `vehicle_certificate` — see app.repositories.google_sheets.schemas).
    #
    # TEXT-COERCION PROTECTION (same defect class as Batch 1's `phone` —
    # see the LIVE UAT DEFECT FIX note above `_DRIVER_TEXT_ONLY_HEADERS`):
    # any opaque identifier/passthrough column whose value can look like a
    # number (a document number with a leading zero, an ID, an opaque
    # storage reference) is protected from both write-side USER_ENTERED
    # auto-detection (`_force_text_for_sheet`) and read-side gspread
    # `numericise_all()` client-side coercion (`text_only_headers`).
    # `alert_lead_days` is deliberately excluded — it is a genuine integer
    # column (app.domain.vehicle_certificate module docstring), never
    # opaque text.
    _CERTIFICATE_TEXT_ONLY_HEADERS = (
        "certificate_id",
        "vehicle_id",
        "certificate_type_code",
        "document_no",
        "replaced_by_certificate_id",
        "storage_ref",
    )

    @classmethod
    def _certificate_sheet_write_row(cls, row: dict) -> dict:
        written = dict(row)
        for header in cls._CERTIFICATE_TEXT_ONLY_HEADERS:
            if written.get(header):
                written[header] = cls._force_text_for_sheet(written[header])
        return written

    @staticmethod
    def _certificate_alert_lead_days_from_cell(value: object) -> int | None:
        """Defensive int coercion — mirrors `_driver_phone_from_cell`'s
        reasoning: a blank cell is genuinely null (no default is
        fabricated), and a numeric-looking cell read back as `float` by
        the Sheets API (e.g. `7.0`) is rendered as the plain int `7`
        rather than raising a pydantic validation error."""
        if value is None or value == "":
            return None
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return int(float(value))  # type: ignore[arg-type]

    def _vehicle_certificate_from_row(self, row: dict) -> VehicleCertificate:
        status_raw = row.get("certificate_status") or None
        return VehicleCertificate(
            certificate_id=row["certificate_id"],
            vehicle_id=row.get("vehicle_id", ""),
            certificate_type_code=row.get("certificate_type_code") or None,
            certificate_type_name_th=row.get("certificate_type_name_th") or None,
            document_no=row.get("document_no") or None,
            issue_date=self._parse_date(row.get("issue_date", "")),
            expiry_date=self._parse_date(row.get("expiry_date", "")),
            alert_lead_days=self._certificate_alert_lead_days_from_cell(
                row.get("alert_lead_days")
            ),
            certificate_status=CertificateStatus(status_raw) if status_raw else None,
            replaced_by_certificate_id=row.get("replaced_by_certificate_id") or None,
            storage_ref=row.get("storage_ref") or None,
            created_by_user_id=row.get("created_by_user_id") or None,
            created_at=self._parse_datetime(row.get("created_at", "")) or _epoch(),
            note_th=row.get("note_th") or None,
        )

    async def create_vehicle_certificate(
        self,
        vehicle_id: str,
        certificate_type_code: str | None,
        certificate_type_name_th: str | None,
        document_no: str | None,
        issue_date: date | None,
        expiry_date: date | None,
        alert_lead_days: int | None,
        certificate_status: CertificateStatus | None,
        storage_ref: str | None,
        note_th: str | None,
        created_by_user_id: str | None,
        created_at: datetime,
    ) -> VehicleCertificate:
        self._ensure_configured(schemas.VEHICLE_CERTIFICATE_SHEET.tab_name)
        rows = await self._client.read_rows(
            schemas.VEHICLE_CERTIFICATE_SHEET,
            text_only_headers=self._CERTIFICATE_TEXT_ONLY_HEADERS,
        )
        certificate_id = self._next_id(rows, "certificate_id", "CERT")
        row = {
            "certificate_id": certificate_id,
            "vehicle_id": vehicle_id,
            "certificate_type_code": certificate_type_code or "",
            "certificate_type_name_th": certificate_type_name_th or "",
            "document_no": document_no or "",
            "issue_date": issue_date.isoformat() if issue_date else "",
            "expiry_date": expiry_date.isoformat() if expiry_date else "",
            "alert_lead_days": alert_lead_days if alert_lead_days is not None else "",
            "certificate_status": certificate_status.value if certificate_status else "",
            "replaced_by_certificate_id": "",
            "storage_ref": storage_ref or "",
            "created_by_user_id": created_by_user_id or "",
            "created_at": created_at.isoformat(),
            "note_th": note_th or "",
        }
        # Append-only: no existing row is ever rewritten/removed here.
        await self._client.append_row(
            schemas.VEHICLE_CERTIFICATE_SHEET, self._certificate_sheet_write_row(row)
        )
        return self._vehicle_certificate_from_row(row)

    async def get_vehicle_certificate(self, certificate_id: str) -> VehicleCertificate | None:
        self._ensure_configured(schemas.VEHICLE_CERTIFICATE_SHEET.tab_name)
        found = await self._client.find_row(
            schemas.VEHICLE_CERTIFICATE_SHEET,
            "certificate_id",
            certificate_id,
            text_only_headers=self._CERTIFICATE_TEXT_ONLY_HEADERS,
        )
        if found is None:
            return None
        return self._vehicle_certificate_from_row(found[1])

    async def list_vehicle_certificates_for_vehicle(
        self, vehicle_id: str
    ) -> list[VehicleCertificate]:
        self._ensure_configured(schemas.VEHICLE_CERTIFICATE_SHEET.tab_name)
        rows = await self._client.read_rows(
            schemas.VEHICLE_CERTIFICATE_SHEET,
            text_only_headers=self._CERTIFICATE_TEXT_ONLY_HEADERS,
        )
        entries = [
            self._vehicle_certificate_from_row(row)
            for row in rows
            if row.get("vehicle_id") == vehicle_id
        ]
        entries.sort(key=lambda e: e.created_at, reverse=True)
        return entries

    # ---- Vehicle Certificate lifecycle (Web/API Phase 6 Batch 2B) ----
    # Narrow, single-purpose row updates — never a generic PATCH. Each
    # finds the exact row by `certificate_id`, copies it, mutates only
    # the named lifecycle fields, and writes the full row back through
    # `_certificate_sheet_write_row` so every existing text-coercion
    # protection (document_no, replaced_by_certificate_id, etc.) applies
    # automatically on this round trip too — the same discipline
    # `update_driver`/`end_vehicle_driver_assignment` already established
    # for full-row read-modify-write updates.

    async def mark_vehicle_certificate_replaced(
        self, certificate_id: str, replaced_by_certificate_id: str
    ) -> VehicleCertificate:
        self._ensure_configured(schemas.VEHICLE_CERTIFICATE_SHEET.tab_name)
        found = await self._client.find_row(
            schemas.VEHICLE_CERTIFICATE_SHEET,
            "certificate_id",
            certificate_id,
            text_only_headers=self._CERTIFICATE_TEXT_ONLY_HEADERS,
        )
        if found is None:
            raise RepositoryError(f"Vehicle certificate '{certificate_id}' was not found")
        row_number, row = found
        updated_row = dict(row)
        updated_row["certificate_status"] = CertificateStatus.REPLACED.value
        updated_row["replaced_by_certificate_id"] = replaced_by_certificate_id
        await self._client.update_row(
            schemas.VEHICLE_CERTIFICATE_SHEET,
            row_number,
            self._certificate_sheet_write_row(updated_row),
        )
        return self._vehicle_certificate_from_row(updated_row)

    async def mark_vehicle_certificate_expired(self, certificate_id: str) -> VehicleCertificate:
        self._ensure_configured(schemas.VEHICLE_CERTIFICATE_SHEET.tab_name)
        found = await self._client.find_row(
            schemas.VEHICLE_CERTIFICATE_SHEET,
            "certificate_id",
            certificate_id,
            text_only_headers=self._CERTIFICATE_TEXT_ONLY_HEADERS,
        )
        if found is None:
            raise RepositoryError(f"Vehicle certificate '{certificate_id}' was not found")
        row_number, row = found
        updated_row = dict(row)
        updated_row["certificate_status"] = CertificateStatus.EXPIRED.value
        await self._client.update_row(
            schemas.VEHICLE_CERTIFICATE_SHEET,
            row_number,
            self._certificate_sheet_write_row(updated_row),
        )
        return self._vehicle_certificate_from_row(updated_row)

    # ---- Model Document (Web/API Phase 6 Batch 3A) ----
    #
    # Column correspondence: mapped by header name (verified live tab
    # `model_document` — see app.repositories.google_sheets.schemas).
    #
    # TEXT-COERCION PROTECTION (same defect class as Batch 1's `phone`/
    # Batch 2A's `document_no` — see the LIVE UAT DEFECT FIX note above
    # `_DRIVER_TEXT_ONLY_HEADERS`): every opaque identifier/passthrough
    # column is protected from both write-side USER_ENTERED
    # auto-detection and read-side gspread `numericise_all()` client-side
    # coercion. `version` is included — no authoritative source defines
    # its format, and a value like "001"/"1.0" must never be silently
    # coerced into a number. `effective_from`/`effective_to` are
    # deliberately excluded — they are genuine date columns (Phase 6
    # Batch 3 audit section 9/4D), and Batch 1 already proved a
    # formatted date string is never numericised by gspread even without
    # this protection.
    _MODEL_DOCUMENT_TEXT_ONLY_HEADERS = (
        "model_document_id",
        "model_id",
        "document_type",
        "document_name_th",
        "version",
        "storage_ref",
        "file_status",
        "active_status",
        "replaced_by_document_id",
    )

    @classmethod
    def _model_document_sheet_write_row(cls, row: dict) -> dict:
        written = dict(row)
        for header in cls._MODEL_DOCUMENT_TEXT_ONLY_HEADERS:
            if written.get(header):
                written[header] = cls._force_text_for_sheet(written[header])
        return written

    def _model_document_from_row(self, row: dict) -> ModelDocument:
        return ModelDocument(
            model_document_id=row["model_document_id"],
            model_id=row.get("model_id", ""),
            document_type=row.get("document_type") or None,
            document_name_th=row.get("document_name_th") or None,
            version=row.get("version") or None,
            effective_from=self._parse_date(row.get("effective_from", "")),
            effective_to=self._parse_date(row.get("effective_to", "")),
            storage_ref=row.get("storage_ref") or None,
            file_status=row.get("file_status") or None,
            active_status=row.get("active_status") or None,
            replaced_by_document_id=row.get("replaced_by_document_id") or None,
            note_th=row.get("note_th") or None,
        )

    async def create_model_document(
        self,
        model_id: str,
        document_type: str | None,
        document_name_th: str | None,
        version: str | None,
        effective_from: date | None,
        effective_to: date | None,
        storage_ref: str | None,
        file_status: str | None,
        active_status: str | None,
        note_th: str | None,
    ) -> ModelDocument:
        self._ensure_configured(schemas.MODEL_DOCUMENT_SHEET.tab_name)
        rows = await self._client.read_rows(
            schemas.MODEL_DOCUMENT_SHEET,
            text_only_headers=self._MODEL_DOCUMENT_TEXT_ONLY_HEADERS,
        )
        model_document_id = self._next_id(rows, "model_document_id", "MDOC")
        row = {
            "model_document_id": model_document_id,
            "model_id": model_id,
            "document_type": document_type or "",
            "document_name_th": document_name_th or "",
            "version": version or "",
            "effective_from": effective_from.isoformat() if effective_from else "",
            "effective_to": effective_to.isoformat() if effective_to else "",
            "storage_ref": storage_ref or "",
            "file_status": file_status or "",
            "active_status": active_status or "",
            "replaced_by_document_id": "",
            "note_th": note_th or "",
        }
        # Append-only: no existing row is ever rewritten/removed here.
        await self._client.append_row(
            schemas.MODEL_DOCUMENT_SHEET, self._model_document_sheet_write_row(row)
        )
        return self._model_document_from_row(row)

    async def get_model_document(self, model_document_id: str) -> ModelDocument | None:
        self._ensure_configured(schemas.MODEL_DOCUMENT_SHEET.tab_name)
        found = await self._client.find_row(
            schemas.MODEL_DOCUMENT_SHEET,
            "model_document_id",
            model_document_id,
            text_only_headers=self._MODEL_DOCUMENT_TEXT_ONLY_HEADERS,
        )
        if found is None:
            return None
        return self._model_document_from_row(found[1])

    async def list_model_documents_for_model(self, model_id: str) -> list[ModelDocument]:
        self._ensure_configured(schemas.MODEL_DOCUMENT_SHEET.tab_name)
        rows = await self._client.read_rows(
            schemas.MODEL_DOCUMENT_SHEET,
            text_only_headers=self._MODEL_DOCUMENT_TEXT_ONLY_HEADERS,
        )
        return [
            self._model_document_from_row(row) for row in rows if row.get("model_id") == model_id
        ]

    async def finalize_model_document_revision(
        self, model_document_id: str, effective_to: date, replaced_by_document_id: str
    ) -> ModelDocument:
        """Web/API Phase 6 Batch 3B. Narrow read-modify-write — finds the
        exact row, mutates only `effective_to`/`replaced_by_document_id`,
        writes the full row back through `_model_document_sheet_write_row`
        so `replaced_by_document_id`'s existing text-coercion protection
        applies automatically. `effective_to` is a genuine date column
        (never in `_MODEL_DOCUMENT_TEXT_ONLY_HEADERS`), so it is written
        as a real Sheet date here, not text-forced."""
        self._ensure_configured(schemas.MODEL_DOCUMENT_SHEET.tab_name)
        found = await self._client.find_row(
            schemas.MODEL_DOCUMENT_SHEET,
            "model_document_id",
            model_document_id,
            text_only_headers=self._MODEL_DOCUMENT_TEXT_ONLY_HEADERS,
        )
        if found is None:
            raise RepositoryError(f"Model document '{model_document_id}' was not found")
        row_number, row = found
        updated_row = dict(row)
        updated_row["effective_to"] = effective_to.isoformat()
        updated_row["replaced_by_document_id"] = replaced_by_document_id
        await self._client.update_row(
            schemas.MODEL_DOCUMENT_SHEET,
            row_number,
            self._model_document_sheet_write_row(updated_row),
        )
        return self._model_document_from_row(updated_row)
