"""Material request routes (Core Demo Fixes Delta REV03, section D/H).

Store/Inventory integration boundary — this router never implements a
stock balance, warehouse approval, or purchasing workflow. PM's own
automatic scope-approval requisition is created internally by
`PmService.approve_scope`; `POST /material-requests` is the explicit,
manual creation path (used by Repair's "ขอเบิกอะไหล่" — never automatic,
never duplicating the Repair record itself — see Delta section H).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.material_request_schemas import (
    CreateMaterialRequestRequest,
    MaterialRequestDetailResponse,
    MaterialRequestResponse,
    RequisitionLineResponse,
)
from app.context import RequestContext
from app.dependencies import get_current_context, get_material_request_service
from app.domain.material_request_service import MaterialRequestService, RequisitionLineInput
from app.domain.requisition import MaterialRequestDetail

router = APIRouter(tags=["material-requests"])


def _detail_response(detail: MaterialRequestDetail) -> MaterialRequestDetailResponse:
    return MaterialRequestDetailResponse(
        request=MaterialRequestResponse.model_validate(detail.request.model_dump()),
        lines=[RequisitionLineResponse.model_validate(line.model_dump()) for line in detail.lines],
    )


@router.post("/material-requests", response_model=MaterialRequestDetailResponse)
async def create_material_request(
    body: CreateMaterialRequestRequest,
    service: MaterialRequestService = Depends(get_material_request_service),
    context: RequestContext = Depends(get_current_context),
) -> MaterialRequestDetailResponse:
    detail = await service.create(
        source_type=body.source_type,
        source_work_order_id=body.source_work_order_id,
        asset_type=body.asset_type,
        asset_id=body.asset_id,
        lines=[
            RequisitionLineInput(
                part_description=line.part_description,
                quantity=line.quantity,
                unit=line.unit,
                part_id=line.part_id,
                part_instance_id=line.part_instance_id,
                line_source=(
                    "REPAIR_PART_MASTER"
                    if line.part_id
                    else "REPAIR_UNREGISTERED" if body.source_type.value == "REPAIR" else "PM_STANDARD"
                ),
            )
            for line in body.lines
        ],
        created_by=context.user_id,
        note=body.note,
    )
    return _detail_response(detail)


@router.get("/material-requests/{material_request_id}", response_model=MaterialRequestDetailResponse)
async def get_material_request(
    material_request_id: str, service: MaterialRequestService = Depends(get_material_request_service)
) -> MaterialRequestDetailResponse:
    detail = await service.get(material_request_id)
    return _detail_response(detail)


@router.get(
    "/material-requests/by-work-order/{source_work_order_id}",
    response_model=list[MaterialRequestResponse],
)
async def list_material_requests_for_work_order(
    source_work_order_id: str,
    service: MaterialRequestService = Depends(get_material_request_service),
) -> list[MaterialRequestResponse]:
    requests = await service.list_for_work_order(source_work_order_id)
    return [MaterialRequestResponse.model_validate(r.model_dump()) for r in requests]
