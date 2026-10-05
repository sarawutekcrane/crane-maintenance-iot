"""Vehicle model / vehicle routes (Phase 2).

`/vehicles/{vehicle_id}` backs the stable QR entry point described in the
baseline (section 5): the frontend route `/vehicle/{vehicle_id}` calls
`GET /api/v1/vehicles/{vehicle_id}` for the detail view.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.v1.registry_schemas import VehicleRegistryResponse, VehicleWithRegistryResponse
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
from app.domain.vehicle_service import VehicleService, vehicle_master_read_error
from app.repositories.base import RepositoryError

router = APIRouter(tags=["vehicles"])

# Phase 7 Batch 7G2: the vehicle list is validated like the fleet status
# summary. Unlike the dashboard, this route is not capability-gated, so a
# data error carries counts by issue code only — never vehicle ids.
_LIST_VEHICLES_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    500: {
        "description": (
            "VEHICLE_MASTER_SCHEMA_INVALID (details: tab, problem, headers) or "
            "VEHICLE_MASTER_DATA_INVALID (details: issue_counts only). One invalid "
            "vehicle master record fails every list request, whatever the filters; "
            "no items or totals are returned. Phase 7 Batch 7J2: a q with usable "
            "terms also reads model_master; a structural problem there gives "
            "MODEL_MASTER_SCHEMA_INVALID (details: tab, problem, headers)."
        )
    },
    503: {
        "description": (
            "VEHICLE_MASTER_READ_FAILED — the vehicle master could not be read; or "
            "(q with usable terms only) MODEL_MASTER_READ_FAILED — model_master could "
            "not be read. Vehicle errors are reported first."
        )
    },
}

_VEHICLE_Q_DESCRIPTION = (
    "Phase 7 Batch 7J2: whitespace-separated terms, all of which must match "
    "(case-insensitive substrings) machine_no, vehicle_id, or the model_code / "
    "model_name of ONE model row joined by exact model_id. Identifier fields also "
    "match with spaces and '-' ignored; a Thai+digit term (e.g. 'รถเครน25') may "
    "match when all its parts occur in one model name. A term made only of '-' "
    "is ignored; a q of only such terms matches nothing."
)

# Phase 7 Batch 7H2: validated, text-preserving vehicle paths. Identities are
# matched exactly (no trimming or case folding); a blank id is not found.
_LOOKUP_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"description": "VEHICLE_NOT_FOUND — no vehicle_master record has exactly this vehicle_id."},
    409: {"description": "VEHICLE_ID_AMBIGUOUS (details: match_count) — more than one record has this vehicle_id; nothing was changed."},
    500: {
        "description": (
            "VEHICLE_MASTER_SCHEMA_INVALID (details: tab, problem, headers) or "
            "VEHICLE_MASTER_DATA_INVALID (details: issue_counts) for the located record."
        )
    },
    503: {"description": "VEHICLE_MASTER_READ_FAILED — the vehicle master could not be read."},
}
_MODEL_ERRORS: dict[int | str, dict[str, Any]] = {
    500: {"description": "MODEL_MASTER_SCHEMA_INVALID (details: tab, problem, headers; tab may be maintenance_plan)."},
    503: {"description": "MODEL_MASTER_READ_FAILED — model_master or maintenance_plan could not be read."},
}
_DETAIL_ERRORS: dict[int | str, dict[str, Any]] = {
    **_LOOKUP_ERRORS,
    500: {
        "description": (
            "VEHICLE_MASTER_SCHEMA_INVALID, VEHICLE_MASTER_DATA_INVALID, "
            "MODEL_MASTER_SCHEMA_INVALID or VEHICLE_COMPONENT_SCHEMA_INVALID."
        )
    },
    503: {"description": "VEHICLE_MASTER_READ_FAILED, MODEL_MASTER_READ_FAILED or VEHICLE_COMPONENT_READ_FAILED."},
}
_MACHINE_NO_ERRORS: dict[int | str, dict[str, Any]] = {
    **_LOOKUP_ERRORS,
    422: {"description": "VALIDATION_ERROR — includes a machine_no consisting only of whitespace; nothing is read."},
    503: {
        "description": (
            "VEHICLE_MASTER_READ_FAILED, or VEHICLE_MASTER_WRITE_FAILED (details: "
            "vehicle_write_outcome 'rejected' | 'unknown'; 'unknown' means the update MAY "
            "have been applied). Never retried."
        )
    },
}
_STATUS_ERRORS: dict[int | str, dict[str, Any]] = {
    **_LOOKUP_ERRORS,
    500: {
        "description": (
            "VEHICLE_MASTER_SCHEMA_INVALID, VEHICLE_MASTER_DATA_INVALID or "
            "VEHICLE_STATUS_HISTORY_SCHEMA_INVALID — detected before anything is written."
        )
    },
    503: {
        "description": (
            "VEHICLE_MASTER_READ_FAILED / VEHICLE_STATUS_HISTORY_READ_FAILED (nothing written); "
            "VEHICLE_MASTER_WRITE_FAILED (vehicle_write_outcome; history not attempted); "
            "VEHICLE_STATUS_HISTORY_WRITE_FAILED (vehicle_status_updated: true = the vehicle "
            "write was acknowledged, not re-read; history_write_outcome 'rejected' | 'unknown'). "
            "Never retried, compensated or re-read."
        )
    },
}
_COMPONENT_ERRORS: dict[int | str, dict[str, Any]] = {
    **_LOOKUP_ERRORS,
    500: {"description": "VEHICLE_MASTER_* or VEHICLE_COMPONENT_SCHEMA_INVALID."},
    503: {"description": "VEHICLE_MASTER_READ_FAILED or VEHICLE_COMPONENT_READ_FAILED."},
}
_HISTORY_ERRORS: dict[int | str, dict[str, Any]] = {
    **_LOOKUP_ERRORS,
    500: {"description": "VEHICLE_MASTER_* or VEHICLE_STATUS_HISTORY_SCHEMA_INVALID."},
    503: {"description": "VEHICLE_MASTER_READ_FAILED or VEHICLE_STATUS_HISTORY_READ_FAILED."},
}


@router.get("/models", response_model=Page[VehicleModelResponse], responses=_MODEL_ERRORS)
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


@router.get(
    "/models/{model_id}",
    response_model=VehicleModelResponse,
    responses={404: {"description": "MODEL_NOT_FOUND"}, **_MODEL_ERRORS},
)
async def get_model(
    model_id: str, service: VehicleService = Depends(get_vehicle_service)
) -> VehicleModelResponse:
    model = await service.get_model(model_id)
    return VehicleModelResponse.model_validate(model.model_dump())


def _with_registry(vehicle, registry) -> VehicleWithRegistryResponse:
    """Phase 7 Batch 7O2a (§7.1): the unchanged vehicle fields plus `registry`."""
    return VehicleWithRegistryResponse(
        **VehicleResponse.model_validate(vehicle.model_dump()).model_dump(),
        registry=VehicleRegistryResponse.of(registry),
    )


_BRANCH_ID_DESCRIPTION = (
    "Phase 7 Batch 7O2a: exact match on the stored responsible_branch_id (no trimming, "
    "case-sensitive, no reference lookup); ANDed with status, model_id and q. 409 "
    "VEHICLE_BRANCH_FILTER_UNAVAILABLE when vehicle_master has no responsible_branch_id column."
)


@router.get(
    "/vehicles",
    response_model=Page[VehicleWithRegistryResponse],
    responses={
        **_LIST_VEHICLES_ERROR_RESPONSES,
        409: {"description": "VEHICLE_BRANCH_FILTER_UNAVAILABLE (details: column) — branch_id given but the column is absent."},
    },
)
async def list_vehicles(
    q: str | None = Query(default=None, description=_VEHICLE_Q_DESCRIPTION),
    status: OperationalStatus | None = Query(default=None),
    model_id: str | None = Query(default=None),
    branch_id: str | None = Query(default=None, min_length=1, max_length=100, description=_BRANCH_ID_DESCRIPTION),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    service: VehicleService = Depends(get_vehicle_service),
) -> Page[VehicleWithRegistryResponse]:
    try:
        result = await service.list_vehicles_with_registry(
            q=q,
            operational_status=status,
            model_id=model_id,
            params=PageParams(page=page, page_size=page_size),
            branch_id=branch_id,
        )
    except RepositoryError as exc:
        raise vehicle_master_read_error(exc) from exc
    return Page[VehicleWithRegistryResponse](
        items=[_with_registry(e.vehicle, e.registry) for e in result.items],
        page=result.page,
        page_size=result.page_size,
        total_items=result.total_items,
    )


@router.get("/vehicles/{vehicle_id}", response_model=VehicleDetailResponse, responses=_DETAIL_ERRORS)
async def get_vehicle(
    vehicle_id: str, service: VehicleService = Depends(get_vehicle_service)
) -> VehicleDetailResponse:
    detail = await service.get_vehicle_detail(vehicle_id)
    return VehicleDetailResponse(
        vehicle=_with_registry(detail.vehicle, detail.registry),
        model=(
            VehicleModelResponse.model_validate(detail.model.model_dump())
            if detail.model
            else None
        ),
        components=[
            VehicleComponentResponse.model_validate(c.model_dump()) for c in detail.components
        ],
    )


@router.patch("/vehicles/{vehicle_id}", response_model=VehicleResponse, responses=_MACHINE_NO_ERRORS)
async def update_vehicle_machine_no(
    vehicle_id: str,
    body: UpdateMachineNoRequest,
    service: VehicleService = Depends(get_vehicle_service),
) -> VehicleResponse:
    vehicle = await service.update_machine_no(vehicle_id, body.machine_no)
    return VehicleResponse.model_validate(vehicle.model_dump())


@router.get(
    "/vehicles/{vehicle_id}/components",
    response_model=list[VehicleComponentResponse],
    responses=_COMPONENT_ERRORS,
)
async def list_vehicle_components(
    vehicle_id: str, service: VehicleService = Depends(get_vehicle_service)
) -> list[VehicleComponentResponse]:
    components = await service.list_components(vehicle_id)
    return [VehicleComponentResponse.model_validate(c.model_dump()) for c in components]


@router.get(
    "/vehicles/{vehicle_id}/status-history",
    response_model=list[VehicleStatusHistoryResponse],
    responses=_HISTORY_ERRORS,
)
async def list_vehicle_status_history(
    vehicle_id: str, service: VehicleService = Depends(get_vehicle_service)
) -> list[VehicleStatusHistoryResponse]:
    entries = await service.list_status_history(vehicle_id)
    return [VehicleStatusHistoryResponse.model_validate(e.model_dump()) for e in entries]


@router.patch(
    "/vehicles/{vehicle_id}/status",
    response_model=ChangeVehicleStatusResponse,
    responses=_STATUS_ERRORS,
)
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
