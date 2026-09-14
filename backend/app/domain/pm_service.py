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

from dataclasses import dataclass, field

from fastapi import status

from app.domain.asset import AssetType
from app.domain.asset_lookup import require_asset_exists
from app.domain.common import Page, PageParams
from app.domain.meter_service import MeterService
from app.domain.part import PartActionType
from app.domain.part_lookup import require_part_exists, require_part_instance_exists
from app.domain.pm import (
    PmPlan,
    PmPlanStatus,
    PmTaskRevisionDetail,
    PmTriggerType,
    PmWorkOrderDetail,
    PmWorkOrderStatus,
    PmWorkOrderSummary,
)
from app.domain.requisition import RequisitionSourceType
from app.errors import ApiError
from app.repositories.base import Repository


@dataclass(frozen=True)
class UsedPartInput:
    part_description: str
    quantity: float | None = None
    unit: str | None = None
    part_id: str | None = None
    part_instance_id: str | None = None
    action: PartActionType | None = None


class PmService:
    def __init__(self, repository: Repository, meter_service: MeterService) -> None:
        self._repository = repository
        self._meter = meter_service

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
        await require_asset_exists(self._repository, asset_type, asset_id)
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
        group/task set. Section F: auto-generate a material-requisition
        line (Store/Inventory integration boundary — see
        `app.domain.requisition`) from each in-scope task's standard
        `PmTaskPart` list. Never decrements any stock balance."""
        detail = await self.get_work_order(pm_work_order_id)
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
        for task in tasks_in_scope:
            for part in task.standard_parts:
                await self._repository.create_requisition_line(
                    work_order_reference=pm_work_order_id,
                    source_type=RequisitionSourceType.PM,
                    part_id=part.part_id,
                    part_instance_id=None,
                    part_description=part.part_description,
                    requested_quantity=part.quantity,
                    unit=part.unit,
                    created_by=approved_by,
                )
        return await self.get_work_order(pm_work_order_id)

    async def list_requisition_lines(self, pm_work_order_id: str) -> list:
        await self.get_work_order(pm_work_order_id)
        return await self._repository.list_requisition_lines_for_work_order(pm_work_order_id)

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
        self, asset_type: AssetType | None, asset_id: str | None, params: PageParams
    ) -> Page[PmWorkOrderSummary]:
        items, total = await self._repository.list_pm_work_orders(
            asset_type=asset_type, asset_id=asset_id, params=params
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
