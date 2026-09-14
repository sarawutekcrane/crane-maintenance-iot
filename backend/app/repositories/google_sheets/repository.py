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

from app.config import Settings
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
    InspectionDetail,
    InspectionFinding,
    InspectionItemResult,
    InspectionSummary,
    NewInspectionItemInput,
)
from app.domain.lifetime_rule import LifetimeRule, LifetimeRuleScope, LifetimeTriggerType
from app.domain.meter import MeterReading, MeterSnapshot
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
    PmWorkOrderSummary,
    PmWorkResult,
)
from app.domain.position_lifetime import PositionLifetimeRecord
from app.domain.requisition import RequisitionLine, RequisitionSourceType
from app.domain.repair import Repair, RepairDetail, RepairSourceType, RepairStatus, RepairSummary
from app.domain.vehicle import Vehicle, VehicleComponent, VehicleStatusHistoryEntry
from app.domain.vehicle_model import ComponentRole, VehicleModel
from app.repositories.base import Repository, RepositoryError
from app.repositories.google_sheets.client import GoogleSheetsClient
from app.repositories.google_sheets import schemas


class GoogleSheetsRepository(Repository):
    def __init__(self, settings: Settings) -> None:
        self._client = GoogleSheetsClient(settings)

    @property
    def mode(self) -> str:
        return "google_sheets"

    async def check_ready(self) -> tuple[bool, str | None]:
        return await self._client.verify_connectivity()

    def _require_configured(self, entity: str) -> None:
        if not self._client.is_configured:
            raise RepositoryError(
                f"Cannot read/write '{entity}': GOOGLE_SHEET_ID / "
                "GOOGLE_APPLICATION_CREDENTIALS are not configured. See "
                "docs/claude-prompts/web-api/00_LOCAL_DEVELOPMENT_AND_NO_SERVER_SETUP_EN.txt "
                "section 6 to connect a local Google Sheets prototype."
            )
        raise NotImplementedError(
            f"Google Sheets read/write for '{entity}' (tab schema declared in "
            "app.repositories.google_sheets.schemas) is implemented once local "
            "credentials are available and the tab/header schema is validated "
            "against the prototype spreadsheet."
        )

    # ---- Vehicle model ----

    async def list_vehicle_models(
        self, q: str | None, params: PageParams
    ) -> tuple[list[VehicleModel], int]:
        self._require_configured(schemas.VEHICLE_MODEL_SHEET.tab_name)

    async def get_vehicle_model(self, model_id: str) -> VehicleModel | None:
        self._require_configured(schemas.VEHICLE_MODEL_SHEET.tab_name)

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
        self._require_configured(schemas.VEHICLE_SHEET.tab_name)

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

    async def get_equipment(self, equipment_id: str) -> Equipment | None:
        self._require_configured(schemas.EQUIPMENT_SHEET.tab_name)

    async def change_equipment_status(
        self,
        equipment_id: str,
        status: EquipmentOperationalStatus,
        reason: str | None,
        changed_by: str | None,
    ) -> Equipment:
        self._require_configured(schemas.EQUIPMENT_STATUS_HISTORY_SHEET.tab_name)

    async def list_equipment_status_history(
        self, equipment_id: str
    ) -> list[EquipmentStatusHistoryEntry]:
        self._require_configured(schemas.EQUIPMENT_STATUS_HISTORY_SHEET.tab_name)

    # ---- Checklist / inspection (Phase 3) ----

    async def get_active_checklist_revision(
        self, asset_type: AssetType
    ) -> ChecklistRevisionDetail | None:
        self._require_configured(schemas.CHECKLIST_REVISION_SHEET.tab_name)

    async def get_checklist_revision(
        self, checklist_id: str, revision_id: str
    ) -> ChecklistRevisionDetail | None:
        self._require_configured(schemas.CHECKLIST_REVISION_SHEET.tab_name)

    async def create_attachment(
        self,
        purpose: AttachmentPurpose,
        storage_ref: str,
        filename: str,
        content_type: str,
        size_bytes: int,
        uploaded_by: str | None,
    ) -> Attachment:
        self._require_configured(schemas.ATTACHMENT_SHEET.tab_name)

    async def get_attachment(self, attachment_id: str) -> Attachment | None:
        self._require_configured(schemas.ATTACHMENT_SHEET.tab_name)

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

    # ---- PM plan / task revision (Phase 4) ----

    async def list_pm_plans(self, asset_type: AssetType | None, model_id: str | None) -> list[PmPlan]:
        self._require_configured(schemas.PM_PLAN_SHEET.tab_name)

    async def get_pm_plan(self, pm_plan_id: str) -> PmPlan | None:
        self._require_configured(schemas.PM_PLAN_SHEET.tab_name)

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
        self._require_configured(schemas.PM_WORK_ORDER_SHEET.tab_name)

    async def approve_pm_scope(
        self, pm_work_order_id: str, approved_by: str | None
    ) -> PmWorkOrder:
        self._require_configured(schemas.PM_WORK_ORDER_SHEET.tab_name)

    async def get_pm_work_order(self, pm_work_order_id: str) -> PmWorkOrderDetail | None:
        self._require_configured(schemas.PM_WORK_ORDER_SHEET.tab_name)

    async def list_pm_work_orders(
        self,
        asset_type: AssetType | None,
        asset_id: str | None,
        params: PageParams,
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
        self._require_configured(schemas.METER_SNAPSHOT_SHEET.tab_name)

    async def get_meter_snapshot(self, meter_snapshot_id: str) -> MeterSnapshot | None:
        self._require_configured(schemas.METER_SNAPSHOT_SHEET.tab_name)

    async def list_meter_snapshots_for_asset(
        self, asset_type: AssetType, asset_id: str
    ) -> list[MeterSnapshot]:
        self._require_configured(schemas.METER_SNAPSHOT_SHEET.tab_name)

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
    ) -> tuple[list[RepairSummary], int]:
        self._require_configured(schemas.REPAIR_SHEET.tab_name)

    async def assign_repair(
        self,
        repair_id: str,
        primary_technician: str | None,
        collaborators: list[str],
    ) -> Repair:
        self._require_configured(schemas.REPAIR_SHEET.tab_name)

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

    # ---- Requisition line (Core Demo Fix, Store/Inventory boundary) ----

    async def create_requisition_line(
        self,
        work_order_reference: str,
        source_type: RequisitionSourceType,
        part_id: str | None,
        part_instance_id: str | None,
        part_description: str,
        requested_quantity: float | None,
        unit: str | None,
        created_by: str | None,
    ) -> RequisitionLine:
        self._require_configured(schemas.REQUISITION_LINE_SHEET.tab_name)

    async def list_requisition_lines_for_work_order(
        self, work_order_reference: str
    ) -> list[RequisitionLine]:
        self._require_configured(schemas.REQUISITION_LINE_SHEET.tab_name)
