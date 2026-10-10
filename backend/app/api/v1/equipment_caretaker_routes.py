"""R2 Batch R2f-d — Equipment ↔ Technician caretaker routes (history-only, no delete):
- GET  /equipment/{equipment_id}/caretakers         current caretaker + period history (can_view)
- POST /equipment/{equipment_id}/caretaker-events   TRANSFER / INSERTION / END / CORRECTION / CANCELLATION
                                                     (can_assign_equipment_caretaker)
- GET  /technicians/{technician_id}/equipment        reverse read: equipment currently in this technician's care
                                                     (can_view)
Write order: the capability (403), the client `X-Request-Id` (422
REQUEST_ID_REQUIRED), then the body (422) — all with zero repository calls.
The caretaker is display information only: no inspection route reads it, and
it never selects, authorizes or gates an inspection or its inspector.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.v1.equipment_caretaker_schemas import (
    CaretakerChangedResponse,
    CaretakerEventRequest,
    CaretakerNoOpResponse,
    CaretakerPeriodResponse,
    CaretakerReplayResponse,
    CaretakerTechnicianResponse,
    EquipmentCaretakersResponse,
    TechnicianEquipmentItemResponse,
    TechnicianEquipmentResponse,
)
from app.api.v1.registry_mutation_body import effective_test_batch_id, openapi_body, parse_body
from app.api.v1.request_id_dependency import require_capability_dependency, require_client_request_id
from app.config import Settings
from app.context import RequestContext
from app.dependencies import get_current_context, get_repository, get_settings_dependency
from app.domain.authz import CAN_ASSIGN_EQUIPMENT_CARETAKER, CAN_VIEW, require_capability
from app.domain.equipment_caretaker import CaretakerOutcome, EquipmentCaretakerService
from app.repositories.base import Repository

router = APIRouter(tags=["equipment-caretaker"])

_require_assign = require_capability_dependency(
    CAN_ASSIGN_EQUIPMENT_CARETAKER, "การกำหนดผู้ดูแลอุปกรณ์ (equipment caretaker)"
)


def get_equipment_caretaker_service(
    repository: Repository = Depends(get_repository),
    settings: Settings = Depends(get_settings_dependency),
) -> EquipmentCaretakerService:
    return EquipmentCaretakerService(repository, settings.registry_context_effective, effective_test_batch_id(settings))


def _respond(outcome: CaretakerOutcome) -> JSONResponse:
    body: BaseModel
    if outcome.replayed:
        body = CaretakerReplayResponse(request_id=outcome.request_id, replayed=True, record_ids=list(outcome.record_ids))
    elif not outcome.changed:
        body = CaretakerNoOpResponse(request_id=outcome.request_id, changed=False)
    else:
        body = CaretakerChangedResponse(
            request_id=outcome.request_id,
            changed=True,
            record_id=outcome.record_id or "",
            event_id=outcome.event_id or "",
            timeline_status_after=outcome.timeline_status_after,  # type: ignore[arg-type]
            current_status=outcome.current_status,  # type: ignore[arg-type]
            current_technician_id=outcome.current_technician_id,
        )
    return JSONResponse(content=body.model_dump(mode="json"))


_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"model": CaretakerChangedResponse,
          "description": "changed / no-op {request_id, changed:false} / replayed {request_id, replayed, record_ids}"},
    403: {"description": "HTTP_ERROR — the caller lacks can_assign_equipment_caretaker. Zero repository calls."},
    404: {"description": "EQUIPMENT_NOT_FOUND (in the request's data scope); CARETAKER_EVENT_NOT_FOUND."},
    409: {"description": "EQUIPMENT_ID_AMBIGUOUS; TECHNICIAN_ID_AMBIGUOUS; TECHNICIAN_PERSONNEL_AMBIGUOUS; "
                         "CARETAKER_HISTORY_STALE {field}; CARETAKER_TIMELINE_AMBIGUOUS {reason}; "
                         "CARETAKER_EVENT_SAME_INSTANT; CARETAKER_EVENT_NOT_LATEST; CARETAKER_INSERTION_NOT_HISTORICAL; "
                         "CARETAKER_EVENT_CANCELLED; CARETAKER_END_WITHOUT_CARETAKER; REQUEST_ID_REUSED."},
    422: {"description": "REQUEST_ID_REQUIRED; VALIDATION_ERROR; REASON_REQUIRED; EFFECTIVE_*; "
                         "CARETAKER_TECHNICIAN_REQUIRED; CARETAKER_CORRECTION_CHANGES_EVENT_NATURE; "
                         "EQUIPMENT_SCOPE_UNPROVEN; TECHNICIAN_NOT_FOUND; TECHNICIAN_SCOPE_UNPROVEN; "
                         "TECHNICIAN_NOT_ACTIVE; TECHNICIAN_PERSONNEL_UNRESOLVED; PERSONNEL_NOT_ACTIVE."},
    500: {"description": "EQUIPMENT_MASTER_SCHEMA_INVALID; TECHNICIAN_MASTER_SCHEMA_INVALID; "
                         "PERSONNEL_MASTER_SCHEMA_INVALID / _DATA_INVALID; "
                         "EQUIPMENT_CARETAKER_HISTORY_SCHEMA_INVALID / _DATA_INVALID {issues}."},
    503: {"description": "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED; *_READ_FAILED; CARETAKER_HISTORY_WRITE_FAILED "
                         "{history_write_outcome, request_id}."},
}


@router.post("/equipment/{equipment_id}/caretaker-events", response_model=None, responses=_RESPONSES,
             openapi_extra=openapi_body(CaretakerEventRequest))
async def record_equipment_caretaker_event(
    equipment_id: str,
    request: Request,
    context: RequestContext = Depends(_require_assign),
    request_id: str = Depends(require_client_request_id),
    service: EquipmentCaretakerService = Depends(get_equipment_caretaker_service),
) -> JSONResponse:
    _parsed, body = await parse_body(request, CaretakerEventRequest)
    outcome = await service.record_event(equipment_id, body, request_id=request_id, user_id=context.user_id or "")
    return _respond(outcome)


@router.get("/equipment/{equipment_id}/caretakers", response_model=EquipmentCaretakersResponse)
async def get_equipment_caretakers(
    equipment_id: str,
    context: RequestContext = Depends(get_current_context),
    service: EquipmentCaretakerService = Depends(get_equipment_caretaker_service),
) -> EquipmentCaretakersResponse:
    require_capability(context, CAN_VIEW, "ผู้ดูแลอุปกรณ์ (equipment caretaker)")
    read = await service.caretakers(equipment_id)
    tl = read.timeline
    technician = read.current_technician
    return EquipmentCaretakersResponse(
        equipment_id=read.equipment_id,
        timeline_status=tl.status,  # type: ignore[arg-type]
        current_status=tl.current_status,  # type: ignore[arg-type]
        current_technician_id=tl.current_technician_id,
        current_since=tl.current_since,
        current_technician_resolution=read.current_technician_resolution,  # type: ignore[arg-type]
        current_technician=CaretakerTechnicianResponse(
            technician_id=technician.technician_id, first_name=technician.first_name,
            last_name=technician.last_name, active_status=technician.active_status,
        ) if technician else None,
        events=[
            CaretakerPeriodResponse(
                event_id=e.event_id, in_force=e.in_force, entry_operation=e.entry_operation,  # type: ignore[arg-type]
                revision_no=e.revision_no, head_record_id=e.head_record_id, technician_id=e.technician_id,
                effective_at=e.effective_at, effective_precision=e.effective_precision,
                derived_end_at=e.derived_end_at, recorded_at=e.recorded_at, recorded_by=e.recorded_by,
                notes=list(e.notes),
            )
            for e in tl.events
        ],
    )


@router.get("/technicians/{technician_id}/equipment", response_model=TechnicianEquipmentResponse)
async def get_technician_equipment(
    technician_id: str,
    context: RequestContext = Depends(get_current_context),
    service: EquipmentCaretakerService = Depends(get_equipment_caretaker_service),
) -> TechnicianEquipmentResponse:
    require_capability(context, CAN_VIEW, "อุปกรณ์ในความดูแลของช่าง (technician caretaker equipment)")
    read = await service.technician_equipment(technician_id)
    return TechnicianEquipmentResponse(
        technician_id=read.technician_id,
        items=[TechnicianEquipmentItemResponse(equipment_id=i.equipment_id, since=i.since, event_id=i.event_id)
               for i in read.items],
    )
