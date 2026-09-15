"""Repair routes (Phase 4). Separate from PM — never merges into a PM
work order, even for a `source_type=PM_RESULT` repair.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.v1.repair_schemas import (
    AddRepairActionRequest,
    AddRepairPartRequest,
    AssignRepairRequest,
    CloseRepairRequest,
    CreateRepairRequest,
    RepairActionResponse,
    RepairAssignmentHistoryEntryResponse,
    RepairDetailResponse,
    RepairPartResponse,
    RepairResponse,
    RepairSummaryResponse,
)
from app.context import RequestContext
from app.dependencies import get_current_context, get_material_request_service, get_repair_service
from app.domain.asset import AssetType
from app.domain.authz import (
    CAN_CLOSE_REPAIR,
    CAN_MANAGE_REPAIR,
    require_assignment_or_capability,
    require_capability,
)
from app.domain.common import Page, PageParams
from app.domain.material_request_service import MaterialRequestService
from app.domain.repair import Repair, RepairDetail, RepairStatus
from app.domain.repair_service import RepairService

router = APIRouter(tags=["repairs"])


def _repair_response(repair: Repair) -> RepairResponse:
    return RepairResponse.model_validate(repair.model_dump())


def _detail_response(detail: RepairDetail, awaiting_parts: bool | None = None) -> RepairDetailResponse:
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
    context: RequestContext = Depends(get_current_context),
) -> RepairDetailResponse:
    """Core Demo Fixes Delta REV05 section 2A: only an authorized
    Maintenance actor may create/accept a Repair Work Order directly.
    Everyone else uses `POST /repair-requests` (แจ้งปัญหา/แจ้งซ่อม), which
    an authorized Maintenance actor later converts via
    `POST /repair-requests/{id}/convert`."""
    require_capability(context, CAN_MANAGE_REPAIR, "การเปิดใบงานซ่อม (open a Repair Work Order)")
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
    return _detail_response(detail)


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


@router.get("/repairs/my-work", response_model=Page[RepairSummaryResponse])
async def list_my_open_repairs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    service: RepairService = Depends(get_repair_service),
    context: RequestContext = Depends(get_current_context),
) -> Page[RepairSummaryResponse]:
    """งานของฉัน — OPEN repairs assigned (as primary technician or
    collaborator) to the current application actor/user context."""
    result = await service.list_repairs(
        asset_type=None,
        asset_id=None,
        repair_status=RepairStatus.OPEN,
        params=PageParams(page=page, page_size=page_size),
        assigned_to=context.user_id,
    )
    return Page[RepairSummaryResponse](
        items=[RepairSummaryResponse.model_validate(s.model_dump()) for s in result.items],
        page=result.page,
        page_size=result.page_size,
        total_items=result.total_items,
    )


@router.get("/repairs/open-queue", response_model=Page[RepairSummaryResponse])
async def list_open_repair_queue(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    service: RepairService = Depends(get_repair_service),
    context: RequestContext = Depends(get_current_context),
) -> Page[RepairSummaryResponse]:
    """งานซ่อมค้าง — every OPEN repair (assigned and unassigned),
    Maintenance-only (REV05 section 5C)."""
    require_capability(context, CAN_MANAGE_REPAIR, "งานซ่อมค้าง (Open Repair Queue)")
    result = await service.list_repairs(
        asset_type=None,
        asset_id=None,
        repair_status=RepairStatus.OPEN,
        params=PageParams(page=page, page_size=page_size),
    )
    return Page[RepairSummaryResponse](
        items=[RepairSummaryResponse.model_validate(s.model_dump()) for s in result.items],
        page=result.page,
        page_size=result.page_size,
        total_items=result.total_items,
    )


@router.get("/repairs/waiting-assignment", response_model=Page[RepairSummaryResponse])
async def list_repairs_waiting_assignment(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    service: RepairService = Depends(get_repair_service),
    context: RequestContext = Depends(get_current_context),
) -> Page[RepairSummaryResponse]:
    """รอมอบหมายช่าง — every OPEN repair with no active PRIMARY
    technician (REV05 section 5B). Derived from the same
    `primary_technician`/`repair_assignment` fields `assign_repair`
    already keeps in sync — never a separate stored table, never a second
    copy of the Repair record. Maintenance-only."""
    require_capability(context, CAN_MANAGE_REPAIR, "รอมอบหมายช่าง (waiting-assignment queue)")
    result = await service.list_repairs(
        asset_type=None,
        asset_id=None,
        repair_status=RepairStatus.OPEN,
        params=PageParams(page=page, page_size=page_size),
        unassigned_only=True,
    )
    return Page[RepairSummaryResponse](
        items=[RepairSummaryResponse.model_validate(s.model_dump()) for s in result.items],
        page=result.page,
        page_size=result.page_size,
        total_items=result.total_items,
    )


@router.post("/repairs/{repair_id}/assign", response_model=RepairDetailResponse)
async def assign_repair(
    repair_id: str,
    body: AssignRepairRequest,
    service: RepairService = Depends(get_repair_service),
    context: RequestContext = Depends(get_current_context),
) -> RepairDetailResponse:
    """REV05 section 2A: Maintenance assigns/reassigns technicians."""
    require_capability(
        context, CAN_MANAGE_REPAIR, "การมอบหมายช่างซ่อม (assign/reassign a technician)"
    )
    detail = await service.assign(
        repair_id=repair_id,
        primary_technician=body.primary_technician,
        collaborators=body.collaborators,
        assigned_by=context.user_id,
    )
    return _detail_response(detail)


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
    awaiting_parts = await material_request_service.is_awaiting_parts(repair_id)
    return _detail_response(detail, awaiting_parts=awaiting_parts)


@router.post("/repairs/{repair_id}/actions", response_model=RepairDetailResponse)
async def add_repair_action(
    repair_id: str,
    body: AddRepairActionRequest,
    service: RepairService = Depends(get_repair_service),
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
    primary_technician, collaborators = await service.get_active_assignment(repair_id)
    require_assignment_or_capability(
        context,
        CAN_MANAGE_REPAIR,
        primary_technician,
        collaborators,
        "การบันทึกการดำเนินการซ่อม (record repair work)",
    )
    detail = await service.add_action(
        repair_id=repair_id,
        action_text=body.action_text,
        actor=context.user_id,
        attachment_ids=list(body.attachment_ids),
    )
    return _detail_response(detail)


@router.post("/repairs/{repair_id}/parts", response_model=RepairDetailResponse)
async def add_repair_part(
    repair_id: str,
    body: AddRepairPartRequest,
    service: RepairService = Depends(get_repair_service),
    context: RequestContext = Depends(get_current_context),
) -> RepairDetailResponse:
    """REV06 section 12 (P1): same assignment-or-can_manage_repair gate as
    `add_repair_action` — recording a part used is also repair work.
    REV06.1 (CONSISTENCY-2 fix): sourced from active assignment history —
    see `RepairService.get_active_assignment`."""
    primary_technician, collaborators = await service.get_active_assignment(repair_id)
    require_assignment_or_capability(
        context,
        CAN_MANAGE_REPAIR,
        primary_technician,
        collaborators,
        "การบันทึกอะไหล่ที่ใช้ (record a repair part)",
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
    return _detail_response(detail)


@router.post("/repairs/{repair_id}/close", response_model=RepairDetailResponse)
async def close_repair(
    repair_id: str,
    body: CloseRepairRequest,
    service: RepairService = Depends(get_repair_service),
    context: RequestContext = Depends(get_current_context),
) -> RepairDetailResponse:
    """REV05 section 2A: final Repair closure is Maintenance-authorized
    only."""
    require_capability(context, CAN_CLOSE_REPAIR, "การปิดใบงานซ่อม (final Repair closure)")
    detail = await service.close_repair(
        repair_id=repair_id, closed_by=context.user_id, close_note=body.close_note
    )
    return _detail_response(detail)
