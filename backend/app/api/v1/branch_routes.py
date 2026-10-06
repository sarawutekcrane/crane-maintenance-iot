"""Phase 7 Batch 7O2c — responsible-branch mutations (contract Final Rev2 §3,
§6.1-§6.6; Outcome Classification Addendum; review clarifications C-c1..C-c7):

- POST /vehicles/{vehicle_id}/branch-transfers                         (can_transfer_vehicle_branch)
- POST /vehicles/{vehicle_id}/branch-history/insertions                (can_correct_branch_history)
- POST /vehicles/{vehicle_id}/branch-history/events/{event_id}/corrections    (can_correct_branch_history)
- POST /vehicles/{vehicle_id}/branch-history/events/{event_id}/cancellations  (can_correct_branch_history)
- POST /vehicles/{vehicle_id}/branch-projection/reconciliations        (can_transfer_vehicle_branch)

Order: the capability dependency (403), then the client `X-Request-Id`
dependency (422 REQUEST_ID_REQUIRED), then the body parsed here (422
VALIDATION_ERROR) — all three with zero repository calls.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.v1.registry_mutation_body import effective_test_batch_id, openapi_body, parse_body
from app.api.v1.registry_schemas import (
    BranchCancellationRequest,
    BranchChangedResponse,
    BranchCorrectionRequest,
    BranchInsertionRequest,
    BranchNoOpResponse,
    BranchProjectionReconciliationRequest,
    BranchReplayResponse,
    BranchTransferRequest,
)
from app.api.v1.request_id_dependency import require_capability_dependency, require_client_request_id
from app.config import Settings
from app.context import RequestContext
from app.dependencies import get_repository, get_settings_dependency
from app.domain.authz import CAN_CORRECT_BRANCH_HISTORY, CAN_TRANSFER_VEHICLE_BRANCH
from app.domain.branch_write_service import BranchWriteOutcome, BranchWriteService
from app.repositories.base import Repository

router = APIRouter(tags=["vehicle-registry"])

_require_transfer = require_capability_dependency(
    CAN_TRANSFER_VEHICLE_BRANCH, "การย้ายสาขาที่รับผิดชอบ (branch transfer)"
)
_require_correct = require_capability_dependency(
    CAN_CORRECT_BRANCH_HISTORY, "การแก้ไขประวัติสาขา (branch history correction)"
)


def get_branch_write_service(
    repository: Repository = Depends(get_repository),
    settings: Settings = Depends(get_settings_dependency),
) -> BranchWriteService:
    return BranchWriteService(repository, settings.registry_context_effective, effective_test_batch_id(settings))


def _respond(outcome: BranchWriteOutcome) -> JSONResponse:
    if outcome.replayed:
        body: BaseModel = BranchReplayResponse(
            request_id=outcome.request_id, replayed=True, record_ids=list(outcome.record_ids),
            consistency=outcome.consistency,  # type: ignore[arg-type]
        )
    elif not outcome.changed:
        body = BranchNoOpResponse(request_id=outcome.request_id, changed=False, warnings=[])
    else:
        body = BranchChangedResponse(
            request_id=outcome.request_id,
            changed=True,
            record_id=outcome.record_id or "",
            event_id=outcome.event_id,
            projection_write=outcome.projection_write,  # type: ignore[arg-type]
            timeline_status_after=outcome.timeline_status_after,  # type: ignore[arg-type]
            current_branch_id=outcome.current_branch_id,
            consistency=outcome.consistency,  # type: ignore[arg-type]
        )
    return JSONResponse(content=body.model_dump(mode="json"))


def _responses(extra_409: str, extra_422: str, extra_404: str = "VEHICLE_NOT_FOUND.") -> dict[int | str, dict[str, Any]]:
    return {
        200: {"model": BranchChangedResponse, "description": "changed / no-op (changed:false) / replayed"},
        403: {"description": "HTTP_ERROR — the caller lacks the capability. Zero repository calls."},
        404: {"description": extra_404},
        409: {"description": f"{extra_409}; REQUEST_ID_REUSED; VEHICLE_ID_AMBIGUOUS."},
        422: {"description": f"REQUEST_ID_REQUIRED; VALIDATION_ERROR; {extra_422}"},
        500: {
            "description": "VEHICLE_MASTER_SCHEMA_INVALID (incl. {problem: MISSING_HEADERS}) / VEHICLE_MASTER_DATA_INVALID / "
            "BRANCH_HISTORY_SCHEMA_INVALID / BRANCH_HISTORY_DATA_INVALID {issues} / BRANCH_MASTER_SCHEMA_INVALID / "
            "BRANCH_MASTER_DATA_INVALID. INTERNAL_ERROR proves nothing about writes."
        },
        503: {
            "description": "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED; *_READ_FAILED; BRANCH_HISTORY_WRITE_FAILED "
            "{history_write_outcome, projection_write: NOT_ATTEMPTED, request_id}; BRANCH_PROJECTION_WRITE_FAILED "
            "{event_recorded: true, record_id, projection_write_outcome, request_id}."
        },
    }


_TIME_422 = (
    "EFFECTIVE_MODE_INVALID; EFFECTIVE_MODE_NOT_ALLOWED; EFFECTIVE_TIME_OFFSET_REQUIRED; EFFECTIVE_TIME_PRECISION; "
    "FUTURE_EFFECTIVE_NOT_ALLOWED; EFFECTIVE_TIME_OUT_OF_RANGE; BRANCH_NOT_FOUND; BRANCH_INACTIVE"
)


@router.post(
    "/vehicles/{vehicle_id}/branch-transfers",
    response_model=None,
    responses=_responses(
        "BRANCH_HISTORY_STALE {field}; BRANCH_TIMELINE_AMBIGUOUS; BRANCH_PROJECTION_MISMATCH; "
        "BRANCH_EVENT_SAME_INSTANT; BRANCH_TRANSFER_NOT_LATEST",
        _TIME_422,
    ),
    openapi_extra=openapi_body(BranchTransferRequest),
)
async def transfer_branch(
    vehicle_id: str,
    request: Request,
    context: RequestContext = Depends(_require_transfer),
    request_id: str = Depends(require_client_request_id),
    service: BranchWriteService = Depends(get_branch_write_service),
) -> JSONResponse:
    _parsed, body = await parse_body(request, BranchTransferRequest)
    return _respond(await service.transfer(vehicle_id, body, request_id=request_id, user_id=context.user_id or ""))


@router.post(
    "/vehicles/{vehicle_id}/branch-history/insertions",
    response_model=None,
    responses=_responses(
        "BRANCH_HISTORY_STALE; BRANCH_TIMELINE_AMBIGUOUS; BRANCH_PROJECTION_MISMATCH; BRANCH_EVENT_SAME_INSTANT; "
        "BRANCH_INSERTION_NOT_HISTORICAL",
        f"REASON_REQUIRED; {_TIME_422}",
    ),
    openapi_extra=openapi_body(BranchInsertionRequest),
)
async def insert_branch_event(
    vehicle_id: str,
    request: Request,
    context: RequestContext = Depends(_require_correct),
    request_id: str = Depends(require_client_request_id),
    service: BranchWriteService = Depends(get_branch_write_service),
) -> JSONResponse:
    _parsed, body = await parse_body(request, BranchInsertionRequest)
    return _respond(await service.insert(vehicle_id, body, request_id=request_id, user_id=context.user_id or ""))


@router.post(
    "/vehicles/{vehicle_id}/branch-history/events/{event_id}/corrections",
    response_model=None,
    responses=_responses(
        "BRANCH_HISTORY_STALE {field}; BRANCH_PROJECTION_MISMATCH; BRANCH_EVENT_CANCELLED; BRANCH_EVENT_SAME_INSTANT; "
        "BRANCH_TIMELINE_AMBIGUOUS (target not tied, or the source at the new instant is not uniquely derivable)",
        f"REASON_REQUIRED; {_TIME_422}",
        "VEHICLE_NOT_FOUND; BRANCH_EVENT_NOT_FOUND.",
    ),
    openapi_extra=openapi_body(BranchCorrectionRequest),
)
async def correct_branch_event(
    vehicle_id: str,
    event_id: str,
    request: Request,
    context: RequestContext = Depends(_require_correct),
    request_id: str = Depends(require_client_request_id),
    service: BranchWriteService = Depends(get_branch_write_service),
) -> JSONResponse:
    _parsed, body = await parse_body(request, BranchCorrectionRequest)
    return _respond(
        await service.correct(vehicle_id, event_id, body, request_id=request_id, user_id=context.user_id or "")
    )


@router.post(
    "/vehicles/{vehicle_id}/branch-history/events/{event_id}/cancellations",
    response_model=None,
    responses=_responses(
        "BRANCH_HISTORY_STALE {field}; BRANCH_PROJECTION_MISMATCH; BRANCH_EVENT_CANCELLED; "
        "BRANCH_TIMELINE_AMBIGUOUS (target not tied)",
        "REASON_REQUIRED",
        "VEHICLE_NOT_FOUND; BRANCH_EVENT_NOT_FOUND.",
    ),
    openapi_extra=openapi_body(BranchCancellationRequest),
)
async def cancel_branch_event(
    vehicle_id: str,
    event_id: str,
    request: Request,
    context: RequestContext = Depends(_require_correct),
    request_id: str = Depends(require_client_request_id),
    service: BranchWriteService = Depends(get_branch_write_service),
) -> JSONResponse:
    _parsed, body = await parse_body(request, BranchCancellationRequest)
    return _respond(
        await service.cancel(vehicle_id, event_id, body, request_id=request_id, user_id=context.user_id or "")
    )


@router.post(
    "/vehicles/{vehicle_id}/branch-projection/reconciliations",
    response_model=None,
    responses=_responses("BRANCH_HISTORY_STALE {field}; BRANCH_TIMELINE_AMBIGUOUS", "REASON_REQUIRED; RELATED_REQUEST_NOT_FOUND"),
    openapi_extra=openapi_body(BranchProjectionReconciliationRequest),
)
async def reconcile_branch_projection(
    vehicle_id: str,
    request: Request,
    context: RequestContext = Depends(_require_transfer),
    request_id: str = Depends(require_client_request_id),
    service: BranchWriteService = Depends(get_branch_write_service),
) -> JSONResponse:
    _parsed, body = await parse_body(request, BranchProjectionReconciliationRequest)
    return _respond(await service.reconcile(vehicle_id, body, request_id=request_id, user_id=context.user_id or ""))
