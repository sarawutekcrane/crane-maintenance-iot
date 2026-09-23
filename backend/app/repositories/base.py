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
from dataclasses import dataclass, field
from datetime import date, datetime

from app.domain.asset import AssetType
from app.domain.assignment import PmAssignmentHistoryEntry, RepairAssignmentHistoryEntry
from app.domain.attachment import Attachment, AttachmentPurpose
from app.domain.checklist import ChecklistRevisionDetail
from app.domain.common import OperationalStatus, PageParams
from app.domain.driver import Driver, VehicleDriverAssignment
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
from app.domain.location_snapshot import CurrentLocation, LocationSnapshot
from app.domain.meter import CurrentCounterReading, MeterReading, MeterSnapshot
from app.domain.model_document import ModelDocument
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
from app.domain.alert import Alert, AlertStatus
from app.domain.alert_setting import AlertSetting
from app.domain.daily_summary import DailySummary, DailySummaryDataStatus, DailySummaryMetricType
from app.domain.vehicle import Vehicle, VehicleComponent, VehicleStatusHistoryEntry
from app.domain.vehicle_certificate import CertificateStatus, VehicleCertificate
from app.domain.certificate_expiry_report import CertificateReportRead
from app.domain.vehicle_event import TimeQuality, VehicleEvent, VehicleEventType
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


class RepositorySchemaError(RepositoryError):
    """Phase 7 Batch 7B2: a PROVEN structural problem with a backing
    table (tab confirmed missing, no header row, missing/duplicate
    headers, or data the header cannot name) — as distinct from an
    unclassified read failure, which stays a plain `RepositoryError`.
    `problem` is one of the `SCHEMA_PROBLEM_*` codes in
    `app.domain.fleet_summary`; `headers` names the headers concerned."""

    def __init__(self, tab: str, problem: str, headers: tuple[str, ...] = ()) -> None:
        self.tab = tab
        self.problem = problem
        self.headers = headers
        detail = f": {', '.join(headers)}" if headers else ""
        super().__init__(f"'{tab}' schema is invalid ({problem}){detail}")


@dataclass(frozen=True)
class VehicleMasterSummaryRead:
    """Phase 7 Batch 7B2: result of one validated vehicle-master read for
    the fleet status summary. `vehicles` are the records that passed the
    repository's status/mapping checks; `issue_counts` counts the records
    that did not (by issue code), and `issue_vehicle_ids` lists their
    non-blank vehicle ids. Identity checks (blank/duplicate ids) are made
    by the service over `vehicles`."""

    vehicles: list[Vehicle]
    issue_counts: dict[str, int] = field(default_factory=dict)
    issue_vehicle_ids: list[str] = field(default_factory=list)


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
    async def read_vehicle_master_for_summary(self) -> VehicleMasterSummaryRead:
        """Phase 7 Batch 7B2: read every vehicle master record ONCE for the
        fleet status summary, read-only. Raises `RepositorySchemaError`
        for a proven structural problem and `RepositoryError` for any
        other read failure; never returns partial data silently."""

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
        order) — immutable historical capture. `MeterService.
        capture_current_state` sources its values from `current_counter`
        (`list_current_counters`) instead, never from this history; never
        used to compute a due/remaining value."""

    @abstractmethod
    async def list_current_counters(self, vehicle_id: str) -> list[CurrentCounterReading]:
        """Return the authoritative CURRENT counter state rows
        (`current_counter`) for one vehicle — REV05: the current-state
        half of the shared automatic machine-state snapshot mechanism,
        distinct from `meter_snapshot`'s immutable historical capture.
        A dimension with no row is simply absent from the returned list
        (UNKNOWN, never fabricated `0`) — the caller (`MeterService.
        _current_readings`) never falls back to snapshot history for a
        missing dimension."""

    @abstractmethod
    async def get_current_location(self, vehicle_id: str) -> CurrentLocation | None:
        """Return the authoritative CURRENT location state
        (`latest_location`) for one vehicle, or `None` if no row exists —
        REV05: the current-state half of the shared automatic
        machine-state snapshot mechanism, distinct from
        `location_snapshot`'s immutable historical capture."""

    @abstractmethod
    async def upsert_current_location(
        self,
        vehicle_id: str,
        latitude: float | None,
        longitude: float | None,
        gps_time: datetime | None,
        received_at: datetime | None,
        source_device_id: str | None,
        source_component_id: str | None,
    ) -> CurrentLocation:
        """Web/API Phase 6 Batch 4B. Create or replace the single
        authoritative CURRENT location row for `vehicle_id` — at most one
        row per vehicle ever exists; if none exists yet this creates it,
        if one exists this replaces it in place (a targeted update, never
        a full-sheet rewrite). Writes unconditionally exactly the 6
        fields given — this method itself performs no eligibility/
        ordering comparison (never checks `gps_time` against what was
        previously stored); the caller
        (`app.domain.vehicle_event_service.VehicleEventService.
        _project_latest_location`) is solely responsible for deciding
        WHETHER and with what values to call this, per the Batch 4B
        frozen current-state-ordering rules."""

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
        stored queue/table either way.

        Phase 7 Batch 7C2: ordering is `(opened_at, repair_id)` descending
        — the repair_id string is only a tie-breaker for equal timestamps
        (plain string order; numeric suffixes are not interpreted, and
        identical pairs keep no identity-based order)."""

    @abstractmethod
    async def list_open_repairs_for_report(
        self, asset_type: AssetType | None, params: PageParams
    ) -> tuple[list[RepairSummary], int]:
        """Phase 7 Batch 7C2 open-repair report ("งานซ่อมค้าง"): the OPEN
        repair work orders (vehicles and equipment unless `asset_type`
        narrows it), with the same mapping, defaults, ordering, action
        counts and pagination as `list_repairs(status=OPEN)`. Read-only.
        No deduplication: blank or repeated repair ids stay separate rows.

        Unlike `list_repairs`, a backing store that has raw headers must
        validate the repair table's structure on the SAME response its
        rows come from, and raise `RepositorySchemaError` for a proven
        structural problem instead of returning a false empty/defaulted
        result; any other read failure raises `RepositoryError`."""

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

    # ---- Driver / Operator (Web/API Phase 6 Batch 1) ----
    # Verified live sheets `driver_master` / `vehicle_driver` — see
    # `app.domain.driver` module docstring for the exact header mapping
    # and the NO-GUESSING RULE governing `active_status`/
    # `assignment_status` (plain opaque strings, never an Enum).

    @abstractmethod
    async def create_driver(
        self,
        driver_name_th: str,
        phone: str | None,
        license_no: str | None,
        license_expiry_date: date | None,
        active_status: str | None,
        note_th: str | None,
    ) -> Driver:
        """Create a new driver/operator master record."""

    @abstractmethod
    async def get_driver(self, driver_id: str) -> Driver | None:
        """Return the driver, or None if it does not exist."""

    @abstractmethod
    async def list_drivers(
        self, q: str | None, params: PageParams
    ) -> tuple[list[Driver], int]:
        """Return drivers matching free-text `q` (name/phone/license_no),
        paginated."""

    @abstractmethod
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
        """Replace the driver's own mutable fields. `driver_id` never
        changes. Full-replace contract, unchanged by the Phase 6 Batch 1
        LIVE UAT PATCH-preservation defect fix: resolving an HTTP PATCH
        request's "field omitted vs explicit null" distinction is the
        caller's responsibility (`DriverService.update_driver`), not
        this repository method's — every parameter here is always the
        final value to store."""

    @abstractmethod
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
        """Append a new vehicle<->driver assignment period. Never mutates
        or removes any existing `VehicleDriverAssignment` row — a caller
        that wants a prior period closed calls
        `end_vehicle_driver_assignment` explicitly/first (see
        `DriverService.assign_driver`)."""

    @abstractmethod
    async def get_vehicle_driver_assignment(
        self, assignment_id: str
    ) -> VehicleDriverAssignment | None:
        """Return the assignment, or None if it does not exist."""

    @abstractmethod
    async def end_vehicle_driver_assignment(
        self,
        assignment_id: str,
        end_at: datetime,
        changed_by_user_id: str | None,
    ) -> VehicleDriverAssignment:
        """Close one existing assignment period in place (`end_at`/
        `changed_by_user_id` set) — never deletes the row, and never
        creates a new one."""

    @abstractmethod
    async def list_vehicle_driver_assignments(
        self, vehicle_id: str
    ) -> list[VehicleDriverAssignment]:
        """Return every assignment period ever recorded for this vehicle
        (any status, active or ended), for the full history view."""

    # ---- Vehicle Certificate (Web/API Phase 6 Batch 2A) ----
    # Verified live sheet `vehicle_certificate` — see
    # `app.domain.vehicle_certificate` module docstring for the exact
    # header mapping. Batch 2A is create/list/get only: no update/delete
    # method exists here, and no method ever writes
    # `replaced_by_certificate_id` — renewal/replacement lifecycle is
    # deferred to Batch 2B pending unresolved project decisions.

    @abstractmethod
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
        """Append a new certificate record. Never overwrites/deletes any
        existing certificate row — a second call for the same vehicle is
        always a distinct new row (Batch 2A "certificate history
        preserved" acceptance requirement). `replaced_by_certificate_id`
        is always stored `None` by this method."""

    @abstractmethod
    async def get_vehicle_certificate(self, certificate_id: str) -> VehicleCertificate | None:
        """Return the certificate, or None if it does not exist."""

    @abstractmethod
    async def list_vehicle_certificates_for_vehicle(
        self, vehicle_id: str
    ) -> list[VehicleCertificate]:
        """Return every certificate record ever created for this vehicle
        (any status), for the full history view."""

    # ---- Vehicle Certificate lifecycle (Web/API Phase 6 Batch 2B) ----
    # Narrow, single-purpose mutation methods — never a generic PATCH.
    # Each finds the exact existing row, preserves every unrelated
    # column untouched, and modifies only the two lifecycle-transition
    # fields named in its signature. No method here ever deletes a row
    # or creates one (see `create_vehicle_certificate` above for the
    # only append path).

    @abstractmethod
    async def mark_vehicle_certificate_replaced(
        self, certificate_id: str, replaced_by_certificate_id: str
    ) -> VehicleCertificate:
        """Set `certificate_status=REPLACED` and
        `replaced_by_certificate_id=<replaced_by_certificate_id>` on the
        existing row identified by `certificate_id`. Every other column
        (including `document_no`, dates, `storage_ref`, etc.) is left
        exactly as it was. Raises if `certificate_id` does not exist."""

    @abstractmethod
    async def mark_vehicle_certificate_expired(self, certificate_id: str) -> VehicleCertificate:
        """Set `certificate_status=EXPIRED` on the existing row
        identified by `certificate_id`. `replaced_by_certificate_id` and
        every other column are left exactly as they were. Raises if
        `certificate_id` does not exist."""

    # ---- Certificate expiry report (Web/API Phase 7 Batch 7D2) ----

    @abstractmethod
    async def read_vehicle_certificates_for_report(self) -> CertificateReportRead:
        """Phase 7 Batch 7D2: read EVERY certificate record ONCE for the
        certificate expiry report, read-only — one classified
        `CertificateReportRow` per non-phantom record, in read order
        (`read_index` is a per-read position, not an identity). No vehicle
        joins, no expiry reconciliation, no writes. Row-value defects are
        classified on the rows, never raised. A backing store with raw
        headers must validate the certificate table's structure on the
        SAME response its rows come from and raise
        `RepositorySchemaError` for a proven structural problem; any other
        read failure raises `RepositoryError`."""

    # ---- Model Document (Web/API Phase 6 Batch 3A create/list/get +
    # Batch 3B revision lifecycle) ----
    # Verified live sheet `model_document` — see
    # `app.domain.model_document` module docstring for the exact header
    # mapping.

    @abstractmethod
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
        """Append a new model-document record. Never overwrites/deletes
        any existing document row — a second call for the same model is
        always a distinct new row (Batch 3A "document history preserved"
        acceptance requirement). `replaced_by_document_id` is always
        stored `None` by this method — the only method that ever links a
        row to a successor is `finalize_model_document_revision` below."""

    @abstractmethod
    async def get_model_document(self, model_document_id: str) -> ModelDocument | None:
        """Return the document, or None if it does not exist."""

    @abstractmethod
    async def list_model_documents_for_model(self, model_id: str) -> list[ModelDocument]:
        """Return every document record ever created for this model (any
        status), for the full history view."""

    @abstractmethod
    async def finalize_model_document_revision(
        self, model_document_id: str, effective_to: date, replaced_by_document_id: str
    ) -> ModelDocument:
        """Web/API Phase 6 Batch 3B. Narrow, single-purpose mutation —
        never a generic PATCH. Sets exactly `effective_to` and
        `replaced_by_document_id` on the existing row identified by
        `model_document_id`; every other column (`model_id`,
        `document_type`, `document_name_th`, `version`, `effective_from`,
        `storage_ref`, `file_status`, `active_status`, `note_th`) is left
        exactly as it was. Raises if `model_document_id` does not exist."""

    # ---- Vehicle Event (Web/API Phase 6 Batch 4A — Raw Vehicle Event
    # Foundation + Idempotent Device Event Ingestion) ----
    # See `app.domain.vehicle_event` module docstring for the full
    # frozen-contract rule set (event identity, idempotency, sequence,
    # created_offline, time_quality, event_time/received_at, device/
    # component ownership, event type, GPS). `VEHICLE_ONLINE`/
    # `DEVICE_OFFLINE` generation, latest_location writes, daily-summary
    # aggregation, and any Phase 8 Device Master concept are all
    # explicitly out of scope for every method below.

    @abstractmethod
    async def find_vehicle_event_by_device_event(
        self, device_id: str, device_event_id: str
    ) -> VehicleEvent | None:
        """Idempotency lookup — the identity is exactly `(device_id,
        device_event_id)`, never `event_time`/`event_type`/`sequence`/
        `component_id`/`latitude`/`longitude`. Returns the previously
        stored event, or `None` if this exact pair has never been
        ingested. `VehicleEventService.ingest_device_event` calls this
        BEFORE any other validation and, if it returns non-`None`,
        returns that event directly without calling
        `create_vehicle_event` — so this method itself never needs to
        guard against duplicates on the write side."""

    @abstractmethod
    async def create_vehicle_event(
        self,
        vehicle_id: str,
        device_id: str,
        component_id: str,
        event_type: VehicleEventType,
        event_time: datetime | None,
        fuel_level_value: float | None,
        fuel_level_unit: str | None,
        latitude: float | None,
        longitude: float | None,
        gps_valid: bool | None,
        note_th: str | None,
        device_event_id: str,
        sequence: int,
        created_offline: bool,
        time_quality: TimeQuality,
    ) -> VehicleEvent:
        """Append-only: always creates exactly one new row. Backend-
        generates `event_id` (opaque `EVT-` prefix, never client-
        suppliable) and `received_at` (server ingestion time, UTC, never
        client-suppliable). Never mutates, rewrites, or deletes any
        existing row — this method itself performs no idempotency check;
        the caller (`VehicleEventService`) is responsible for calling
        `find_vehicle_event_by_device_event` first."""

    @abstractmethod
    async def get_vehicle_event(self, event_id: str) -> VehicleEvent | None:
        """Return the event, or `None` if `event_id` does not exist."""

    @abstractmethod
    async def list_vehicle_events_for_vehicle(self, vehicle_id: str) -> list[VehicleEvent]:
        """Return every event ever ingested for this vehicle, in
        undefined/storage order — never assumed to be chronological here.
        Ordering for display (trusted-time vs. untrusted-time buckets,
        Batch 4A frozen contract section 16) is `VehicleEventService`'s
        responsibility, never this repository's."""

    # ---- Daily Summary (Web/API Phase 6 Batch 4C — Daily Summary
    # Reconciliation) ----
    # See `app.domain.daily_summary` module docstring and
    # `app.domain.daily_summary_service.DailySummaryService.
    # reconcile_vehicle_component` for the full frozen reconciliation
    # rule set. `daily_summary` is DERIVED current state, computed
    # entirely from `vehicle_event` — these methods never read/write
    # `vehicle_event` themselves.

    @abstractmethod
    async def upsert_daily_summary(
        self,
        summary_date: date,
        vehicle_id: str,
        component_id: str,
        metric_type: DailySummaryMetricType,
        value: float | None,
        unit: str,
        data_status: DailySummaryDataStatus,
    ) -> DailySummary:
        """Create or replace the single row for the authoritative
        uniqueness key `(summary_date, vehicle_id, component_id,
        metric_type)` — at most one row per key ever exists. If none
        exists yet, appends one with a freshly backend-generated
        `DSUM-` `daily_summary_id` and `created_at=` the current backend
        UTC time. If one already exists, updates ONLY `value`/`unit`/
        `data_status` in place (a targeted update, never a full-sheet
        rewrite) — `daily_summary_id` and the row's original `created_at`
        are always preserved unchanged. This method itself performs no
        reconciliation logic; it unconditionally stores exactly the
        derived values it is given."""

    @abstractmethod
    async def list_daily_summaries_for_vehicle(self, vehicle_id: str) -> list[DailySummary]:
        """Return the Batch-4C-MANAGED `daily_summary` rows for this
        vehicle (D23) — every date/component, but ONLY the two managed
        metric types (`ENGINE_RUN_DURATION`/`PTO_RUN_DURATION`), in
        undefined/storage order (ordering for display is the caller's
        responsibility, never this repository's). This is intentional
        bounded-context behavior, not an oversight: the underlying
        physical storage may contain additional rows for a metric type a
        later phase introduces, but `DailySummary.metric_type` is
        deliberately restricted to exactly these two values, so an
        implementation MUST filter any such row out before constructing
        one — never raise, never silently coerce/rename it into a
        supported value, and never mutate/delete it just because it
        exists. See `app.repositories.google_sheets.repository.
        GoogleSheetsRepository.list_daily_summaries_for_vehicle` for the
        concrete raw-row-filtered-before-parsing implementation this
        matters for; `MockRepository` cannot hold an unmanaged metric row
        at all, since its storage is itself typed as `DailySummary`."""

    @abstractmethod
    async def delete_daily_summary(self, daily_summary_id: str) -> None:
        """Web/API Phase 6 Batch 4C D22 review fix. Delete exactly the
        one daily_summary row identified by `daily_summary_id` — never
        `vehicle_event`, never another vehicle's/component's/metric's
        row. Deleting an already-missing `daily_summary_id` is a no-op,
        never an error (idempotent, matching this method's only caller,
        `DailySummaryService.reconcile_vehicle_component`, which computes
        staleness from its own already-fresh read and could in principle
        race with another reconciliation run in this non-transactional
        prototype)."""

    # ---- Alert (Web/API Phase 6 Batch 5A — Alert Read Foundation) ----
    # READ-ONLY: no create/update/delete/acknowledge/mute/resolve method
    # exists here or anywhere in this batch — see `app.domain.alert`
    # module docstring for why (A07 unresolved; no alert-write RBAC
    # permission exists yet).

    @abstractmethod
    async def get_alert(self, alert_id: str) -> Alert | None:
        """Return the alert, or `None` if `alert_id` does not exist."""

    @abstractmethod
    async def list_alerts_for_vehicle(self, vehicle_id: str) -> list[Alert]:
        """Return every alert row for this vehicle (any type/status), in
        undefined/storage order — ordering for display is the caller's
        (`AlertService`'s) responsibility, never this repository's."""

    # ---- Alert lifecycle (Web/API Phase 6 Batch 5B — D25, internal only)
    # ----
    # These three methods are the ONLY alert-write surface added by
    # Batch 5B, and they are internal (no HTTP route calls any of them —
    # see `app.api.v1.alerts`, unchanged by this batch). D25's actual
    # transition rules (open identity, dedup, acknowledge/mute/mute-
    # expiry/resolve) live entirely in `AlertService`; every method here
    # persists EXACTLY the state it is given and performs no business
    # validation of its own.

    @abstractmethod
    async def list_alerts_by_identity(
        self,
        vehicle_id: str,
        alert_type: str,
        source_type: str | None,
        source_id: str | None,
    ) -> list[Alert]:
        """Return every alert row (any `alert_status`, full history —
        never filtered/collapsed by status) whose
        `(vehicle_id, alert_type, source_type, source_id)` tuple exactly
        equals the given identity. Exact equality only: `None`/blank
        matches only `None`/blank, never treated as a wildcard."""

    @abstractmethod
    async def create_alert(self, alert: Alert) -> Alert:
        """Append exactly one new alert row using `alert` as given.
        Never generates `alert.alert_id` — the caller must already have
        assigned it (D25/A01: no alert_id generation strategy is
        introduced by this batch). Raises `RepositoryError` if an alert
        with this `alert_id` already exists anywhere in storage — never
        silently overwrites an existing row."""

    @abstractmethod
    async def update_alert_lifecycle(
        self,
        alert_id: str,
        *,
        alert_status: AlertStatus,
        muted_until: datetime | None,
        acknowledged_by_user_id: str | None,
        acknowledged_at: datetime | None,
        resolved_at: datetime | None,
    ) -> Alert:
        """Overwrite ONLY these five lifecycle columns on the existing
        row identified by `alert_id`. Every other column (`alert_id`,
        `vehicle_id`, `alert_type`, `source_type`, `source_id`,
        `severity`, `created_at`, `message_th`) is preserved exactly as
        stored. Raises `RepositoryError` if `alert_id` does not exist.
        Performs no transition validation itself — persists exactly the
        state `AlertService` has already decided is valid."""

    # ---- Alert Setting (Web/API Phase 6 Batch 5C — Alert Setting Read
    # Foundation) ----
    # READ-ONLY: no create/update/delete/mutation method exists here or
    # anywhere in this batch — see `app.domain.alert_setting` module
    # docstring (alert-setting precedence, DEVICE_OFFLINE timing,
    # operational-status suppression, and alert-setting write RBAC all
    # remain unresolved and are explicitly not decided by this batch).

    @abstractmethod
    async def list_alert_settings(self) -> list[AlertSetting]:
        """Return every alert_setting row, in undefined/storage order —
        deterministic display ordering is the caller's
        (`AlertSettingService`'s) responsibility, never this
        repository's."""

    @abstractmethod
    async def get_alert_setting(self, alert_setting_id: str) -> AlertSetting | None:
        """Return the alert setting, or `None` if `alert_setting_id` does
        not exist."""

    @abstractmethod
    async def list_alert_settings_for_type(self, alert_type: str) -> list[AlertSetting]:
        """Return every alert_setting row whose `alert_type` exactly
        equals the given value (opaque string equality only — no
        precedence/scope resolution of any kind), in undefined/storage
        order."""
