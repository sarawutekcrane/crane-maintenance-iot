"""R2 Batch R2f-g — Personnel department movement routes (history-only, no delete):
- GET  /personnel/{personnel_id}/department-history   current department, periods, optional as-of (can_view)
- POST /personnel/{personnel_id}/department-events    TRANSFER / INSERTION / CORRECTION / CANCELLATION
                                                       (can_move_personnel_department — GOVERNANCE PENDING:
                                                       held by NO role, so every caller is refused today)
Write order: the capability (403), the client `X-Request-Id` (422
REQUEST_ID_REQUIRED), then the body (422) — all with zero repository calls.
personnel_master.department is never read or written by these routes.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.v1.personnel_department_history_schemas import (
    DepartmentChangedResponse,
    DepartmentEventRequest,
    DepartmentNoOpResponse,
    DepartmentPeriodResponse,
    DepartmentReplayResponse,
    PersonnelDepartmentHistoryResponse,
)
from app.api.v1.registry_mutation_body import effective_test_batch_id, openapi_body, parse_body
from app.api.v1.request_id_dependency import require_capability_dependency, require_client_request_id
from app.config import Settings
from app.context import RequestContext
from app.dependencies import get_current_context, get_repository, get_settings_dependency
from app.domain.authz import CAN_MOVE_PERSONNEL_DEPARTMENT, CAN_VIEW, require_capability
from app.domain.personnel_department_history import DepartmentOutcome, PersonnelDepartmentHistoryService
from app.domain.registry_write_support import error
from app.repositories.base import Repository

router = APIRouter(tags=["personnel-department-history"])

_require_move = require_capability_dependency(
    CAN_MOVE_PERSONNEL_DEPARTMENT, "การย้ายแผนกของบุคลากร (personnel department movement)"
)


def get_personnel_department_history_service(
    repository: Repository = Depends(get_repository),
    settings: Settings = Depends(get_settings_dependency),
) -> PersonnelDepartmentHistoryService:
    return PersonnelDepartmentHistoryService(repository, settings.registry_context_effective,
                                             effective_test_batch_id(settings))


def _respond(outcome: DepartmentOutcome) -> JSONResponse:
    body: BaseModel
    if outcome.replayed:
        body = DepartmentReplayResponse(request_id=outcome.request_id, replayed=True,
                                        record_ids=list(outcome.record_ids))
    elif not outcome.changed:
        body = DepartmentNoOpResponse(request_id=outcome.request_id, changed=False)
    else:
        body = DepartmentChangedResponse(
            request_id=outcome.request_id, changed=True, record_id=outcome.record_id or "",
            event_id=outcome.event_id or "",
            timeline_status_after=outcome.timeline_status_after,  # type: ignore[arg-type]
            current_department_id=outcome.current_department_id,
        )
    return JSONResponse(content=body.model_dump(mode="json"))


_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"model": DepartmentChangedResponse,
          "description": "changed / no-op {request_id, changed:false} / replayed {request_id, replayed, record_ids}"},
    403: {"description": "HTTP_ERROR — the caller lacks can_move_personnel_department (GOVERNANCE PENDING: no "
                         "role holds it). Zero repository calls."},
    404: {"description": "PERSONNEL_NOT_FOUND (in the request's data scope); PERSONNEL_DEPARTMENT_EVENT_NOT_FOUND."},
    409: {"description": "PERSONNEL_ID_AMBIGUOUS; DEPARTMENT_ID_AMBIGUOUS; PERSONNEL_DEPARTMENT_HISTORY_STALE "
                         "{field}; PERSONNEL_DEPARTMENT_TIMELINE_AMBIGUOUS {reason}; PERSONNEL_DEPARTMENT_EVENT_SAME_"
                         "INSTANT / _EVENT_NOT_LATEST / _INSERTION_NOT_HISTORICAL / _EVENT_CANCELLED; "
                         "REQUEST_ID_REUSED."},
    422: {"description": "REQUEST_ID_REQUIRED; VALIDATION_ERROR; REASON_REQUIRED; EFFECTIVE_*; "
                         "PERSONNEL_DEPARTMENT_DEPARTMENT_REQUIRED; DEPARTMENT_NOT_FOUND; DEPARTMENT_SCOPE_UNPROVEN."},
    500: {"description": "PERSONNEL_MASTER_SCHEMA_INVALID / _DATA_INVALID; DEPARTMENT_MASTER_SCHEMA_INVALID / "
                         "_DATA_INVALID; PERSONNEL_DEPARTMENT_HISTORY_SCHEMA_INVALID / _DATA_INVALID {issues}."},
    503: {"description": "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED; *_READ_FAILED; PERSONNEL_DEPARTMENT_HISTORY_"
                         "WRITE_FAILED {history_write_outcome, request_id}."},
}


@router.post("/personnel/{personnel_id}/department-events", response_model=None, responses=_RESPONSES,
             openapi_extra=openapi_body(DepartmentEventRequest))
async def record_personnel_department_event(
    personnel_id: str,
    request: Request,
    context: RequestContext = Depends(_require_move),
    request_id: str = Depends(require_client_request_id),
    service: PersonnelDepartmentHistoryService = Depends(get_personnel_department_history_service),
) -> JSONResponse:
    _parsed, body = await parse_body(request, DepartmentEventRequest)
    outcome = await service.record_event(personnel_id, body, request_id=request_id, user_id=context.user_id or "")
    return _respond(outcome)


@router.get("/personnel/{personnel_id}/department-history", response_model=PersonnelDepartmentHistoryResponse)
async def get_personnel_department_history(
    personnel_id: str,
    as_of_date: str | None = Query(default=None, description="YYYY-MM-DD (00:00 Asia/Bangkok)"),
    as_of_at: str | None = Query(default=None, description="ISO 8601 with offset"),
    context: RequestContext = Depends(get_current_context),
    service: PersonnelDepartmentHistoryService = Depends(get_personnel_department_history_service),
) -> PersonnelDepartmentHistoryResponse:
    require_capability(context, CAN_VIEW, "ประวัติแผนกของบุคลากร (personnel department history)")
    if as_of_date is not None and as_of_at is not None:
        raise error("AS_OF_INVALID", "Give as_of_date or as_of_at, not both", 422)
    as_of = ({"mode": "DATE", "date": as_of_date} if as_of_date is not None
             else {"mode": "DATETIME", "at": as_of_at} if as_of_at is not None else None)
    read = await service.department_history(personnel_id, as_of)
    tl = read.timeline
    return PersonnelDepartmentHistoryResponse(
        personnel_id=read.personnel_id,
        timeline_status=tl.status,  # type: ignore[arg-type]
        current_status=tl.current_status,  # type: ignore[arg-type]
        current_department_id=tl.current_department_id,
        current_since=tl.current_since,
        as_of=read.as_of,
        as_of_status=read.as_of_status,  # type: ignore[arg-type]
        as_of_department_id=read.as_of_department_id,
        as_of_since=read.as_of_since,
        events=[
            DepartmentPeriodResponse(
                event_id=e.event_id, in_force=e.in_force, entry_operation=e.entry_operation,  # type: ignore[arg-type]
                revision_no=e.revision_no, head_record_id=e.head_record_id, department_id=e.department_id,
                effective_at=e.effective_at, effective_precision=e.effective_precision,
                derived_end_at=e.derived_end_at, recorded_at=e.recorded_at, recorded_by=e.recorded_by,
                notes=list(e.notes),
            )
            for e in tl.events
        ],
    )
