"""Location snapshot routes (Core Demo Fixes Delta REV03 section E).

Read-only — snapshots are created only as a side effect of
`MeterService.capture_current_state` (the shared automatic machine-state
snapshot mechanism), never directly through this router.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.api.v1.location_snapshot_schemas import LocationSnapshotResponse
from app.dependencies import get_location_service
from app.domain.location_snapshot import LocationService
from app.errors import ApiError

router = APIRouter(tags=["location-snapshots"])


@router.get("/location-snapshots/{location_snapshot_id}", response_model=LocationSnapshotResponse)
async def get_location_snapshot(
    location_snapshot_id: str, service: LocationService = Depends(get_location_service)
) -> LocationSnapshotResponse:
    snapshot = await service.get_snapshot(location_snapshot_id)
    if snapshot is None:
        raise ApiError(
            code="LOCATION_SNAPSHOT_NOT_FOUND",
            message=f"Location snapshot '{location_snapshot_id}' was not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return LocationSnapshotResponse.model_validate(snapshot.model_dump())


@router.get(
    "/location-snapshots/by-event/{event_id}", response_model=list[LocationSnapshotResponse]
)
async def list_location_snapshots_for_event(
    event_id: str, service: LocationService = Depends(get_location_service)
) -> list[LocationSnapshotResponse]:
    """`event_id` is the `meter_snapshot_id` of the counter snapshot
    captured for the same event."""
    snapshots = await service.list_for_event(event_id)
    return [LocationSnapshotResponse.model_validate(s.model_dump()) for s in snapshots]
