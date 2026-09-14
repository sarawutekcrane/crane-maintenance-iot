"""PM (preventive maintenance) routes (Phase 4).

Reachable from Vehicle/Equipment Detail via a "PM" action, mirroring the
Phase 3 "ตรวจเช็ค" pattern — the frozen `/vehicle/{vehicle_id}` and
`/equipment/{equipment_id}` QR routes/endpoints are untouched.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.v1.pm_schemas import (
    AddPmScopeTaskRequest,
    AssignPmWorkOrderRequest,
    ClosePmWorkOrderRequest,
    OpenPmWorkOrderRequest,
    PmAssignmentHistoryEntryResponse,
    PmPlanResponse,
    PmPlanStatusResponse,
    PmScopeAdditionResponse,
    PmTaskPartResponse,
    PmTaskResponse,
    PmTaskRevisionDetailResponse,
    PmTaskRevisionResponse,
    PmUsedPartResponse,
    PmWorkOrderDetailResponse,
    PmWorkOrderResponse,
    PmWorkOrderSummaryResponse,
    PmWorkResultResponse,
    RequisitionLineResponse,
    SubmitPmTaskResultRequest,
)
from app.context import RequestContext
from app.dependencies import get_current_context, get_pm_service
from app.domain.asset import AssetType
from app.domain.authz import CAN_MANAGE_PM, require_capability
from app.domain.common import Page, PageParams
from app.domain.pm import (
    PmPlan,
    PmPlanStatus,
    PmScopeAdditionAudit,
    PmTask,
    PmTaskRevision,
    PmTaskRevisionDetail,
    PmWorkOrder,
    PmWorkOrderDetail,
    PmWorkOrderStatus,
    PmWorkResult,
)
from app.domain.pm_service import PmService, UsedPartInput
from app.domain.requisition import RequisitionLine

router = APIRouter(tags=["pm"])


def _plan_response(plan: PmPlan) -> PmPlanResponse:
    return PmPlanResponse(
        pm_plan_id=plan.pm_plan_id,
        plan_code=plan.plan_code,
        asset_type=plan.asset_type,
        name=plan.name,
        model_ids=list(plan.model_ids),
    )


def _revision_response(revision: PmTaskRevision) -> PmTaskRevisionResponse:
    return PmTaskRevisionResponse.model_validate(revision.model_dump())


def _task_response(task: PmTask) -> PmTaskResponse:
    return PmTaskResponse(
        pm_task_id=task.pm_task_id,
        revision_id=task.revision_id,
        sequence=task.sequence,
        group=task.group,
        description=task.description,
        trigger_type=task.trigger_type,
        interval_value=task.interval_value,
        interval_unit=task.interval_unit,
        standard_parts=[
            PmTaskPartResponse.model_validate(p.model_dump()) for p in task.standard_parts
        ],
    )


def _revision_detail_response(detail: PmTaskRevisionDetail) -> PmTaskRevisionDetailResponse:
    return PmTaskRevisionDetailResponse(
        plan=_plan_response(detail.plan),
        revision=_revision_response(detail.revision),
        tasks=[_task_response(t) for t in detail.tasks],
    )


def _plan_status_response(status_: PmPlanStatus) -> PmPlanStatusResponse:
    return PmPlanStatusResponse(
        plan=_plan_response(status_.plan),
        active_revision=_revision_response(status_.active_revision)
        if status_.active_revision
        else None,
        last_completed_work_order_id=status_.last_completed_work_order_id,
        last_completed_at=status_.last_completed_at,
        last_completed_meter_snapshot_id=status_.last_completed_meter_snapshot_id,
        due_status=status_.due_status,
        due_status_note=status_.due_status_note,
    )


def _work_order_response(work_order: PmWorkOrder) -> PmWorkOrderResponse:
    return PmWorkOrderResponse.model_validate(work_order.model_dump())


def _work_result_response(result: PmWorkResult) -> PmWorkResultResponse:
    return PmWorkResultResponse(
        pm_work_result_id=result.pm_work_result_id,
        pm_work_order_id=result.pm_work_order_id,
        pm_task_id=result.pm_task_id,
        revision_id=result.revision_id,
        sequence=result.sequence,
        task_description=result.task_description,
        completed=result.completed,
        meter_snapshot_id=result.meter_snapshot_id,
        remark=result.remark,
        used_parts=[
            PmUsedPartResponse.model_validate(p.model_dump()) for p in result.used_parts
        ],
        evidence_attachment_ids=list(result.evidence_attachment_ids),
        performed_by=result.performed_by,
        performed_at=result.performed_at,
    )


def _scope_addition_response(addition: PmScopeAdditionAudit) -> PmScopeAdditionResponse:
    return PmScopeAdditionResponse.model_validate(addition.model_dump())


def _requisition_line_response(line: RequisitionLine) -> RequisitionLineResponse:
    return RequisitionLineResponse.model_validate(line.model_dump())


def _work_order_detail_response(detail: PmWorkOrderDetail) -> PmWorkOrderDetailResponse:
    return PmWorkOrderDetailResponse(
        work_order=_work_order_response(detail.work_order),
        results=[_work_result_response(r) for r in detail.results],
        scope_additions=[_scope_addition_response(a) for a in detail.scope_additions],
    )


@router.get("/pm/plans/status", response_model=list[PmPlanStatusResponse])
async def get_pm_plan_status(
    asset_type: AssetType = Query(...),
    asset_id: str = Query(...),
    service: PmService = Depends(get_pm_service),
) -> list[PmPlanStatusResponse]:
    statuses = await service.list_applicable_plan_status(asset_type, asset_id)
    return [_plan_status_response(s) for s in statuses]


@router.get("/pm/plans/{pm_plan_id}/active-revision", response_model=PmTaskRevisionDetailResponse)
async def get_active_pm_task_revision(
    pm_plan_id: str, service: PmService = Depends(get_pm_service)
) -> PmTaskRevisionDetailResponse:
    detail = await service.get_active_task_revision(pm_plan_id)
    return _revision_detail_response(detail)


@router.get(
    "/pm/plans/{pm_plan_id}/revisions/{revision_id}",
    response_model=PmTaskRevisionDetailResponse,
)
async def get_pm_task_revision(
    pm_plan_id: str, revision_id: str, service: PmService = Depends(get_pm_service)
) -> PmTaskRevisionDetailResponse:
    detail = await service.get_task_revision(pm_plan_id, revision_id)
    return _revision_detail_response(detail)


@router.post("/pm/work-orders", response_model=PmWorkOrderDetailResponse)
async def open_pm_work_order(
    body: OpenPmWorkOrderRequest,
    service: PmService = Depends(get_pm_service),
    context: RequestContext = Depends(get_current_context),
) -> PmWorkOrderDetailResponse:
    """REV05 section 2B: Maintenance opens PM Work Orders — a Driver must
    not, and a Technician must not merely because the PM is due."""
    require_capability(context, CAN_MANAGE_PM, "การเปิดใบสั่งงาน PM (open a PM Work Order)")
    detail = await service.open_work_order(
        asset_type=body.asset_type,
        asset_id=body.asset_id,
        pm_plan_id=body.pm_plan_id,
        due_reason=body.due_reason,
        opened_by=context.user_id,
        note=body.note,
        initial_scope_task_ids=body.initial_scope_task_ids,
    )
    return _work_order_detail_response(detail)


@router.get("/pm/work-orders", response_model=Page[PmWorkOrderSummaryResponse])
async def list_pm_work_orders(
    asset_type: AssetType | None = Query(default=None),
    asset_id: str | None = Query(default=None),
    status: PmWorkOrderStatus | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    service: PmService = Depends(get_pm_service),
) -> Page[PmWorkOrderSummaryResponse]:
    result = await service.list_work_orders(
        asset_type=asset_type,
        asset_id=asset_id,
        params=PageParams(page=page, page_size=page_size),
        status=status,
    )
    return Page[PmWorkOrderSummaryResponse](
        items=[
            PmWorkOrderSummaryResponse.model_validate(s.model_dump()) for s in result.items
        ],
        page=result.page,
        page_size=result.page_size,
        total_items=result.total_items,
    )


@router.get("/pm/work-orders/{pm_work_order_id}", response_model=PmWorkOrderDetailResponse)
async def get_pm_work_order(
    pm_work_order_id: str, service: PmService = Depends(get_pm_service)
) -> PmWorkOrderDetailResponse:
    detail = await service.get_work_order(pm_work_order_id)
    return _work_order_detail_response(detail)


@router.post(
    "/pm/work-orders/{pm_work_order_id}/results", response_model=PmWorkOrderDetailResponse
)
async def submit_pm_task_result(
    pm_work_order_id: str,
    body: SubmitPmTaskResultRequest,
    service: PmService = Depends(get_pm_service),
    context: RequestContext = Depends(get_current_context),
) -> PmWorkOrderDetailResponse:
    detail = await service.submit_task_result(
        pm_work_order_id=pm_work_order_id,
        pm_task_id=body.pm_task_id,
        completed=body.completed,
        meter_snapshot_id=body.meter_snapshot_id,
        remark=body.remark,
        used_parts=[
            UsedPartInput(
                part_description=p.part_description,
                quantity=p.quantity,
                unit=p.unit,
                part_id=p.part_id,
                part_instance_id=p.part_instance_id,
                action=p.action,
            )
            for p in body.used_parts
        ],
        evidence_attachment_ids=list(body.evidence_attachment_ids),
        performed_by=context.user_id,
    )
    return _work_order_detail_response(detail)


@router.post("/pm/work-orders/{pm_work_order_id}/close", response_model=PmWorkOrderDetailResponse)
async def close_pm_work_order(
    pm_work_order_id: str,
    body: ClosePmWorkOrderRequest,
    service: PmService = Depends(get_pm_service),
    context: RequestContext = Depends(get_current_context),
) -> PmWorkOrderDetailResponse:
    """REV05 section 2B: final PM Work Order closure is
    Maintenance-authorized only."""
    require_capability(context, CAN_MANAGE_PM, "การปิดใบสั่งงาน PM (final PM Work Order closure)")
    detail = await service.close_work_order(
        pm_work_order_id=pm_work_order_id, closed_by=context.user_id, note=body.note
    )
    return _work_order_detail_response(detail)


@router.post(
    "/pm/work-orders/{pm_work_order_id}/scope/add", response_model=PmWorkOrderDetailResponse
)
async def add_pm_scope_task(
    pm_work_order_id: str,
    body: AddPmScopeTaskRequest,
    service: PmService = Depends(get_pm_service),
    context: RequestContext = Depends(get_current_context),
) -> PmWorkOrderDetailResponse:
    """Core Demo Fix, PM WORKFLOW REDESIGN section D: authorized addition
    of a near-due group/task from the SAME plan only, audited (who/when/
    reason)."""
    require_capability(context, CAN_MANAGE_PM, "การเพิ่มกลุ่มงาน PM ล่วงหน้า (add near-due PM scope)")
    detail = await service.add_scope_task(
        pm_work_order_id=pm_work_order_id,
        pm_task_id=body.pm_task_id,
        reason=body.reason,
        added_by=context.user_id,
    )
    return _work_order_detail_response(detail)


@router.post(
    "/pm/work-orders/{pm_work_order_id}/scope/approve", response_model=PmWorkOrderDetailResponse
)
async def approve_pm_scope(
    pm_work_order_id: str,
    service: PmService = Depends(get_pm_service),
    context: RequestContext = Depends(get_current_context),
) -> PmWorkOrderDetailResponse:
    """Core Demo Fix, PM WORKFLOW REDESIGN section D: freeze the work
    order's selected group/task set and auto-generate requisition lines
    from its standard PM parts (section F)."""
    require_capability(context, CAN_MANAGE_PM, "การอนุมัติขอบเขตงาน PM (PM scope approval)")
    detail = await service.approve_scope(pm_work_order_id=pm_work_order_id, approved_by=context.user_id)
    return _work_order_detail_response(detail)


@router.get(
    "/pm/work-orders/{pm_work_order_id}/requisition-lines",
    response_model=list[RequisitionLineResponse],
)
async def list_pm_requisition_lines(
    pm_work_order_id: str, service: PmService = Depends(get_pm_service)
) -> list[RequisitionLineResponse]:
    lines = await service.list_requisition_lines(pm_work_order_id)
    return [_requisition_line_response(line) for line in lines]


@router.post("/pm/work-orders/{pm_work_order_id}/assign", response_model=PmWorkOrderDetailResponse)
async def assign_pm_work_order(
    pm_work_order_id: str,
    body: AssignPmWorkOrderRequest,
    service: PmService = Depends(get_pm_service),
    context: RequestContext = Depends(get_current_context),
) -> PmWorkOrderDetailResponse:
    """Core Demo Fixes Delta section B: PM technician/team assignment.
    REV05 section 2B: Maintenance-only."""
    require_capability(context, CAN_MANAGE_PM, "การมอบหมายทีมช่าง PM (assign PM technician/team)")
    detail = await service.assign(
        pm_work_order_id=pm_work_order_id,
        primary_technician=body.primary_technician,
        collaborators=body.collaborators,
        assigned_by=context.user_id,
    )
    return _work_order_detail_response(detail)


@router.get(
    "/pm/work-orders/{pm_work_order_id}/assignment-history",
    response_model=list[PmAssignmentHistoryEntryResponse],
)
async def list_pm_assignment_history(
    pm_work_order_id: str, service: PmService = Depends(get_pm_service)
) -> list[PmAssignmentHistoryEntryResponse]:
    entries = await service.list_assignment_history(pm_work_order_id)
    return [PmAssignmentHistoryEntryResponse.model_validate(e.model_dump()) for e in entries]
