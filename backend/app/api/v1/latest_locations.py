"""Latest Location read route (Web/API Phase 6 Batch 6D).

Read-only: exposes the existing Batch 4B `latest_location` projection
(`Repository.get_current_location`, via `LocationService.
get_current_location`) for display — never a write path, never a second
current-location calculation, and never a fallback to `location_snapshot`
history. See `app.domain.location_snapshot.LocationService.
get_current_location` for the full frozen contract.

Same open-to-any-authenticated-actor precedent as
`app.api.v1.vehicle_events`/`app.api.v1.daily_summaries` (see those
modules' docstrings): H03 (Location Privacy / Access) remains
TBD-BLOCKING before production RBAC — this is the Phase 6
prototype/read precedent only, not a final production access policy."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.latest_location_schemas import LatestLocationResponse
from app.dependencies import get_location_service
from app.domain.location_snapshot import LocationService

router = APIRouter(tags=["latest-location"])


@router.get(
    "/vehicles/{vehicle_id}/latest-location",
    response_model=LatestLocationResponse | None,
)
async def get_vehicle_latest_location(
    vehicle_id: str,
    service: LocationService = Depends(get_location_service),
) -> LatestLocationResponse | None:
    current = await service.get_current_location(vehicle_id)
    if current is None:
        return None
    return LatestLocationResponse.model_validate(current.model_dump())
