"""Repair Request routes (Core Demo Fixes Delta REV05 section 3).

A reported problem waiting for Maintenance review — never a Repair Work
Order (see `app.domain.repair_request` module docstring). Attachments for
a Repair Request reuse the shared `POST /attachments` upload endpoint
with `purpose=REPAIR_REQUEST_EVIDENCE`,
`source_type="REPAIR_REQUEST"`/`source_id=<repair_request_id>`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.v1.repair_request_schemas import (
    ConvertRepairRequestRequest,
    RepairRequestResponse,
    SubmitRepairRequestRequest,
    SubmitRepairRequestResponse,
)
from app.api.v1.repair_schemas import (
    RepairActionResponse,
    RepairDetailResponse,
    RepairPartResponse,
    RepairResponse,
)
from app.context import RequestContext
from app.dependencies import get_current_context, get_repair_request_service
from app.domain.authz import CAN_MANAGE_REPAIR, CAN_REPORT_REPAIR, require_capability
from app.domain.common import Page, PageParams
from app.domain.repair import RepairDetail
from app.domain.repair_request import RepairRequest
from app.domain.repair_request_service import RepairRequestService

router = APIRouter(tags=["repair-requests"])


def _request_response(request: RepairRequest) -> RepairRequestResponse:
    return RepairRequestResponse.model_validate(request.model_dump())


def _repair_detail_response(detail: RepairDetail) -> RepairDetailResponse:
    return RepairDetailResponse(
        repair=RepairResponse.model_validate(detail.repair.model_dump()),
        actions=[RepairActionResponse.model_validate(a.model_dump()) for a in detail.actions],
        parts=[RepairPartResponse.model_validate(p.model_dump()) for p in detail.parts],
    )


@router.post("/repair-requests", response_model=SubmitRepairRequestResponse)
async def submit_repair_request(
    body: SubmitRepairRequestRequest,
    service: RepairRequestService = Depends(get_repair_request_service),
    context: RequestContext = Depends(get_current_context),
) -> SubmitRepairRequestResponse:
    """แจ้งปัญหา/แจ้งซ่อม — reporting a problem never creates an RPR
    (REV05 section 2A). Open to any actor with `can_report_repair`,
    including Maintenance recording a report on behalf of someone else
    (radio/phone/verbal) via the optional `reporter_*` fields."""
    require_capability(context, CAN_REPORT_REPAIR, "การแจ้งปัญหา/แจ้งซ่อม (report a problem)")
    request, meter_snapshot_id = await service.create(
        vehicle_id=body.vehicle_id,
        reported_by_user_id=context.user_id,
        reporter_type=body.reporter_type,
        reporter_driver_id=body.reporter_driver_id,
        reporter_name_snapshot_th=body.reporter_name_snapshot_th,
        report_channel=body.report_channel,
        symptom_th=body.symptom_th,
        priority=body.priority,
        note_th=body.note_th,
    )
    return SubmitRepairRequestResponse(
        request=_request_response(request), meter_snapshot_id=meter_snapshot_id
    )


@router.get("/repair-requests/pending", response_model=Page[RepairRequestResponse])
async def list_pending_repair_requests(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    service: RepairRequestService = Depends(get_repair_request_service),
    context: RequestContext = Depends(get_current_context),
) -> Page[RepairRequestResponse]:
    """รายการแจ้งซ่อมรอตรวจรับ — Maintenance-only (REV05 section 5A)."""
    require_capability(
        context, CAN_MANAGE_REPAIR, "รายการแจ้งซ่อมรอตรวจรับ (pending Repair Request queue)"
    )
    result = await service.list_pending(PageParams(page=page, page_size=page_size))
    return Page[RepairRequestResponse](
        items=[_request_response(r) for r in result.items],
        page=result.page,
        page_size=result.page_size,
        total_items=result.total_items,
    )


@router.get("/repair-requests/{repair_request_id}", response_model=RepairRequestResponse)
async def get_repair_request(
    repair_request_id: str,
    service: RepairRequestService = Depends(get_repair_request_service),
) -> RepairRequestResponse:
    request = await service.get(repair_request_id)
    return _request_response(request)


@router.post(
    "/repair-requests/{repair_request_id}/convert", response_model=RepairDetailResponse
)
async def convert_repair_request(
    repair_request_id: str,
    body: ConvertRepairRequestRequest,
    service: RepairRequestService = Depends(get_repair_request_service),
    context: RequestContext = Depends(get_current_context),
) -> RepairDetailResponse:
    """Maintenance accepts a pending Repair Request as a Repair Work
    Order (REV05 section 3) — safe to retry: an already-`CONVERTED`
    request returns its existing Repair rather than creating a duplicate."""
    require_capability(
        context, CAN_MANAGE_REPAIR, "การเปิดใบงานซ่อมจากรายการแจ้งซ่อม (convert to Repair Work Order)"
    )
    detail = await service.convert(
        repair_request_id=repair_request_id,
        reviewed_by_user_id=context.user_id,
        category=body.category,
        primary_technician=body.primary_technician,
        collaborators=body.collaborators,
    )
    return _repair_detail_response(detail)
