"""R2 Batch R2-C1 — E2 operational driver assignment routes (Mock/TEST only; no DELETE):
- GET  /vehicles/{vehicle_id}/operational-driver-assignments          schedule, current state, warnings (can_view)
- GET  /vehicles/{vehicle_id}/operational-driver-assignment-history   every stored row and revision (can_view)
- GET  /drivers/{driver_id}/operational-driver-assignments            the driver axis across vehicles (can_view)
- POST /vehicles/{vehicle_id}/operational-driver-assignment-operations
       CREATE / REVISE / SUBSTITUTE / CANCEL / EARLY_END (can_assign_crane_driver)
The schedule GETs take the optional G-1 filters `from` / `to` (inclusive
Bangkok dates) and `mode`. Write order: the capability (403), the client
`X-Request-Id` (422 REQUEST_ID_REQUIRED), then the body (422) — all with zero
repository calls. Separate from R2f-f (`responsible-driver*`), the Personnel ↔
Driver link and the Phase 6 Driver / vehicle_driver routes, none of which is
changed. E2 REAL writes are refused before R11 (O1); the Google Sheets
repository answers 501 FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE before any
workbook request (DQ-1).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.v1.operational_driver_assignment_schemas import (
    ConflictResponse,
    DriverScheduleResponse,
    HistoryEventResponse,
    HistoryRecordResponse,
    IntervalResponse,
    OperationChangedResponse,
    OperationNoOpResponse,
    OperationReplayResponse,
    OperationRequest,
    UnknownResponse,
    VehicleHistoryResponse,
    VehicleScheduleResponse,
    WarningResponse,
)
from app.api.v1.registry_mutation_body import effective_test_batch_id, openapi_body, parse_body
from app.api.v1.request_id_dependency import require_capability_dependency, require_client_request_id
from app.config import Settings
from app.context import RequestContext
from app.dependencies import get_current_context, get_repository, get_settings_dependency
from app.domain.authz import CAN_ASSIGN_CRANE_DRIVER, CAN_VIEW, require_capability
from app.domain.operational_driver_assignment import (
    OperationalDriverAssignmentService,
    OperationOutcome,
    Warning,
)
from app.domain.operational_driver_timeline import (
    MODES,
    TRUE,
    Conflict,
    Interval,
    iso,
    parse_date,
    parse_dates,
)
from app.domain.registration import text
from app.domain.registry_write_support import error
from app.repositories.base import Repository

router = APIRouter(tags=["operational-driver-assignment"])

_require_assign = require_capability_dependency(
    CAN_ASSIGN_CRANE_DRIVER, "การมอบหมายผู้ขับปฏิบัติงาน (E2 operational driver assignment)"
)


def get_operational_driver_assignment_service(
    repository: Repository = Depends(get_repository),
    settings: Settings = Depends(get_settings_dependency),
) -> OperationalDriverAssignmentService:
    return OperationalDriverAssignmentService(repository, settings.registry_context_effective,
                                              effective_test_batch_id(settings))


def _warning(w: Warning) -> WarningResponse:
    return WarningResponse(code=w.code, event_id=w.event_id, driver_id=w.driver_id, vehicle_id=w.vehicle_id,
                           related_event_id=w.related_event_id)


def _interval(i: Interval) -> IntervalResponse:
    return IntervalResponse(event_id=i.event_id, revision_no=i.revision_no, vehicle_id=i.vehicle_id,
                            assigned_driver_id=i.driver_id, mode=i.mode, label_date=i.label_date.isoformat(),
                            effective_start=iso(i.start), effective_end=iso(i.end))


def _conflict(c: Conflict) -> ConflictResponse:
    return ConflictResponse(axis=c.axis, key=c.key, first=_interval(c.first),  # type: ignore[arg-type]
                            second=_interval(c.second))


def _filters(date_from: str | None, date_to: str | None, mode: str | None):
    parsed = []
    for name, raw in (("from", date_from), ("to", date_to)):
        value = parse_date(raw) if raw is not None else None
        if raw is not None and value is None:
            raise error("E2_DATE_INVALID", f"{name} must be a calendar date YYYY-MM-DD", 422, {"field": name})
        parsed.append(value)
    if parsed[0] and parsed[1] and parsed[1] < parsed[0]:
        raise error("E2_RANGE_INVALID", "to must not be before from", 422, {"field": "to"})
    if mode is not None and mode not in MODES:
        raise error("E2_MODE_INVALID", "mode must be FULL_DAY, DAY_SHIFT or NIGHT_SHIFT", 422, {"field": "mode"})
    return parsed[0], parsed[1], mode


def _respond(outcome: OperationOutcome) -> JSONResponse:
    body: BaseModel
    if outcome.replayed:
        body = OperationReplayResponse(request_id=outcome.request_id, replayed=True,
                                       operation_id=outcome.operation_id or "", record_ids=list(outcome.record_ids),
                                       event_ids=list(outcome.event_ids))
    elif not outcome.changed:
        body = OperationNoOpResponse(request_id=outcome.request_id, changed=False,
                                     existing_event_id=outcome.existing_event_id)
    else:
        body = OperationChangedResponse(request_id=outcome.request_id, changed=True,
                                        operation_id=outcome.operation_id or "", record_ids=list(outcome.record_ids),
                                        event_ids=list(outcome.event_ids),
                                        warnings=[_warning(w) for w in outcome.warnings])
    return JSONResponse(content=body.model_dump(mode="json"))


_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"model": OperationChangedResponse,
          "description": "changed / no-op or duplicate {request_id, changed:false, existing_event_id} / "
                         "replayed {request_id, replayed, operation_id, record_ids, event_ids}"},
    403: {"description": "HTTP_ERROR — the caller lacks can_assign_crane_driver. Zero repository calls."},
    404: {"description": "VEHICLE_NOT_FOUND; E2_ASSIGNMENT_NOT_FOUND."},
    409: {"description": "E2_REAL_WRITES_NOT_ENABLED; E2_VEHICLE_CONFLICT / E2_DRIVER_CONFLICT {axis, "
                         "conflicting_event_id, first, second}; E2_ASSIGNMENT_STALE; E2_ASSIGNMENT_CANCELLED / "
                         "_VOIDED / _ALREADY_STARTED / _NOT_STARTED / _ALREADY_ENDED; E2_HANDOVER_NOT_PERMITTED / "
                         "_INVALIDATED; E2_SUBSTITUTION_UNIT_INVALID; E2_TIMELINE_CONFLICTED; E2_CONCURRENT_CHANGE; "
                         "REQUEST_ID_REUSED; VEHICLE_ID_AMBIGUOUS; DRIVER_ID_AMBIGUOUS; DRIVER_PERSONNEL_AMBIGUOUS."},
    422: {"description": "REQUEST_ID_REQUIRED; VALIDATION_ERROR; REASON_REQUIRED; E2_DATE_INVALID; "
                         "E2_TIME_INVALID; E2_RANGE_INVALID; E2_RANGE_TOO_LONG {limit}; E2_SHIFT_*; "
                         "E2_SPLIT_INVALID; E2_EARLY_END_INVALID; E2_SUBSTITUTION_DRIVER_UNCHANGED; "
                         "VEHICLE_SCOPE_UNPROVEN; DRIVER_NOT_FOUND; DRIVER_SCOPE_UNPROVEN; DRIVER_NOT_ACTIVE; "
                         "PERSONNEL_NOT_ACTIVE."},
    500: {"description": "E2_HISTORY_DATA_INVALID {issues}; VEHICLE_MASTER_SCHEMA_INVALID; "
                         "DRIVER_MASTER_SCHEMA_INVALID; PERSONNEL_MASTER_*."},
    501: {"description": "FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE (Google Sheets: E2 is Mock/TEST only)."},
    503: {"description": "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED; *_READ_FAILED; "
                         "E2_HISTORY_WRITE_FAILED {history_write_outcome, request_id}."},
}


@router.post("/vehicles/{vehicle_id}/operational-driver-assignment-operations", response_model=None,
             responses=_RESPONSES, openapi_extra=openapi_body(OperationRequest))
async def apply_operational_driver_assignment_operation(
    vehicle_id: str,
    request: Request,
    context: RequestContext = Depends(_require_assign),
    request_id: str = Depends(require_client_request_id),
    service: OperationalDriverAssignmentService = Depends(get_operational_driver_assignment_service),
) -> JSONResponse:
    _parsed, body = await parse_body(request, OperationRequest)
    outcome = await service.apply(vehicle_id, body, request_id=request_id, user_id=context.user_id or "")
    return _respond(outcome)


@router.get("/vehicles/{vehicle_id}/operational-driver-assignments", response_model=VehicleScheduleResponse)
async def get_vehicle_operational_driver_assignments(
    vehicle_id: str,
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
    mode: str | None = Query(default=None),
    context: RequestContext = Depends(get_current_context),
    service: OperationalDriverAssignmentService = Depends(get_operational_driver_assignment_service),
) -> VehicleScheduleResponse:
    require_capability(context, CAN_VIEW, "ผู้ขับปฏิบัติงานของรถ (vehicle operational driver assignments)")
    lo, hi, m = _filters(date_from, date_to, mode)
    read = await service.vehicle_schedule(vehicle_id, date_from=lo, date_to=hi, mode=m)
    return VehicleScheduleResponse(
        vehicle_id=read.vehicle_id,
        timeline_status=read.timeline_status,  # type: ignore[arg-type]
        current_status=read.current_status,  # type: ignore[arg-type]
        current=_interval(read.current) if read.current else None,
        intervals=[_interval(i) for i in read.intervals],
        unknown=[UnknownResponse(vehicle_id=u.vehicle_id, start=iso(u.start), end=iso(u.end),
                                 handover_event_id=u.handover_event_id) for u in read.unknown],
        conflicts=[_conflict(c) for c in read.conflicts],
        warnings=[_warning(w) for w in read.warnings],
    )


@router.get("/drivers/{driver_id}/operational-driver-assignments", response_model=DriverScheduleResponse)
async def get_driver_operational_driver_assignments(
    driver_id: str,
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
    mode: str | None = Query(default=None),
    context: RequestContext = Depends(get_current_context),
    service: OperationalDriverAssignmentService = Depends(get_operational_driver_assignment_service),
) -> DriverScheduleResponse:
    require_capability(context, CAN_VIEW, "การมอบหมายผู้ขับปฏิบัติงานของผู้ขับ (driver operational assignments)")
    lo, hi, m = _filters(date_from, date_to, mode)
    read = await service.driver_schedule(driver_id, date_from=lo, date_to=hi, mode=m)
    return DriverScheduleResponse(
        driver_id=read.driver_id,
        timeline_status=read.timeline_status,  # type: ignore[arg-type]
        intervals=[_interval(i) for i in read.intervals],
        conflicts=[_conflict(c) for c in read.conflicts],
        warnings=[_warning(w) for w in read.warnings],
    )


def _opt(row, name: str) -> str | None:
    value = text(row.get(name))
    return value or None


@router.get("/vehicles/{vehicle_id}/operational-driver-assignment-history", response_model=VehicleHistoryResponse)
async def get_vehicle_operational_driver_assignment_history(
    vehicle_id: str,
    context: RequestContext = Depends(get_current_context),
    service: OperationalDriverAssignmentService = Depends(get_operational_driver_assignment_service),
) -> VehicleHistoryResponse:
    require_capability(context, CAN_VIEW, "ประวัติการมอบหมายผู้ขับปฏิบัติงาน (operational assignment history)")
    read = await service.vehicle_history(vehicle_id)
    events = [HistoryEventResponse(event_id=a.event_id, kind="ASSIGNMENT", lifecycle=a.lifecycle,  # type: ignore
                                   revision_no=a.revision_no, head_record_id=a.head_record_id)
              for a in read.assignments]
    events += [HistoryEventResponse(event_id=h.event_id, kind="HANDOVER",
                                    lifecycle="IN_FORCE" if h.in_force else "CANCELLED",
                                    revision_no=h.revision_no, head_record_id=h.head_record_id)
               for h in read.handovers]
    records = [
        HistoryRecordResponse(
            record_id=text(r.get("record_id")), operation_id=text(r.get("operation_id")),
            record_kind=text(r.get("record_kind")), entry_operation=text(r.get("entry_operation")),
            event_id=text(r.get("event_id")), revision_no=text(r.get("revision_no")),
            supersedes_record_id=_opt(r, "supersedes_record_id"), assigned_driver_id=_opt(r, "driver_id"),
            mode=_opt(r, "mode"), start_date=_opt(r, "start_date"), end_date=_opt(r, "end_date"),
            shift_start_time=_opt(r, "shift_start_time"), shift_end_time=_opt(r, "shift_end_time"),
            shift_end_day_offset=_opt(r, "shift_end_day_offset"),
            excluded_dates=[d.isoformat() for d in parse_dates(r.get("excluded_dates")) or []],
            related_event_id=_opt(r, "related_event_id"), relation=_opt(r, "relation"),
            early_end_at=_opt(r, "early_end_at"), voided=text(r.get("voided")) == TRUE,
            handover_kind=_opt(r, "handover_kind"), predecessor_event_id=_opt(r, "predecessor_event_id"),
            predecessor_revision_no=_opt(r, "predecessor_revision_no"),
            successor_event_id=_opt(r, "successor_event_id"), successor_revision_no=_opt(r, "successor_revision_no"),
            handover_at=_opt(r, "handover_at"), unknown_start_at=_opt(r, "unknown_start_at"),
            unknown_end_at=_opt(r, "unknown_end_at"), reason_th=_opt(r, "reason_th"),
            recorded_at=text(r.get("recorded_at")), recorded_by=text(r.get("recorded_by")),
            request_id=text(r.get("request_id")),
        )
        for r in read.records
    ]
    return VehicleHistoryResponse(vehicle_id=read.vehicle_id, events=events, records=records)


__all__ = ["router"]
