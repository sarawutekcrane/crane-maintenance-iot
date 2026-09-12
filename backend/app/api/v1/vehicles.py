"""Vehicle model / vehicle routes (Phase 2).

`/vehicles/{vehicle_id}` backs the stable QR entry point described in the
baseline (section 5): the frontend route `/vehicle/{vehicle_id}` calls
`GET /api/v1/vehicles/{vehicle_id}` for the detail view.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.v1.vehicle_schemas import (
    ChangeVehicleStatusRequest,
    ChangeVehicleStatusResponse,
    UpdateMachineNoRequest,
    VehicleComponentResponse,
    VehicleDetailResponse,
    VehicleModelResponse,
    VehicleResponse,
    VehicleStatusHistoryResponse,
)
from app.context import RequestContext
from app.dependencies import get_current_context, get_vehicle_service
from app.domain.common import OperationalStatus, Page, PageParams
from app.domain.vehicle_service import VehicleService

router = APIRouter(tags=["vehicles"])


@router.get("/models", response_model=Page[VehicleModelResponse])
async def list_models(
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    service: VehicleService = Depends(get_vehicle_service),
) -> Page[VehicleModelResponse]:
    result = await service.list_models(q=q, params=PageParams(page=page, page_size=page_size))
    return Page[VehicleModelResponse](
        items=[VehicleModelResponse.model_validate(m.model_dump()) for m in result.items],
        page=result.page,
        page_size=result.page_size,
        total_items=result.total_items,
    )


@router.get("/models/{model_id}", response_model=VehicleModelResponse)
async def get_model(
    model_id: str, service: VehicleService = Depends(get_vehicle_service)
) -> VehicleModelResponse:
    model = await service.get_model(model_id)
    return VehicleModelResponse.model_validate(model.model_dump())


@router.get("/vehicles", response_model=Page[VehicleResponse])
async def list_vehicles(
    q: str | None = Query(default=None),
    status: OperationalStatus | None = Query(default=None),
    model_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    service: VehicleService = Depends(get_vehicle_service),
) -> Page[VehicleResponse]:
    result = await service.list_vehicles(
        q=q,
        operational_status=status,
        model_id=model_id,
        params=PageParams(page=page, page_size=page_size),
    )
    return Page[VehicleResponse](
        items=[VehicleResponse.model_validate(v.model_dump()) for v in result.items],
        page=result.page,
        page_size=result.page_size,
        total_items=result.total_items,
    )


@router.get("/vehicles/{vehicle_id}", response_model=VehicleDetailResponse)
async def get_vehicle(
    vehicle_id: str, service: VehicleService = Depends(get_vehicle_service)
) -> VehicleDetailResponse:
    detail = await service.get_vehicle_detail(vehicle_id)
    return VehicleDetailResponse(
        vehicle=VehicleResponse.model_validate(detail.vehicle.model_dump()),
        model=(
            VehicleModelResponse.model_validate(detail.model.model_dump())
            if detail.model
            else None
        ),
        components=[
            VehicleComponentResponse.model_validate(c.model_dump()) for c in detail.components
        ],
    )


@router.patch("/vehicles/{vehicle_id}", response_model=VehicleResponse)
async def update_vehicle_machine_no(
    vehicle_id: str,
    body: UpdateMachineNoRequest,
    service: VehicleService = Depends(get_vehicle_service),
) -> VehicleResponse:
    vehicle = await service.update_machine_no(vehicle_id, body.machine_no)
    return VehicleResponse.model_validate(vehicle.model_dump())


@router.get("/vehicles/{vehicle_id}/components", response_model=list[VehicleComponentResponse])
async def list_vehicle_components(
    vehicle_id: str, service: VehicleService = Depends(get_vehicle_service)
) -> list[VehicleComponentResponse]:
    components = await service.list_components(vehicle_id)
    return [VehicleComponentResponse.model_validate(c.model_dump()) for c in components]


@router.get(
    "/vehicles/{vehicle_id}/status-history",
    response_model=list[VehicleStatusHistoryResponse],
)
async def list_vehicle_status_history(
    vehicle_id: str, service: VehicleService = Depends(get_vehicle_service)
) -> list[VehicleStatusHistoryResponse]:
    entries = await service.list_status_history(vehicle_id)
    return [VehicleStatusHistoryResponse.model_validate(e.model_dump()) for e in entries]


@router.patch("/vehicles/{vehicle_id}/status", response_model=ChangeVehicleStatusResponse)
async def change_vehicle_status(
    vehicle_id: str,
    body: ChangeVehicleStatusRequest,
    service: VehicleService = Depends(get_vehicle_service),
    context: RequestContext = Depends(get_current_context),
) -> ChangeVehicleStatusResponse:
    vehicle, entry = await service.change_status(
        vehicle_id, new_status=body.status, changed_by=context.user_id, note=body.note
    )
    return ChangeVehicleStatusResponse(
        vehicle=VehicleResponse.model_validate(vehicle.model_dump()),
        history_entry=VehicleStatusHistoryResponse.model_validate(entry.model_dump()),
    )
