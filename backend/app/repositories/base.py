"""Repository interface.

Frozen in Phase 1: the domain/service layer depends only on this
interface, never on a concrete storage technology. Phase 1 only defined
the readiness/self-check contract; domain-entity repository methods
(vehicles, inspections, PM, parts, ...) are added starting Phase 2 as
extensions of `Repository`, without changing this base shape (see
`check_ready`/`mode`, which remain untouched below).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from app.domain.asset import AssetType
from app.domain.attachment import Attachment, AttachmentPurpose
from app.domain.checklist import ChecklistRevisionDetail
from app.domain.common import OperationalStatus, PageParams
from app.domain.equipment import Equipment, EquipmentCategory
from app.domain.inspection import (
    InspectionDetail,
    InspectionFinding,
    InspectionItemResult,
    NewInspectionItemInput,
    InspectionSummary,
)
from app.domain.lifetime_rule import LifetimeRule, LifetimeRuleScope, LifetimeTriggerType
from app.domain.meter import MeterReading, MeterSnapshot
from app.domain.part import (
    PartActionType,
    PartMaster,
    PartSet,
    PartSetRevisionDetail,
    TrackingMode,
)
from app.domain.part_instance import (
    InstallationSegment,
    LifecycleStartReason,
    PartInstanceDetail,
    PartInstanceStatus,
    PriorUsage,
)
from app.domain.pm import (
    PmPlan,
    PmTaskRevisionDetail,
    PmTriggerType,
    PmWorkOrder,
    PmWorkOrderDetail,
    PmWorkOrderSummary,
    PmWorkResult,
)
from app.domain.position_lifetime import PositionLifetimeRecord
from app.domain.repair import Repair, RepairDetail, RepairSourceType, RepairStatus, RepairSummary
from app.domain.vehicle import Vehicle, VehicleComponent, VehicleStatusHistoryEntry
from app.domain.vehicle_model import ComponentRole, VehicleModel


class RepositoryError(Exception):
    """Raised when a repository cannot serve a request (connectivity,
    missing schema, etc.). Domain/service code should translate this into
    an ApiError; it must never leak raw driver exceptions (e.g. Google API
    exceptions) upward.
    """


class Repository(ABC):
    """Base interface every concrete repository (mock, Google Sheets,
    PostgreSQL) must implement.
    """

    @property
    @abstractmethod
    def mode(self) -> str:
        """Short identifier of the backing mode, e.g. "mock", "google_sheets"."""

    @abstractmethod
    async def check_ready(self) -> tuple[bool, str | None]:
        """Return (is_ready, reason_if_not_ready).

        Used by GET /api/v1/readiness. Mock repositories are always ready.
        Google Sheets / PostgreSQL repositories should verify connectivity
        and required schema here.
        """

    # ---- Vehicle model (Phase 2) ----

    @abstractmethod
    async def list_vehicle_models(
        self, q: str | None, params: PageParams
    ) -> tuple[list[VehicleModel], int]:
        """Return (page of models matching `q`, total matching count)."""

    @abstractmethod
    async def get_vehicle_model(self, model_id: str) -> VehicleModel | None:
        """Return the model, or None if `model_id` does not exist."""

    # ---- Vehicle (Phase 2) ----

    @abstractmethod
    async def list_vehicles(
        self,
        q: str | None,
        operational_status: OperationalStatus | None,
        model_id: str | None,
        params: PageParams,
    ) -> tuple[list[Vehicle], int]:
        """Return (page of vehicles matching the filters, total matching count)."""

    @abstractmethod
    async def get_vehicle(self, vehicle_id: str) -> Vehicle | None:
        """Return the vehicle, or None if `vehicle_id` does not exist."""

    @abstractmethod
    async def update_vehicle_machine_no(self, vehicle_id: str, machine_no: str) -> Vehicle:
        """Update the operational machine number. `vehicle_id` never changes."""

    @abstractmethod
    async def list_vehicle_components(self, vehicle_id: str) -> list[VehicleComponent]:
        """Return the component-role read model for one vehicle."""

    @abstractmethod
    async def list_vehicle_status_history(
        self, vehicle_id: str
    ) -> list[VehicleStatusHistoryEntry]:
        """Return all status-history entries for one vehicle, newest first."""

    @abstractmethod
    async def change_vehicle_status(
        self,
        vehicle_id: str,
        new_status: OperationalStatus,
        changed_by: str | None,
        note: str | None,
    ) -> VehicleStatusHistoryEntry:
        """Append a new status-history entry and update the vehicle's
        current status. Must never overwrite a previous entry."""

    # ---- Workshop equipment (Phase 2) ----

    @abstractmethod
    async def list_equipment(
        self, q: str | None, category: EquipmentCategory | None, params: PageParams
    ) -> tuple[list[Equipment], int]:
        """Return (page of equipment matching the filters, total matching count)."""

    @abstractmethod
    async def get_equipment(self, equipment_id: str) -> Equipment | None:
        """Return the equipment item, or None if `equipment_id` does not exist."""

    # ---- Checklist / inspection (Phase 3) ----

    @abstractmethod
    async def get_active_checklist_revision(
        self, asset_type: AssetType
    ) -> ChecklistRevisionDetail | None:
        """Return the checklist revision currently effective for
        `asset_type`, with its items, or None if no checklist is configured
        for that asset type. Selection is by `effective_date` within one
        checklist family per asset type (see `app.domain.checklist` module
        docstring for why: OPEN_DECISIONS_REGISTER_EN.txt D01 has no
        approved asset/model assignment policy yet)."""

    @abstractmethod
    async def get_checklist_revision(
        self, checklist_id: str, revision_id: str
    ) -> ChecklistRevisionDetail | None:
        """Return one specific historical revision by ID, or None if it
        does not exist. Proves old revisions remain readable even after a
        newer revision becomes active."""

    @abstractmethod
    async def create_attachment(
        self,
        purpose: AttachmentPurpose,
        storage_ref: str,
        filename: str,
        content_type: str,
        size_bytes: int,
        uploaded_by: str | None,
    ) -> Attachment:
        """Record metadata for a file already saved via StorageProvider."""

    @abstractmethod
    async def get_attachment(self, attachment_id: str) -> Attachment | None:
        """Return attachment metadata, or None if it does not exist."""

    @abstractmethod
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
    ) -> InspectionDetail:
        """Persist a new immutable inspection submission: header + item
        results + one OPEN finding per FAIL item. Must never mutate or
        remove any previously stored inspection."""

    @abstractmethod
    async def get_inspection(self, inspection_id: str) -> InspectionDetail | None:
        """Return one inspection submission, or None if it does not exist."""

    @abstractmethod
    async def list_inspections(
        self,
        asset_type: AssetType | None,
        asset_id: str | None,
        params: PageParams,
    ) -> tuple[list[InspectionSummary], int]:
        """Return (page of inspection summaries newest first, total matching
        count), optionally filtered to one asset."""

    @abstractmethod
    async def find_inspection_finding(self, finding_id: str) -> InspectionFinding | None:
        """Look up one finding across all stored inspections, or None if it
        does not exist. Used only to validate a Repair's FINDING source
        link (Phase 4) — never mutates the finding."""

    @abstractmethod
    async def find_inspection_result(self, result_id: str) -> InspectionItemResult | None:
        """Look up one inspection item result across all stored
        inspections, or None if it does not exist. Used only to validate a
        Repair's INSPECTION_RESULT source link (Phase 4)."""

    # ---- PM plan / task revision (Phase 4) ----

    @abstractmethod
    async def list_pm_plans(
        self, asset_type: AssetType | None, model_id: str | None
    ) -> list[PmPlan]:
        """Return PM plans applicable to `asset_type` and, when a plan
        declares `model_ids`, matching `model_id` (see `app.domain.pm`
        module docstring — a metadata-only scope filter, not an assignment
        matrix)."""

    @abstractmethod
    async def get_pm_plan(self, pm_plan_id: str) -> PmPlan | None:
        """Return the plan, or None if `pm_plan_id` does not exist."""

    @abstractmethod
    async def get_active_pm_task_revision(self, pm_plan_id: str) -> PmTaskRevisionDetail | None:
        """Return the task revision currently effective for `pm_plan_id`,
        with its tasks, or None if the plan has no task revision (e.g. a
        plan with no approved source data yet — E05)."""

    @abstractmethod
    async def get_pm_task_revision(
        self, pm_plan_id: str, revision_id: str
    ) -> PmTaskRevisionDetail | None:
        """Return one specific historical task revision by ID, or None if
        it does not exist. Proves old revisions remain readable even after
        a newer revision becomes active."""

    # ---- PM work order / work result (Phase 4) ----

    @abstractmethod
    async def create_pm_work_order(
        self,
        asset_type: AssetType,
        asset_id: str,
        pm_plan_id: str,
        revision_id: str,
        due_reason: PmTriggerType | None,
        opened_by: str | None,
        note: str | None,
    ) -> PmWorkOrder:
        """Open a new PM work order against the given plan/task revision."""

    @abstractmethod
    async def get_pm_work_order(self, pm_work_order_id: str) -> PmWorkOrderDetail | None:
        """Return one work order with all of its task results, or None if
        it does not exist."""

    @abstractmethod
    async def list_pm_work_orders(
        self,
        asset_type: AssetType | None,
        asset_id: str | None,
        params: PageParams,
    ) -> tuple[list[PmWorkOrderSummary], int]:
        """Return (page of work order summaries newest first, total
        matching count), optionally filtered to one asset."""

    @abstractmethod
    async def get_last_closed_pm_work_order(
        self, asset_type: AssetType, asset_id: str, pm_plan_id: str
    ) -> PmWorkOrderDetail | None:
        """Return the most recently CLOSED work order for this asset/plan,
        or None if none has ever been closed. Used only to report the fact
        of the last completion (never to compute a due/remaining value —
        E02/E03/E04 remain unresolved)."""

    @abstractmethod
    async def close_pm_work_order(
        self, pm_work_order_id: str, closed_by: str | None, note: str | None
    ) -> PmWorkOrder:
        """Mark a work order CLOSED. Must never be called on an already
        non-existent work order (the service layer checks existence
        first)."""

    @abstractmethod
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
        """Persist one immutable task result. Must never overwrite or
        remove a previously stored result for the same task within the
        same work order (the service layer also checks this, but the
        repository must never silently allow it either)."""

    @abstractmethod
    async def find_pm_work_result(self, pm_work_result_id: str) -> PmWorkResult | None:
        """Look up one PM work result across all stored work orders, or
        None if it does not exist. Used only to validate a Repair's
        PM_RESULT source link (Phase 4)."""

    # ---- Meter snapshot (Phase 4) ----

    @abstractmethod
    async def create_meter_snapshot(
        self,
        asset_type: AssetType,
        asset_id: str,
        readings: list[MeterReading],
        recorded_by: str | None,
    ) -> MeterSnapshot:
        """Persist one immutable meter/counter snapshot."""

    @abstractmethod
    async def get_meter_snapshot(self, meter_snapshot_id: str) -> MeterSnapshot | None:
        """Return the snapshot, or None if it does not exist."""

    # ---- Repair (Phase 4) ----

    @abstractmethod
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
    ) -> Repair:
        """Create a new repair header. Never mutates any source record
        (finding/inspection result/PM result) referenced by `source_id`."""

    @abstractmethod
    async def get_repair(self, repair_id: str) -> RepairDetail | None:
        """Return one repair with its actions and parts, or None if it
        does not exist."""

    @abstractmethod
    async def list_repairs(
        self,
        asset_type: AssetType | None,
        asset_id: str | None,
        status: RepairStatus | None,
        params: PageParams,
    ) -> tuple[list[RepairSummary], int]:
        """Return (page of repair summaries newest first, total matching
        count), optionally filtered to one asset and/or status."""

    @abstractmethod
    async def add_repair_action(
        self,
        repair_id: str,
        action_text: str,
        actor: str | None,
        attachment_ids: list[str],
    ) -> None:
        """Append one action to a repair's history. Must never edit or
        remove a previously appended action (baseline section 10:
        "Repair action history is append-only")."""

    @abstractmethod
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
        """Append one actual-part-used record to a repair. `part_id`/
        `part_instance_id`/`action` are additive Phase 5 fields (see
        `app.domain.repair.RepairPart`)."""

    @abstractmethod
    async def close_repair(
        self, repair_id: str, closed_by: str | None, close_note: str | None
    ) -> Repair:
        """Mark a repair CLOSED."""

    # ---- Part Master / Part Set (Phase 5) ----

    @abstractmethod
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
        """Create a new Part Master on demand. Different specifications
        always get a different `part_id`, even when `name` matches an
        existing part."""

    @abstractmethod
    async def get_part_master(self, part_id: str) -> PartMaster | None:
        """Return the part, or None if `part_id` does not exist."""

    @abstractmethod
    async def list_part_masters(
        self, q: str | None, tracking_mode: TrackingMode | None, params: PageParams
    ) -> tuple[list[PartMaster], int]:
        """Return (page of parts matching the filters, total matching count)."""

    @abstractmethod
    async def create_part_set(self, set_code: str, name: str) -> PartSet:
        """Create a new Part Set / Kit identity (no revision yet)."""

    @abstractmethod
    async def get_part_set(self, part_set_id: str) -> PartSet | None:
        """Return the part set, or None if `part_set_id` does not exist."""

    @abstractmethod
    async def create_part_set_revision(
        self,
        part_set_id: str,
        effective_date: date,
        items: list[dict],
    ) -> PartSetRevisionDetail:
        """Create an entirely new, immutable Part Set revision. Must never
        edit a previous revision's items (baseline section 15: "A later
        kit revision must not rewrite historical PM/Repair usage")."""

    @abstractmethod
    async def get_active_part_set_revision(self, part_set_id: str) -> PartSetRevisionDetail | None:
        """Return the revision currently effective for `part_set_id`, or
        None if none is configured."""

    @abstractmethod
    async def get_part_set_revision(
        self, part_set_id: str, revision_id: str
    ) -> PartSetRevisionDetail | None:
        """Return one specific historical revision by ID, or None if it
        does not exist. Proves old revisions remain readable."""

    # ---- Part Instance / lifecycle / installation segment (Phase 5) ----

    @abstractmethod
    async def create_part_instance(
        self,
        part_id: str,
        serial_number: str | None,
        prior_usage: PriorUsage,
        note: str | None,
        created_by: str | None,
    ) -> PartInstanceDetail:
        """Create a new PartInstance on demand, together with its first
        `PartLifecycle` (start_reason=ENROLLMENT). Never pre-registered for
        an entire machine's BOM (guardrails section 12)."""

    @abstractmethod
    async def get_part_instance(self, part_instance_id: str) -> PartInstanceDetail | None:
        """Return the instance with every lifecycle and every installation
        segment across every lifecycle, or None if it does not exist."""

    @abstractmethod
    async def list_part_instances(
        self, part_id: str | None, status: PartInstanceStatus | None, params: PageParams
    ) -> tuple[list[PartInstanceDetail], int]:
        """Return (page of instances matching the filters, total matching
        count)."""

    @abstractmethod
    async def update_part_instance_status(
        self, part_instance_id: str, status: PartInstanceStatus
    ) -> None:
        """Update only the instance's current status. Never used to alter
        any other field."""

    @abstractmethod
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
        """Append a new ACTIVE installation segment. Must never edit or
        remove a previously stored segment (baseline section 13:
        append-oriented history)."""

    @abstractmethod
    async def close_installation_segment(
        self,
        segment_id: str,
        removed_by: str | None,
        removal_meter_snapshot_id: str | None,
        removal_reason: str | None,
    ) -> InstallationSegment:
        """Set `removed_at`/status=CLOSED on an existing segment. Must
        never edit any other field of a previously stored segment."""

    @abstractmethod
    async def start_new_part_lifecycle(
        self,
        part_instance_id: str,
        start_reason: LifecycleStartReason,
        started_note: str | None,
        started_by: str | None,
    ) -> None:
        """End the instance's current `PartLifecycle` (`ended_at` set) and
        create a new one as `current_lifecycle_id`. Must never edit or
        remove the previous lifecycle or any of its installation segments
        (OPEN_DECISIONS_REGISTER_EN.txt G04: "preserve all old lifecycle
        history")."""

    # ---- Position lifetime (Phase 5) ----

    @abstractmethod
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
        """Create a new position-lifetime enrollment. Never requires a
        serialized PartInstance."""

    @abstractmethod
    async def get_position_lifetime(
        self, position_lifetime_id: str
    ) -> PositionLifetimeRecord | None:
        """Return the record, or None if it does not exist."""

    @abstractmethod
    async def list_position_lifetime_for_asset(
        self, asset_type: AssetType, asset_id: str
    ) -> list[PositionLifetimeRecord]:
        """Return every position-lifetime record for one asset."""

    # ---- Lifetime rule (Phase 5) ----

    @abstractmethod
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
        """Create a new lifetime rule. Structural only — see
        `app.domain.lifetime_rule` module docstring (G01/G02
        SOURCE-DATA-REQUIRED)."""

    @abstractmethod
    async def get_lifetime_rule(self, lifetime_rule_id: str) -> LifetimeRule | None:
        """Return the rule, or None if it does not exist."""

    @abstractmethod
    async def list_lifetime_rules_for_part(self, part_id: str) -> list[LifetimeRule]:
        """Return every lifetime rule declared for one part."""
