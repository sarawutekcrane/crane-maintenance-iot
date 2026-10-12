"""R2 Batch R2f-h1 — V2 technician assignment routes (append-only, no delete):
- POST /repairs/{repair_id}/technician-assignments                 (can_manage_repair)
- GET  /repairs/{repair_id}/technician-assignments                 current set + set history (can_view)
- POST /pm/work-orders/{pm_work_order_id}/technician-assignments   (can_manage_pm)
- GET  /pm/work-orders/{pm_work_order_id}/technician-assignments   (can_view)
V2 jobs only: a legacy job is refused with 409 ASSIGNMENT_MODEL_MISMATCH (and
the legacy `/assign` and `/assignment-history` routes refuse V2 jobs). Write
order: the capability (403), the client `X-Request-Id` (422
REQUEST_ID_REQUIRED), then the body (422) — all with zero repository calls.
No role or capability grant is added: the existing management capabilities
are reused unchanged (C1 §16).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.v1.registry_mutation_body import openapi_body, parse_body
from app.api.v1.request_id_dependency import require_capability_dependency, require_client_request_id
from app.api.v1.technician_assignment_schemas import (
    AssignmentSetResponse,
    TechnicianAssignmentChangedResponse,
    TechnicianAssignmentNoOpResponse,
    TechnicianAssignmentReplayResponse,
    TechnicianAssignmentRequest,
    TechnicianAssignmentsResponse,
)
from app.config import Settings
from app.context import RequestContext
from app.dependencies import get_current_context, get_repository, get_settings_dependency
from app.domain.authz import CAN_MANAGE_PM, CAN_MANAGE_REPAIR, CAN_VIEW, require_capability
from app.domain.technician_assignment import (
    PM,
    REPAIR,
    AssignmentOutcome,
    AssignmentSet,
    TechnicianAssignmentService,
    WorkKind,
    cutover_from_settings,
)
from app.repositories.base import Repository

router = APIRouter(tags=["technician-assignment"])

_require_repair = require_capability_dependency(
    CAN_MANAGE_REPAIR, "การมอบหมายช่างซ่อม V2 (V2 repair technician assignment)"
)
_require_pm = require_capability_dependency(
    CAN_MANAGE_PM, "การมอบหมายทีมช่าง PM V2 (V2 PM technician assignment)"
)


def get_technician_assignment_service(
    repository: Repository = Depends(get_repository),
    settings: Settings = Depends(get_settings_dependency),
) -> TechnicianAssignmentService:
    return TechnicianAssignmentService(repository, cutover_from_settings(settings))


def _set(value: AssignmentSet) -> AssignmentSetResponse:
    return AssignmentSetResponse(
        assignment_set_id=value.set_id, assigned_at=value.assigned_at, assigned_by_user_id=value.assigned_by_user_id,
        primary_technician_id=value.primary_technician_id,
        collaborator_technician_ids=list(value.collaborator_technician_ids), reason_th=value.reason_th or None,
        record_ids=list(value.record_ids),
    )


def _respond(outcome: AssignmentOutcome) -> JSONResponse:
    body: BaseModel
    if outcome.replayed:
        body = TechnicianAssignmentReplayResponse(request_id=outcome.request_id, replayed=True,
                                                  record_ids=list(outcome.record_ids))
    elif not outcome.changed:
        body = TechnicianAssignmentNoOpResponse(request_id=outcome.request_id, changed=False)
    else:
        assert outcome.current is not None
        body = TechnicianAssignmentChangedResponse(request_id=outcome.request_id, changed=True,
                                                   record_ids=list(outcome.record_ids), current=_set(outcome.current))
    return JSONResponse(content=body.model_dump(mode="json"))


_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"model": TechnicianAssignmentChangedResponse,
          "description": "changed / no-op {request_id, changed:false} / replayed {request_id, replayed, record_ids}"},
    403: {"description": "HTTP_ERROR — the caller lacks the management capability. Zero repository calls."},
    404: {"description": "REPAIR_NOT_FOUND / PM_WORK_ORDER_NOT_FOUND."},
    409: {"description": "ASSIGNMENT_MODEL_MISMATCH; TECHNICIAN_ASSIGNMENT_LIVE_TEST_UNSUPPORTED; "
                         "TECHNICIAN_ASSIGNMENT_SCOPE_MISMATCH; TECHNICIAN_ASSIGNMENT_ORDER_AMBIGUOUS; "
                         "TECHNICIAN_ASSIGNMENT_STALE; REQUEST_ID_REUSED; TECHNICIAN_ID_AMBIGUOUS; "
                         "TECHNICIAN_PERSONNEL_AMBIGUOUS."},
    422: {"description": "REQUEST_ID_REQUIRED; VALIDATION_ERROR; REASON_REQUIRED; "
                         "TECHNICIAN_ASSIGNMENT_PRIMARY_REQUIRED; TECHNICIAN_ASSIGNMENT_DUPLICATE_ASSIGNEE; "
                         "TECHNICIAN_NOT_FOUND; TECHNICIAN_SCOPE_UNPROVEN; TECHNICIAN_NOT_ACTIVE; "
                         "TECHNICIAN_PERSONNEL_UNRESOLVED; PERSONNEL_NOT_ACTIVE."},
    500: {"description": "ASSIGNMENT_MODEL_DATA_INVALID; TECHNICIAN_ASSIGNMENT_JOB_DATA_INVALID; "
                         "TECHNICIAN_ASSIGNMENT_SCHEMA_INVALID; TECHNICIAN_ASSIGNMENT_DATA_INVALID {issues}; "
                         "TECHNICIAN_MASTER_SCHEMA_INVALID; PERSONNEL_MASTER_SCHEMA_INVALID / _DATA_INVALID."},
    503: {"description": "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED; *_READ_FAILED; TECHNICIAN_ASSIGNMENT_WRITE_FAILED "
                         "{write_outcome, request_id}."},
}


async def _assign(kind: WorkKind, job_id: str, request: Request, context: RequestContext, request_id: str,
                  service: TechnicianAssignmentService) -> JSONResponse:
    _parsed, body = await parse_body(request, TechnicianAssignmentRequest)
    outcome = await service.assign(kind, job_id, body, request_id=request_id, user_id=context.user_id or "")
    return _respond(outcome)


async def _read(kind: WorkKind, job_id: str, context: RequestContext,
                service: TechnicianAssignmentService) -> TechnicianAssignmentsResponse:
    require_capability(context, CAN_VIEW, "การมอบหมายช่าง V2 (V2 technician assignment)")
    read = await service.read(kind, job_id)
    state = read.state
    return TechnicianAssignmentsResponse(
        job_id=read.job_id, assignment_model="TECHNICIAN_V2", status=state.status,  # type: ignore[arg-type]
        current=_set(state.current) if state.current else None, sets=[_set(s) for s in state.sets],
    )


@router.post("/repairs/{repair_id}/technician-assignments", response_model=None, responses=_RESPONSES,
             openapi_extra=openapi_body(TechnicianAssignmentRequest))
async def assign_repair_technicians(
    repair_id: str,
    request: Request,
    context: RequestContext = Depends(_require_repair),
    request_id: str = Depends(require_client_request_id),
    service: TechnicianAssignmentService = Depends(get_technician_assignment_service),
) -> JSONResponse:
    return await _assign(REPAIR, repair_id, request, context, request_id, service)


@router.get("/repairs/{repair_id}/technician-assignments", response_model=TechnicianAssignmentsResponse)
async def get_repair_technician_assignments(
    repair_id: str,
    context: RequestContext = Depends(get_current_context),
    service: TechnicianAssignmentService = Depends(get_technician_assignment_service),
) -> TechnicianAssignmentsResponse:
    return await _read(REPAIR, repair_id, context, service)


@router.post("/pm/work-orders/{pm_work_order_id}/technician-assignments", response_model=None,
             responses=_RESPONSES, openapi_extra=openapi_body(TechnicianAssignmentRequest))
async def assign_pm_technicians(
    pm_work_order_id: str,
    request: Request,
    context: RequestContext = Depends(_require_pm),
    request_id: str = Depends(require_client_request_id),
    service: TechnicianAssignmentService = Depends(get_technician_assignment_service),
) -> JSONResponse:
    return await _assign(PM, pm_work_order_id, request, context, request_id, service)


@router.get("/pm/work-orders/{pm_work_order_id}/technician-assignments", response_model=TechnicianAssignmentsResponse)
async def get_pm_technician_assignments(
    pm_work_order_id: str,
    context: RequestContext = Depends(get_current_context),
    service: TechnicianAssignmentService = Depends(get_technician_assignment_service),
) -> TechnicianAssignmentsResponse:
    return await _read(PM, pm_work_order_id, context, service)
