"""PM (preventive maintenance) routes (Phase 4).

Reachable from Vehicle/Equipment Detail via a "PM" action, mirroring the
Phase 3 "ตรวจเช็ค" pattern — the frozen `/vehicle/{vehicle_id}` and
`/equipment/{equipment_id}` QR routes/endpoints are untouched.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.api.v1.pm_schemas import (
    AddPmScopeTaskRequest,
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
    PmItemOutcomeResponse,
    PmItemSaveResponse,
    PmOutstandingItemResponse,
    PmOutstandingResolutionResponse,
    PmWorkOrderTransitionResponse,
    ReasonedPmTransitionRequest,
    RecordPmItemOutcomeRequest,
    ResolvePmOutstandingRequest,
    SubmitPmWorkOrderRequest,
)
from app.api.v1.request_id_dependency import require_client_request_id
from app.context import RequestContext
from app.dependencies import get_current_context, get_pm_service
from app.domain.asset import AssetType
from app.domain.authz import (
    CAN_MANAGE_PM,
    require_capability,
)
from app.domain.common import Page, PageParams
from app.domain.legacy_assignment_retired import legacy_route_retired
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
    PmItemOutcome,
    PmWorkResult,
)
from app.domain.pm_service import PmOutstandingState, PmService, UsedPartInput
from app.domain.technician_assignment import ASSIGNMENT_MODEL_TECHNICIAN_V2, assignment_model_of
from app.domain.read_signals import assignment_model_signal
from app.domain.requisition import RequisitionLine

# R2 Batch R2f-h4 B6 (D3): retired legacy assignment routes (410, no read, no write).
_RETIRED: dict[int | str, dict[str, object]] = {
    410: {"description": "LEGACY_ASSIGNMENT_RETIRED — technician assignment uses the Technician V2 routes; "
                         "nothing is read or changed."},
}

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
    # R2f-h4 precondition (D-H4-1): the persisted marker as the read-only signal.
    return PmWorkOrderResponse.model_validate(
        {**work_order.model_dump(), "assignment_model": assignment_model_signal(work_order.assignment_model)}
    )


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


@router.get("/pm/work-orders/my-work", response_model=None, status_code=410, responses=_RETIRED)
async def list_my_pm_work_orders() -> None:
    """R2 Batch R2f-h4 B6 (D3): RETIRED — technician assignment is V2-only. Always
    410 LEGACY_ASSIGNMENT_RETIRED, before any read or write (see
    `app.domain.legacy_assignment_retired`)."""
    raise legacy_route_retired("GET /pm/work-orders/my-work")


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
    """REV06 section 13 (P1): recording a PM task result is restricted to
    this work order's own active PRIMARY/COLLABORATOR technician or an
    actor holding `can_manage_pm` — an ordinary technician not assigned to
    THIS PMWO is refused, even though they may be assigned elsewhere.

    F1 cross-phase integration fix: sourced from the active assignment
    history (`PmService.get_active_assignment`), not the denormalized
    `PmWorkOrder.primary_technician`/`.collaborators` fields — mirrors the
    same REV06.1 fix already applied to Repair action/part authorization."""
    # R2 Batch R2f-h1: per job model — legacy jobs keep exactly this F1 gate;
    # V2 jobs use the capability or current V2 set membership.
    await service.authorize_recording(
        pm_work_order_id, context, CAN_MANAGE_PM, "การบันทึกผลงาน PM (record a PM task result)"
    )
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
    request: Request,
    service: PmService = Depends(get_pm_service),
    context: RequestContext = Depends(get_current_context),
) -> PmWorkOrderDetailResponse:
    """REV05 section 2B: final PM Work Order closure is
    Maintenance-authorized only. R4 PM Workflow: a V2 work order closes only
    through E01 review (PENDING_REVIEW -> CLOSED, client `X-Request-Id`
    required); a historical legacy work order keeps its original closure."""
    require_capability(context, CAN_MANAGE_PM, "การปิดใบสั่งงาน PM (final PM Work Order closure)")
    existing = await service.get_work_order(pm_work_order_id)
    if assignment_model_of(existing.work_order) == ASSIGNMENT_MODEL_TECHNICIAN_V2:
        detail = await service.close_after_review(pm_work_order_id, context,
                                                  request_id=require_client_request_id(request), note=body.note)
        return _work_order_detail_response(detail)
    detail = await service.close_work_order(
        pm_work_order_id=pm_work_order_id, closed_by=context.user_id, note=body.note
    )
    return _work_order_detail_response(detail)


# ---- R4 PM Workflow (E01 A3, Q-R4-03/04/05): V2 work orders only ----
# Every lifecycle change needs the client's own `X-Request-Id` (an identical
# re-send is a replay, a different body under the same id is refused). The
# service enforces the Owner-approved actor rule of each action.


@router.post("/pm/work-orders/{pm_work_order_id}/start", response_model=PmWorkOrderDetailResponse)
async def start_pm_work_order(
    pm_work_order_id: str,
    request_id: str = Depends(require_client_request_id),
    service: PmService = Depends(get_pm_service),
    context: RequestContext = Depends(get_current_context),
) -> PmWorkOrderDetailResponse:
    detail = await service.start_work_order(pm_work_order_id, context, request_id=request_id)
    return _work_order_detail_response(detail)


@router.post("/pm/work-orders/{pm_work_order_id}/submit", response_model=PmWorkOrderDetailResponse)
async def submit_pm_work_order(
    pm_work_order_id: str,
    body: SubmitPmWorkOrderRequest,
    request_id: str = Depends(require_client_request_id),
    service: PmService = Depends(get_pm_service),
    context: RequestContext = Depends(get_current_context),
) -> PmWorkOrderDetailResponse:
    detail = await service.submit_for_review(pm_work_order_id, context, request_id=request_id,
                                             expected_set_id=body.expected_set_id)
    return _work_order_detail_response(detail)


@router.post("/pm/work-orders/{pm_work_order_id}/return", response_model=PmWorkOrderDetailResponse)
async def return_pm_work_order(
    pm_work_order_id: str,
    body: ReasonedPmTransitionRequest,
    request_id: str = Depends(require_client_request_id),
    service: PmService = Depends(get_pm_service),
    context: RequestContext = Depends(get_current_context),
) -> PmWorkOrderDetailResponse:
    detail = await service.return_for_rework(pm_work_order_id, context, request_id=request_id,
                                             reason=body.reason)
    return _work_order_detail_response(detail)


@router.post("/pm/work-orders/{pm_work_order_id}/cancel", response_model=PmWorkOrderDetailResponse)
async def cancel_pm_work_order(
    pm_work_order_id: str,
    body: ReasonedPmTransitionRequest,
    request_id: str = Depends(require_client_request_id),
    service: PmService = Depends(get_pm_service),
    context: RequestContext = Depends(get_current_context),
) -> PmWorkOrderDetailResponse:
    detail = await service.cancel_work_order(pm_work_order_id, context, request_id=request_id,
                                             reason=body.reason)
    return _work_order_detail_response(detail)


def _outcome_response(outcome: PmItemOutcome) -> PmItemOutcomeResponse:
    return PmItemOutcomeResponse(
        outcome_id=outcome.outcome_id, pm_work_order_id=outcome.pm_work_order_id, pm_task_id=outcome.pm_task_id,
        revision_id=outcome.revision_id, disposition=outcome.disposition,
        performed_actions=list(outcome.performed_actions), reason_code=outcome.reason_code,
        other_text=outcome.other_text, evidence_attachment_ids=list(outcome.evidence_attachment_ids),
        recorded_by=outcome.recorded_by, recorded_at=outcome.recorded_at,
        source_pm_work_result_id=outcome.source_pm_work_result_id,
    )


def _outstanding_response(state: PmOutstandingState) -> PmOutstandingItemResponse:
    item, resolution = state.item, state.resolution
    return PmOutstandingItemResponse(
        outstanding_id=item.outstanding_id, pm_work_order_id=item.pm_work_order_id, pm_task_id=item.pm_task_id,
        revision_id=item.revision_id, origin_reason_code=item.origin_reason_code,
        origin_other_text=item.origin_other_text, origin_recorded_by=item.origin_recorded_by,
        origin_recorded_at=item.origin_recorded_at, origin_pm_work_result_id=item.origin_pm_work_result_id,
        created_at=item.created_at, resolved=resolution is not None,
        resolution=None if resolution is None else PmOutstandingResolutionResponse(
            later_pm_work_result_id=resolution.later_pm_work_result_id,
            later_repair_id=resolution.later_repair_id,
            evidence_attachment_ids=list(resolution.evidence_attachment_ids),
            referenced_by=resolution.referenced_by, referenced_at=resolution.referenced_at),
    )


@router.post("/pm/work-orders/{pm_work_order_id}/items/{pm_task_id}/outcome", response_model=PmItemSaveResponse)
async def record_pm_item_outcome(
    pm_work_order_id: str,
    pm_task_id: str,
    body: RecordPmItemOutcomeRequest,
    service: PmService = Depends(get_pm_service),
    context: RequestContext = Depends(get_current_context),
) -> PmItemSaveResponse:
    """Save one PM item as Performed (1-2 approved actions) or Not Performed
    (one approved reason; Other needs text). Idempotent by the item itself."""
    saved = await service.record_item_outcome(
        pm_work_order_id, pm_task_id, body.disposition, context,
        performed_actions=tuple(body.performed_actions), reason_code=body.reason_code, other_text=body.other_text,
        evidence_attachment_ids=tuple(body.evidence_attachment_ids), remark=body.remark,
        meter_snapshot_id=body.meter_snapshot_id,
        used_parts=tuple(UsedPartInput(part_description=p.part_description, quantity=p.quantity, unit=p.unit,
                                       part_id=p.part_id, part_instance_id=p.part_instance_id, action=p.action)
                         for p in body.used_parts),
    )
    return PmItemSaveResponse(result=_work_result_response(saved.result), outcome=_outcome_response(saved.outcome),
                              replayed=saved.result_replayed and saved.outcome_replayed)


@router.get("/pm/work-orders/{pm_work_order_id}/outcomes", response_model=list[PmItemOutcomeResponse])
async def list_pm_item_outcomes(
    pm_work_order_id: str,
    service: PmService = Depends(get_pm_service),
    context: RequestContext = Depends(get_current_context),
) -> list[PmItemOutcomeResponse]:
    return [_outcome_response(o) for o in await service.list_item_outcomes(pm_work_order_id, context)]


@router.get("/pm/work-orders/{pm_work_order_id}/history", response_model=list[PmWorkOrderTransitionResponse])
async def list_pm_work_order_history(
    pm_work_order_id: str,
    service: PmService = Depends(get_pm_service),
    context: RequestContext = Depends(get_current_context),
) -> list[PmWorkOrderTransitionResponse]:
    return [PmWorkOrderTransitionResponse(event_id=e.event_id, action=e.action.value, from_status=e.from_status,
                                          to_status=e.to_status, actor=e.actor, occurred_at=e.occurred_at,
                                          reason=e.reason)
            for e in await service.list_work_order_history(pm_work_order_id, context)]


@router.get("/pm/work-orders/{pm_work_order_id}/outstanding", response_model=list[PmOutstandingItemResponse])
async def list_pm_work_order_outstanding(
    pm_work_order_id: str,
    service: PmService = Depends(get_pm_service),
    context: RequestContext = Depends(get_current_context),
) -> list[PmOutstandingItemResponse]:
    return [_outstanding_response(s) for s in await service.list_outstanding_items(pm_work_order_id, context)]


@router.get("/pm/outstanding", response_model=list[PmOutstandingItemResponse])
async def list_pm_asset_outstanding(
    asset_type: AssetType,
    asset_id: str,
    service: PmService = Depends(get_pm_service),
    context: RequestContext = Depends(get_current_context),
) -> list[PmOutstandingItemResponse]:
    """The post-PM Outstanding backlog of one asset — separate from PM Due."""
    return [_outstanding_response(s) for s in await service.list_asset_outstanding(asset_type, asset_id, context)]


@router.post("/pm/outstanding/{outstanding_id}/resolve", response_model=PmOutstandingItemResponse)
async def resolve_pm_outstanding(
    outstanding_id: str,
    body: ResolvePmOutstandingRequest,
    service: PmService = Depends(get_pm_service),
    context: RequestContext = Depends(get_current_context),
) -> PmOutstandingItemResponse:
    """Resolve one Outstanding item with verified evidence of later actual
    work on that item (`can_manage_pm`). Idempotent by the item itself."""
    resolution, _ = await service.resolve_outstanding(
        outstanding_id, context, later_pm_work_result_id=body.later_pm_work_result_id,
        later_repair_id=body.later_repair_id, evidence_attachment_ids=tuple(body.evidence_attachment_ids))
    item = await service.get_outstanding_item(outstanding_id)
    return _outstanding_response(PmOutstandingState(item=item, resolution=resolution))


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


@router.post("/pm/work-orders/{pm_work_order_id}/assign", response_model=None, status_code=410,
             responses=_RETIRED)
async def assign_pm_work_order(pm_work_order_id: str) -> None:
    """R2 Batch R2f-h4 B6 (D3): RETIRED — technician assignment is V2-only. Always
    410 LEGACY_ASSIGNMENT_RETIRED, before any read or write (see
    `app.domain.legacy_assignment_retired`)."""
    raise legacy_route_retired("POST /pm/work-orders/{pm_work_order_id}/assign")


@router.get(
    "/pm/work-orders/{pm_work_order_id}/assignment-history",
    response_model=list[PmAssignmentHistoryEntryResponse],
)
async def list_pm_assignment_history(
    pm_work_order_id: str, service: PmService = Depends(get_pm_service)
) -> list[PmAssignmentHistoryEntryResponse]:
    entries = await service.list_assignment_history(pm_work_order_id)
    return [PmAssignmentHistoryEntryResponse.model_validate(e.model_dump()) for e in entries]
