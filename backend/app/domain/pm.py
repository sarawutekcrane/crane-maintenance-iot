"""Revision-controlled Preventive Maintenance (PM) plan/task master data,
and the PM work-order/work-result occurrence model (Phase 4 scope; baseline
section 9; docs/claude-prompts/web-api/04_PHASE4_PM_REPAIR_WORKFLOW_EN.txt).

SOURCE DATA RULE (OPEN_DECISIONS_REGISTER_EN.txt E05 — "PLAN2/PLAN3/PLAN4
Data: SOURCE-DATA-REQUIRED, do not fabricate"): no authoritative PM plan,
task wording, interval, standard part, or threshold exists anywhere in
this repository for ANY plan, including PLAN1 (repo-wide search confirms
no PM content exists outside governance/prompt documents that only name
the plan codes as concepts). This module therefore mirrors the Phase 3
checklist pattern exactly: a plan/task-revision structure that supports
arbitrary plan codes and arbitrary trigger/interval metadata, seeded (see
`app.repositories.mock.seed_data`) with only clearly-labeled example/
placeholder content for a single plan, and PLAN2/PLAN3/PLAN4 are not
seeded with any task content at all — creating a `PmPlan` master record
for a plan code without an approved task list is not the same as
fabricating that task list.

REVISION MODEL (mirrors `app.domain.checklist` exactly, per this phase's
mandatory requirement "Historical PM work must retain the exact task
revision used at execution time. Do not allow a later task revision to
change old PM history."): a `PmTask` belongs to exactly one immutable
`PmTaskRevision`; a new revision is an entirely new set of tasks, never an
edit of a previous revision's tasks.

STATUS LIFECYCLE WARNING (OPEN_DECISIONS_REGISTER_EN.txt E01 — "PM Status
Lifecycle: TBD-BLOCKING, need stable states and transitions"): E01 is NOT
approved. `PmWorkOrderStatus` below intentionally has only the two states
technically unavoidable to know whether a work order is still open for
task results or has been closed (mirroring how Phase 3's `FindingStatus`
used a single member for the same reason) — there is no IN_PROGRESS,
CANCELLED, or any other state, and no transition matrix is enforced
anywhere in `PmService`. This is a provisional/configurable placeholder,
not a resolution of E01, and must not be read as one.

DUE CALCULATION WARNING (E02 PM Warning Windows, E03 PM Completion
Baseline, E04 Missing Counter Behavior — all unresolved): this module
carries no warning-window threshold, no overdue-tolerance value, and no
rule choosing which completed snapshot becomes the next baseline. See
`PmPlanStatus` / `PmService.get_pm_status`, which expose only the last
completed reference (fact, not a business rule) and an explicit
`due_status="UNKNOWN"` placeholder with a note naming exactly which
decisions block a real calculation.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict

from app.domain.asset import AssetType
from app.domain.meter import CounterType
from app.domain.part import PartActionType


class PmTriggerType(str, Enum):
    """PM trigger metadata (baseline section 9: "PM triggers may use").
    Purely descriptive metadata in Phase 4 — no due/remaining calculation
    reads these values yet (E02/E03/E04 unresolved)."""

    ENGINE_HOUR = "ENGINE_HOUR"
    PTO_HOUR = "PTO_HOUR"
    ODOMETER = "ODOMETER"
    CALENDAR = "CALENDAR"


class PmPlan(BaseModel):
    """Stable PM plan identity (e.g. plan_code="PLAN1"). `asset_type` fixes
    which kind of asset the plan applies to; `model_ids`, when non-empty,
    restricts the plan to specific vehicle models (empty/None = applies to
    every model of that asset type) — this is metadata only, no assignment
    matrix is implemented beyond this simple optional scope filter."""

    pm_plan_id: str
    plan_code: str
    asset_type: AssetType
    name: str
    model_ids: list[str] = []
    created_at: datetime
    updated_at: datetime


class PmTaskPart(BaseModel):
    """Standard/expected part for a PM task (kept separate from the actual
    part used at execution time — see `PmUsedPart` — per this phase's
    explicit requirement not to write actual usage back into the standard
    definition). `part_description` remains free text so this stays valid
    even when no Part Master mapping exists.

    `part_id` (Core Demo Fixes, PM WORKFLOW REDESIGN section F) is
    additive/optional: when a real PM Task Master -> Part Master mapping
    exists, linking it here lets `PmService.approve_scope` generate a real
    `RequisitionLine`; when it does not, the requisition line still
    carries `part_description` alone rather than inventing a mapping."""

    pm_task_part_id: str
    pm_task_id: str
    part_description: str
    quantity: float | None = None
    unit: str | None = None
    part_id: str | None = None


class PmTask(BaseModel):
    """One task within a specific, immutable `PmTaskRevision`."""

    pm_task_id: str
    revision_id: str
    sequence: int
    group: str | None = None
    description: str
    trigger_type: PmTriggerType | None = None
    interval_value: float | None = None
    interval_unit: str | None = None
    standard_parts: list[PmTaskPart] = []


class PmTaskRevision(BaseModel):
    """One immutable revision of a PM plan's task list. `effective_date`
    selects which revision is the plan's current one, exactly like
    `app.domain.checklist.ChecklistRevision`."""

    revision_id: str
    pm_plan_id: str
    revision_number: int
    effective_date: date
    source_revision_note: str | None = None
    created_at: datetime


class PmTaskRevisionDetail(BaseModel):
    plan: PmPlan
    revision: PmTaskRevision
    tasks: list[PmTask]


class PmWorkOrderStatus(str, Enum):
    """PROVISIONAL/CONFIGURABLE placeholder only — see module docstring's
    STATUS LIFECYCLE WARNING. E01 is not approved."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"


class PmWorkOrder(BaseModel):
    """One PM occurrence/header. References the exact plan/task revision
    active when the work order was opened; individual `PmWorkResult`
    records additionally snapshot the task text they were executed
    against (mirroring `InspectionItemResult`'s snapshot pattern), so a
    later task revision can never change this work order's history."""

    pm_work_order_id: str
    asset_type: AssetType
    asset_id: str
    pm_plan_id: str
    revision_id: str
    due_reason: PmTriggerType | None = None
    status: PmWorkOrderStatus
    opened_at: datetime
    opened_by: str | None = None
    closed_at: datetime | None = None
    closed_by: str | None = None
    note: str | None = None
    opened_snapshot_id: str | None = None
    """Core Demo Fix: automatic machine-state snapshot captured when the
    work order was opened (see MeterService.capture_current_state)."""
    closed_snapshot_id: str | None = None
    """Core Demo Fix: automatic machine-state snapshot captured at closure."""
    scope_task_ids: list[str] = []
    """Core Demo Fix, PM WORKFLOW REDESIGN section C/D: the working set of
    `PmTask` IDs (from this work order's own revision only — cross-plan
    tasks are structurally impossible since a revision belongs to exactly
    one plan) currently in scope for this PM occurrence. Set at open time
    (defaults to every task in the active revision when the caller does
    not name a due subset — E02/E03 due-calculation remain unresolved, so
    this branch cannot compute "due" on its own), and may grow only via
    the explicit, audited `PmService.add_scope_task` action before/at
    approval — never by silently pulling in a task from another plan."""
    scope_approved_at: datetime | None = None
    scope_approved_by: str | None = None
    """Core Demo Fix section D: once set, `scope_task_ids` is frozen —
    `PmService.add_scope_task` refuses to add anything further, matching
    "freeze the PM Work Order's selected group/task revision snapshot so
    later master edits do not rewrite historical work.\""""
    primary_technician: str | None = None
    """Core Demo Fixes Delta section B: PM technician/team assignment,
    structurally symmetric with `Repair.primary_technician`. References
    `user_account.user_id` (legacy, opaque). R2f-a reads technician_master
    only for relationship resolution; this field is never reinterpreted."""
    collaborators: list[str] = []
    assignment_model: str = ""
    """R2 Batch R2f-h1 (C1 §12): blank = legacy, "TECHNICIAN_V2" = V2. Set once
    at creation, never changed. `is_test_data` / `test_batch_id`: the job's own
    scope flags (V2 jobs only; blank on legacy jobs)."""
    is_test_data: str = ""
    test_batch_id: str = ""


class PmScopeAdditionAudit(BaseModel):
    """Core Demo Fix section D: "Record who added it, when, and the
    reason" for a group/task added to a PM work order's scope after open
    time but not yet due. Append-only — never edited or removed."""

    pm_work_order_id: str
    pm_task_id: str
    added_by: str | None
    added_at: datetime
    reason: str


class PmUsedPart(BaseModel):
    """Actual part used during PM work — separate from `PmTaskPart`
    (standard/expected) per this phase's explicit requirement.

    `part_id`/`part_instance_id`/`action` are additive Phase 5 fields
    (baseline "PHASE 4 INTEGRATION": "Phase 5 may enrich actual part
    records with part_id / part_instance_id where appropriate") — all
    optional, defaulting to `None`, so every Phase 4 record and caller is
    unaffected. When provided, `PmService` validates the reference is real
    (see `app.domain.part_lookup`); this never rewrites the standard PM
    task definition (`PmTaskPart`) and never mutates completed Phase 4
    history."""

    pm_used_part_id: str
    pm_work_result_id: str
    part_description: str
    quantity: float | None = None
    unit: str | None = None
    part_id: str | None = None
    part_instance_id: str | None = None
    action: PartActionType | None = None
    recorded_by: str | None = None
    recorded_at: datetime


class PmWorkResult(BaseModel):
    """Immutable result for one task occurrence within a `PmWorkOrder`.
    Snapshots the task's description/trigger at execution time so a later
    task revision can never mutate this history (mirrors
    `InspectionItemResult`). There is intentionally no update/void/
    supersede model here — only creation and read exist, matching Phase
    3's D04-style precedent for a domain with no approved correction
    policy."""

    pm_work_result_id: str
    pm_work_order_id: str
    pm_task_id: str
    revision_id: str
    sequence: int
    task_description: str
    completed: bool
    meter_snapshot_id: str | None = None
    remark: str | None = None
    used_parts: list[PmUsedPart] = []
    evidence_attachment_ids: list[str] = []
    performed_by: str | None = None
    performed_at: datetime


class PmWorkOrderDetail(BaseModel):
    work_order: PmWorkOrder
    results: list[PmWorkResult]
    scope_additions: list[PmScopeAdditionAudit] = []


class PmWorkOrderSummary(BaseModel):
    """Lightweight row for history/list views."""

    pm_work_order_id: str
    asset_type: AssetType
    asset_id: str
    pm_plan_id: str
    revision_id: str
    status: PmWorkOrderStatus
    opened_at: datetime
    closed_at: datetime | None = None
    result_count: int
    primary_technician: str | None = None
    collaborators: list[str] = []
    """REV06 section 18 (PM My Work): carried onto the summary row —
    structurally symmetric with `RepairSummary.primary_technician`/
    `collaborators` — so `GET /pm/work-orders/my-work` can be a normal
    `list_work_orders(assigned_to=...)` filter, never a separate stored
    table."""


class PmPlanStatus(BaseModel):
    """Backend-authoritative, but deliberately minimal, PM status summary
    for one applicable plan (baseline section 3: "Backend is
    authoritative... Dashboard, Vehicle Detail... must use the same domain
    services"). `due_status` is always `"UNKNOWN"` in Phase 4: a real
    due/overdue/remaining calculation requires E02 (warning windows), E03
    (completion baseline), and E04 (missing-counter behavior), none of
    which are approved. Frontend must render this as-is and must not
    compute its own due/remaining value from `last_completed_*` fields."""

    plan: PmPlan
    active_revision: PmTaskRevision | None
    last_completed_work_order_id: str | None = None
    last_completed_at: datetime | None = None
    last_completed_meter_snapshot_id: str | None = None
    due_status: str = "UNKNOWN"
    due_status_note: str = (
        "PM due/remaining calculation requires approved decisions E02 (warning "
        "windows), E03 (completion baseline), and E04 (missing-counter behavior); "
        "not implemented in Phase 4."
    )


# R4-PM-WF-01 B01 Rev2: dormant, pure contract helpers only. Existing PM runtime,
# persisted PmWorkOrderStatus, schemas and service behavior are unchanged.
class PmE01ContractState(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    PENDING_REVIEW = "PENDING_REVIEW"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PmE01ContractAction(str, Enum):
    START = "START"
    SUBMIT = "SUBMIT"
    RETURN = "RETURN"
    CLOSE = "CLOSE"
    CANCEL = "CANCEL"


_PM_E01_CONTRACT_EDGES = {
    (PmE01ContractState.OPEN, PmE01ContractAction.START): PmE01ContractState.IN_PROGRESS,
    (PmE01ContractState.IN_PROGRESS, PmE01ContractAction.SUBMIT): PmE01ContractState.PENDING_REVIEW,
    (PmE01ContractState.PENDING_REVIEW, PmE01ContractAction.RETURN): PmE01ContractState.IN_PROGRESS,
    (PmE01ContractState.PENDING_REVIEW, PmE01ContractAction.CLOSE): PmE01ContractState.CLOSED,
}


def pm_e01_contract_transition(
    state: PmE01ContractState,
    action: PmE01ContractAction,
    *,
    cancellation_eligibility_proven: bool = False,
    actual_performed_count: int = 0,
    existing_result_count: int = 0,
    existing_evidence_count: int = 0,
    return_reason: str | None = None,
    cancellation_reason: str | None = None,
) -> PmE01ContractState:
    """Pure state precheck, NOT an authorization or persistence decision.

    V2 PRIMARY / reviewer identity, Store impacts, replay, and eligibility
    must be proven separately by the future runtime service. Cancellation
    is never authorized by this helper alone.
    """
    if min(actual_performed_count, existing_result_count, existing_evidence_count) < 0:
        raise ValueError("PM_CANCELLATION_COUNTS_INVALID")
    if action == PmE01ContractAction.CANCEL:
        if (state not in (PmE01ContractState.OPEN, PmE01ContractState.IN_PROGRESS)
                or actual_performed_count != 0
                or existing_result_count != 0
                or existing_evidence_count != 0
                or not cancellation_eligibility_proven
                or not (cancellation_reason or "").strip()):
            raise ValueError("PM_CANCEL_NOT_ELIGIBLE")
        return PmE01ContractState.CANCELLED
    target = _PM_E01_CONTRACT_EDGES.get((state, action))
    if target is None:
        raise ValueError("PM_E01_INVALID_TRANSITION")
    if action == PmE01ContractAction.RETURN and not (return_reason or "").strip():
        raise ValueError("PM_RETURN_REASON_REQUIRED")
    return target


class PmItemContractDisposition(str, Enum):
    PERFORMED = "PERFORMED"
    NOT_PERFORMED = "NOT_PERFORMED"


def validate_pm_item_contract(
    disposition: PmItemContractDisposition,
    *,
    reason_code: str | None = None,
    other_text: str | None = None,
    approved_not_performed_reasons: frozenset[str],
    approved_other_reason_code: str,
    performed_actions: tuple[str, ...] = (),
    approved_performed_actions: frozenset[str] = frozenset(),
) -> None:
    """Fail closed: caller must supply the *approved* Owner reason vocabulary.

    B01 deliberately does not invent or persist any reason code. Do not wire
    to API until the existing authoritative list has been reconciled.
    """
    if not approved_not_performed_reasons or approved_other_reason_code not in approved_not_performed_reasons:
        raise ValueError("PM_APPROVED_REASON_SOURCE_REQUIRED")
    if disposition == PmItemContractDisposition.PERFORMED:
        # Supplied by the approved business contract; never invent labels.
        if not approved_performed_actions:
            raise ValueError("PM_APPROVED_ACTION_SOURCE_REQUIRED")
        if (not 1 <= len(performed_actions) <= 2
                or len(set(performed_actions)) != len(performed_actions)
                or not set(performed_actions).issubset(approved_performed_actions)):
            raise ValueError("PM_PERFORMED_ACTION_INVALID")
        if reason_code is not None or (other_text or "").strip():
            raise ValueError("PM_PERFORMED_REASON_CONFLICT")
        return
    if performed_actions:
        raise ValueError("PM_NOT_PERFORMED_ACTION_CONFLICT")
    if disposition != PmItemContractDisposition.NOT_PERFORMED:
        raise ValueError("PM_INVALID_DISPOSITION")
    if not reason_code or reason_code not in approved_not_performed_reasons:
        raise ValueError("PM_NOT_PERFORMED_REASON_REQUIRED")
    if reason_code == approved_other_reason_code and not (other_text or "").strip():
        raise ValueError("PM_OTHER_REASON_TEXT_REQUIRED")


def assess_pm_contract_completion(*, in_scope_task_ids: tuple[str, ...],
                                  performed_task_ids: tuple[str, ...],
                                  accounted_not_performed_ids: tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
    """Pure eligibility assessment; never closes a WO or changes a PM Set anchor.

    Outstanding records must be durably persisted/readable before the future
    partial-close runtime is enabled. This helper does not grant closure.
    """
    scope = set(in_scope_task_ids)
    performed = set(performed_task_ids)
    not_performed = set(accounted_not_performed_ids)
    if (len(scope) != len(in_scope_task_ids)
            or len(performed) != len(performed_task_ids)
            or len(not_performed) != len(accounted_not_performed_ids)
            or not performed.issubset(scope)
            or not not_performed.issubset(scope)
            or performed & not_performed
            or performed | not_performed != scope):
        raise ValueError("PM_ITEM_SCOPE_ACCOUNTING_INVALID")
    if not performed:
        raise ValueError("PM_ZERO_ACTUAL_WORK_FORBIDDEN")
    outstanding = tuple(item for item in in_scope_task_ids if item in not_performed)
    return ("PARTIAL" if outstanding else "COMPLETE", outstanding)


# R4-PM-WF-01 B02-A: dormant outcome / Outstanding / resolution-reference
# contracts. Nothing in the PM service, API or Google Sheets adapter builds or
# stores these; only MockRepository persists Outstanding records. No
# Owner-facing status or reason code is defined here: the vocabulary is always
# supplied by the caller (B01 validators) and an Outstanding record has no
# lifecycle field — in B02-A its existence means one unresolved obligation.

def _pm_contract_text(value: str | None, code: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError(code)
    return text


def _pm_contract_digest(*parts: str | None) -> str:
    """Deterministic SHA-256 over the parts (None and "" are distinct)."""
    joined = "\x1f".join("\x00" if part is None else part for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


class PmItemOutcome(BaseModel):
    """A01: one truthful PM item outcome, bound to the frozen source Work
    Order, task and revision. `source_pm_work_result_id` is provenance only;
    the existing immutable `PmWorkResult` is never modified."""

    model_config = ConfigDict(frozen=True)

    pm_work_order_id: str
    pm_task_id: str
    revision_id: str
    disposition: PmItemContractDisposition
    performed_actions: tuple[str, ...] = ()
    reason_code: str | None = None
    other_text: str | None = None
    evidence_attachment_ids: tuple[str, ...] = ()
    recorded_by: str | None = None
    recorded_at: datetime
    source_pm_work_result_id: str | None = None


def build_pm_item_outcome(
    *,
    pm_work_order_id: str,
    pm_task_id: str,
    revision_id: str,
    disposition: PmItemContractDisposition,
    recorded_at: datetime,
    approved_not_performed_reasons: frozenset[str],
    approved_other_reason_code: str,
    approved_performed_actions: frozenset[str] = frozenset(),
    performed_actions: tuple[str, ...] = (),
    reason_code: str | None = None,
    other_text: str | None = None,
    evidence_attachment_ids: tuple[str, ...] = (),
    recorded_by: str | None = None,
    source_pm_work_result_id: str | None = None,
) -> PmItemOutcome:
    """Validate with the B01 contract (fail closed) and freeze the outcome."""
    identity = pm_outstanding_source_identity(pm_work_order_id, pm_task_id, revision_id)
    validate_pm_item_contract(
        disposition,
        reason_code=reason_code,
        other_text=other_text,
        approved_not_performed_reasons=approved_not_performed_reasons,
        approved_other_reason_code=approved_other_reason_code,
        performed_actions=performed_actions,
        approved_performed_actions=approved_performed_actions,
    )
    return PmItemOutcome(
        pm_work_order_id=identity.pm_work_order_id,
        pm_task_id=identity.pm_task_id,
        revision_id=identity.revision_id,
        disposition=disposition,
        performed_actions=tuple(performed_actions),
        reason_code=reason_code,
        other_text=other_text,
        evidence_attachment_ids=tuple(evidence_attachment_ids),
        recorded_by=recorded_by,
        recorded_at=recorded_at,
        source_pm_work_result_id=source_pm_work_result_id,
    )


class PmOutstandingSourceIdentity(BaseModel):
    """A02: immutable source identity — PM Work Order, task, frozen revision."""

    model_config = ConfigDict(frozen=True)

    pm_work_order_id: str
    pm_task_id: str
    revision_id: str

    @property
    def outstanding_id(self) -> str:
        """Stable id: the same source identity always yields the same id."""
        return "PMOS-" + _pm_contract_digest(self.pm_work_order_id, self.pm_task_id, self.revision_id)[:24]


def pm_outstanding_source_identity(pm_work_order_id: str, pm_task_id: str,
                                   revision_id: str) -> PmOutstandingSourceIdentity:
    return PmOutstandingSourceIdentity(
        pm_work_order_id=_pm_contract_text(pm_work_order_id, "PM_OUTSTANDING_SOURCE_IDENTITY_INVALID"),
        pm_task_id=_pm_contract_text(pm_task_id, "PM_OUTSTANDING_SOURCE_IDENTITY_INVALID"),
        revision_id=_pm_contract_text(revision_id, "PM_OUTSTANDING_SOURCE_IDENTITY_INVALID"),
    )


class PmOutstandingItem(BaseModel):
    """A02: one unresolved PM obligation created from a NOT_PERFORMED outcome.
    Carries the original outcome's provenance; no status/lifecycle field."""

    model_config = ConfigDict(frozen=True)

    outstanding_id: str
    pm_work_order_id: str
    pm_task_id: str
    revision_id: str
    origin_reason_code: str
    origin_other_text: str | None = None
    origin_recorded_by: str | None = None
    origin_recorded_at: datetime
    origin_pm_work_result_id: str | None = None
    created_by: str | None = None
    created_at: datetime

    @property
    def source_identity(self) -> PmOutstandingSourceIdentity:
        return PmOutstandingSourceIdentity(pm_work_order_id=self.pm_work_order_id, pm_task_id=self.pm_task_id,
                                           revision_id=self.revision_id)

    @property
    def creation_fingerprint(self) -> str:
        """Identity + original outcome provenance. `created_by`/`created_at`
        are excluded so an identical replay is recognised as the same record."""
        return _pm_contract_digest(
            self.pm_work_order_id, self.pm_task_id, self.revision_id, self.origin_reason_code,
            self.origin_other_text, self.origin_recorded_by, self.origin_recorded_at.isoformat(),
            self.origin_pm_work_result_id,
        )


def build_pm_outstanding_item(outcome: PmItemOutcome, *, created_by: str | None,
                              created_at: datetime) -> PmOutstandingItem:
    """Only a validated NOT_PERFORMED outcome becomes an Outstanding record."""
    if outcome.disposition != PmItemContractDisposition.NOT_PERFORMED or not outcome.reason_code:
        raise ValueError("PM_OUTSTANDING_REQUIRES_NOT_PERFORMED")
    identity = pm_outstanding_source_identity(outcome.pm_work_order_id, outcome.pm_task_id, outcome.revision_id)
    return PmOutstandingItem(
        outstanding_id=identity.outstanding_id,
        pm_work_order_id=identity.pm_work_order_id,
        pm_task_id=identity.pm_task_id,
        revision_id=identity.revision_id,
        origin_reason_code=outcome.reason_code,
        origin_other_text=outcome.other_text,
        origin_recorded_by=outcome.recorded_by,
        origin_recorded_at=outcome.recorded_at,
        origin_pm_work_result_id=outcome.source_pm_work_result_id,
        created_by=created_by,
        created_at=created_at,
    )


class PmOutstandingResolutionReference(BaseModel):
    """A03: a pointer to LATER actual work (a later PM work result or a
    Repair) offered as evidence for an Outstanding item. Dormant: B02-A has no
    resolution writer, and a valid reference is never proof of resolution —
    proof requires the future runtime to verify the actual work performed."""

    model_config = ConfigDict(frozen=True)

    outstanding_id: str
    later_pm_work_result_id: str | None = None
    later_repair_id: str | None = None
    evidence_attachment_ids: tuple[str, ...] = ()
    referenced_by: str | None = None
    referenced_at: datetime


def validate_pm_outstanding_resolution_reference(reference: PmOutstandingResolutionReference,
                                                 outstanding: PmOutstandingItem) -> None:
    """Structural provenance check only. Returns nothing and changes nothing:
    the Outstanding item, its origin and the PM result stay untouched."""
    if reference.outstanding_id != outstanding.outstanding_id:
        raise ValueError("PM_RESOLUTION_REFERENCE_OUTSTANDING_MISMATCH")
    pm_ref = (reference.later_pm_work_result_id or "").strip()
    repair_ref = (reference.later_repair_id or "").strip()
    if bool(pm_ref) == bool(repair_ref):
        raise ValueError("PM_RESOLUTION_REFERENCE_SOURCE_INVALID")
    if pm_ref and pm_ref == (outstanding.origin_pm_work_result_id or ""):
        raise ValueError("PM_RESOLUTION_REFERENCE_SELF")
    if not any((e or "").strip() for e in reference.evidence_attachment_ids):
        raise ValueError("PM_RESOLUTION_REFERENCE_EVIDENCE_REQUIRED")
    if reference.referenced_at < outstanding.created_at:
        raise ValueError("PM_RESOLUTION_REFERENCE_PREDATES_OUTSTANDING")


__all__ = [
    "PmE01ContractState",
    "PmE01ContractAction",
    "pm_e01_contract_transition",
    "PmItemContractDisposition",
    "validate_pm_item_contract",
    "assess_pm_contract_completion",
    "PmItemOutcome",
    "build_pm_item_outcome",
    "PmOutstandingSourceIdentity",
    "pm_outstanding_source_identity",
    "PmOutstandingItem",
    "build_pm_outstanding_item",
    "PmOutstandingResolutionReference",
    "validate_pm_outstanding_resolution_reference",
    "PmTriggerType",
    "PmPlan",
    "PmTaskPart",
    "PmTask",
    "PmTaskRevision",
    "PmTaskRevisionDetail",
    "PmWorkOrderStatus",
    "PmWorkOrder",
    "PmScopeAdditionAudit",
    "PmUsedPart",
    "PmWorkResult",
    "PmWorkOrderDetail",
    "PmWorkOrderSummary",
    "PmPlanStatus",
    "CounterType",
]
