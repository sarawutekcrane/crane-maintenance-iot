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

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel

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


__all__ = [
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
