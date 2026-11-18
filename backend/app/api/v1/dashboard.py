"""Dashboard routes (Phase 7 Batch 7B2).

`GET /dashboard/fleet-status` returns only K1 `vehicle_total` and the K2-K6
recorded operational-status counts, computed by `VehicleService` from one
validated vehicle-master read. Any failure is a whole-response error with no
counts. Unknown query parameters are ignored, as on every route.

R8 (R8-01 / R8-S1): one optional query parameter, `branch_id` — an exact
responsible-branch filter computed with the same read, gates and predicate as
`GET /vehicles?branch_id=` (parity), echoed back. It is a filter, not an
authorization boundary (no branch-level data authorization exists). The read
guard is now `require_trusted_reader` (trusted actor + can_view) before any read.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.v1.dashboard_schemas import FleetStatusCountsResponse, FleetStatusSummaryResponse
from app.context import RequestContext
from app.dependencies import get_current_context, get_vehicle_service
from app.domain.authz import require_trusted_reader
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
    409: {"description": "VEHICLE_BRANCH_FILTER_UNAVAILABLE (details: column) — branch_id given but the column is absent."},
    503: {"description": "VEHICLE_MASTER_READ_FAILED — the vehicle master could not be read."},
}


@router.get(
    "/dashboard/fleet-status",
    response_model=FleetStatusSummaryResponse,
    response_model_exclude_none=True,
    responses=_ERROR_RESPONSES,
    summary="Fleet status summary (optional exact branch filter)",
)
async def get_fleet_status(
    branch_id: str | None = Query(default=None, min_length=1, max_length=100),
    context: RequestContext = Depends(get_current_context),
    service: VehicleService = Depends(get_vehicle_service),
) -> FleetStatusSummaryResponse:
    # Authorization before any repository read: a denied request reads nothing.
    require_trusted_reader(context, "ภาพรวมกองรถ (fleet status overview)")
    summary = await service.get_fleet_status_summary(branch_id)
    return FleetStatusSummaryResponse(
        branch_id=branch_id,
        population=summary.population,
        vehicle_total=summary.vehicle_total,
        status_counts=FleetStatusCountsResponse(**summary.status_counts),
    )
