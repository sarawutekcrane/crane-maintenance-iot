"""R2 Batch R2f-a — read-only technician and relationship routes (`can_view`).

- GET /technicians                              bounded technician_master list (REAL scope)
- GET /technicians/{technician_id}              exact-id detail
- GET /personnel/{personnel_id}/relationships   technician + account link resolution
- GET /technicians/{technician_id}/personnel    reverse Technician -> Personnel resolution

No mutation route, no Driver relationship (R2f-e), no user_account listing. The
R2c-1 `GET /personnel` routes stay join-free; relationship resolution lives
only here. The two relationship routes resolve in the server's data scope
(registry data context + test batch, the R2e rule) and answer 503
REGISTRY_DATA_CONTEXT_NOT_CONFIGURED when it is not configured.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.v1.registry_mutation_body import effective_test_batch_id
from app.api.v1.relationship_schemas import (
    AccountLinkResponse,
    PersonnelRelationshipsResponse,
    TechnicianLinkResponse,
    TechnicianPersonnelResponse,
    TechnicianResponse,
)
from app.config import Settings
from app.context import RequestContext
from app.dependencies import get_current_context, get_repository, get_settings_dependency
from app.domain.authz import CAN_VIEW, require_capability
from app.domain.common import Page, PageParams
from app.domain.personnel_relationship import PersonnelRelationshipService
from app.domain.technician import TechnicianRecord, TechnicianService
from app.repositories.base import Repository

router = APIRouter(tags=["relationships"])


def get_technician_service(repository: Repository = Depends(get_repository)) -> TechnicianService:
    return TechnicianService(repository)


def get_relationship_service(
    repository: Repository = Depends(get_repository),
    settings: Settings = Depends(get_settings_dependency),
) -> PersonnelRelationshipService:
    return PersonnelRelationshipService(
        repository, settings.registry_context_effective, effective_test_batch_id(settings)
    )


def _technician(record: TechnicianRecord) -> TechnicianResponse:
    return TechnicianResponse(
        technician_id=record.technician_id,
        first_name=record.first_name,
        last_name=record.last_name,
        active_status=record.active_status,
    )


_FORBIDDEN = {403: {"description": "HTTP_ERROR — the caller lacks the 'can_view' capability. No data is read."}}
_TECHNICIAN_ERRORS: dict[int | str, dict[str, Any]] = {
    **_FORBIDDEN,
    500: {"description": "TECHNICIAN_MASTER_SCHEMA_INVALID (tab, problem, headers) / TECHNICIAN_MASTER_DATA_INVALID "
                         "(issues — counts only)."},
    503: {"description": "TECHNICIAN_MASTER_READ_FAILED. A failed read is never answered with an empty list."},
}
_RELATIONSHIP_ERRORS: dict[int | str, dict[str, Any]] = {
    **_FORBIDDEN,
    500: {"description": "PERSONNEL_MASTER_SCHEMA_INVALID / PERSONNEL_MASTER_DATA_INVALID (TEST_FLAG_INVALID) / "
                         "TECHNICIAN_MASTER_SCHEMA_INVALID / USER_ACCOUNT_SCHEMA_INVALID."},
    503: {"description": "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED / PERSONNEL_MASTER_READ_FAILED / "
                         "TECHNICIAN_MASTER_READ_FAILED / USER_ACCOUNT_READ_FAILED. A failed read is never a "
                         "resolution state."},
}


@router.get("/technicians", response_model=Page[TechnicianResponse], responses=_TECHNICIAN_ERRORS)
async def list_technicians(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    context: RequestContext = Depends(get_current_context),
    service: TechnicianService = Depends(get_technician_service),
) -> Page[TechnicianResponse]:
    require_capability(context, CAN_VIEW, "รายชื่อช่าง (technician list)")
    result = await service.list_technicians(PageParams(page=page, page_size=page_size))
    return Page[TechnicianResponse](
        items=[_technician(r) for r in result.items],
        page=result.page,
        page_size=result.page_size,
        total_items=result.total_items,
    )


@router.get(
    "/technicians/{technician_id}",
    response_model=TechnicianResponse,
    responses={
        **_TECHNICIAN_ERRORS,
        404: {"description": "TECHNICIAN_NOT_FOUND — no record has exactly this technician_id."},
        409: {"description": "TECHNICIAN_ID_AMBIGUOUS (details: match_count)."},
    },
)
async def get_technician(
    technician_id: str,
    context: RequestContext = Depends(get_current_context),
    service: TechnicianService = Depends(get_technician_service),
) -> TechnicianResponse:
    require_capability(context, CAN_VIEW, "ข้อมูลช่าง (technician detail)")
    return _technician(await service.get_technician(technician_id))


@router.get(
    "/personnel/{personnel_id}/relationships",
    response_model=PersonnelRelationshipsResponse,
    responses={
        **_RELATIONSHIP_ERRORS,
        404: {"description": "PERSONNEL_NOT_FOUND (in the request's data-context scope)."},
        409: {"description": "PERSONNEL_ID_AMBIGUOUS (details: match_count)."},
    },
)
async def get_personnel_relationships(
    personnel_id: str,
    context: RequestContext = Depends(get_current_context),
    service: PersonnelRelationshipService = Depends(get_relationship_service),
) -> PersonnelRelationshipsResponse:
    require_capability(context, CAN_VIEW, "ความสัมพันธ์ของบุคลากร (personnel relationships)")
    result = await service.personnel_relationships(personnel_id)
    return PersonnelRelationshipsResponse(
        personnel_id=result.personnel_id,
        technician=TechnicianLinkResponse(
            resolution=result.technician.resolution,
            technician_id=result.technician.linked_id,
            technician=_technician(result.technician_record) if result.technician_record else None,
        ),
        account=AccountLinkResponse(resolution=result.account.resolution),
    )


@router.get(
    "/technicians/{technician_id}/personnel",
    response_model=TechnicianPersonnelResponse,
    responses={
        **_RELATIONSHIP_ERRORS,
        404: {"description": "TECHNICIAN_NOT_FOUND (in the request's data-context scope)."},
        409: {"description": "TECHNICIAN_ID_AMBIGUOUS (details: match_count)."},
    },
)
async def get_technician_personnel(
    technician_id: str,
    context: RequestContext = Depends(get_current_context),
    service: PersonnelRelationshipService = Depends(get_relationship_service),
) -> TechnicianPersonnelResponse:
    require_capability(context, CAN_VIEW, "บุคลากรของช่าง (technician personnel)")
    result = await service.technician_personnel(technician_id)
    return TechnicianPersonnelResponse(
        technician_id=result.technician_id,
        resolution=result.resolution,
        personnel_id=result.personnel_id,
        match_count=result.match_count,
    )
