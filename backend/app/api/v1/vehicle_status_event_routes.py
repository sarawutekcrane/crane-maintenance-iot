"""R5 routes: effective-dated vehicle status events, effective-time corrections
and downtime (Revision 4 §6.2). Every write passes the AMB-1 guard first
(`can_manage_repair` before any read, then the server data context and the
vehicle's proven scope); reads keep the existing status-history read rules."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.api.v1.request_id_dependency import require_client_request_id
from app.api.v1.vehicle_schemas import VehicleResponse, VehicleStatusHistoryResponse
from app.api.v1.vehicle_status_event_schemas import (
    CorrectVehicleStatusTimeRequest,
    DowntimeIntervalResponse,
    RecordVehicleStatusEventRequest,
    VehicleDowntimeResponse,
    VehicleStatusCorrectionWriteResponse,
    VehicleStatusEventResponse,
    VehicleStatusEventWriteResponse,
    VehicleStatusTimeCorrectionResponse,
)
from app.context import RequestContext
from app.dependencies import get_current_context, get_vehicle_status_event_service
from app.domain.vehicle_status_events import (
    UNAVAILABLE_STATUSES,
    VehicleStatusEventService,
    require_vehicle_status_capability,
)

router = APIRouter(tags=["vehicles"])

_WRITE_ERRORS: dict[int | str, dict[str, object]] = {
    403: {"description": "Missing can_manage_repair (checked before any read); nothing written."},
    404: {"description": "VEHICLE_NOT_FOUND / VEHICLE_STATUS_EVENT_NOT_FOUND"},
    409: {"description": "VEHICLE_ID_AMBIGUOUS, VEHICLE_STATUS_EVENT_OUT_OF_ORDER, VEHICLE_STATUS_REQUEST_CONFLICT"},
    422: {"description": "VEHICLE_SCOPE_UNPROVEN, REQUEST_ID_REQUIRED or invalid values"},
    503: {"description": "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED"},
}


def _capability_first(context: RequestContext = Depends(get_current_context)) -> RequestContext:
    """AMB-1: refuse an unauthorized caller (403) before the request id, the body
    or any repository read is looked at."""
    require_vehicle_status_capability(context)
    return context


@router.post("/vehicles/{vehicle_id}/status-events", response_model=VehicleStatusEventWriteResponse,
             responses=_WRITE_ERRORS)
async def record_vehicle_status_event(
    vehicle_id: str,
    body: RecordVehicleStatusEventRequest,
    context: RequestContext = Depends(_capability_first),
    request_id: str = Depends(require_client_request_id),
    service: VehicleStatusEventService = Depends(get_vehicle_status_event_service),
) -> VehicleStatusEventWriteResponse:
    vehicle, entry, replayed = await service.record_effective_event(
        context, vehicle_id, new_status=body.status, effective_at=body.effective_at, note=body.note,
        request_id=request_id, body=body.model_dump(mode="json"))
    return VehicleStatusEventWriteResponse(
        vehicle=VehicleResponse.model_validate(vehicle.model_dump()),
        history_entry=VehicleStatusHistoryResponse.model_validate(entry.model_dump()), replayed=replayed)


@router.post("/vehicles/{vehicle_id}/status-events/{history_id}/time-corrections",
             response_model=VehicleStatusCorrectionWriteResponse, responses=_WRITE_ERRORS)
async def correct_vehicle_status_time(
    vehicle_id: str,
    history_id: str,
    body: CorrectVehicleStatusTimeRequest,
    context: RequestContext = Depends(_capability_first),
    request_id: str = Depends(require_client_request_id),
    service: VehicleStatusEventService = Depends(get_vehicle_status_event_service),
) -> VehicleStatusCorrectionWriteResponse:
    correction, replayed = await service.correct_effective_time(
        context, vehicle_id, history_id, new_effective_at=body.new_effective_at, reason=body.reason,
        request_id=request_id, body=body.model_dump(mode="json"))
    return VehicleStatusCorrectionWriteResponse(
        correction=VehicleStatusTimeCorrectionResponse.model_validate(correction.model_dump()), replayed=replayed)


@router.get("/vehicles/{vehicle_id}/status-events", response_model=list[VehicleStatusEventResponse])
async def list_vehicle_status_events(
    vehicle_id: str,
    context: RequestContext = Depends(get_current_context),
    service: VehicleStatusEventService = Depends(get_vehicle_status_event_service),
) -> list[VehicleStatusEventResponse]:
    events = await service.list_events(vehicle_id)
    return [VehicleStatusEventResponse(
        history_id=e.entry.history_id, status=e.entry.status, effective_at=e.effective_at,
        effective_source=e.effective_source, recorded_at=e.entry.changed_at, changed_by=e.entry.changed_by,
        note=e.entry.note,
        corrections=[VehicleStatusTimeCorrectionResponse.model_validate(c.model_dump()) for c in e.corrections],
    ) for e in reversed(events)]


@router.get("/vehicles/{vehicle_id}/downtime", response_model=VehicleDowntimeResponse)
async def get_vehicle_downtime(
    vehicle_id: str,
    from_: datetime = Query(alias="from"),
    to: datetime = Query(),
    context: RequestContext = Depends(get_current_context),
    service: VehicleStatusEventService = Depends(get_vehicle_status_event_service),
) -> VehicleDowntimeResponse:
    result = await service.downtime(vehicle_id, from_, to)
    return VehicleDowntimeResponse(
        vehicle_id=vehicle_id, from_=result["from"], to=result["to"],
        unavailable_statuses=sorted(UNAVAILABLE_STATUSES, key=lambda s: s.value),
        intervals=[DowntimeIntervalResponse(started_at=s, ended_at=e) for s, e in result["intervals"]],
        total_seconds=result["total_seconds"],
        unknown=[DowntimeIntervalResponse(started_at=s, ended_at=e) for s, e in result["unknown"]],
        flags=result["flags"])
