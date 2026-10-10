"""R2 Batch R2f-e — Personnel ↔ Driver identity link routes (history-first, no delete):
- POST /personnel/{personnel_id}/driver-links            LINK / UNLINK / RELINK (can_link_personnel_driver)
- POST /personnel/{personnel_id}/driver-links/reconcile  recovery from MISMATCH  (can_link_personnel_driver)
- GET  /personnel/{personnel_id}/driver-links/history    link history            (can_view)
Order: the capability (403), the client `X-Request-Id` (422 REQUEST_ID_REQUIRED),
then the body (422) — all with zero repository calls. Identity-link maintenance
only: no crane / vehicle responsibility, no Driver master edit, no vehicle_driver
change, no ACTIVE gate. The Phase 6 Driver routes are unchanged.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.v1.personnel_link_schemas import (
    LinkNoOpResponse,
    LinkReplayResponse,
    PersonnelDriverLinkChangedResponse,
    PersonnelDriverLinkEventResponse,
    PersonnelDriverLinkHistoryResponse,
    PersonnelDriverLinkReconcileRequest,
    PersonnelDriverLinkRequest,
)
from app.api.v1.registry_mutation_body import effective_test_batch_id, openapi_body, parse_body
from app.api.v1.request_id_dependency import require_capability_dependency, require_client_request_id
from app.config import Settings
from app.context import RequestContext
from app.dependencies import get_current_context, get_repository, get_settings_dependency
from app.domain.authz import CAN_LINK_PERSONNEL_DRIVER, CAN_VIEW, require_capability
from app.domain.personnel_driver_link import personnel_driver_link_service
from app.domain.personnel_link import LinkOutcome, PersonnelLinkService
from app.repositories.base import Repository

router = APIRouter(tags=["personnel"])

_require_link = require_capability_dependency(
    CAN_LINK_PERSONNEL_DRIVER, "การเชื่อมโยงบุคลากรกับผู้ขับ (personnel-driver link)"
)


def get_personnel_driver_link_service(
    repository: Repository = Depends(get_repository),
    settings: Settings = Depends(get_settings_dependency),
) -> PersonnelLinkService:
    return personnel_driver_link_service(repository, settings.registry_context_effective, effective_test_batch_id(settings))


def _respond(outcome: LinkOutcome) -> JSONResponse:
    body: BaseModel
    if outcome.replayed:
        body = LinkReplayResponse(request_id=outcome.request_id, replayed=True, record_ids=list(outcome.record_ids))
    elif not outcome.changed:
        body = LinkNoOpResponse(request_id=outcome.request_id, changed=False)
    else:
        body = PersonnelDriverLinkChangedResponse(
            request_id=outcome.request_id,
            changed=True,
            link_event_id=outcome.record_id or "",
            previous_driver_id=outcome.previous_id or None,
            new_driver_id=outcome.new_id or None,
            relationship_consistency_after=outcome.consistency_after,  # type: ignore[arg-type]
        )
    return JSONResponse(content=body.model_dump(mode="json"))


_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"model": PersonnelDriverLinkChangedResponse,
          "description": "changed / no-op {request_id, changed:false} / replayed {request_id, replayed, record_ids}"},
    403: {"description": "HTTP_ERROR — the caller lacks can_link_personnel_driver. Zero repository calls."},
    404: {"description": "PERSONNEL_NOT_FOUND (in the request's data-context scope)."},
    409: {"description": "PERSONNEL_ID_AMBIGUOUS; DRIVER_ID_AMBIGUOUS; DRIVER_ALREADY_LINKED {driver_id}; "
                         "PERSONNEL_DRIVER_LINK_STALE / _MISMATCH / _RELINK_REQUIRED / _LINK_REQUIRED / "
                         "_RECONCILIATION_NOT_REQUIRED / _RELATED_REQUEST_INVALID; REQUEST_ID_REUSED."},
    422: {"description": "REQUEST_ID_REQUIRED; VALIDATION_ERROR; REASON_REQUIRED; PERSONNEL_DRIVER_LINK_TARGET_"
                         "REQUIRED / _TARGET_NOT_ALLOWED; DRIVER_NOT_FOUND; DRIVER_SCOPE_UNPROVEN."},
    500: {"description": "PERSONNEL_MASTER_SCHEMA_INVALID (e.g. no driver_id column yet) / _DATA_INVALID; "
                         "DRIVER_MASTER_SCHEMA_INVALID; PERSONNEL_DRIVER_LINK_HISTORY_SCHEMA_INVALID / "
                         "_DATA_INVALID {issues}."},
    503: {"description": "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED; *_READ_FAILED; PERSONNEL_DRIVER_LINK_HISTORY_"
                         "WRITE_FAILED {history_write_outcome, request_id} (nothing changed); PERSONNEL_DRIVER_"
                         "LINK_PROJECTION_WRITE_FAILED {event_recorded: true, record_id, request_id} (reconcile)."},
}


@router.post("/personnel/{personnel_id}/driver-links", response_model=None, responses=_RESPONSES,
             openapi_extra=openapi_body(PersonnelDriverLinkRequest))
async def change_personnel_driver_link(
    personnel_id: str,
    request: Request,
    context: RequestContext = Depends(_require_link),
    request_id: str = Depends(require_client_request_id),
    service: PersonnelLinkService = Depends(get_personnel_driver_link_service),
) -> JSONResponse:
    _parsed, body = await parse_body(request, PersonnelDriverLinkRequest)
    outcome = await service.change(personnel_id, body, request_id=request_id, user_id=context.user_id or "")
    return _respond(outcome)


@router.post("/personnel/{personnel_id}/driver-links/reconcile", response_model=None, responses=_RESPONSES,
             openapi_extra=openapi_body(PersonnelDriverLinkReconcileRequest))
async def reconcile_personnel_driver_link(
    personnel_id: str,
    request: Request,
    context: RequestContext = Depends(_require_link),
    request_id: str = Depends(require_client_request_id),
    service: PersonnelLinkService = Depends(get_personnel_driver_link_service),
) -> JSONResponse:
    _parsed, body = await parse_body(request, PersonnelDriverLinkReconcileRequest)
    outcome = await service.reconcile(personnel_id, body, request_id=request_id, user_id=context.user_id or "")
    return _respond(outcome)


@router.get("/personnel/{personnel_id}/driver-links/history", response_model=PersonnelDriverLinkHistoryResponse)
async def get_personnel_driver_link_history(
    personnel_id: str,
    context: RequestContext = Depends(get_current_context),
    service: PersonnelLinkService = Depends(get_personnel_driver_link_service),
) -> PersonnelDriverLinkHistoryResponse:
    require_capability(context, CAN_VIEW, "ประวัติการเชื่อมโยงบุคลากรกับผู้ขับ (personnel-driver link history)")
    read = await service.history(personnel_id)
    return PersonnelDriverLinkHistoryResponse(
        personnel_id=read.personnel_id,
        current_driver_id=read.current_id,
        latest_history_driver_id=read.latest_history_id,
        relationship_consistency=read.consistency,  # type: ignore[arg-type]
        events=[
            PersonnelDriverLinkEventResponse(
                link_event_id=e.link_event_id, event_kind=e.event_kind,  # type: ignore[arg-type]
                previous_driver_id=e.previous_id or None, new_driver_id=e.new_id or None,
                recorded_at=e.recorded_at, recorded_by=e.recorded_by, reason_th=e.reason_th, request_id=e.request_id,
            )
            for e in read.events
        ],
    )
