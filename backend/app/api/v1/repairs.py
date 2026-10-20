"""Repair routes (Phase 4). Separate from PM — never merges into a PM
work order, even for a `source_type=PM_RESULT` repair.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.v1.repair_schemas import (
    AddRepairActionRequest,
    AddRepairPartRequest,
    CancelRepairRequest,
    CloseRepairRequest,
    CreateRepairRequest,
    RepairActionResponse,
    RepairAssignmentHistoryEntryResponse,
    RepairDetailResponse,
    RepairPartResponse,
    RepairResponse,
    RepairSummaryResponse,
    SubmitRepairCompletionRequest,
)
from app.api.v1.request_id_dependency import require_client_request_id
from app.context import RequestContext
from app.dependencies import get_current_context, get_material_request_service, get_repair_service
from app.domain.asset import AssetType
from app.domain.authz import (
    CAN_CLOSE_REPAIR,
    CAN_MANAGE_FINDING_REPAIR,
    CAN_MANAGE_REPAIR,
    require_capability,
)
from app.domain.common import Page, PageParams
from app.domain.legacy_assignment_retired import legacy_route_retired
from app.domain.material_request_service import MaterialRequestService
from app.domain.read_signals import assignment_model_signal
from app.domain.repair import Repair, RepairDetail, RepairSourceType, RepairStatus
from app.domain.repair_service import RepairService


# R2 Batch R2f-h4 B6 (D3): retired legacy assignment routes (410, no read, no write).
_RETIRED: dict[int | str, dict[str, object]] = {
    410: {"description": "LEGACY_ASSIGNMENT_RETIRED — technician assignment uses the Technician V2 routes; "
                         "nothing is read or changed."},
}

router = APIRouter(tags=["repairs"])


def _repair_response(repair: Repair) -> RepairResponse:
    # R2f-h4 precondition (D-H4-1): the persisted marker as the read-only signal.
    return RepairResponse.model_validate(
        {**repair.model_dump(), "assignment_model": assignment_model_signal(repair.assignment_model)}
    )


async def build_repair_detail_response(
    detail: RepairDetail, material_request_service: MaterialRequestService
) -> RepairDetailResponse:
    """The one place every endpoint returning a `RepairDetailResponse`
    (this router's own create/assign/add-action/add-part/close/GET, and
    `app.api.v1.repair_requests`'s convert) builds it — `awaiting_parts`
    is always derived the same way (`MaterialRequestService
    .is_awaiting_parts`), so the same persisted Repair state produces the
    same `awaiting_parts` regardless of which endpoint served the
    response, never `None` just because the caller was a write path."""
    awaiting_parts = await material_request_service.is_awaiting_parts(detail.repair.repair_id)
    return RepairDetailResponse(
        repair=_repair_response(detail.repair),
        actions=[RepairActionResponse.model_validate(a.model_dump()) for a in detail.actions],
        parts=[RepairPartResponse.model_validate(p.model_dump()) for p in detail.parts],
        awaiting_parts=awaiting_parts,
    )


@router.post("/repairs", response_model=RepairDetailResponse)
async def create_repair(
    body: CreateRepairRequest,
    service: RepairService = Depends(get_repair_service),
    material_request_service: MaterialRequestService = Depends(get_material_request_service),
    context: RequestContext = Depends(get_current_context),
) -> RepairDetailResponse:
    """Core Demo Fixes Delta REV05 section 2A: only an authorized
    Maintenance actor may create/accept a Repair Work Order directly.
    Everyone else uses `POST /repair-requests` (แจ้งปัญหา/แจ้งซ่อม), which
    an authorized Maintenance actor later converts via
    `POST /repair-requests/{id}/convert`."""
    require_capability(context, CAN_MANAGE_REPAIR, "การเปิดใบงานซ่อม (open a Repair Work Order)")
    if body.source_type == RepairSourceType.FINDING and await service.r3_finding_id(body.source_id):
        # R3 (O-3, T2): opening a round from an R3 Finding is a manager / delegate action.
        require_capability(context, CAN_MANAGE_FINDING_REPAIR,
                           "การเปิดใบงานซ่อมจากรายการผิดปกติ (open a repair round from a Finding)")
    detail = await service.create_repair(
        asset_type=body.asset_type,
        asset_id=body.asset_id,
        source_type=body.source_type,
        source_id=body.source_id,
        category=body.category,
        symptom=body.symptom,
        meter_snapshot_id=body.meter_snapshot_id,
        opened_by=context.user_id,
        primary_technician=body.primary_technician,
        collaborators=body.collaborators,
    )
    return await build_repair_detail_response(detail, material_request_service)


@router.get("/repairs", response_model=Page[RepairSummaryResponse])
async def list_repairs(
    asset_type: AssetType | None = Query(default=None),
    asset_id: str | None = Query(default=None),
    status: RepairStatus | None = Query(default=None),
    assigned_to: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    service: RepairService = Depends(get_repair_service),
) -> Page[RepairSummaryResponse]:
    result = await service.list_repairs(
        asset_type=asset_type,
        asset_id=asset_id,
        repair_status=status,
        params=PageParams(page=page, page_size=page_size),
        assigned_to=assigned_to,
    )
    return Page[RepairSummaryResponse](
        items=[RepairSummaryResponse.model_validate(s.model_dump()) for s in result.items],
        page=result.page,
        page_size=result.page_size,
        total_items=result.total_items,
    )


@router.get("/repairs/my-work", response_model=None, status_code=410, responses=_RETIRED)
async def list_my_open_repairs() -> None:
    """R2 Batch R2f-h4 B6 (D3): RETIRED — technician assignment is V2-only. Always
    410 LEGACY_ASSIGNMENT_RETIRED, before any read or write (see
    `app.domain.legacy_assignment_retired`)."""
    raise legacy_route_retired("GET /repairs/my-work")

_OPEN_QUEUE_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    403: {
        "description": (
            "HTTP_ERROR — the caller lacks the 'can_manage_repair' capability. No data is read."
        )
    },
    500: {
        "description": (
            "REPAIR_ORDER_SCHEMA_INVALID (details: tab, problem, headers) for a proven "
            "repair_order structural problem, or INTERNAL_ERROR. No rows or totals are returned."
        )
    },
    503: {
        "description": (
            "REPAIR_ORDER_READ_FAILED — repair_order or repair_action could not be read."
        )
    },
}


@router.get(
    "/repairs/open-queue",
    response_model=Page[RepairSummaryResponse],
    responses=_OPEN_QUEUE_ERROR_RESPONSES,
)
async def list_open_repair_queue(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    asset_type: AssetType | None = Query(default=None),
    service: RepairService = Depends(get_repair_service),
    context: RequestContext = Depends(get_current_context),
) -> Page[RepairSummaryResponse]:
    """งานซ่อมค้าง — every OPEN repair work order (assigned and
    unassigned), vehicles and equipment unless `asset_type` narrows it,
    Maintenance-only (REV05 section 5C). Phase 7 Batch 7C2: the Google
    Sheets read validates repair_order's structure (approved DEC-2
    option S); record-value defaults are unchanged. Repair Requests are
    never included."""
    # Authorization before any repository read: a denied request reads nothing.
    require_capability(context, CAN_MANAGE_REPAIR, "งานซ่อมค้าง (Open Repair Queue)")
    result = await service.list_open_repairs_for_report(
        asset_type=asset_type,
        params=PageParams(page=page, page_size=page_size),
    )
    return Page[RepairSummaryResponse](
        items=[RepairSummaryResponse.model_validate(s.model_dump()) for s in result.items],
        page=result.page,
        page_size=result.page_size,
        total_items=result.total_items,
    )


@router.get("/repairs/waiting-assignment", response_model=None, status_code=410, responses=_RETIRED)
async def list_repairs_waiting_assignment() -> None:
    """R2 Batch R2f-h4 B6 (D3): RETIRED — technician assignment is V2-only. Always
    410 LEGACY_ASSIGNMENT_RETIRED, before any read or write (see
    `app.domain.legacy_assignment_retired`)."""
    raise legacy_route_retired("GET /repairs/waiting-assignment")


@router.post("/repairs/{repair_id}/assign", response_model=None, status_code=410, responses=_RETIRED)
async def assign_repair(repair_id: str) -> None:
    """R2 Batch R2f-h4 B6 (D3): RETIRED — technician assignment is V2-only. Always
    410 LEGACY_ASSIGNMENT_RETIRED, before any read or write (see
    `app.domain.legacy_assignment_retired`)."""
    raise legacy_route_retired("POST /repairs/{repair_id}/assign")


@router.get(
    "/repairs/{repair_id}/assignment-history",
    response_model=list[RepairAssignmentHistoryEntryResponse],
)
async def list_repair_assignment_history(
    repair_id: str, service: RepairService = Depends(get_repair_service)
) -> list[RepairAssignmentHistoryEntryResponse]:
    entries = await service.list_assignment_history(repair_id)
    return [RepairAssignmentHistoryEntryResponse.model_validate(e.model_dump()) for e in entries]


@router.get("/repairs/{repair_id}", response_model=RepairDetailResponse)
async def get_repair(
    repair_id: str,
    service: RepairService = Depends(get_repair_service),
    material_request_service: MaterialRequestService = Depends(get_material_request_service),
) -> RepairDetailResponse:
    detail = await service.get_repair(repair_id)
    return await build_repair_detail_response(detail, material_request_service)


@router.post("/repairs/{repair_id}/actions", response_model=RepairDetailResponse)
async def add_repair_action(
    repair_id: str,
    body: AddRepairActionRequest,
    service: RepairService = Depends(get_repair_service),
    material_request_service: MaterialRequestService = Depends(get_material_request_service),
    context: RequestContext = Depends(get_current_context),
) -> RepairDetailResponse:
    """REV06 section 12 (P1): recording repair work is restricted to this
    repair's own active PRIMARY/COLLABORATOR technician or an actor
    holding `can_manage_repair` — an unrelated or differently-assigned
    actor is refused even though every actor could previously write here.
    REV06.1 (CONSISTENCY-2 fix): sourced from the active assignment
    history (`get_active_assignment`), not the denormalized
    `Repair.primary_technician`/`.collaborators` fields — see that
    method's docstring."""
    # R2 Batch R2f-h1: per job model — legacy jobs keep exactly this REV06.1
    # gate; V2 jobs use the capability or current V2 set membership.
    await service.authorize_recording(
        repair_id, context, CAN_MANAGE_REPAIR, "การบันทึกการดำเนินการซ่อม (record repair work)"
    )
    detail = await service.add_action(
        repair_id=repair_id,
        action_text=body.action_text,
        actor=context.user_id,
        attachment_ids=list(body.attachment_ids),
    )
    return await build_repair_detail_response(detail, material_request_service)


@router.post("/repairs/{repair_id}/parts", response_model=RepairDetailResponse)
async def add_repair_part(
    repair_id: str,
    body: AddRepairPartRequest,
    service: RepairService = Depends(get_repair_service),
    material_request_service: MaterialRequestService = Depends(get_material_request_service),
    context: RequestContext = Depends(get_current_context),
) -> RepairDetailResponse:
    """REV06 section 12 (P1): same assignment-or-can_manage_repair gate as
    `add_repair_action` — recording a part used is also repair work.
    REV06.1 (CONSISTENCY-2 fix): sourced from active assignment history —
    see `RepairService.get_active_assignment`."""
    # R2 Batch R2f-h1: per job model — legacy jobs keep exactly this REV06.1
    # gate; V2 jobs use the capability or current V2 set membership.
    await service.authorize_recording(
        repair_id, context, CAN_MANAGE_REPAIR, "การบันทึกอะไหล่ที่ใช้ (record a repair part)"
    )
    detail = await service.add_part(
        repair_id=repair_id,
        part_description=body.part_description,
        quantity=body.quantity,
        unit=body.unit,
        recorded_by=context.user_id,
        part_id=body.part_id,
        part_instance_id=body.part_instance_id,
        action=body.action,
    )
    return await build_repair_detail_response(detail, material_request_service)


@router.post("/repairs/{repair_id}/close", response_model=RepairDetailResponse)
async def close_repair(
    repair_id: str,
    body: CloseRepairRequest,
    service: RepairService = Depends(get_repair_service),
    material_request_service: MaterialRequestService = Depends(get_material_request_service),
    context: RequestContext = Depends(get_current_context),
) -> RepairDetailResponse:
    """REV05 section 2A: final Repair closure is Maintenance-authorized
    only."""
    require_capability(context, CAN_CLOSE_REPAIR, "การปิดใบงานซ่อม (final Repair closure)")
    detail = await service.close_repair(
        repair_id=repair_id, closed_by=context.user_id, close_note=body.close_note, context=context
    )
    return await build_repair_detail_response(detail, material_request_service)


@router.post("/repairs/{repair_id}/completion", response_model=RepairDetailResponse)
async def submit_repair_completion(
    repair_id: str,
    body: SubmitRepairCompletionRequest,
    service: RepairService = Depends(get_repair_service),
    material_request_service: MaterialRequestService = Depends(get_material_request_service),
    context: RequestContext = Depends(get_current_context),
    request_id: str = Depends(require_client_request_id),
) -> RepairDetailResponse:
    """R3 W2 (Owner rule Q2): 'ส่งงานซ่อมเสร็จ' — only the current V2 lead
    technician (PRIMARY), proven on the server. Ends the Finding episode; the
    Work Order stays OPEN until the manager closes it. Idempotent on
    X-Request-Id."""
    detail, _ = await service.submit_completion(
        repair_id, context, request_id=request_id, expected_set_id=body.expected_set_id, note=body.note
    )
    return await build_repair_detail_response(detail, material_request_service)


@router.post("/repairs/{repair_id}/cancellation", response_model=RepairDetailResponse)
async def cancel_repair(
    repair_id: str,
    body: CancelRepairRequest,
    service: RepairService = Depends(get_repair_service),
    material_request_service: MaterialRequestService = Depends(get_material_request_service),
    context: RequestContext = Depends(get_current_context),
) -> RepairDetailResponse:
    """R3 W5 (O-2, Q4): cancel an R3 Finding round before any recorded repair
    work, by the manager / delegate, with a mandatory reason. Never automatic."""
    require_capability(context, CAN_MANAGE_REPAIR, "การยกเลิกใบงานซ่อม (cancel a repair round)")
    detail = await service.cancel_repair(repair_id, context, reason=body.reason)
    return await build_repair_detail_response(detail, material_request_service)
