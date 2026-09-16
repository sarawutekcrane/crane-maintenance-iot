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
from app.domain.assignment import PmAssignmentHistoryEntry, RepairAssignmentHistoryEntry
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
    NewInspectionItemInput,
    InspectionSummary,
)
from app.domain.lifetime_rule import LifetimeRule, LifetimeRuleScope, LifetimeTriggerType
from app.domain.location_snapshot import LocationSnapshot
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
    PmScopeAdditionAudit,
    PmTaskRevisionDetail,
    PmTriggerType,
    PmWorkOrder,
    PmWorkOrderDetail,
    PmWorkOrderSummary,
    PmWorkResult,
)
from app.domain.position_lifetime import PositionLifetimeRecord
from app.domain.repair import Repair, RepairDetail, RepairSourceType, RepairStatus, RepairSummary
from app.domain.repair_request import RepairRequest
from app.domain.requisition import (
    MaterialRequest,
    MaterialRequestDetail,
    RequisitionLine,
    RequisitionSourceType,
)
from app.domain.vehicle import Vehicle, VehicleComponent, VehicleStatusHistoryEntry
from app.domain.vehicle_model import ComponentRole, VehicleModel


class RepositoryError(Exception):
    """Raised when a repository cannot serve a request (connectivity,
    missing schema, etc.). Domain/service code should translate this into
    an ApiError; it must never leak raw driver exceptions (e.g. Google API
    exceptions) upward.
    """


class RepositoryFeatureNotImplementedError(RepositoryError):
    """F3 cross-phase integration fix: raised for a repository operation
    that is KNOWN and intentionally unimplemented for the active
    `DATA_REPOSITORY` mode (the Google Sheets stubs still pending real I/O
    — see docs/phase-results/core-demo-fixes-result.md) — as distinct from
    `RepositoryError`'s other, unexpected failure conditions (connectivity,
    misconfiguration) and from an ordinary programming defect. Callers
    should let this propagate; `app.errors` maps it to a stable,
    user-safe `FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE` API error rather
    than the generic `INTERNAL_ERROR` an unrecognized exception gets."""

    def __init__(self, feature: str) -> None:
        self.feature = feature
        super().__init__(
            f"'{feature}' is not implemented for the active repository mode"
        )


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

    @abstractmethod
    async def change_equipment_status(
        self,
        equipment_id: str,
        status: EquipmentOperationalStatus,
        reason: str | None,
        changed_by: str | None,
    ) -> Equipment:
        """Append a new status-history entry (never overwriting a previous
        one) and update the equipment's current status. Mirrors
        `change_vehicle_status`'s identical append-only pattern."""

    @abstractmethod
    async def list_equipment_status_history(
        self, equipment_id: str
    ) -> list[EquipmentStatusHistoryEntry]:
        """Return every status-history entry for this equipment, oldest
        first."""

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
        source_type: str | None = None,
        source_id: str | None = None,
    ) -> Attachment:
        """Record metadata for a file already saved via StorageProvider.
        `source_type`/`source_id` (REV05 section 4) are additive/optional —
        only `RepairRequest` uploads set them today (see
        `app.domain.attachment.Attachment.source_type` docstring)."""

    @abstractmethod
    async def get_attachment(self, attachment_id: str) -> Attachment | None:
        """Return attachment metadata, or None if it does not exist."""

    @abstractmethod
    async def list_attachments_for_source(
        self, source_type: str, source_id: str
    ) -> list[Attachment]:
        """Return every attachment uploaded with this exact
        `source_type`/`source_id` pair, oldest first."""

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
        machine_state_snapshot_id: str | None = None,
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

    @abstractmethod
    async def list_inspection_findings(
        self,
        asset_type: AssetType | None,
        asset_id: str | None,
        status: FindingStatus | None,
    ) -> list[InspectionFinding]:
        """Return findings across all stored inspections, optionally
        filtered to one asset and/or status (Core Demo Fixes, VEHICLE LIST
        indicator: "unresolved inspection finding"). Never mutates a
        finding."""

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
        opened_snapshot_id: str | None = None,
        scope_task_ids: list[str] | None = None,
    ) -> PmWorkOrder:
        """Open a new PM work order against the given plan/task revision."""

    @abstractmethod
    async def add_pm_scope_task(
        self,
        pm_work_order_id: str,
        pm_task_id: str,
        added_by: str | None,
        reason: str,
    ) -> PmScopeAdditionAudit:
        """Append `pm_task_id` to the work order's `scope_task_ids` and
        record an audit entry. Must never be called once scope is
        approved (the service layer enforces this)."""

    @abstractmethod
    async def approve_pm_scope(
        self, pm_work_order_id: str, approved_by: str | None
    ) -> PmWorkOrder:
        """Freeze `scope_task_ids` by setting `scope_approved_at`/`by`."""

    @abstractmethod
    async def assign_pm_work_order(
        self,
        pm_work_order_id: str,
        primary_technician: str | None,
        collaborators: list[str],
        assigned_by: str | None = None,
    ) -> PmWorkOrder:
        """Set/replace the PM work order's technician/team assignment
        (Core Demo Fixes Delta section B) — structurally symmetric with
        `assign_repair`, not a production RBAC/authentication system.
        Appends/ends `PmAssignmentHistoryEntry` rows non-destructively."""

    @abstractmethod
    async def list_pm_work_order_assignment_history(
        self, pm_work_order_id: str
    ) -> list[PmAssignmentHistoryEntry]:
        """Return every assignment history entry for one PM work order,
        oldest first."""

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
        status=None,
        assigned_to: str | None = None,
    ) -> tuple[list[PmWorkOrderSummary], int]:
        """Return (page of work order summaries newest first, total
        matching count), optionally filtered to one asset, status, and/or
        the actor assigned as primary technician or collaborator
        (`assigned_to`, REV06 section 18 — "PM My Work", derived exactly
        like `list_repairs(assigned_to=...)`, never a separate table)."""

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
        self,
        pm_work_order_id: str,
        closed_by: str | None,
        note: str | None,
        closed_snapshot_id: str | None = None,
    ) -> PmWorkOrder:
        """Mark a work order CLOSED. Must never be called on an already
        non-existent work order (the service layer checks existence
        first).

        Must also end every currently-active `PmAssignmentHistoryEntry`
        row for this work order (PRIMARY and every active collaborator)
        — `assigned_at`/`ended_at` timestamps aside, use this same
        closure moment for `ended_at` — so `pm_work_assignment` history,
        which is authoritative, never keeps reporting someone as still
        actively assigned to a CLOSED work order. Non-destructive: end
        each row in place (`active_status=False`, `ended_at` set), never
        delete or edit any other field of it, and never touch a row
        belonging to a different work order — mirrors `close_repair`'s
        own identical requirement and `assign_pm_work_order`'s own
        non-destructive ending of a superseded assignment, just with no
        replacement row appended afterward."""

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
        is_automatic: bool = False,
        latitude: float | None = None,
        longitude: float | None = None,
        gps_observed_at=None,
        source_note: str | None = None,
    ) -> MeterSnapshot:
        """Persist one immutable meter/counter snapshot. `is_automatic`
        distinguishes a backend-derived snapshot (Core Demo Fix automatic
        machine-state snapshot) from a caller-supplied manual reading."""

    @abstractmethod
    async def get_meter_snapshot(self, meter_snapshot_id: str) -> MeterSnapshot | None:
        """Return the snapshot, or None if it does not exist."""

    @abstractmethod
    async def list_meter_snapshots_for_asset(
        self, asset_type: AssetType, asset_id: str
    ) -> list[MeterSnapshot]:
        """Return every meter snapshot ever recorded for this asset (any
        order) — used only by `MeterService.capture_current_state` to carry
        forward the latest known reading per counter dimension. Never used
        to compute a due/remaining value."""

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
        primary_technician: str | None = None,
        collaborators: list[str] | None = None,
    ) -> Repair:
        """Create a new repair header. Never mutates any source record
        (finding/inspection result/PM result) referenced by `source_id`.
        Always creates a new `repair_id` — a later repair occurrence must
        never reuse a closed one (Core Demo Fixes prompt, REPAIR WORKFLOW
        CORRECTIONS section A)."""

    @abstractmethod
    async def get_repair(self, repair_id: str) -> RepairDetail | None:
        """Return one repair with its actions and parts, or None if it
        does not exist."""

    @abstractmethod
    async def find_repairs_by_source(
        self, source_type: RepairSourceType, source_id: str
    ) -> list[Repair]:
        """REV06.1 (independent-audit CONSISTENCY-1 fix): return every
        repair whose own `source_type`/`source_id` matches — normally
        zero or one. `RepairRequestService.convert()` uses this to recover
        deterministically from a partial-failure retry (Google Sheets is
        non-transactional: `create_repair` and
        `mark_repair_request_converted` are two separate writes) instead of
        blindly creating a second `RPR-xxxx` for the same Repair Request.
        More than one match means an earlier conversion attempt already
        corrupted state — callers must refuse to create a third rather
        than silently picking one."""

    @abstractmethod
    async def list_repairs(
        self,
        asset_type: AssetType | None,
        asset_id: str | None,
        status: RepairStatus | None,
        params: PageParams,
        assigned_to: str | None = None,
        unassigned_only: bool = False,
    ) -> tuple[list[RepairSummary], int]:
        """Return (page of repair summaries newest first, total matching
        count), optionally filtered to one asset, status, and/or the actor
        assigned as primary technician or collaborator (`assigned_to`) —
        used by the "งานของฉัน" (My Work) page. `unassigned_only` (REV05
        section 5B, "รอมอบหมายช่าง") filters to repairs with no active
        PRIMARY technician. REV06.2 (independent-audit MEDIUM fix): both
        filters are derived from active `repair_assignment` history (the
        same authoritative source `RepairService.get_active_assignment`
        and Repair action/part authorization already use) — never the
        denormalized `primary_technician`/`collaborators` columns, which
        `assign_repair` keeps in sync as a second, non-transactional write
        and can therefore go stale relative to history. Never a separate
        stored queue/table either way."""

    @abstractmethod
    async def assign_repair(
        self,
        repair_id: str,
        primary_technician: str | None,
        collaborators: list[str],
        assigned_by: str | None = None,
    ) -> Repair:
        """Set/replace the repair's assignment. Not a production RBAC
        system — see `app.domain.repair` module docstring. Must also
        append/end `RepairAssignmentHistoryEntry` rows non-destructively
        (Core Demo Fixes Delta section A) — a reassignment ends the
        previous active row(s) rather than deleting them."""

    @abstractmethod
    async def list_repair_assignment_history(
        self, repair_id: str
    ) -> list[RepairAssignmentHistoryEntry]:
        """Return every assignment history entry for one repair, oldest
        first."""

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
        self,
        repair_id: str,
        closed_by: str | None,
        close_note: str | None,
        closed_snapshot_id: str | None = None,
    ) -> Repair:
        """Mark a repair CLOSED. Must also end every currently-active
        `RepairAssignmentHistoryEntry` row for this repair (PRIMARY and
        every active collaborator) — `assigned_at`/`ended_at` timestamps
        aside, use this same closure moment for `ended_at` — so
        `repair_assignment` history, which is authoritative, never keeps
        reporting someone as still actively assigned to a CLOSED repair.
        Non-destructive: end each row in place (`active_status=False`,
        `ended_at` set), never delete or edit any other field of it —
        mirrors `assign_repair`'s own non-destructive ending of a
        superseded assignment exactly, just with no replacement row
        appended afterward."""

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

    # ---- Location snapshot (Core Demo Fixes Delta section E) ----

    @abstractmethod
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
        """Persist one immutable location snapshot, backend-derived from
        `latest_location`. Never fabricates a `0, 0` coordinate — see
        `app.domain.location_snapshot` module docstring."""

    @abstractmethod
    async def get_location_snapshot(self, location_snapshot_id: str) -> LocationSnapshot | None:
        """Return the snapshot, or None if it does not exist."""

    @abstractmethod
    async def list_location_snapshots_for_event(self, event_id: str) -> list[LocationSnapshot]:
        """Return the location snapshot(s) captured for the same event_id
        as a `MeterSnapshot.meter_snapshot_id` — usually zero (EQUIPMENT)
        or one."""

    # ---- Material request (Core Demo Fixes Delta, Store/Inventory boundary) ----

    @abstractmethod
    async def create_material_request(
        self,
        source_type: RequisitionSourceType,
        source_work_order_id: str,
        vehicle_id: str | None,
        created_by: str | None,
        note: str | None = None,
    ) -> MaterialRequest:
        """Create a requisition header referencing a PM work order or
        repair ID. Never decrements any stock balance, never assigns a
        Store approval/transition status beyond the default "OPEN" — see
        `app.domain.requisition` module docstring."""

    @abstractmethod
    async def get_material_request(self, material_request_id: str) -> MaterialRequestDetail | None:
        """Return the requisition header with its lines, or None if it
        does not exist."""

    @abstractmethod
    async def list_material_requests_for_work_order(
        self, source_work_order_id: str
    ) -> list[MaterialRequest]:
        """Return every requisition header raised for one PM work order or
        repair ID (oldest first). Used by the derived "waiting for parts"
        indicator — never a stored/duplicated repair lifecycle state."""

    @abstractmethod
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
        """Append a requisition line to an existing `MaterialRequest`
        header. Never decrements any stock balance."""

    @abstractmethod
    async def list_requisition_lines_for_work_order(
        self, work_order_reference: str
    ) -> list[RequisitionLine]:
        """Return every requisition line across every requisition header
        raised for one PM work order/repair ID."""

    # ---- Repair Request (Core Demo Fixes Delta REV05 section 3) ----

    @abstractmethod
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
        """Create a pending Repair Request row — never a Repair Work
        Order. `request_status` starts as `PENDING`. `meter_snapshot_id`
        is a domain-only convenience (see
        `app.domain.repair_request.RepairRequest.meter_snapshot_id`)."""

    @abstractmethod
    async def get_repair_request(self, repair_request_id: str) -> RepairRequest | None:
        """Return the Repair Request, or None if it does not exist."""

    @abstractmethod
    async def list_pending_repair_requests(
        self, params: PageParams
    ) -> tuple[list[RepairRequest], int]:
        """รายการแจ้งซ่อมรอตรวจรับ — every Repair Request with
        `request_status == "PENDING"`, oldest first."""

    @abstractmethod
    async def list_repair_requests_by_reporter(
        self, reported_by_user_id: str, params: PageParams
    ) -> tuple[list[RepairRequest], int]:
        """Web UAT Defect Fix UAT-F2: every Repair Request this reporter
        created (any `request_status`), newest first — backs "คำขอแจ้งซ่อม
        ของฉัน" so a DRIVER/TECHNICIAN can find a request they already
        submitted. Strictly narrower than `get_repair_request`'s existing
        unrestricted lookup-by-id: results are always scoped to rows this
        exact `reported_by_user_id` created, so this exposes no more than
        that already-unrestricted single-record read already allows."""

    @abstractmethod
    async def list_repair_requests_by_source(
        self, source_type: str, source_id: str
    ) -> list[RepairRequest]:
        """Web UAT Defect Fix UAT-F3: every Repair Request whose decoded
        provenance (`app.domain.repair_request.decode_provenance_note`)
        matches this Finding/PM Work Result — normally zero or one.
        Mirrors `find_repairs_by_source` below; lets the UI derive
        "already reported" from persisted state instead of client-only
        state that disappears on reload."""

    @abstractmethod
    async def mark_repair_request_converted(
        self,
        repair_request_id: str,
        repair_id: str,
        reviewed_by_user_id: str | None,
    ) -> RepairRequest:
        """Record that this Repair Request was accepted/converted into
        `repair_id` — sets `request_status="CONVERTED"`,
        `reviewed_by_user_id`/`reviewed_at`/`repair_id`/`converted_at`.
        Never called twice for the same request with a different
        `repair_id` (see `RepairRequestService.convert`, which is the
        single place idempotency against a retried conversion is
        enforced)."""
