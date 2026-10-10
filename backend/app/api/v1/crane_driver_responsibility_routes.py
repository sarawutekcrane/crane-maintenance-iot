"""R2 Batch R2f-f — Crane / Vehicle ↔ Driver responsibility routes (history-only, no delete):
- GET  /vehicles/{vehicle_id}/responsible-drivers        current driver + period history (can_view)
- POST /vehicles/{vehicle_id}/responsible-driver-events  TRANSFER / INSERTION / END / CORRECTION / CANCELLATION
                                                          (can_assign_crane_driver)
- GET  /drivers/{driver_id}/vehicles                      reverse read: vehicles currently in this driver's
                                                          responsibility (can_view)
Write order: the capability (403), the client `X-Request-Id` (422
REQUEST_ID_REQUIRED), then the body (422) — all with zero repository calls.
The Phase 6 Driver routes and vehicle_driver assignment routes are unchanged
and carry no responsibility semantics; this is not the Personnel ↔ Driver
identity link (R2f-e).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.v1.crane_driver_responsibility_schemas import (
    DriverVehicleItemResponse,
    DriverVehiclesResponse,
    ResponsibilityChangedResponse,
    ResponsibilityEventRequest,
    ResponsibilityNoOpResponse,
    ResponsibilityPeriodResponse,
    ResponsibilityReplayResponse,
    VehicleResponsibleDriversResponse,
)
from app.api.v1.registry_mutation_body import effective_test_batch_id, openapi_body, parse_body
from app.api.v1.request_id_dependency import require_capability_dependency, require_client_request_id
from app.config import Settings
from app.context import RequestContext
from app.dependencies import get_current_context, get_repository, get_settings_dependency
from app.domain.authz import CAN_ASSIGN_CRANE_DRIVER, CAN_VIEW, require_capability
from app.domain.crane_driver_responsibility import CraneDriverResponsibilityService, ResponsibilityOutcome
from app.repositories.base import Repository

router = APIRouter(tags=["crane-driver-responsibility"])

_require_assign = require_capability_dependency(
    CAN_ASSIGN_CRANE_DRIVER, "การกำหนดผู้ขับผู้รับผิดชอบรถเครน (crane driver responsibility)"
)


def get_crane_driver_responsibility_service(
    repository: Repository = Depends(get_repository),
    settings: Settings = Depends(get_settings_dependency),
) -> CraneDriverResponsibilityService:
    return CraneDriverResponsibilityService(repository, settings.registry_context_effective,
                                            effective_test_batch_id(settings))


def _respond(outcome: ResponsibilityOutcome) -> JSONResponse:
    body: BaseModel
    if outcome.replayed:
        body = ResponsibilityReplayResponse(request_id=outcome.request_id, replayed=True,
                                            record_ids=list(outcome.record_ids))
    elif not outcome.changed:
        body = ResponsibilityNoOpResponse(request_id=outcome.request_id, changed=False)
    else:
        body = ResponsibilityChangedResponse(
            request_id=outcome.request_id,
            changed=True,
            record_id=outcome.record_id or "",
            event_id=outcome.event_id or "",
            timeline_status_after=outcome.timeline_status_after,  # type: ignore[arg-type]
            current_status=outcome.current_status,  # type: ignore[arg-type]
            current_driver_id=outcome.current_driver_id,
        )
    return JSONResponse(content=body.model_dump(mode="json"))


_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"model": ResponsibilityChangedResponse,
          "description": "changed / no-op {request_id, changed:false} / replayed {request_id, replayed, record_ids}"},
    403: {"description": "HTTP_ERROR — the caller lacks can_assign_crane_driver. Zero repository calls."},
    404: {"description": "VEHICLE_NOT_FOUND (in the request's data scope); DRIVER_RESPONSIBILITY_EVENT_NOT_FOUND."},
    409: {"description": "VEHICLE_ID_AMBIGUOUS; DRIVER_ID_AMBIGUOUS; DRIVER_PERSONNEL_AMBIGUOUS; "
                         "DRIVER_RESPONSIBILITY_HISTORY_STALE {field}; DRIVER_RESPONSIBILITY_TIMELINE_AMBIGUOUS "
                         "{reason}; DRIVER_RESPONSIBILITY_EVENT_SAME_INSTANT / _EVENT_NOT_LATEST / "
                         "_INSERTION_NOT_HISTORICAL / _EVENT_CANCELLED / _END_WITHOUT_DRIVER; REQUEST_ID_REUSED."},
    422: {"description": "REQUEST_ID_REQUIRED; VALIDATION_ERROR; REASON_REQUIRED; EFFECTIVE_*; "
                         "DRIVER_RESPONSIBILITY_DRIVER_REQUIRED / _CORRECTION_CHANGES_EVENT_NATURE; "
                         "VEHICLE_SCOPE_UNPROVEN; DRIVER_NOT_FOUND; DRIVER_SCOPE_UNPROVEN; DRIVER_NOT_ACTIVE; "
                         "PERSONNEL_NOT_ACTIVE."},
    500: {"description": "VEHICLE_MASTER_SCHEMA_INVALID; DRIVER_MASTER_SCHEMA_INVALID; "
                         "PERSONNEL_MASTER_SCHEMA_INVALID / _DATA_INVALID; "
                         "CRANE_DRIVER_RESPONSIBILITY_HISTORY_SCHEMA_INVALID / _DATA_INVALID {issues}."},
    503: {"description": "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED; *_READ_FAILED; "
                         "DRIVER_RESPONSIBILITY_HISTORY_WRITE_FAILED {history_write_outcome, request_id}."},
}


@router.post("/vehicles/{vehicle_id}/responsible-driver-events", response_model=None, responses=_RESPONSES,
             openapi_extra=openapi_body(ResponsibilityEventRequest))
async def record_vehicle_responsible_driver_event(
    vehicle_id: str,
    request: Request,
    context: RequestContext = Depends(_require_assign),
    request_id: str = Depends(require_client_request_id),
    service: CraneDriverResponsibilityService = Depends(get_crane_driver_responsibility_service),
) -> JSONResponse:
    _parsed, body = await parse_body(request, ResponsibilityEventRequest)
    outcome = await service.record_event(vehicle_id, body, request_id=request_id, user_id=context.user_id or "")
    return _respond(outcome)


@router.get("/vehicles/{vehicle_id}/responsible-drivers", response_model=VehicleResponsibleDriversResponse)
async def get_vehicle_responsible_drivers(
    vehicle_id: str,
    context: RequestContext = Depends(get_current_context),
    service: CraneDriverResponsibilityService = Depends(get_crane_driver_responsibility_service),
) -> VehicleResponsibleDriversResponse:
    require_capability(context, CAN_VIEW, "ผู้ขับผู้รับผิดชอบรถ (vehicle responsible drivers)")
    read = await service.responsible_drivers(vehicle_id)
    tl = read.timeline
    return VehicleResponsibleDriversResponse(
        vehicle_id=read.vehicle_id,
        timeline_status=tl.status,  # type: ignore[arg-type]
        current_status=tl.current_status,  # type: ignore[arg-type]
        current_driver_id=tl.current_driver_id,
        current_since=tl.current_since,
        events=[
            ResponsibilityPeriodResponse(
                event_id=e.event_id, in_force=e.in_force, entry_operation=e.entry_operation,  # type: ignore[arg-type]
                revision_no=e.revision_no, head_record_id=e.head_record_id, driver_id=e.driver_id,
                effective_at=e.effective_at, effective_precision=e.effective_precision,
                derived_end_at=e.derived_end_at, recorded_at=e.recorded_at, recorded_by=e.recorded_by,
                notes=list(e.notes),
            )
            for e in tl.events
        ],
    )


@router.get("/drivers/{driver_id}/vehicles", response_model=DriverVehiclesResponse)
async def get_driver_vehicles(
    driver_id: str,
    context: RequestContext = Depends(get_current_context),
    service: CraneDriverResponsibilityService = Depends(get_crane_driver_responsibility_service),
) -> DriverVehiclesResponse:
    require_capability(context, CAN_VIEW, "รถในความรับผิดชอบของผู้ขับ (driver responsible vehicles)")
    read = await service.driver_vehicles(driver_id)
    return DriverVehiclesResponse(
        driver_id=read.driver_id,
        items=[DriverVehicleItemResponse(vehicle_id=i.vehicle_id, since=i.since, event_id=i.event_id)
               for i in read.items],
    )
