"""R2 Batch R2d — responsible-branch writes for workshop equipment (history-only):
- POST /equipment/{equipment_id}/branch-assignments                              (can_transfer_equipment_branch)
- POST /equipment/{equipment_id}/branch-history/insertions                       (can_correct_branch_history)
- POST /equipment/{equipment_id}/branch-history/events/{event_id}/corrections    (can_correct_branch_history)
- POST /equipment/{equipment_id}/branch-history/events/{event_id}/cancellations  (can_correct_branch_history)
No equipment projection reconciliation route: no equipment projection exists.
Order (as the R1 vehicle routes): the capability dependency (403), then the
client `X-Request-Id` dependency (422 REQUEST_ID_REQUIRED), then the body
parsed here (422 VALIDATION_ERROR) — all three with zero repository calls.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.v1.equipment_branch_write_schemas import (
    EquipmentBranchAssignmentRequest,
    EquipmentBranchCancellationRequest,
    EquipmentBranchChangedResponse,
    EquipmentBranchCorrectionRequest,
    EquipmentBranchInsertionRequest,
    EquipmentBranchReplayResponse,
)
from app.api.v1.registry_mutation_body import (
    effective_test_batch_id,
    openapi_body,
    parse_body,
)
from app.api.v1.registry_schemas import BranchNoOpResponse
from app.api.v1.request_id_dependency import (
    require_capability_dependency,
    require_client_request_id,
)
from app.config import Settings
from app.context import RequestContext
from app.dependencies import get_repository, get_settings_dependency
from app.domain.authz import CAN_CORRECT_BRANCH_HISTORY, CAN_TRANSFER_EQUIPMENT_BRANCH
from app.domain.equipment_branch_write_service import (
    EquipmentBranchWriteOutcome,
    EquipmentBranchWriteService,
)
from app.repositories.base import Repository

router = APIRouter(tags=["equipment"])

_require_assign = require_capability_dependency(
    CAN_TRANSFER_EQUIPMENT_BRANCH, "การกำหนด/ย้ายสาขาของเครื่องมือ (equipment branch assignment)"
)
_require_correct = require_capability_dependency(
    CAN_CORRECT_BRANCH_HISTORY, "การแก้ไขประวัติสาขา (branch history correction)"
)


def get_equipment_branch_write_service(
    repository: Repository = Depends(get_repository),
    settings: Settings = Depends(get_settings_dependency),
) -> EquipmentBranchWriteService:
    return EquipmentBranchWriteService(
        repository, settings.registry_context_effective, effective_test_batch_id(settings)
    )


def _respond(outcome: EquipmentBranchWriteOutcome) -> JSONResponse:
    if outcome.replayed:
        body: BaseModel = EquipmentBranchReplayResponse(
            request_id=outcome.request_id, replayed=True, record_ids=list(outcome.record_ids)
        )
    elif not outcome.changed:
        body = BranchNoOpResponse(request_id=outcome.request_id, changed=False, warnings=[])
    else:
        body = EquipmentBranchChangedResponse(
            request_id=outcome.request_id,
            changed=True,
            record_id=outcome.record_id or "",
            event_id=outcome.event_id,
            timeline_status_after=outcome.timeline_status_after,  # type: ignore[arg-type]
            current_branch_id=outcome.current_branch_id,
            current_source=outcome.current_source,  # type: ignore[arg-type]
        )
    return JSONResponse(content=body.model_dump(mode="json"))


def _responses(extra_409: str, extra_422: str, extra_404: str = "EQUIPMENT_NOT_FOUND.") -> dict[int | str, dict[str, Any]]:
    return {
        200: {"model": EquipmentBranchChangedResponse, "description": "changed / no-op (changed:false) / replayed"},
        403: {"description": "HTTP_ERROR — the caller lacks the capability. Zero repository calls."},
        404: {"description": extra_404},
        409: {"description": f"{extra_409}; REQUEST_ID_REUSED; EQUIPMENT_ID_AMBIGUOUS."},
        422: {"description": f"REQUEST_ID_REQUIRED; VALIDATION_ERROR; {extra_422}"},
        500: {
            "description": "EQUIPMENT_MASTER_SCHEMA_INVALID / EQUIPMENT_MASTER_DATA_INVALID / "
            "BRANCH_HISTORY_SCHEMA_INVALID / BRANCH_HISTORY_DATA_INVALID {issues} / BRANCH_MASTER_SCHEMA_INVALID / "
            "BRANCH_MASTER_DATA_INVALID. INTERNAL_ERROR proves nothing about writes."
        },
        503: {
            "description": "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED; *_READ_FAILED; BRANCH_HISTORY_WRITE_FAILED "
            "{history_write_outcome, request_id} (history only: there is no second write)."
        },
    }


_TIME_422 = (
    "EFFECTIVE_MODE_INVALID; EFFECTIVE_MODE_NOT_ALLOWED; EFFECTIVE_TIME_OFFSET_REQUIRED; EFFECTIVE_TIME_PRECISION; "
    "FUTURE_EFFECTIVE_NOT_ALLOWED; EFFECTIVE_TIME_OUT_OF_RANGE; BRANCH_NOT_FOUND; BRANCH_INACTIVE"
)


@router.post(
    "/equipment/{equipment_id}/branch-assignments",
    response_model=None,
    responses=_responses(
        "BRANCH_HISTORY_STALE {field}; BRANCH_TIMELINE_AMBIGUOUS; BRANCH_EVENT_SAME_INSTANT; "
        "BRANCH_TRANSFER_NOT_LATEST",
        _TIME_422,
    ),
    openapi_extra=openapi_body(EquipmentBranchAssignmentRequest),
)
async def assign_equipment_branch(
    equipment_id: str,
    request: Request,
    context: RequestContext = Depends(_require_assign),
    request_id: str = Depends(require_client_request_id),
    service: EquipmentBranchWriteService = Depends(get_equipment_branch_write_service),
) -> JSONResponse:
    _parsed, body = await parse_body(request, EquipmentBranchAssignmentRequest)
    return _respond(await service.assign(equipment_id, body, request_id=request_id, user_id=context.user_id or ""))


@router.post(
    "/equipment/{equipment_id}/branch-history/insertions",
    response_model=None,
    responses=_responses(
        "BRANCH_HISTORY_STALE; BRANCH_TIMELINE_AMBIGUOUS; BRANCH_EVENT_SAME_INSTANT; BRANCH_INSERTION_NOT_HISTORICAL",
        f"REASON_REQUIRED; {_TIME_422}",
    ),
    openapi_extra=openapi_body(EquipmentBranchInsertionRequest),
)
async def insert_equipment_branch_event(
    equipment_id: str,
    request: Request,
    context: RequestContext = Depends(_require_correct),
    request_id: str = Depends(require_client_request_id),
    service: EquipmentBranchWriteService = Depends(get_equipment_branch_write_service),
) -> JSONResponse:
    _parsed, body = await parse_body(request, EquipmentBranchInsertionRequest)
    return _respond(await service.insert(equipment_id, body, request_id=request_id, user_id=context.user_id or ""))


@router.post(
    "/equipment/{equipment_id}/branch-history/events/{event_id}/corrections",
    response_model=None,
    responses=_responses(
        "BRANCH_HISTORY_STALE {field}; BRANCH_EVENT_CANCELLED; BRANCH_EVENT_SAME_INSTANT; "
        "BRANCH_TIMELINE_AMBIGUOUS (target not tied, or the source at the new instant is not uniquely derivable)",
        f"REASON_REQUIRED; {_TIME_422}",
        "EQUIPMENT_NOT_FOUND; BRANCH_EVENT_NOT_FOUND.",
    ),
    openapi_extra=openapi_body(EquipmentBranchCorrectionRequest),
)
async def correct_equipment_branch_event(
    equipment_id: str,
    event_id: str,
    request: Request,
    context: RequestContext = Depends(_require_correct),
    request_id: str = Depends(require_client_request_id),
    service: EquipmentBranchWriteService = Depends(get_equipment_branch_write_service),
) -> JSONResponse:
    _parsed, body = await parse_body(request, EquipmentBranchCorrectionRequest)
    return _respond(
        await service.correct(equipment_id, event_id, body, request_id=request_id, user_id=context.user_id or "")
    )


@router.post(
    "/equipment/{equipment_id}/branch-history/events/{event_id}/cancellations",
    response_model=None,
    responses=_responses(
        "BRANCH_HISTORY_STALE {field}; BRANCH_EVENT_CANCELLED; BRANCH_TIMELINE_AMBIGUOUS (target not tied)",
        "REASON_REQUIRED",
        "EQUIPMENT_NOT_FOUND; BRANCH_EVENT_NOT_FOUND.",
    ),
    openapi_extra=openapi_body(EquipmentBranchCancellationRequest),
)
async def cancel_equipment_branch_event(
    equipment_id: str,
    event_id: str,
    request: Request,
    context: RequestContext = Depends(_require_correct),
    request_id: str = Depends(require_client_request_id),
    service: EquipmentBranchWriteService = Depends(get_equipment_branch_write_service),
) -> JSONResponse:
    _parsed, body = await parse_body(request, EquipmentBranchCancellationRequest)
    return _respond(
        await service.cancel(equipment_id, event_id, body, request_id=request_id, user_id=context.user_id or "")
    )
