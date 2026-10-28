"""PM (preventive maintenance) domain service.

Owns every business rule Phase 4 is allowed to define without an approved
open decision (E01-E05 in OPEN_DECISIONS_REGISTER_EN.txt — see
`app.domain.pm` module docstring for the full explanation of each):

- which plans apply to an asset: same `asset_type`, and — when a plan
  declares `model_ids` — the vehicle's `model_id` must be in that list
  (metadata-only scope filter, not an assignment matrix),
- a PM work order is opened against the plan's currently active task
  revision; every task result it later receives is validated against
  that exact revision (never a newer one), and a task can only receive
  one result per work order — an existing result is never overwritten,
- closing a work order requires nothing beyond it existing and being
  open (no mandatory task-completion requirement is invented),
- a meter snapshot referenced by a task result is validated to exist via
  `MeterService`, which is itself where component/asset validation lives.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import status

from app.context import RequestContext
from app.domain.asset import AssetType
from app.domain.attachment import AttachmentPurpose
from app.domain.asset_lookup import require_asset_exists, require_asset_for_new_work
from app.domain.assignment import active_primary_and_collaborators
from app.domain.authz import CAN_MANAGE_PM, require_capability
from app.domain.common import Page, PageParams
from app.domain.meter_service import MeterService
from app.domain.part import PartActionType
from app.domain.part_lookup import require_part_exists, require_part_instance_exists
from app.domain.pm import (
    PmE01ContractAction,
    PmItemContractDisposition,
    PmItemOutcome,
    PmOutstandingItem,
    PmOutstandingResolutionReference,
    PmWorkOrderTransition,
    PmWorkResult,
    assess_pm_contract_completion,
    build_pm_item_outcome,
    build_pm_outstanding_item,
    pm_e01_contract_transition,
    pm_e01_state,
    pm_item_outcome_id,
    pm_work_order_transition_fingerprint,
    PmPlan,
    PmPlanStatus,
    PmTaskRevisionDetail,
    PmTriggerType,
    PmWorkOrder,
    PmWorkOrderDetail,
    PmWorkOrderStatus,
    PmWorkOrderSummary,
)
from app.domain.requisition import RequisitionSourceType
from app.domain.technician_assignment import (
    ASSIGNMENT_MODEL_LEGACY,
    ASSIGNMENT_MODEL_TECHNICIAN_V2,
    PM,
    AssignmentCutover,
    STATUS_AMBIGUOUS,
    TechnicianAssignmentService,
    assignment_model_of,
    current_legacy_entries,
    model_mismatch,
    require_legacy,
    require_v2_context,
    require_v2_job_in_scope,
    v2_job_marker,
)
from app.domain.repair import RepairSourceType, RepairStatus
from app.errors import ApiError
from app.repositories.base import Repository


# R4-PM-WF-01 B02-B2A: server-owned PM item vocabulary — the exact approved
# wording of Owner Agreements, R4 Final Contract FC-1 (Performed /
# Not Performed). Never supplied or extended by a caller; checked only through
# the B01 builder / validator.
PM_APPROVED_PERFORMED_ACTIONS: frozenset[str] = frozenset({
    "ตรวจเช็ค",
    "ทำความสะอาด",
    "เปลี่ยน / เติม",
})
PM_APPROVED_OTHER_REASON = "อื่น ๆ (ระบุ)"
PM_APPROVED_NOT_PERFORMED_REASONS: frozenset[str] = frozenset({
    "มีการเปลี่ยนอะไหล่แล้วในการซ่อมครั้งก่อน",
    "รออะไหล่",
    "พบความผิดปกติ รอซ่อม",
    "พื้นที่ไม่เพียงพอ",
    "เวลาไม่เพียงพอ",
    PM_APPROVED_OTHER_REASON,
})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class PmItemOutcomeRecording:
    """One saved PM item: the factual `PmWorkResult` (parts, meter, evidence,
    Repair source) and the authoritative truthful `PmItemOutcome`, both read
    back and verified. `*_replayed` is True when the record already existed
    (identical retry or partial-write recovery). No Outstanding record is
    created at item save: Outstanding becomes effective only at CLOSE."""
    result: PmWorkResult
    outcome: PmItemOutcome
    result_replayed: bool
    outcome_replayed: bool


@dataclass(frozen=True)
class PmOutstandingState:
    """An effective Outstanding record (its source work order is CLOSED) and
    its single resolution, if any."""
    item: PmOutstandingItem
    resolution: PmOutstandingResolutionReference | None = None


def _vocabulary() -> dict:
    """The server-owned vocabulary, as B01 keyword arguments."""
    return {"approved_not_performed_reasons": PM_APPROVED_NOT_PERFORMED_REASONS,
            "approved_other_reason_code": PM_APPROVED_OTHER_REASON,
            "approved_performed_actions": PM_APPROVED_PERFORMED_ACTIONS}


def _rejected(exc: ValueError, http_status: int | None = None) -> ApiError:
    return ApiError(code=str(exc), message="The PM item outcome was rejected; nothing was changed",
                    status_code=http_status or status.HTTP_422_UNPROCESSABLE_ENTITY)


def _conflict(code: str, message: str, details: dict | None = None) -> ApiError:
    return ApiError(code=code, message=message, status_code=status.HTTP_409_CONFLICT, details=details)


def _invalid(code: str, message: str, details: dict | None = None) -> ApiError:
    return ApiError(code=code, message=message, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, details=details)


def _readback_mismatch(record: str) -> ApiError:
    return ApiError(code="PM_OUTCOME_READBACK_MISMATCH",
                    message=f"The stored {record} does not match what was written; not reported as recorded",
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@dataclass(frozen=True)
class UsedPartInput:
    part_description: str
    quantity: float | None = None
    unit: str | None = None
    part_id: str | None = None
    part_instance_id: str | None = None
    action: PartActionType | None = None


class PmService:
    def __init__(self, repository: Repository, meter_service: MeterService,
                 assignment_cutover: AssignmentCutover | None = None) -> None:
        self._repository = repository
        self._meter = meter_service
        # R2 Batch R2f-h1: the V2 cutover setting + server context (default OFF).
        self._cutover = assignment_cutover or AssignmentCutover()

    # ---- Plan / task revision ----

    async def list_applicable_plan_status(
        self, asset_type: AssetType, asset_id: str
    ) -> list[PmPlanStatus]:
        await require_asset_exists(self._repository, asset_type, asset_id)

        plans: list[PmPlan]
        if asset_type == AssetType.VEHICLE:
            # Core Demo Fixes, PM WORKFLOW REDESIGN section A — APPROVED
            # CORRECTION: a vehicle's PM plan comes from its model's own
            # single `assigned_pm_plan_id`, never from scanning every
            # plan's `model_ids` (which permitted an unintended many-to-
            # many mapping — see web-phase-04-result.md Section 31 risk
            # note). `None` means SOURCE-DATA-REQUIRED: no plan at all.
            vehicle = await self._repository.get_vehicle(asset_id)
            model = await self._repository.get_vehicle_model(vehicle.model_id) if vehicle else None
            assigned_plan_id = model.assigned_pm_plan_id if model else None
            if assigned_plan_id is None:
                plans = []
            else:
                plan = await self._repository.get_pm_plan(assigned_plan_id)
                plans = [plan] if plan is not None else []
        else:
            # Equipment has no model/assigned-plan concept in this branch
            # (C03 equipment counter/component model remains TBD-DEFERRED)
            # — unchanged from Phase 4's plan.model_ids-based filter.
            plans = await self._repository.list_pm_plans(asset_type=asset_type, model_id=None)

        statuses: list[PmPlanStatus] = []
        for plan in plans:
            revision_detail = await self._repository.get_active_pm_task_revision(plan.pm_plan_id)
            last_detail = await self._repository.get_last_closed_pm_work_order(
                asset_type=asset_type, asset_id=asset_id, pm_plan_id=plan.pm_plan_id
            )
            last_snapshot_id: str | None = None
            if last_detail is not None:
                for result in reversed(last_detail.results):
                    if result.meter_snapshot_id:
                        last_snapshot_id = result.meter_snapshot_id
                        break
            statuses.append(
                PmPlanStatus(
                    plan=plan,
                    active_revision=revision_detail.revision if revision_detail else None,
                    last_completed_work_order_id=(
                        last_detail.work_order.pm_work_order_id if last_detail else None
                    ),
                    last_completed_at=last_detail.work_order.closed_at if last_detail else None,
                    last_completed_meter_snapshot_id=last_snapshot_id,
                )
            )
        return statuses

    async def _require_plan(self, pm_plan_id: str) -> PmPlan:
        plan = await self._repository.get_pm_plan(pm_plan_id)
        if plan is None:
            raise ApiError(
                code="PM_PLAN_NOT_FOUND",
                message=f"PM plan '{pm_plan_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return plan

    async def get_active_task_revision(self, pm_plan_id: str) -> PmTaskRevisionDetail:
        await self._require_plan(pm_plan_id)
        detail = await self._repository.get_active_pm_task_revision(pm_plan_id)
        if detail is None:
            raise ApiError(
                code="NO_ACTIVE_PM_TASK_REVISION",
                message=f"No active PM task revision is configured for plan '{pm_plan_id}'",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return detail

    async def get_task_revision(self, pm_plan_id: str, revision_id: str) -> PmTaskRevisionDetail:
        detail = await self._repository.get_pm_task_revision(pm_plan_id, revision_id)
        if detail is None:
            raise ApiError(
                code="PM_TASK_REVISION_NOT_FOUND",
                message=f"PM task revision '{revision_id}' was not found for plan '{pm_plan_id}'",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return detail

    # ---- Work order ----

    async def open_work_order(
        self,
        asset_type: AssetType,
        asset_id: str,
        pm_plan_id: str,
        due_reason: PmTriggerType | None,
        opened_by: str | None,
        note: str | None,
        initial_scope_task_ids: list[str] | None = None,
    ) -> PmWorkOrderDetail:
        await require_asset_for_new_work(self._repository, asset_type, asset_id)
        plan = await self._require_plan(pm_plan_id)
        if plan.asset_type != asset_type:
            raise ApiError(
                code="VALIDATION_ERROR",
                message=(
                    f"PM plan '{pm_plan_id}' applies to asset type "
                    f"'{plan.asset_type.value}', not '{asset_type.value}'"
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if asset_type == AssetType.VEHICLE:
            # APPROVED CORRECTION: a user may never manually switch a
            # vehicle's PM work order to a plan other than its model's own
            # single assigned plan.
            vehicle = await self._repository.get_vehicle(asset_id)
            model = await self._repository.get_vehicle_model(vehicle.model_id) if vehicle else None
            assigned_plan_id = model.assigned_pm_plan_id if model else None
            if assigned_plan_id is None or assigned_plan_id != pm_plan_id:
                raise ApiError(
                    code="PM_PLAN_NOT_ASSIGNED_TO_MODEL",
                    message=(
                        f"Plan '{pm_plan_id}' is not the PM plan assigned to this vehicle's "
                        "model — a vehicle's PM work order must use only its model's own "
                        "assigned plan (SOURCE-DATA-REQUIRED if no mapping is configured)"
                    ),
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    details={"assigned_pm_plan_id": assigned_plan_id},
                )
        revision_detail = await self.get_active_task_revision(pm_plan_id)

        all_task_ids = [t.pm_task_id for t in revision_detail.tasks]
        if initial_scope_task_ids is None:
            # No due-calculation exists in this branch (E02/E03/E04
            # unresolved) — default to every task in the active revision,
            # matching Phase 4's prior behavior exactly (non-breaking).
            scope_task_ids = all_task_ids
        else:
            unknown = set(initial_scope_task_ids) - set(all_task_ids)
            if unknown:
                raise ApiError(
                    code="VALIDATION_ERROR",
                    message="initial_scope_task_ids must all belong to this plan's active revision",
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    details={"unknown_task_ids": sorted(unknown)},
                )
            scope_task_ids = list(initial_scope_task_ids)

        # R2 Batch R2f-h4 B6 Rev2 (owner final decision: V2 only): EVERY new PM
        # work order is a V2 job. After the input validation (as for the former
        # default) and before ANY write — the open-time snapshot included — the
        # data context and the extended-header proof; no legacy fallback.
        assignment_marker = await v2_job_marker(self._repository, PM, self._cutover)

        # Core Demo Fix: automatic machine-state snapshot at open time —
        # backend-derived, never a manually-typed browser field.
        snapshot = await self._meter.capture_current_state(
            asset_type=asset_type,
            asset_id=asset_id,
            recorded_by=opened_by,
            source_note="PM_WORK_ORDER_OPEN",
        )
        work_order = await self._repository.create_pm_work_order(
            asset_type=asset_type,
            asset_id=asset_id,
            pm_plan_id=pm_plan_id,
            revision_id=revision_detail.revision.revision_id,
            due_reason=due_reason,
            opened_by=opened_by,
            note=note,
            opened_snapshot_id=snapshot.meter_snapshot_id,
            scope_task_ids=scope_task_ids,
            assignment_marker=assignment_marker,
        )
        return await self.get_work_order(work_order.pm_work_order_id)

    async def add_scope_task(
        self,
        pm_work_order_id: str,
        pm_task_id: str,
        reason: str,
        added_by: str | None,
    ) -> PmWorkOrderDetail:
        """Core Demo Fix section D: authorized addition of a near-due group
        from the SAME plan (guaranteed structurally: `pm_task_id` must
        belong to this work order's own revision, which belongs to exactly
        one plan). Caller (route layer) is responsible for the "authorized
        PM scope authority" gate — this service enforces only that scope is
        not already frozen and that the task is real."""
        if not reason or not reason.strip():
            raise ApiError(
                code="VALIDATION_ERROR",
                message="reason is required when manually adding a PM scope task",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        detail = await self.get_work_order(pm_work_order_id)
        self._require_scope_editable(detail)
        if detail.work_order.scope_approved_at is not None:
            raise ApiError(
                code="PM_SCOPE_ALREADY_APPROVED",
                message="This work order's scope is approved/frozen and cannot be extended",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        revision_detail = await self._repository.get_pm_task_revision(
            detail.work_order.pm_plan_id, detail.work_order.revision_id
        )
        task_ids = {t.pm_task_id for t in revision_detail.tasks} if revision_detail else set()
        if pm_task_id not in task_ids:
            raise ApiError(
                code="VALIDATION_ERROR",
                message=f"Task '{pm_task_id}' does not belong to this work order's own plan/revision",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if pm_task_id in detail.work_order.scope_task_ids:
            raise ApiError(
                code="VALIDATION_ERROR",
                message=f"Task '{pm_task_id}' is already in this work order's scope",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        await self._repository.add_pm_scope_task(
            pm_work_order_id=pm_work_order_id, pm_task_id=pm_task_id, added_by=added_by, reason=reason
        )
        return await self.get_work_order(pm_work_order_id)

    async def approve_scope(
        self, pm_work_order_id: str, approved_by: str | None
    ) -> PmWorkOrderDetail:
        """Core Demo Fix section D: freeze the work order's selected
        group/task set. Section F / Delta section D: auto-generate one
        `MaterialRequest` header plus its `RequisitionLine`s (Store/
        Inventory integration boundary — see `app.domain.requisition`)
        from each in-scope task's standard `PmTaskPart` list. Never
        decrements any stock balance; no header is created when the
        approved scope has no standard parts at all (nothing to request)."""
        detail = await self.get_work_order(pm_work_order_id)
        self._require_scope_editable(detail)
        if detail.work_order.scope_approved_at is not None:
            raise ApiError(
                code="PM_SCOPE_ALREADY_APPROVED",
                message="This work order's scope is already approved",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        revision_detail = await self._repository.get_pm_task_revision(
            detail.work_order.pm_plan_id, detail.work_order.revision_id
        )
        tasks_in_scope = (
            [t for t in revision_detail.tasks if t.pm_task_id in detail.work_order.scope_task_ids]
            if revision_detail
            else []
        )
        await self._repository.approve_pm_scope(pm_work_order_id, approved_by=approved_by)

        lines_to_create = [
            (task, part) for task in tasks_in_scope for part in task.standard_parts
        ]
        if lines_to_create:
            vehicle_id = (
                detail.work_order.asset_id if detail.work_order.asset_type == AssetType.VEHICLE else None
            )
            material_request = await self._repository.create_material_request(
                source_type=RequisitionSourceType.PM,
                source_work_order_id=pm_work_order_id,
                vehicle_id=vehicle_id,
                created_by=approved_by,
            )
            for task, part in lines_to_create:
                await self._repository.create_requisition_line(
                    material_request_id=material_request.material_request_id,
                    part_id=part.part_id,
                    part_instance_id=None,
                    part_code_snapshot=None,
                    part_description=part.part_description,
                    requested_quantity=part.quantity,
                    unit=part.unit,
                    source_task_revision_id=task.revision_id,
                    line_source="PM_STANDARD",
                    created_by=approved_by,
                )
        return await self.get_work_order(pm_work_order_id)

    async def list_requisition_lines(self, pm_work_order_id: str) -> list:
        await self.get_work_order(pm_work_order_id)
        return await self._repository.list_requisition_lines_for_work_order(pm_work_order_id)

    async def list_assignment_history(self, pm_work_order_id: str):
        # R2 Batch R2f-h1: the legacy history view serves legacy jobs only.
        require_legacy((await self.get_work_order(pm_work_order_id)).work_order)
        return await self._repository.list_pm_work_order_assignment_history(pm_work_order_id)

    async def authorize_recording(self, pm_work_order_id: str, context, capability: str,
                                  action_description: str) -> None:
        """R2 Batch R2f-h1: recording authorization per job model (see
        `RepairService.authorize_recording`)."""
        from app.domain.authz import require_assignment_or_capability

        detail = await self.get_work_order(pm_work_order_id)
        if assignment_model_of(detail.work_order) == ASSIGNMENT_MODEL_LEGACY:
            history = await self._repository.list_pm_work_order_assignment_history(pm_work_order_id)
            primary_technician, collaborators = active_primary_and_collaborators(
                current_legacy_entries(history, context))
            require_assignment_or_capability(context, capability, primary_technician, collaborators,
                                             action_description)
            return
        await TechnicianAssignmentService(self._repository, self._cutover).require_recording(
            PM, detail.work_order, context, capability, action_description)

    async def get_active_assignment(self, pm_work_order_id: str) -> tuple[str | None, list[str]]:
        """F1 cross-phase integration fix: PM's equivalent of
        `RepairService.get_active_assignment` — returns
        `(active_primary_technician, active_collaborators)` derived from
        the append-only `pm_work_order_assignment` history's currently-
        active rows, never from the denormalized
        `PmWorkOrder.primary_technician`/`.collaborators` fields. Those two
        fields remain on `PmWorkOrder` for display/compatibility only and
        are kept in sync by `assign_pm_work_order`, but that sync is a
        second, separate write after the history rows are appended/ended
        (Google Sheets has no transactions) — a failure between the two
        writes must never let the stale denormalized field authorize (or
        deny) the wrong actor, exactly the same stale-state class REV06.1
        already closed for Repair."""
        await self.get_work_order(pm_work_order_id)
        history = await self._repository.list_pm_work_order_assignment_history(pm_work_order_id)
        return active_primary_and_collaborators(history)

    async def get_work_order(self, pm_work_order_id: str) -> PmWorkOrderDetail:
        detail = await self._repository.get_pm_work_order(pm_work_order_id)
        if detail is None:
            raise ApiError(
                code="PM_WORK_ORDER_NOT_FOUND",
                message=f"PM work order '{pm_work_order_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return detail

    async def list_work_orders(
        self,
        asset_type: AssetType | None,
        asset_id: str | None,
        params: PageParams,
        status: PmWorkOrderStatus | None = None,
        assigned_to: str | None = None,
    ) -> Page[PmWorkOrderSummary]:
        items, total = await self._repository.list_pm_work_orders(
            asset_type=asset_type,
            asset_id=asset_id,
            params=params,
            status=status,
            assigned_to=assigned_to,
        )
        return Page(items=items, page=params.page, page_size=params.page_size, total_items=total)

    async def submit_task_result(
        self,
        pm_work_order_id: str,
        pm_task_id: str,
        completed: bool,
        meter_snapshot_id: str | None,
        remark: str | None,
        used_parts: list[UsedPartInput],
        evidence_attachment_ids: list[str],
        performed_by: str | None,
    ) -> PmWorkOrderDetail:
        detail = await self.get_work_order(pm_work_order_id)
        if assignment_model_of(detail.work_order) == ASSIGNMENT_MODEL_TECHNICIAN_V2:
            # R4 PM Workflow: a V2 item is saved only through the truthful E01
            # item save (`record_item_outcome`); never a typed `completed` flag.
            raise _conflict("PM_E01_ITEM_SAVE_REQUIRED",
                            "V2 PM work orders record items as Performed / Not Performed through the PM workflow")
        if detail.work_order.status == PmWorkOrderStatus.CLOSED:
            raise ApiError(
                code="PM_WORK_ORDER_CLOSED",
                message="Cannot add a task result to a closed PM work order",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        revision_detail = await self._repository.get_pm_task_revision(
            detail.work_order.pm_plan_id, detail.work_order.revision_id
        )
        if revision_detail is None:
            raise ApiError(
                code="PM_TASK_REVISION_NOT_FOUND",
                message="The task revision this work order was opened against no longer exists",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        task = next((t for t in revision_detail.tasks if t.pm_task_id == pm_task_id), None)
        if task is None:
            raise ApiError(
                code="VALIDATION_ERROR",
                message=(
                    f"Task '{pm_task_id}' does not belong to this work order's task revision"
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"pm_task_id": pm_task_id},
            )
        if pm_task_id not in detail.work_order.scope_task_ids:
            raise ApiError(
                code="PM_TASK_NOT_IN_SCOPE",
                message=(
                    f"Task '{pm_task_id}' is not in this work order's selected scope — "
                    "use the authorized scope-addition action first"
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"pm_task_id": pm_task_id},
            )
        if any(r.pm_task_id == pm_task_id for r in detail.results):
            raise ApiError(
                code="PM_TASK_RESULT_ALREADY_EXISTS",
                message=(
                    f"A result already exists for task '{pm_task_id}' on this work order — "
                    "task results are immutable and cannot be overwritten"
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"pm_task_id": pm_task_id},
            )

        if meter_snapshot_id is not None:
            await self._meter.require_snapshot_exists(meter_snapshot_id)
        else:
            # Normal path: the technician does not manually type a reading —
            # the backend automatically captures current machine state.
            snapshot = await self._meter.capture_current_state(
                asset_type=detail.work_order.asset_type,
                asset_id=detail.work_order.asset_id,
                recorded_by=performed_by,
                source_note="PM_TASK_RESULT",
            )
            meter_snapshot_id = snapshot.meter_snapshot_id
        for part in used_parts:
            if part.part_id is not None:
                await require_part_exists(self._repository, part.part_id)
            if part.part_instance_id is not None:
                await require_part_instance_exists(self._repository, part.part_instance_id)

        await self._repository.create_pm_work_result(
            pm_work_order_id=pm_work_order_id,
            pm_task_id=pm_task_id,
            revision_id=detail.work_order.revision_id,
            sequence=task.sequence,
            task_description=task.description,
            completed=completed,
            meter_snapshot_id=meter_snapshot_id,
            remark=remark,
            used_parts=[
                {
                    "part_description": p.part_description,
                    "quantity": p.quantity,
                    "unit": p.unit,
                    "part_id": p.part_id,
                    "part_instance_id": p.part_instance_id,
                    "action": p.action,
                }
                for p in used_parts
            ],
            evidence_attachment_ids=list(evidence_attachment_ids),
            performed_by=performed_by,
        )
        return await self.get_work_order(pm_work_order_id)

    async def close_work_order(
        self, pm_work_order_id: str, closed_by: str | None, note: str | None
    ) -> PmWorkOrderDetail:
        detail = await self.get_work_order(pm_work_order_id)
        if assignment_model_of(detail.work_order) == ASSIGNMENT_MODEL_TECHNICIAN_V2:
            # R4 PM Workflow: a V2 work order closes only through E01 review.
            raise _conflict("PM_E01_REVIEW_REQUIRED",
                            "V2 PM work orders close only from PENDING_REVIEW through the PM review")
        if detail.work_order.status == PmWorkOrderStatus.CLOSED:
            raise ApiError(
                code="PM_WORK_ORDER_ALREADY_CLOSED",
                message=f"PM work order '{pm_work_order_id}' is already closed",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if detail.work_order.scope_approved_at is not None:
            # Core Demo Fix section H: "A technician may close a PM once
            # all tasks in the approved PM scope are completed." Only
            # enforced once a scope has actually been approved — a work
            # order that never went through scope approval keeps Phase 4's
            # original permissive closure behavior (E01 remains
            # unresolved; this is a closure precondition, not a new
            # lifecycle state).
            completed_task_ids = {r.pm_task_id for r in detail.results if r.completed}
            incomplete = set(detail.work_order.scope_task_ids) - completed_task_ids
            if incomplete:
                raise ApiError(
                    code="PM_SCOPE_NOT_COMPLETE",
                    message=(
                        "All tasks in the approved PM scope must be completed before closing"
                    ),
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    details={"incomplete_task_ids": sorted(incomplete)},
                )
        snapshot = await self._meter.capture_current_state(
            asset_type=detail.work_order.asset_type,
            asset_id=detail.work_order.asset_id,
            recorded_by=closed_by,
            source_note="PM_WORK_ORDER_CLOSE",
        )
        await self._repository.close_pm_work_order(
            pm_work_order_id,
            closed_by=closed_by,
            note=note,
            closed_snapshot_id=snapshot.meter_snapshot_id,
        )
        return await self.get_work_order(pm_work_order_id)

    # ---- R4 PM Workflow (E01 A3, Q-R4-03/04/05): V2 work orders ----
    #
    # One authority path for every V2 work order: a trusted RequestContext,
    # the job's TEST/REAL data scope, then the action's own Owner-approved
    # actor rule (START: current V2 member or `can_manage_pm` with a current
    # set; SUBMIT: current V2 PRIMARY only; RETURN / CLOSE / CANCEL / resolve:
    # `can_manage_pm`). Lifecycle changes are appended to the E01 journal first
    # and then projected onto `PmWorkOrder.status`; every step is read back, a
    # retry completes whatever is missing, and nothing immutable is ever
    # rewritten. Outstanding records become effective only when a partially
    # performed work order is reviewed and CLOSED. Legacy work orders are
    # refused here and keep their historical behaviour.

    @staticmethod
    def _require_trusted(context: RequestContext | None) -> RequestContext:
        if not isinstance(context, RequestContext) or not (context.user_id or "").strip():
            raise ApiError(
                code="PM_OUTCOME_CONTEXT_REQUIRED",
                message="A trusted, authenticated request context is required",
                status_code=status.HTTP_403_FORBIDDEN,
            )
        return context

    def _require_scope_editable(self, detail: PmWorkOrderDetail) -> None:
        """A V2 scope may change only before review (OPEN / IN_PROGRESS)."""
        if (assignment_model_of(detail.work_order) == ASSIGNMENT_MODEL_TECHNICIAN_V2
                and detail.work_order.status not in (PmWorkOrderStatus.OPEN, PmWorkOrderStatus.IN_PROGRESS)):
            raise _conflict("PM_SCOPE_LOCKED", "The PM scope cannot change once the work order is submitted, "
                            "closed or cancelled")

    async def _v2_detail(self, pm_work_order_id: str, context: RequestContext | None) -> PmWorkOrderDetail:
        """Trusted context, existing V2 work order, inside the server's TEST/REAL
        data scope — for every actor, `can_manage_pm` included."""
        self._require_trusted(context)
        detail = await self.get_work_order(pm_work_order_id)
        if assignment_model_of(detail.work_order) != ASSIGNMENT_MODEL_TECHNICIAN_V2:
            raise model_mismatch(ASSIGNMENT_MODEL_TECHNICIAN_V2)
        require_v2_job_in_scope(PM, detail.work_order, require_v2_context(self._cutover),
                                self._cutover.test_batch_id)
        return detail

    async def _authorize_outcome_access(self, pm_work_order_id: str, context: RequestContext | None,
                                        action_description: str) -> PmWorkOrderDetail:
        detail = await self._v2_detail(pm_work_order_id, context)
        await TechnicianAssignmentService(self._repository, self._cutover).require_recording(
            PM, detail.work_order, context, CAN_MANAGE_PM, action_description)
        return detail

    # -- journal / projection --

    async def _current_status(self, detail: PmWorkOrderDetail
                              ) -> tuple[PmWorkOrderStatus, list[PmWorkOrderTransition]]:
        """The authoritative state from the journal. A projection that lags one
        event behind (interrupted write) is completed; any other disagreement
        fails closed and is never repaired silently."""
        journal = await self._repository.list_pm_work_order_transitions(detail.work_order.pm_work_order_id)
        header = detail.work_order.status
        if not journal or journal[-1].to_status == header:
            return header, journal
        last = journal[-1]
        if last.from_status != header:
            raise _conflict("PM_E01_STATE_INCONSISTENT",
                            "The work order status disagrees with its lifecycle history; nothing was changed")
        await self._project(detail, last)
        return last.to_status, journal

    async def _project(self, detail: PmWorkOrderDetail, event: PmWorkOrderTransition) -> None:
        work_order = detail.work_order
        snapshot_id = None
        if event.to_status == PmWorkOrderStatus.CLOSED:
            snapshot_id = await self._close_snapshot_id(work_order, event)
        try:
            await self._repository.set_pm_work_order_status(
                work_order.pm_work_order_id, event.from_status, event.to_status, actor=event.actor,
                at=event.occurred_at, note=event.reason if event.to_status == PmWorkOrderStatus.CLOSED else None,
                closed_snapshot_id=snapshot_id)
        except ValueError as exc:
            raise _conflict(str(exc), "The work order status changed concurrently; nothing was changed") from exc
        readback = await self._repository.get_pm_work_order(work_order.pm_work_order_id)
        if (readback is None or readback.work_order.status != event.to_status
                or (snapshot_id is not None and readback.work_order.closed_snapshot_id != snapshot_id)):
            raise ApiError(code="PM_E01_READBACK_MISMATCH",
                           message="The stored work order status does not match the recorded transition",
                           status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    async def _close_snapshot_id(self, work_order: PmWorkOrder, event: PmWorkOrderTransition) -> str:
        """The one machine-state snapshot of a CLOSE event. The capture and the status
        compare-and-set are separate writes, so an interrupted projection may already have
        captured it: a retry reuses that capture when it is provably this event's own and
        complete, instead of capturing again. Otherwise a fresh capture is taken, as before;
        no capture is ever deleted or rewritten."""
        reused = await self._interrupted_close_capture(work_order, event)
        if reused is not None:
            return reused
        snapshot = await self._meter.capture_current_state(
            asset_type=work_order.asset_type, asset_id=work_order.asset_id,
            recorded_by=event.actor, source_note="PM_WORK_ORDER_CLOSE")
        return snapshot.meter_snapshot_id

    async def _interrupted_close_capture(self, work_order: PmWorkOrder,
                                         event: PmWorkOrderTransition) -> str | None:
        """The close capture an interrupted projection of `event` left behind, or None. It must
        be the only automatic PM close capture on the asset by the event's actor since the
        event, and no other work order on the asset may have produced it: an unfinished V2
        close, an open legacy job (its close attempts leave no trace), or a closed one whose own
        capture is not older than it (which also excludes every referenced capture). A VEHICLE
        capture must have its GPS half."""
        snapshots = await self._repository.list_meter_snapshots_for_asset(work_order.asset_type, work_order.asset_id)
        others, page = [], 1
        while True:
            rows, total = await self._repository.list_pm_work_orders(
                work_order.asset_type, work_order.asset_id, PageParams(page=page, page_size=200))
            for row in rows:
                if row.pm_work_order_id != work_order.pm_work_order_id:
                    other = await self._repository.get_pm_work_order(row.pm_work_order_id)
                    if other is not None:
                        others.append(other.work_order)
            if not rows or page * 200 >= total:
                break
            page += 1
        candidates = [s for s in snapshots if s.source_note == "PM_WORK_ORDER_CLOSE" and s.is_automatic
                      and s.recorded_by == event.actor and s.recorded_at >= event.occurred_at]
        if len(candidates) != 1:
            return None
        candidate = candidates[0]
        recorded = {s.meter_snapshot_id: s.recorded_at for s in snapshots}
        for other in others:
            if other.status == PmWorkOrderStatus.CANCELLED:
                continue
            if other.status == PmWorkOrderStatus.CLOSED:
                bound = recorded.get(other.closed_snapshot_id) if other.closed_snapshot_id else other.closed_at
                if bound is None or candidate.recorded_at <= bound:
                    return None
                continue
            if assignment_model_of(other) != ASSIGNMENT_MODEL_TECHNICIAN_V2:
                return None
            other_journal = await self._repository.list_pm_work_order_transitions(other.pm_work_order_id)
            if other_journal and other_journal[-1].action == PmE01ContractAction.CLOSE:
                return None
        if work_order.asset_type == AssetType.VEHICLE and len(
                await self._repository.list_location_snapshots_for_event(candidate.meter_snapshot_id)) != 1:
            return None
        return candidate.meter_snapshot_id

    @staticmethod
    def _replay_of(journal: list[PmWorkOrderTransition], request_id: str, action: PmE01ContractAction,
                   fingerprint: str) -> PmWorkOrderTransition | None:
        for event in journal:
            if event.request_id == request_id:
                if event.action != action or event.request_fingerprint != fingerprint:
                    raise _conflict("PM_E01_REQUEST_CONFLICT",
                                    "This request id was already used for a different change; nothing was changed")
                return event
        return None

    async def _transition(self, detail: PmWorkOrderDetail, current: PmWorkOrderStatus,
                          action: PmE01ContractAction, context: RequestContext, request_id: str,
                          fingerprint: str, *, reason: str | None = None, **eligibility) -> PmWorkOrderDetail:
        """Validate with the B01 edge table, append the journal event, verify
        it, then project the status."""
        work_order = detail.work_order
        try:
            target = pm_e01_contract_transition(
                pm_e01_state(current), action, return_reason=reason, cancellation_reason=reason, **eligibility)
        except ValueError as exc:
            code = str(exc)
            if code == "PM_RETURN_REASON_REQUIRED":
                raise _invalid(code, "A reason is required to return the work order") from exc
            raise _conflict(code, f"{action.value} is not allowed from {current.value}; nothing was changed",
                            {"status": current.value}) from exc
        event = PmWorkOrderTransition(
            event_id="PMEV-" + hashlib.sha256(f"{work_order.pm_work_order_id}\x1f{request_id}".encode()).hexdigest()[:24],
            pm_work_order_id=work_order.pm_work_order_id, action=action, from_status=current,
            to_status=PmWorkOrderStatus(target.value), actor=context.user_id, occurred_at=_utcnow(),
            reason=(reason or "").strip() or None, request_id=request_id, request_fingerprint=fingerprint,
            is_test_data=work_order.is_test_data, test_batch_id=work_order.test_batch_id)
        try:
            stored, _ = await self._repository.append_pm_work_order_transition(event)
        except ValueError as exc:
            raise _conflict(str(exc), "The lifecycle history changed concurrently; nothing was changed") from exc
        journal = await self._repository.list_pm_work_order_transitions(work_order.pm_work_order_id)
        if not journal or journal[-1] != stored:
            raise ApiError(code="PM_E01_READBACK_MISMATCH",
                           message="The stored lifecycle event does not match what was written",
                           status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        await self._project(detail, stored)
        return await self.get_work_order(work_order.pm_work_order_id)

    async def _begin(self, pm_work_order_id: str, context: RequestContext | None, action: PmE01ContractAction,
                     request_id: str, fingerprint: str
                     ) -> tuple[PmWorkOrderDetail, PmWorkOrderStatus, PmWorkOrderTransition | None]:
        detail = await self._v2_detail(pm_work_order_id, context)
        if not (request_id or "").strip():
            raise _invalid("REQUEST_ID_REQUIRED", "A client request id is required for this change")
        current, journal = await self._current_status(detail)
        if current != detail.work_order.status:  # a lagging projection was just completed
            detail = await self.get_work_order(pm_work_order_id)
        return detail, current, self._replay_of(journal, request_id, action, fingerprint)

    async def start_work_order(self, pm_work_order_id: str, context: RequestContext | None, *,
                               request_id: str) -> PmWorkOrderDetail:
        """OPEN -> IN_PROGRESS: a current V2 member or `can_manage_pm`, and a
        current valid V2 assignment set must exist."""
        action = PmE01ContractAction.START
        fingerprint = pm_work_order_transition_fingerprint(pm_work_order_id, action, None)
        detail = await self._v2_detail(pm_work_order_id, context)
        assignment = TechnicianAssignmentService(self._repository, self._cutover)
        await assignment.require_recording(PM, detail.work_order, context, CAN_MANAGE_PM,
                                           "การเริ่มงาน PM (start a PM work order)")
        detail, current, replay = await self._begin(pm_work_order_id, context, action, request_id, fingerprint)
        if replay is not None:
            return detail
        state = (await assignment.read(PM, pm_work_order_id)).state
        if state.status == STATUS_AMBIGUOUS:
            raise _conflict("TECHNICIAN_ASSIGNMENT_ORDER_AMBIGUOUS", "The current assignment set cannot be determined")
        if state.current is None:
            raise _conflict("PM_E01_ASSIGNMENT_REQUIRED",
                            "A current V2 technician assignment is required before work can start")
        return await self._transition(detail, current, action, context, request_id, fingerprint)

    async def submit_for_review(self, pm_work_order_id: str, context: RequestContext | None, *,
                                request_id: str, expected_set_id: str | None) -> PmWorkOrderDetail:
        """IN_PROGRESS -> PENDING_REVIEW: only the current V2 PRIMARY (no
        capability substitute), every in-scope item disposed, at least one
        genuinely PERFORMED."""
        action = PmE01ContractAction.SUBMIT
        fingerprint = pm_work_order_transition_fingerprint(pm_work_order_id, action, None, expected_set_id)
        detail = await self._v2_detail(pm_work_order_id, context)
        await self._require_current_primary(detail, context, expected_set_id)
        detail, current, replay = await self._begin(pm_work_order_id, context, action, request_id, fingerprint)
        if replay is not None:
            return detail
        if current == PmWorkOrderStatus.IN_PROGRESS:
            await self._require_complete_accounting(detail)
        return await self._transition(detail, current, action, context, request_id, fingerprint)

    async def return_for_rework(self, pm_work_order_id: str, context: RequestContext | None, *,
                                request_id: str, reason: str | None) -> PmWorkOrderDetail:
        """PENDING_REVIEW -> IN_PROGRESS with a mandatory reason; saved items
        and the earlier history are never changed."""
        action = PmE01ContractAction.RETURN
        fingerprint = pm_work_order_transition_fingerprint(pm_work_order_id, action, reason)
        self._require_trusted(context)
        require_capability(context, CAN_MANAGE_PM, "การส่งคืนงาน PM ให้แก้ไข (return a PM work order)")
        detail, current, replay = await self._begin(pm_work_order_id, context, action, request_id, fingerprint)
        if replay is not None:
            return detail
        return await self._transition(detail, current, action, context, request_id, fingerprint, reason=reason)

    async def close_after_review(self, pm_work_order_id: str, context: RequestContext | None, *,
                                 request_id: str, note: str | None = None) -> PmWorkOrderDetail:
        """PENDING_REVIEW -> CLOSED by `can_manage_pm`. Each NOT_PERFORMED item
        becomes exactly one effective Outstanding record, created from its
        stored Outcome before the CLOSED event is recorded."""
        action = PmE01ContractAction.CLOSE
        fingerprint = pm_work_order_transition_fingerprint(pm_work_order_id, action, note)
        self._require_trusted(context)
        require_capability(context, CAN_MANAGE_PM, "การปิดใบสั่งงาน PM (final PM Work Order closure)")
        detail, current, replay = await self._begin(pm_work_order_id, context, action, request_id, fingerprint)
        if replay is not None:
            return detail
        if current == PmWorkOrderStatus.PENDING_REVIEW:
            outcomes = await self._require_complete_accounting(detail)
            for outcome in outcomes:
                if outcome.disposition == PmItemContractDisposition.NOT_PERFORMED:
                    await self._store_outstanding_from(outcome, context.user_id)
        return await self._transition(detail, current, action, context, request_id, fingerprint, reason=note)

    async def cancel_work_order(self, pm_work_order_id: str, context: RequestContext | None, *,
                                request_id: str, reason: str | None) -> PmWorkOrderDetail:
        """OPEN / IN_PROGRESS -> CANCELLED by `can_manage_pm`, with a reason,
        only with no PM result, Outcome, PM evidence or Store request at all.
        Nothing linked is changed or deleted."""
        action = PmE01ContractAction.CANCEL
        fingerprint = pm_work_order_transition_fingerprint(pm_work_order_id, action, reason)
        self._require_trusted(context)
        require_capability(context, CAN_MANAGE_PM, "การยกเลิกใบสั่งงาน PM (cancel a PM work order)")
        detail, current, replay = await self._begin(pm_work_order_id, context, action, request_id, fingerprint)
        if replay is not None:
            return detail
        outcomes = await self._repository.list_pm_item_outcomes(pm_work_order_id)
        evidence = await self._repository.list_attachments_for_source("PM_WORK_ORDER", pm_work_order_id)
        store_requests = await self._repository.list_material_requests_for_work_order(pm_work_order_id)
        store_lines = await self._repository.list_requisition_lines_for_work_order(pm_work_order_id)
        blockers = [name for name, present in (("PM_RESULT", detail.results), ("PM_ITEM_OUTCOME", outcomes),
                                               ("PM_EVIDENCE", evidence), ("STORE_REQUEST", store_requests),
                                               ("STORE_REQUISITION_LINE", store_lines)) if present]
        if blockers and (reason or "").strip() and current in (PmWorkOrderStatus.OPEN, PmWorkOrderStatus.IN_PROGRESS):
            raise _conflict("PM_CANCEL_NOT_ELIGIBLE", "This work order already has PM work, evidence or Store "
                            "requests and cannot be cancelled; nothing was changed", {"blockers": blockers})
        performed = sum(1 for o in outcomes if o.disposition == PmItemContractDisposition.PERFORMED)
        return await self._transition(
            detail, current, action, context, request_id, fingerprint, reason=reason,
            cancellation_eligibility_proven=not store_requests and not store_lines,
            actual_performed_count=performed, existing_result_count=len(detail.results) + len(outcomes),
            existing_evidence_count=len(evidence))

    async def _require_current_primary(self, detail: PmWorkOrderDetail, context: RequestContext,
                                       expected_set_id: str | None) -> None:
        codes = {"REPAIR_COMPLETION_LEAD_ONLY": "PM_SUBMIT_PRIMARY_ONLY",
                 "REPAIR_LEAD_NOT_ASSIGNED": "PM_E01_ASSIGNMENT_REQUIRED",
                 "REPAIR_ACTOR_NOT_ELIGIBLE": "PM_SUBMIT_ACTOR_NOT_ELIGIBLE",
                 "REPAIR_ASSIGNMENT_STALE": "PM_ASSIGNMENT_STALE"}
        try:
            await TechnicianAssignmentService(self._repository, self._cutover).require_current_primary(
                PM, detail.work_order, context.user_id, expected_set_id, context)
        except ApiError as exc:
            if exc.code not in codes:
                raise
            raise ApiError(code=codes[exc.code], message="Only the current V2 PRIMARY technician of this PM work "
                           "order may submit it for review", status_code=exc.status_code, details=exc.details) from exc

    async def _require_complete_accounting(self, detail: PmWorkOrderDetail) -> list[PmItemOutcome]:
        """Every in-scope item saved completely (result + Outcome, linked), and
        at least one genuinely PERFORMED; otherwise no submit or close."""
        work_order = detail.work_order
        outcomes = await self._repository.list_pm_item_outcomes(work_order.pm_work_order_id)
        results = {r.pm_work_result_id: r for r in detail.results}
        linked = {o.source_pm_work_result_id for o in outcomes}
        incomplete = sorted({o.pm_task_id for o in outcomes
                             if o.source_pm_work_result_id not in results
                             or results[o.source_pm_work_result_id].pm_task_id != o.pm_task_id}
                            | {r.pm_task_id for r in detail.results if r.pm_work_result_id not in linked})
        if incomplete:
            raise _conflict("PM_E01_ITEM_RECORD_INCOMPLETE", "Some PM items were not saved completely; save them "
                            "again before review", {"pm_task_ids": incomplete})
        performed = tuple(o.pm_task_id for o in outcomes if o.disposition == PmItemContractDisposition.PERFORMED)
        not_performed = tuple(o.pm_task_id for o in outcomes
                              if o.disposition == PmItemContractDisposition.NOT_PERFORMED)
        try:
            assess_pm_contract_completion(in_scope_task_ids=tuple(work_order.scope_task_ids),
                                          performed_task_ids=performed, accounted_not_performed_ids=not_performed)
        except ValueError as exc:
            missing = sorted(set(work_order.scope_task_ids) - set(performed) - set(not_performed))
            raise _invalid(str(exc), "Every in-scope PM item must be Performed or Not Performed with a reason, "
                           "and at least one must be genuinely Performed", {"missing_pm_task_ids": missing}) from exc
        return outcomes

    # -- reads --

    async def list_item_outcomes(self, pm_work_order_id: str,
                                 context: RequestContext | None) -> list[PmItemOutcome]:
        await self._authorize_outcome_access(
            pm_work_order_id, context, "การอ่านผลการปฏิบัติงาน PM (read PM item outcomes)")
        return await self._repository.list_pm_item_outcomes(pm_work_order_id)

    async def list_work_order_history(self, pm_work_order_id: str,
                                      context: RequestContext | None) -> list[PmWorkOrderTransition]:
        detail = await self._authorize_outcome_access(
            pm_work_order_id, context, "การอ่านประวัติสถานะงาน PM (read PM work order history)")
        await self._current_status(detail)
        return await self._repository.list_pm_work_order_transitions(pm_work_order_id)

    async def list_outstanding_items(self, pm_work_order_id: str,
                                     context: RequestContext | None) -> list[PmOutstandingState]:
        """Effective Outstanding records of one work order: none until it is
        CLOSED (an interrupted close never surfaces partial records)."""
        detail = await self._authorize_outcome_access(
            pm_work_order_id, context, "การอ่านงาน PM ค้าง (read PM Outstanding items)")
        current, _ = await self._current_status(detail)
        if current != PmWorkOrderStatus.CLOSED:
            return []
        return [await self._outstanding_state(i)
                for i in await self._repository.list_pm_outstanding_items(pm_work_order_id)]

    async def list_asset_outstanding(self, asset_type: AssetType, asset_id: str,
                                     context: RequestContext | None) -> list[PmOutstandingState]:
        """The post-PM Outstanding backlog of one asset (separate from Due):
        effective records of in-scope CLOSED V2 work orders only."""
        self._require_trusted(context)
        data_context = require_v2_context(self._cutover)
        states = []
        for item in await self._repository.list_pm_outstanding_items_for_asset(asset_type, asset_id):
            detail = await self._repository.get_pm_work_order(item.pm_work_order_id)
            if detail is None or assignment_model_of(detail.work_order) != ASSIGNMENT_MODEL_TECHNICIAN_V2:
                continue
            try:
                require_v2_job_in_scope(PM, detail.work_order, data_context, self._cutover.test_batch_id)
            except ApiError:
                continue
            if (await self._current_status(detail))[0] == PmWorkOrderStatus.CLOSED:
                states.append(await self._outstanding_state(item))
        return states

    async def get_outstanding_item(self, outstanding_id: str) -> PmOutstandingItem:
        item = await self._repository.get_pm_outstanding_item(outstanding_id)
        if item is None:
            raise ApiError(code="PM_OUTSTANDING_NOT_FOUND", message=f"Outstanding item '{outstanding_id}' was not "
                           "found", status_code=status.HTTP_404_NOT_FOUND)
        return item

    async def _outstanding_state(self, item: PmOutstandingItem) -> PmOutstandingState:
        return PmOutstandingState(item=item,
                                  resolution=await self._repository.get_pm_outstanding_resolution(item.outstanding_id))

    # -- item save --

    async def record_item_outcome(
        self,
        pm_work_order_id: str,
        pm_task_id: str,
        disposition: PmItemContractDisposition,
        context: RequestContext | None,
        *,
        performed_actions: tuple[str, ...] = (),
        reason_code: str | None = None,
        other_text: str | None = None,
        evidence_attachment_ids: tuple[str, ...] = (),
        remark: str | None = None,
        meter_snapshot_id: str | None = None,
        used_parts: tuple[UsedPartInput, ...] = (),
    ) -> PmItemOutcomeRecording:
        """Save one PM item while IN_PROGRESS: one factual `PmWorkResult`
        (`completed` written from the stated disposition, never the other way
        round) and one truthful `PmItemOutcome` referencing it.

        The actor is always `context.user_id`, never a caller-supplied id, and
        no caller-supplied list is ever an approved vocabulary. A
        NOT_PERFORMED item can be saved only after at least one genuinely
        PERFORMED item is saved (before that it stays an unsaved draft).
        Success is returned only after both records are read back and verified;
        a retry with the same payload completes a partially saved item."""
        detail = await self._authorize_outcome_access(
            pm_work_order_id, context, "การบันทึกผลการปฏิบัติงาน PM (record a PM item outcome)")
        work_order = detail.work_order
        current, _ = await self._current_status(detail)
        if current != PmWorkOrderStatus.IN_PROGRESS:
            raise _conflict("PM_E01_ITEM_SAVE_NOT_ALLOWED", "PM items can be saved only while the work order is "
                            "IN_PROGRESS", {"status": current.value})
        if not isinstance(disposition, PmItemContractDisposition):
            raise _invalid("VALIDATION_ERROR", "disposition must be PERFORMED or NOT_PERFORMED")
        revision_detail = await self._repository.get_pm_task_revision(work_order.pm_plan_id,
                                                                      work_order.revision_id)
        if revision_detail is None or revision_detail.revision.revision_id != work_order.revision_id:
            raise ApiError(
                code="PM_TASK_REVISION_NOT_FOUND",
                message="The frozen task revision of this work order cannot be read",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        task = next((t for t in revision_detail.tasks if t.pm_task_id == pm_task_id), None)
        if task is None:
            raise _invalid("VALIDATION_ERROR",
                           f"Task '{pm_task_id}' does not belong to this work order's task revision",
                           {"pm_task_id": pm_task_id})
        if pm_task_id not in work_order.scope_task_ids:
            raise _invalid("PM_TASK_NOT_IN_SCOPE", f"Task '{pm_task_id}' is not in this work order's selected "
                           "scope", {"pm_task_id": pm_task_id})
        for attachment_id in evidence_attachment_ids:
            attachment = await self._repository.get_attachment(attachment_id) if (attachment_id or "").strip() else None
            if (attachment is None or attachment.purpose != AttachmentPurpose.PM_EVIDENCE
                    or attachment.source_type != "PM_WORK_ORDER" or attachment.source_id != pm_work_order_id):
                raise _invalid("PM_OUTCOME_EVIDENCE_INVALID",
                               "Every evidence attachment must be existing PM evidence of this work order",
                               {"attachment_id": attachment_id})
        for part in used_parts:
            if part.part_id is not None:
                await require_part_exists(self._repository, part.part_id)
            if part.part_instance_id is not None:
                await require_part_instance_exists(self._repository, part.part_instance_id)
        candidate = self._build_outcome(work_order, pm_task_id, disposition, context, performed_actions,
                                        reason_code, other_text, evidence_attachment_ids, _utcnow(), None)
        stored_outcome = await self._repository.get_pm_item_outcome(candidate.outcome_id)
        if disposition == PmItemContractDisposition.NOT_PERFORMED and stored_outcome is None and not any(
            o.disposition == PmItemContractDisposition.PERFORMED
            for o in await self._repository.list_pm_item_outcomes(pm_work_order_id)
        ):
            raise _invalid("PM_NOT_PERFORMED_REQUIRES_PERFORMED_FIRST",
                           "Save at least one genuinely Performed item before saving a Not Performed item")
        completed = disposition == PmItemContractDisposition.PERFORMED
        parts = [{"part_description": p.part_description, "quantity": p.quantity, "unit": p.unit,
                  "part_id": p.part_id, "part_instance_id": p.part_instance_id, "action": p.action}
                 for p in used_parts]
        result = next((r for r in detail.results if r.pm_task_id == pm_task_id), None)
        result_replayed = result is not None
        if result is not None:
            same = (result.completed == completed and result.remark == remark
                    and result.evidence_attachment_ids == list(evidence_attachment_ids)
                    and result.performed_by == context.user_id
                    and (meter_snapshot_id is None or result.meter_snapshot_id == meter_snapshot_id)
                    and [(u.part_description, u.quantity, u.unit, u.part_id, u.part_instance_id, u.action)
                         for u in result.used_parts]
                    == [(p["part_description"], p["quantity"], p["unit"], p["part_id"], p["part_instance_id"],
                         p["action"]) for p in parts])
            if not same:
                raise _conflict("PM_OUTCOME_CONFLICT",
                                "A different result is already saved for this item; nothing was changed")
        else:
            if meter_snapshot_id is not None:
                await self._meter.require_snapshot_exists(meter_snapshot_id)
            else:
                snapshot = await self._meter.capture_current_state(
                    asset_type=work_order.asset_type, asset_id=work_order.asset_id,
                    recorded_by=context.user_id, source_note="PM_TASK_RESULT")
                meter_snapshot_id = snapshot.meter_snapshot_id
            written = await self._repository.create_pm_work_result(
                pm_work_order_id=pm_work_order_id, pm_task_id=pm_task_id, revision_id=work_order.revision_id,
                sequence=task.sequence, task_description=task.description, completed=completed,
                meter_snapshot_id=meter_snapshot_id, remark=remark, used_parts=parts,
                evidence_attachment_ids=list(evidence_attachment_ids), performed_by=context.user_id)
            result = await self._repository.find_pm_work_result(written.pm_work_result_id)
            if result is None or result != written:
                raise _readback_mismatch("PM work result")
        candidate = self._build_outcome(work_order, pm_task_id, disposition, context, performed_actions,
                                        reason_code, other_text, evidence_attachment_ids, result.performed_at,
                                        result.pm_work_result_id)
        outcome, outcome_replayed = await self._store_item_outcome(candidate)
        return PmItemOutcomeRecording(result=result, outcome=outcome, result_replayed=result_replayed,
                                      outcome_replayed=outcome_replayed)

    @staticmethod
    def _build_outcome(work_order, pm_task_id: str, disposition: PmItemContractDisposition,
                       context: RequestContext, performed_actions, reason_code, other_text,
                       evidence_attachment_ids, recorded_at: datetime, result_id: str | None) -> PmItemOutcome:
        try:
            return build_pm_item_outcome(
                pm_work_order_id=work_order.pm_work_order_id, pm_task_id=pm_task_id,
                revision_id=work_order.revision_id, disposition=disposition, recorded_at=recorded_at,
                performed_actions=tuple(performed_actions), reason_code=reason_code, other_text=other_text,
                evidence_attachment_ids=tuple(evidence_attachment_ids), recorded_by=context.user_id,
                source_pm_work_result_id=result_id, **_vocabulary())
        except ValueError as exc:
            raise _rejected(exc) from exc

    async def _store_item_outcome(self, candidate: PmItemOutcome) -> tuple[PmItemOutcome, bool]:
        """Store `candidate` once, or reuse the stored Outcome of the same
        identity when it is identical. Any difference — actor included — is a
        conflict, so a reused Outcome always equals a candidate the B01 builder
        accepted."""
        stored = await self._repository.get_pm_item_outcome(candidate.outcome_id)
        if stored is not None:
            if stored != candidate:
                raise ApiError(code="PM_OUTCOME_CONFLICT",
                               message="A different outcome is already recorded for this item; nothing was changed",
                               status_code=status.HTTP_409_CONFLICT)
            return stored, True
        try:
            await self._repository.create_pm_item_outcome(candidate)
        except ValueError as exc:
            raise _rejected(exc, status.HTTP_409_CONFLICT) from exc
        readback = await self._repository.get_pm_item_outcome(candidate.outcome_id)
        if readback != candidate:
            raise _readback_mismatch("PM item outcome")
        return readback, False

    async def _store_outstanding_from(self, outcome: PmItemOutcome,
                                      created_by: str) -> tuple[PmOutstandingItem, bool]:
        """Build the Outstanding record only from the stored NOT_PERFORMED
        Outcome, store it once and verify its provenance against that Outcome."""
        try:
            item = build_pm_outstanding_item(outcome, created_by=created_by, created_at=_utcnow())
        except ValueError as exc:
            raise _rejected(exc, status.HTTP_409_CONFLICT) from exc
        try:
            _, replayed = await self._repository.create_pm_outstanding_item(item)
        except ValueError as exc:
            raise _rejected(exc, status.HTTP_409_CONFLICT) from exc
        readback = await self._repository.get_pm_outstanding_item(item.outstanding_id)
        if (readback is None or readback.creation_fingerprint != item.creation_fingerprint
                or (not replayed and readback != item)
                or readback.source_identity != outcome.source_identity
                or (readback.origin_reason_code, readback.origin_other_text, readback.origin_recorded_by,
                    readback.origin_recorded_at, readback.origin_pm_work_result_id)
                != (outcome.reason_code, outcome.other_text, outcome.recorded_by, outcome.recorded_at,
                    outcome.source_pm_work_result_id)):
            raise _readback_mismatch("PM Outstanding record")
        return readback, replayed

    # -- Outstanding resolution --

    async def resolve_outstanding(
        self,
        outstanding_id: str,
        context: RequestContext | None,
        *,
        later_pm_work_result_id: str | None = None,
        later_repair_id: str | None = None,
        evidence_attachment_ids: tuple[str, ...] = (),
    ) -> tuple[PmOutstandingResolutionReference, bool]:
        """Resolve exactly one effective Outstanding record with verified proof
        of later actual work on that item: a later CLOSED V2 PM work order with
        a genuinely PERFORMED Outcome for the same task (evidence from that
        Outcome), or a CLOSED Repair raised from this item's own PM result
        (evidence from that Repair). Nothing else is changed."""
        self._require_trusted(context)
        require_capability(context, CAN_MANAGE_PM, "การปิดงาน PM ค้าง (resolve a PM Outstanding item)")
        item = await self._repository.get_pm_outstanding_item(outstanding_id)
        if item is None:
            raise ApiError(code="PM_OUTSTANDING_NOT_FOUND", message=f"Outstanding item '{outstanding_id}' was not "
                           "found", status_code=status.HTTP_404_NOT_FOUND)
        source = await self._v2_detail(item.pm_work_order_id, context)
        if (await self._current_status(source))[0] != PmWorkOrderStatus.CLOSED:
            raise _conflict("PM_OUTSTANDING_NOT_EFFECTIVE", "This item is not an effective Outstanding obligation")
        evidence = tuple(evidence_attachment_ids)
        if bool((later_pm_work_result_id or "").strip()) == bool((later_repair_id or "").strip()):
            raise _invalid("PM_RESOLUTION_REFERENCE_SOURCE_INVALID",
                           "Name exactly one later PM result or one later Repair")
        if not evidence or not all((e or "").strip() for e in evidence):
            raise _invalid("PM_RESOLUTION_REFERENCE_EVIDENCE_REQUIRED", "Evidence of the actual work is required")
        if later_pm_work_result_id:
            await self._verify_later_pm(item, source, later_pm_work_result_id, evidence, context)
        else:
            await self._verify_later_repair(item, source, later_repair_id, evidence)
        resolution = PmOutstandingResolutionReference(
            outstanding_id=outstanding_id, later_pm_work_result_id=later_pm_work_result_id or None,
            later_repair_id=later_repair_id or None, evidence_attachment_ids=evidence,
            referenced_by=context.user_id, referenced_at=_utcnow())
        try:
            stored, replayed = await self._repository.create_pm_outstanding_resolution(resolution)
        except ValueError as exc:
            raise _rejected(exc, status.HTTP_409_CONFLICT) from exc
        readback = await self._repository.get_pm_outstanding_resolution(outstanding_id)
        if readback is None or readback != stored or (
                readback.model_dump(exclude={"referenced_at"}) != resolution.model_dump(exclude={"referenced_at"})):
            raise _readback_mismatch("PM Outstanding resolution")
        return readback, replayed

    def _evidence_error(self, message: str) -> ApiError:
        return _invalid("PM_RESOLUTION_EVIDENCE_INVALID", message)

    async def _verify_later_pm(self, item: PmOutstandingItem, source: PmWorkOrderDetail, result_id: str,
                               evidence: tuple[str, ...], context: RequestContext) -> None:
        result = await self._repository.find_pm_work_result(result_id)
        if result is None or result.pm_work_order_id == item.pm_work_order_id:
            raise self._evidence_error("The later PM result must exist on a different PM work order")
        later = await self._v2_detail(result.pm_work_order_id, context)
        if (later.work_order.asset_type, later.work_order.asset_id) != (
                source.work_order.asset_type, source.work_order.asset_id):
            raise self._evidence_error("The later PM work order is on a different asset")
        if (await self._current_status(later))[0] != PmWorkOrderStatus.CLOSED:
            raise self._evidence_error("The later PM work order is not CLOSED")
        if result.pm_task_id != item.pm_task_id:
            raise self._evidence_error("The later PM result is for a different PM item")
        outcome = await self._repository.get_pm_item_outcome(
            pm_item_outcome_id(later.work_order.pm_work_order_id, result.pm_task_id, later.work_order.revision_id))
        if (outcome is None or outcome.disposition != PmItemContractDisposition.PERFORMED
                or outcome.source_pm_work_result_id != result.pm_work_result_id):
            raise self._evidence_error("The later PM item was not genuinely Performed")
        if outcome.recorded_at <= item.created_at:
            raise self._evidence_error("The later PM work does not postdate the Outstanding item")
        if not set(evidence) <= set(outcome.evidence_attachment_ids):
            raise self._evidence_error("Evidence must be the later PM item's own evidence")

    async def _verify_later_repair(self, item: PmOutstandingItem, source: PmWorkOrderDetail, repair_id: str,
                                   evidence: tuple[str, ...]) -> None:
        detail = await self._repository.get_repair(repair_id)
        repair = detail.repair if detail is not None else None
        if repair is None:
            raise self._evidence_error("The later Repair does not exist")
        if (repair.asset_type, repair.asset_id) != (source.work_order.asset_type, source.work_order.asset_id):
            raise self._evidence_error("The Repair is on a different asset")
        if repair.status != RepairStatus.CLOSED or repair.closed_at is None:
            raise self._evidence_error("The Repair is not CLOSED")
        origin = item.origin_pm_work_result_id
        related = origin is not None and repair.source_type == RepairSourceType.PM_RESULT and repair.source_id == origin
        if not related and origin is not None and repair.source_type == RepairSourceType.REPAIR_REQUEST:
            request = await self._repository.get_repair_request(repair.source_id) if repair.source_id else None
            related = (request is not None and request.source_type == RepairSourceType.PM_RESULT.value
                       and request.source_id == origin and request.repair_id == repair.repair_id)
        if not related:
            raise self._evidence_error("The Repair was not raised from this Outstanding PM item")
        if repair.closed_at <= item.origin_recorded_at:
            raise self._evidence_error("The Repair work does not postdate the Not Performed item")
        for attachment_id in evidence:
            attachment = await self._repository.get_attachment(attachment_id)
            if (attachment is None or attachment.purpose != AttachmentPurpose.REPAIR_EVIDENCE
                    or attachment.source_type != "REPAIR" or attachment.source_id != repair.repair_id):
                raise self._evidence_error("Evidence must be this Repair's own evidence")
