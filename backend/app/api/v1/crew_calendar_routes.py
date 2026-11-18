"""R8 early workstream — Crew Assignment Extension + Resource Calendar routes
(Owner source approval 2026-11-18; Mock/TEST only; no DELETE):

- POST /vehicles/{vehicle_id}/crew-assignment-operations
       CREATE / REVISE / CANCEL / EARLY_END (OD-4 = A). Guard, before ANY
       repository call: a trusted actor, an Access-Management-verified employee,
       holding BOTH `can_assign_crane_crew` (OD-3 = A: per-employee TEST grant only,
       no default holder) and `can_view`; then the client `X-Request-Id` (422); then
       the body (422). Google Sheets -> 501; REAL -> 409 CREW_REAL_WRITES_NOT_ENABLED.
- GET  /vehicles/{vehicle_id}/crew-assignments           (trusted can_view; optional from / to)
- GET  /vehicles/{vehicle_id}/crew-assignment-history    (trusted can_view)
- GET  /resource-calendar?from&to&view[&vehicle_id&personnel_id&branch_id]
       OD-7 = A: a trusted actor holding can_assign_crane_driver OR can_assign_crane_crew
       (fleet-wide personal schedules); window <= 42 Bangkok days.

Every read is refused (403) before any repository read and answers the same for a
real and a guessed id. Payloads carry the public personnel name only.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.v1.crew_calendar_schemas import (
    CalendarConflictResponse,
    CalendarEntryResponse,
    CrewHistoryEventResponse,
    CrewHistoryRecordResponse,
    CrewIntervalResponse,
    CrewOperationChangedResponse,
    CrewOperationNoOpResponse,
    CrewOperationReplayResponse,
    CrewOperationRequest,
    CrewWarningResponse,
    ResourceCalendarResponse,
    VehicleCrewHistoryResponse,
    VehicleCrewResponse,
)
from app.api.v1.registry_mutation_body import effective_test_batch_id, openapi_body, parse_body
from app.api.v1.request_id_dependency import require_client_request_id
from app.config import DataRepositoryMode, Settings
from app.context import RequestContext
from app.dependencies import get_current_context, get_repository, get_settings_dependency
from app.domain.authz import (
    CAN_ASSIGN_CRANE_CREW,
    CAN_ASSIGN_CRANE_DRIVER,
    CAN_VIEW,
    require_any_capability,
    require_trusted_reader,
)
from app.domain.crew_assignment import CrewAssignmentService, CrewOutcome
from app.domain.operational_driver_timeline import iso, parse_date, parse_dates
from app.domain.registration import text
from app.domain.registry_write_support import error
from app.domain.resource_calendar import ResourceCalendarService
from app.errors import ApiError
from app.repositories.base import Repository

router = APIRouter(tags=["crew-assignment-resource-calendar"])

_WRITE_TH = "การมอบหมายทีมงานประจำเครน (crew assignment)"
_READ_TH = "การมอบหมายทีมงานประจำเครน (read crew assignments)"
_CALENDAR_TH = "ปฏิทินทรัพยากร (resource calendar)"


def get_crew_assignment_service(
    repository: Repository = Depends(get_repository),
    settings: Settings = Depends(get_settings_dependency),
) -> CrewAssignmentService:
    return CrewAssignmentService(repository, settings.registry_context_effective, effective_test_batch_id(settings),
                                 mock_repository=settings.data_repository == DataRepositoryMode.MOCK)


def get_resource_calendar_service(
    repository: Repository = Depends(get_repository),
    settings: Settings = Depends(get_settings_dependency),
    crew: CrewAssignmentService = Depends(get_crew_assignment_service),
) -> ResourceCalendarService:
    return ResourceCalendarService(repository, crew, settings.registry_context_effective,
                                   effective_test_batch_id(settings))


def _forbidden(code: str, message: str) -> ApiError:
    return ApiError(code=code, message=message, status_code=status.HTTP_403_FORBIDDEN)


async def require_crew_writer(context: RequestContext = Depends(get_current_context)) -> RequestContext:
    """OD-3 = A, before any repository read: a trusted actor, resolved by Access
    Management to exactly one active employee, holding the per-employee
    `can_assign_crane_crew` grant AND `can_view`. No development role holds the
    capability, so legacy mode always refuses here."""
    if not (context.user_id or "").strip():
        raise _forbidden("ACCESS_ACTOR_NOT_VERIFIED", f"{_WRITE_TH} requires a trusted, authenticated actor")
    if CAN_ASSIGN_CRANE_CREW not in context.capabilities or CAN_VIEW not in context.capabilities:
        raise _forbidden("CREW_ASSIGNMENT_NOT_AUTHORIZED",
                         f"{_WRITE_TH} requires the '{CAN_ASSIGN_CRANE_CREW}' grant and '{CAN_VIEW}'")
    if getattr(context, "access", None) is None or not getattr(context, "personnel_id", None):
        raise _forbidden("ACCESS_ACTOR_NOT_VERIFIED",
                         f"{_WRITE_TH} requires an active TEST employee linked to exactly one account")
    return context


def _date_filters(date_from: str | None, date_to: str | None):
    parsed = []
    for name, raw in (("from", date_from), ("to", date_to)):
        value = parse_date(raw) if raw is not None else None
        if raw is not None and value is None:
            raise error("CREW_DATE_INVALID", f"{name} must be a calendar date YYYY-MM-DD", 422, {"field": name})
        parsed.append(value)
    if parsed[0] and parsed[1] and parsed[1] < parsed[0]:
        raise error("CREW_RANGE_INVALID", "to must not be before from", 422, {"field": "to"})
    return parsed[0], parsed[1]


def _respond(outcome: CrewOutcome) -> JSONResponse:
    body: BaseModel
    if outcome.replayed:
        body = CrewOperationReplayResponse(request_id=outcome.request_id, replayed=True,
                                           operation_id=outcome.operation_id or "",
                                           record_ids=list(outcome.record_ids), event_ids=list(outcome.event_ids))
    elif not outcome.changed:
        body = CrewOperationNoOpResponse(request_id=outcome.request_id, changed=False,
                                         existing_event_id=outcome.existing_event_id)
    else:
        body = CrewOperationChangedResponse(
            request_id=outcome.request_id, changed=True, operation_id=outcome.operation_id or "",
            record_ids=list(outcome.record_ids), event_ids=list(outcome.event_ids),
            warnings=[CrewWarningResponse(code=w.code, event_id=w.event_id, personnel_id=w.personnel_id,
                                          vehicle_id=w.vehicle_id, related_event_id=w.related_event_id)
                      for w in outcome.warnings])
    return JSONResponse(content=body.model_dump(mode="json"))


_WRITE_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"model": CrewOperationChangedResponse,
          "description": "changed / no-op or duplicate {request_id, changed:false, existing_event_id} / replayed"},
    403: {"description": "ACCESS_ACTOR_NOT_VERIFIED / CREW_ASSIGNMENT_NOT_AUTHORIZED. Zero repository calls."},
    404: {"description": "VEHICLE_NOT_FOUND; CREW_ASSIGNMENT_NOT_FOUND."},
    409: {"description": "CREW_REAL_WRITES_NOT_ENABLED; RESOURCE_CONFLICT / CROSS_ROLE_IDENTITY_UNVERIFIED {axis: "
                         "PERSON, conflicting_event_id, first, second}; CREW_ASSIGNMENT_STALE / _CANCELLED / "
                         "_ALREADY_STARTED / _NOT_STARTED / _ALREADY_ENDED; CREW_CONCURRENT_CHANGE; REQUEST_ID_REUSED; "
                         "VEHICLE_ID_AMBIGUOUS; PERSONNEL_ID_AMBIGUOUS."},
    422: {"description": "REQUEST_ID_REQUIRED; VALIDATION_ERROR; REASON_REQUIRED; CREW_DATE_INVALID; "
                         "CREW_TIME_INVALID; CREW_RANGE_*; CREW_SHIFT_*; CREW_ROLE_*; CREW_EARLY_END_INVALID; "
                         "VEHICLE_SCOPE_UNPROVEN; PERSONNEL_NOT_FOUND / _SCOPE_UNPROVEN / _NOT_ACTIVE."},
    500: {"description": "CREW_HISTORY_DATA_INVALID; E2_HISTORY_DATA_INVALID; *_SCHEMA_INVALID."},
    501: {"description": "FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE (Google Sheets: crew is Mock/TEST only)."},
    503: {"description": "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED; *_READ_FAILED; CREW_HISTORY_WRITE_FAILED "
                         "{history_write_outcome, request_id}."},
}


@router.post("/vehicles/{vehicle_id}/crew-assignment-operations", response_model=None,
             responses=_WRITE_RESPONSES, openapi_extra=openapi_body(CrewOperationRequest))
async def apply_crew_assignment_operation(
    vehicle_id: str,
    request: Request,
    context: RequestContext = Depends(require_crew_writer),
    request_id: str = Depends(require_client_request_id),
    service: CrewAssignmentService = Depends(get_crew_assignment_service),
) -> JSONResponse:
    _parsed, body = await parse_body(request, CrewOperationRequest)
    outcome = await service.apply(vehicle_id, body, request_id=request_id, user_id=context.user_id or "")
    return _respond(outcome)


@router.get("/vehicles/{vehicle_id}/crew-assignments", response_model=VehicleCrewResponse)
async def get_vehicle_crew_assignments(
    vehicle_id: str,
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
    context: RequestContext = Depends(get_current_context),
    service: CrewAssignmentService = Depends(get_crew_assignment_service),
) -> VehicleCrewResponse:
    require_trusted_reader(context, _READ_TH)
    lo, hi = _date_filters(date_from, date_to)
    read = await service.vehicle_crew(vehicle_id, date_from=lo, date_to=hi)
    return VehicleCrewResponse(vehicle_id=read.vehicle_id, intervals=[
        CrewIntervalResponse(
            event_id=v.interval.event_id, revision_no=v.interval.revision_no, vehicle_id=v.interval.vehicle_id,
            personnel_id=v.interval.personnel_id, personnel_name=read.names.get(v.interval.personnel_id) or None,
            crew_role=v.interval.role, crew_role_note_th=v.interval.role_note_th or None, mode=v.interval.mode,
            label_date=v.interval.label_date.isoformat(), effective_start=iso(v.interval.start),
            effective_end=iso(v.interval.end), status=v.status)  # type: ignore[arg-type]
        for v in read.intervals])


def _opt(row, name: str) -> str | None:
    value = text(row.get(name))
    return value or None


@router.get("/vehicles/{vehicle_id}/crew-assignment-history", response_model=VehicleCrewHistoryResponse)
async def get_vehicle_crew_assignment_history(
    vehicle_id: str,
    context: RequestContext = Depends(get_current_context),
    service: CrewAssignmentService = Depends(get_crew_assignment_service),
) -> VehicleCrewHistoryResponse:
    require_trusted_reader(context, _READ_TH)
    read = await service.vehicle_history(vehicle_id)
    return VehicleCrewHistoryResponse(
        vehicle_id=read.vehicle_id,
        events=[CrewHistoryEventResponse(event_id=a.event_id, lifecycle=a.lifecycle,  # type: ignore[arg-type]
                                         revision_no=a.revision_no, head_record_id=a.head_record_id,
                                         personnel_id=a.personnel_id) for a in read.assignments],
        records=[CrewHistoryRecordResponse(
            record_id=text(r.get("record_id")), operation_id=text(r.get("operation_id")),
            record_kind=text(r.get("record_kind")), entry_operation=text(r.get("entry_operation")),
            event_id=text(r.get("event_id")), revision_no=text(r.get("revision_no")),
            supersedes_record_id=_opt(r, "supersedes_record_id"), personnel_id=_opt(r, "personnel_id"),
            crew_role=_opt(r, "crew_role"), crew_role_note_th=_opt(r, "crew_role_note_th"), mode=_opt(r, "mode"),
            start_date=_opt(r, "start_date"), end_date=_opt(r, "end_date"),
            shift_start_time=_opt(r, "shift_start_time"), shift_end_time=_opt(r, "shift_end_time"),
            shift_end_day_offset=_opt(r, "shift_end_day_offset"),
            excluded_dates=[d.isoformat() for d in parse_dates(r.get("excluded_dates")) or []],
            early_end_at=_opt(r, "early_end_at"), reason_th=_opt(r, "reason_th"),
            recorded_at=text(r.get("recorded_at")), recorded_by=text(r.get("recorded_by")),
            request_id=text(r.get("request_id"))) for r in read.records])


@router.get("/resource-calendar", response_model=ResourceCalendarResponse)
async def get_resource_calendar(
    date_from: str = Query(alias="from"),
    date_to: str = Query(alias="to"),
    view: str = Query(default="BOTH"),
    vehicle_id: str | None = Query(default=None, min_length=1, max_length=100),
    personnel_id: str | None = Query(default=None, min_length=1, max_length=100),
    branch_id: str | None = Query(default=None, min_length=1, max_length=100),
    context: RequestContext = Depends(get_current_context),
    service: ResourceCalendarService = Depends(get_resource_calendar_service),
) -> ResourceCalendarResponse:
    if not (context.user_id or "").strip():
        raise _forbidden("ACCESS_ACTOR_NOT_VERIFIED", f"{_CALENDAR_TH} requires a trusted, authenticated actor")
    require_any_capability(context, (CAN_ASSIGN_CRANE_DRIVER, CAN_ASSIGN_CRANE_CREW), _CALENDAR_TH)
    lo, hi = parse_date(date_from), parse_date(date_to)
    if lo is None or hi is None:
        raise error("CALENDAR_WINDOW_INVALID", "from / to must be calendar dates YYYY-MM-DD", 422,
                    {"field": "from" if lo is None else "to"})
    read = await service.calendar(date_from=lo, date_to=hi, view=view, vehicle_id=vehicle_id,
                                  personnel_id=personnel_id, branch_id=branch_id)
    return ResourceCalendarResponse(
        view=read.view, date_from=read.date_from.isoformat(), date_to=read.date_to.isoformat(),  # type: ignore[arg-type]
        time_zone="Asia/Bangkok",
        entries=[CalendarEntryResponse(
            kind=e.kind, event_id=e.event_id, vehicle_id=e.vehicle_id, machine_no=e.machine_no or None,  # type: ignore[arg-type]
            personnel_id=e.personnel_id, personnel_name=e.personnel_name or None, driver_id=e.driver_id,
            driver_name=e.driver_name, identity=e.identity, role=e.role, role_note_th=e.role_note_th,  # type: ignore[arg-type]
            mode=e.mode, label_date=e.label_date.isoformat(), effective_start=iso(e.start),  # type: ignore[arg-type]
            effective_end=iso(e.end), status=e.status) for e in read.entries],  # type: ignore[arg-type]
        conflicts=[CalendarConflictResponse(code=c.code, first_event_id=c.first.event_id,  # type: ignore[arg-type]
                                            second_event_id=c.second.event_id,
                                            personnel_id=c.first.personnel_id or c.second.personnel_id)
                   for c in read.conflicts])


__all__ = ["router"]
