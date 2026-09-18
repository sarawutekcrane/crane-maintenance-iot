"""Vehicle Event routes (Web/API Phase 6 Batch 4A — Raw Vehicle Event
Foundation + Idempotent Device Event Ingestion).

Same open-to-any-authenticated-actor precedent as
`app.api.v1.model_documents`/`app.api.v1.drivers` (see those modules'
docstrings): final RBAC remains Phase 10. This module never imports
`GoogleSheetsRepository` — routes depend only on `VehicleEventService`,
itself depending only on the `Repository` interface, per the frozen
Repository/Storage abstraction (`docs/architecture/API_CONVENTIONS.md`)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.vehicle_event_schemas import CreateVehicleEventRequest, VehicleEventResponse
from app.dependencies import get_vehicle_event_service
from app.domain.vehicle_event import VehicleEvent
from app.domain.vehicle_event_service import VehicleEventService

router = APIRouter(tags=["vehicle-events"])


def _event_response(event: VehicleEvent) -> VehicleEventResponse:
    return VehicleEventResponse.model_validate(event.model_dump())


@router.post("/vehicle-events", response_model=VehicleEventResponse)
async def create_vehicle_event(
    body: CreateVehicleEventRequest,
    service: VehicleEventService = Depends(get_vehicle_event_service),
) -> VehicleEventResponse:
    event = await service.ingest_device_event(
        vehicle_id=body.vehicle_id,
        device_id=body.device_id,
        component_id=body.component_id,
        event_type=body.event_type,
        event_time=body.event_time,
        fuel_level_value=body.fuel_level_value,
        fuel_level_unit=body.fuel_level_unit,
        latitude=body.latitude,
        longitude=body.longitude,
        gps_valid=body.gps_valid,
        note_th=body.note_th,
        device_event_id=body.device_event_id,
        sequence=body.sequence,
        created_offline=body.created_offline,
        time_quality=body.time_quality,
    )
    return _event_response(event)


@router.get("/vehicle-events/{event_id}", response_model=VehicleEventResponse)
async def get_vehicle_event(
    event_id: str,
    service: VehicleEventService = Depends(get_vehicle_event_service),
) -> VehicleEventResponse:
    event = await service.get_event(event_id)
    return _event_response(event)


@router.get("/vehicles/{vehicle_id}/events", response_model=list[VehicleEventResponse])
async def list_vehicle_events(
    vehicle_id: str,
    service: VehicleEventService = Depends(get_vehicle_event_service),
) -> list[VehicleEventResponse]:
    events = await service.list_for_vehicle(vehicle_id)
    return [_event_response(e) for e in events]
