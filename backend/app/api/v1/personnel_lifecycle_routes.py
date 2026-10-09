"""R2 Batch R2e — personnel lifecycle routes (history-first, no delete):
- POST /personnel/{personnel_id}/deactivations             (can_manage_personnel)
- POST /personnel/{personnel_id}/reactivations             (can_manage_personnel)
- POST /personnel/{personnel_id}/lifecycle-reconciliations (can_manage_personnel)
- GET  /personnel/{personnel_id}/lifecycle-history         (can_view)
Order: the capability (403), the client `X-Request-Id` (422 REQUEST_ID_REQUIRED),
then the body (422) — all with zero repository calls. The existing R2c-1
`GET /personnel` and `GET /personnel/{personnel_id}` are unchanged.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.v1.lifecycle_route_support import respond, responses
from app.api.v1.lifecycle_schemas import (
    PersonnelLifecycleChangedResponse,
    PersonnelLifecycleEventResponse,
    PersonnelLifecycleHistoryResponse,
    PersonnelLifecycleRequest,
)
from app.api.v1.registry_mutation_body import (
    effective_test_batch_id,
    openapi_body,
    parse_body,
)
from app.api.v1.request_id_dependency import (
    require_capability_dependency,
    require_client_request_id,
)
from app.config import Settings
from app.context import RequestContext
from app.dependencies import (
    get_current_context,
    get_repository,
    get_settings_dependency,
)
from app.domain.authz import CAN_MANAGE_PERSONNEL, CAN_VIEW, require_capability
from app.domain.master_lifecycle import LifecycleService
from app.domain.personnel_lifecycle import personnel_lifecycle_service
from app.repositories.base import Repository

router = APIRouter(tags=["personnel"])

_require_manage = require_capability_dependency(
    CAN_MANAGE_PERSONNEL, "การปิด/เปิดใช้งานข้อมูลบุคลากร (personnel lifecycle)"
)


def get_personnel_lifecycle_service(
    repository: Repository = Depends(get_repository),
    settings: Settings = Depends(get_settings_dependency),
) -> LifecycleService:
    return personnel_lifecycle_service(repository, settings.registry_context_effective, effective_test_batch_id(settings))


def _state(value: str) -> str:
    return value


_RESPONSES = responses("PERSONNEL", PersonnelLifecycleChangedResponse)


@router.post("/personnel/{personnel_id}/deactivations", response_model=None, responses=_RESPONSES,
             openapi_extra=openapi_body(PersonnelLifecycleRequest))
async def deactivate_personnel(
    personnel_id: str,
    request: Request,
    context: RequestContext = Depends(_require_manage),
    request_id: str = Depends(require_client_request_id),
    service: LifecycleService = Depends(get_personnel_lifecycle_service),
) -> JSONResponse:
    _parsed, body = await parse_body(request, PersonnelLifecycleRequest)
    outcome = await service.deactivate(personnel_id, body, request_id=request_id, user_id=context.user_id or "")
    return respond(outcome, PersonnelLifecycleChangedResponse, _state)


@router.post("/personnel/{personnel_id}/reactivations", response_model=None, responses=_RESPONSES,
             openapi_extra=openapi_body(PersonnelLifecycleRequest))
async def reactivate_personnel(
    personnel_id: str,
    request: Request,
    context: RequestContext = Depends(_require_manage),
    request_id: str = Depends(require_client_request_id),
    service: LifecycleService = Depends(get_personnel_lifecycle_service),
) -> JSONResponse:
    _parsed, body = await parse_body(request, PersonnelLifecycleRequest)
    outcome = await service.reactivate(personnel_id, body, request_id=request_id, user_id=context.user_id or "")
    return respond(outcome, PersonnelLifecycleChangedResponse, _state)


@router.post("/personnel/{personnel_id}/lifecycle-reconciliations", response_model=None, responses=_RESPONSES,
             openapi_extra=openapi_body(PersonnelLifecycleRequest))
async def reconcile_personnel_lifecycle(
    personnel_id: str,
    request: Request,
    context: RequestContext = Depends(_require_manage),
    request_id: str = Depends(require_client_request_id),
    service: LifecycleService = Depends(get_personnel_lifecycle_service),
) -> JSONResponse:
    _parsed, body = await parse_body(request, PersonnelLifecycleRequest)
    outcome = await service.reconcile(personnel_id, body, request_id=request_id, user_id=context.user_id or "")
    return respond(outcome, PersonnelLifecycleChangedResponse, _state)


@router.get("/personnel/{personnel_id}/lifecycle-history", response_model=PersonnelLifecycleHistoryResponse)
async def get_personnel_lifecycle_history(
    personnel_id: str,
    context: RequestContext = Depends(get_current_context),
    service: LifecycleService = Depends(get_personnel_lifecycle_service),
) -> PersonnelLifecycleHistoryResponse:
    require_capability(context, CAN_VIEW, "ประวัติสถานะบุคลากร (personnel lifecycle history)")
    read = await service.history(personnel_id)
    return PersonnelLifecycleHistoryResponse(
        entity_id=read.entity_id,
        current_state=read.current_state,
        latest_history_state=read.latest_history_state,  # type: ignore[arg-type]
        lifecycle_consistency=read.lifecycle_consistency,  # type: ignore[arg-type]
        events=[
            PersonnelLifecycleEventResponse(
                lifecycle_event_id=e.lifecycle_event_id, event_kind=e.event_kind,  # type: ignore[arg-type]
                previous_state=e.previous_state, new_state=e.new_state,  # type: ignore[arg-type]
                recorded_at=e.recorded_at, recorded_by=e.recorded_by, reason_th=e.reason_th,
            )
            for e in read.events
        ],
    )
