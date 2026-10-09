"""R2 Batch R2e — department lifecycle routes (history-first, no delete):
- POST /departments/{department_id}/deactivations             (can_manage_department)
- POST /departments/{department_id}/reactivations             (can_manage_department)
- POST /departments/{department_id}/lifecycle-reconciliations (can_manage_department)
- GET  /departments/{department_id}/lifecycle-history         (can_view)
Order: the capability (403), the client `X-Request-Id` (422 REQUEST_ID_REQUIRED),
then the body (422) — all with zero repository calls. The existing R2c-2
`GET /departments` and `GET /departments/{department_id}` are unchanged.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.v1.lifecycle_route_support import respond, responses
from app.api.v1.lifecycle_schemas import (
    DepartmentLifecycleChangedResponse,
    DepartmentLifecycleEventResponse,
    DepartmentLifecycleHistoryResponse,
    DepartmentLifecycleRequest,
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
from app.domain.authz import CAN_MANAGE_DEPARTMENT, CAN_VIEW, require_capability
from app.domain.department_lifecycle import department_lifecycle_service
from app.domain.master_lifecycle import LifecycleService
from app.repositories.base import Repository

router = APIRouter(tags=["departments"])

_require_manage = require_capability_dependency(
    CAN_MANAGE_DEPARTMENT, "การปิด/เปิดใช้งานแผนก (department lifecycle)"
)


def get_department_lifecycle_service(
    repository: Repository = Depends(get_repository),
    settings: Settings = Depends(get_settings_dependency),
) -> LifecycleService:
    return department_lifecycle_service(repository, settings.registry_context_effective, effective_test_batch_id(settings))


def _state(value: str) -> bool:
    """The validated source text TRUE / FALSE as the public boolean."""
    return value == "TRUE"


def _optional_state(value: str | None) -> bool | None:
    """Null unless the source text is exactly TRUE / FALSE (never guessed)."""
    return {"TRUE": True, "FALSE": False}.get(value or "")


_RESPONSES = responses("DEPARTMENT", DepartmentLifecycleChangedResponse)


@router.post("/departments/{department_id}/deactivations", response_model=None, responses=_RESPONSES,
             openapi_extra=openapi_body(DepartmentLifecycleRequest))
async def deactivate_department(
    department_id: str,
    request: Request,
    context: RequestContext = Depends(_require_manage),
    request_id: str = Depends(require_client_request_id),
    service: LifecycleService = Depends(get_department_lifecycle_service),
) -> JSONResponse:
    _parsed, body = await parse_body(request, DepartmentLifecycleRequest)
    outcome = await service.deactivate(department_id, body, request_id=request_id, user_id=context.user_id or "")
    return respond(outcome, DepartmentLifecycleChangedResponse, _state)


@router.post("/departments/{department_id}/reactivations", response_model=None, responses=_RESPONSES,
             openapi_extra=openapi_body(DepartmentLifecycleRequest))
async def reactivate_department(
    department_id: str,
    request: Request,
    context: RequestContext = Depends(_require_manage),
    request_id: str = Depends(require_client_request_id),
    service: LifecycleService = Depends(get_department_lifecycle_service),
) -> JSONResponse:
    _parsed, body = await parse_body(request, DepartmentLifecycleRequest)
    outcome = await service.reactivate(department_id, body, request_id=request_id, user_id=context.user_id or "")
    return respond(outcome, DepartmentLifecycleChangedResponse, _state)


@router.post("/departments/{department_id}/lifecycle-reconciliations", response_model=None, responses=_RESPONSES,
             openapi_extra=openapi_body(DepartmentLifecycleRequest))
async def reconcile_department_lifecycle(
    department_id: str,
    request: Request,
    context: RequestContext = Depends(_require_manage),
    request_id: str = Depends(require_client_request_id),
    service: LifecycleService = Depends(get_department_lifecycle_service),
) -> JSONResponse:
    _parsed, body = await parse_body(request, DepartmentLifecycleRequest)
    outcome = await service.reconcile(department_id, body, request_id=request_id, user_id=context.user_id or "")
    return respond(outcome, DepartmentLifecycleChangedResponse, _state)


@router.get("/departments/{department_id}/lifecycle-history", response_model=DepartmentLifecycleHistoryResponse)
async def get_department_lifecycle_history(
    department_id: str,
    context: RequestContext = Depends(get_current_context),
    service: LifecycleService = Depends(get_department_lifecycle_service),
) -> DepartmentLifecycleHistoryResponse:
    require_capability(context, CAN_VIEW, "ประวัติสถานะแผนก (department lifecycle history)")
    read = await service.history(department_id)
    return DepartmentLifecycleHistoryResponse(
        entity_id=read.entity_id,
        current_state=_optional_state(read.current_state),
        latest_history_state=_optional_state(read.latest_history_state),
        lifecycle_consistency=read.lifecycle_consistency,  # type: ignore[arg-type]
        events=[
            DepartmentLifecycleEventResponse(
                lifecycle_event_id=e.lifecycle_event_id, event_kind=e.event_kind,  # type: ignore[arg-type]
                previous_state=_state(e.previous_state), new_state=_state(e.new_state),
                recorded_at=e.recorded_at, recorded_by=e.recorded_by, reason_th=e.reason_th,
            )
            for e in read.events
        ],
    )
