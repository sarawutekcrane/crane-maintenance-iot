"""Dashboard routes (Phase 7 Batch 7B2).

`GET /dashboard/fleet-status` is GLOBAL: it takes no query parameters
(unknown ones are ignored, as on every route) and returns only K1
`vehicle_total` and the K2-K6 recorded operational-status counts, computed
by `VehicleService` from one validated vehicle-master read. Any failure is
a whole-response error with no counts.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.v1.dashboard_schemas import FleetStatusCountsResponse, FleetStatusSummaryResponse
from app.context import RequestContext
from app.dependencies import get_current_context, get_vehicle_service
from app.domain.authz import CAN_VIEW, require_capability
from app.domain.vehicle_service import VehicleService

router = APIRouter(tags=["dashboard"])

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    403: {"description": "HTTP_ERROR — the caller lacks the 'can_view' capability. No data is read."},
    500: {
        "description": (
            "VEHICLE_MASTER_SCHEMA_INVALID (details: tab, problem, headers) or "
            "VEHICLE_MASTER_DATA_INVALID (details: issue_counts, sample_vehicle_ids). "
            "No counts are returned."
        )
    },
    503: {"description": "VEHICLE_MASTER_READ_FAILED — the vehicle master could not be read."},
}


@router.get(
    "/dashboard/fleet-status",
    response_model=FleetStatusSummaryResponse,
    responses=_ERROR_RESPONSES,
    summary="Fleet status summary (global, no filters)",
)
async def get_fleet_status(
    context: RequestContext = Depends(get_current_context),
    service: VehicleService = Depends(get_vehicle_service),
) -> FleetStatusSummaryResponse:
    # Authorization before any repository read: a denied request reads nothing.
    require_capability(context, CAN_VIEW, "ภาพรวมกองรถ (fleet status overview)")
    summary = await service.get_fleet_status_summary()
    return FleetStatusSummaryResponse(
        population=summary.population,
        vehicle_total=summary.vehicle_total,
        status_counts=FleetStatusCountsResponse(**summary.status_counts),
    )
