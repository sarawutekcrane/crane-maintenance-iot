"""Access Management routes (Owner-approved Mock implementation).

Every route answers 409 ACCESS_MANAGEMENT_NOT_ENABLED outside Access Management
mode. Authority is decided only on the server from the actor resolved by
`get_current_context` (account link → employee): client-sent employee,
department or scope values are inputs that are re-checked, never trusted.
Changes need an X-Request-Id (idempotent replay) and the `expected_revision`
the screen loaded (a concurrent change is refused, nothing written).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query

from app.api.v1.request_id_dependency import require_client_request_id
from app.config import Settings
from app.context import RequestContext
from app.dependencies import (
    get_current_context,
    get_repository,
    get_settings_dependency,
)
from app.domain.access_management import AccessService, not_enabled
from app.domain.technician_assignment import cutover_from_settings
from app.repositories.base import Repository

router = APIRouter(prefix="/access", tags=["access-management"])


def get_access_service(
    settings: Settings = Depends(get_settings_dependency),
    repository: Repository = Depends(get_repository),
) -> AccessService:
    if not settings.access_management_mode:
        raise not_enabled()
    cutover = cutover_from_settings(settings)
    return AccessService(repository, cutover.data_context, cutover.test_batch_id)


@router.get("/me")
async def access_me(service: AccessService = Depends(get_access_service),
                    context: RequestContext = Depends(get_current_context)) -> dict[str, Any]:
    return service.me(await service.state(), context)


@router.get("/catalog")
async def access_catalog(service: AccessService = Depends(get_access_service),
                         context: RequestContext = Depends(get_current_context)) -> dict[str, Any]:
    service.require_admin(context)
    return service.catalog()


@router.get("/departments")
async def access_departments(service: AccessService = Depends(get_access_service),
                             context: RequestContext = Depends(get_current_context)) -> list[dict[str, Any]]:
    return service.departments(await service.state(), context)


@router.get("/employees")
async def access_employees(department_id: str = Query(min_length=1),
                           service: AccessService = Depends(get_access_service),
                           context: RequestContext = Depends(get_current_context)) -> dict[str, Any]:
    return service.employees(await service.state(), context, department_id)


@router.post("/grants/preview")
async def access_grants_preview(body: dict[str, Any] = Body(...),
                                service: AccessService = Depends(get_access_service),
                                context: RequestContext = Depends(get_current_context)) -> dict[str, Any]:
    return await service.preview(context, body)


@router.post("/grants")
async def access_grants_apply(body: dict[str, Any] = Body(...),
                              request_id: str = Depends(require_client_request_id),
                              service: AccessService = Depends(get_access_service),
                              context: RequestContext = Depends(get_current_context)) -> dict[str, Any]:
    return await service.apply(context, body, request_id=request_id)


@router.get("/delegations")
async def access_delegations(service: AccessService = Depends(get_access_service),
                             context: RequestContext = Depends(get_current_context)) -> list[dict[str, Any]]:
    return await service.delegations(context)


@router.post("/delegations")
async def access_delegate(body: dict[str, Any] = Body(...),
                          request_id: str = Depends(require_client_request_id),
                          service: AccessService = Depends(get_access_service),
                          context: RequestContext = Depends(get_current_context)) -> dict[str, Any]:
    return await service.delegate(context, body, request_id=request_id)


@router.post("/delegations/{delegation_id}/revocation")
async def access_revoke_delegation(delegation_id: str, body: dict[str, Any] = Body(...),
                                   request_id: str = Depends(require_client_request_id),
                                   service: AccessService = Depends(get_access_service),
                                   context: RequestContext = Depends(get_current_context)) -> dict[str, Any]:
    return await service.revoke_delegation(context, delegation_id, body, request_id=request_id)


@router.get("/root")
async def access_root(service: AccessService = Depends(get_access_service),
                      context: RequestContext = Depends(get_current_context)) -> dict[str, Any]:
    service.authority(context)
    return service.root_view(await service.state())


@router.post("/root/appointment")
async def access_appoint_root(body: dict[str, Any] = Body(...),
                              request_id: str = Depends(require_client_request_id),
                              service: AccessService = Depends(get_access_service),
                              context: RequestContext = Depends(get_current_context)) -> dict[str, Any]:
    return await service.appoint_root(context, body, request_id=request_id)


@router.get("/audit")
async def access_audit(personnel_id: str | None = Query(default=None),
                       department_id: str | None = Query(default=None),
                       service: AccessService = Depends(get_access_service),
                       context: RequestContext = Depends(get_current_context)) -> list[dict[str, Any]]:
    return await service.audit(context, personnel_id=personnel_id, department_id=department_id)
