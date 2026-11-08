"""R4 / TASK-010 Fleet PM Due B1: the read-only fleet and vehicle PM Due routes.

Both need a trusted actor with `can_view` and the server's TEST/REAL scope, checked in
`PmService` before any protected read; they return only the derived Due read model
(never raw Outcomes or E01 journal events). In the application the Master is not
wired (dormant, OPEN-005), so every vehicle reads MASTER_NOT_ACTIVE. GET only:
nothing is projected, captured or written.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.v1.pm_schemas import (
    PmDueAssignmentResponse,
    PmDuePlanResponse,
    PmDueSetResponse,
    VehiclePmDueResponse,
)
from app.context import RequestContext
from app.dependencies import get_current_context, get_pm_service
from app.domain.common import OperationalStatus, Page, PageParams
from app.domain.pm_service import PmService, VehiclePmDue

router = APIRouter(tags=["pm-due"])

_RESPONSES = {
    403: {"description": "No trusted actor with can_view."},
    409: {"description": "PM_E01_TRANSITION_INCOMPLETE / PM_E01_STATE_INCONSISTENT (fail closed, no ids)."},
    500: {"description": "A stored PM record cannot be trusted (issue codes only, no ids)."},
    501: {"description": "FEATURE_NOT_AVAILABLE: the storage adapter has no PM Master bridge storage."},
    503: {"description": "The server's TEST/REAL data context is not configured."},
}


def _vehicle_response(row: VehiclePmDue) -> VehiclePmDueResponse:
    return VehiclePmDueResponse(
        vehicle_id=row.vehicle_id, machine_no=row.machine_no, model_id=row.model_id, state=row.state,
        explanation=row.explanation,
        assignments=[PmDueAssignmentResponse(**vars(a)) for a in row.assignments],
        plans=[PmDuePlanResponse(**vars(p)) for p in row.plans],
        sets=[PmDueSetResponse(**vars(s)) for s in row.sets])


@router.get("/pm/due/vehicles", response_model=Page[VehiclePmDueResponse], responses=_RESPONSES)
async def list_fleet_pm_due(
    q: str | None = Query(default=None),
    status: OperationalStatus | None = Query(default=None),
    model_id: str | None = Query(default=None),
    branch_id: str | None = Query(default=None, min_length=1, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    context: RequestContext = Depends(get_current_context),
    service: PmService = Depends(get_pm_service),
) -> Page[VehiclePmDueResponse]:
    result = await service.list_fleet_pm_due(context, PageParams(page=page, page_size=page_size), q=q,
                                             operational_status=status, model_id=model_id, branch_id=branch_id)
    return Page[VehiclePmDueResponse](items=[_vehicle_response(r) for r in result.items], page=result.page,
                                      page_size=result.page_size, total_items=result.total_items)


@router.get("/pm/due/vehicles/{vehicle_id}", response_model=VehiclePmDueResponse, responses=_RESPONSES)
async def get_vehicle_pm_due(
    vehicle_id: str,
    context: RequestContext = Depends(get_current_context),
    service: PmService = Depends(get_pm_service),
) -> VehiclePmDueResponse:
    return _vehicle_response(await service.read_vehicle_pm_due(context, vehicle_id))
