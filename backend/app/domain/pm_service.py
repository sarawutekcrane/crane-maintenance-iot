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
        model_id: str | None = None
        if asset_type == AssetType.VEHICLE:
            vehicle = await self._repository.get_vehicle(asset_id)
            model_id = vehicle.model_id if vehicle else None

        plans = await self._repository.list_pm_plans(asset_type=asset_type, model_id=model_id)
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
        revision_detail = await self.get_active_task_revision(pm_plan_id)
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
        )
        return await self.get_work_order(work_order.pm_work_order_id)

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
