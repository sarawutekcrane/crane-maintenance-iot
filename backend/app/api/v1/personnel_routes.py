"""R2 Batch R2c-1 — read-only personnel master (`can_view`).

GET /personnel and GET /personnel/{personnel_id}. Only the minimum
identity/display fields are public; account, technician, driver, department,
branch and test-data columns are not exposed or joined. No mutation route.

R2-C2 Personnel Scope Option S (owner decisions S1–S4; supersedes the R2c-1
operational-only rule): both routes read in the SERVER-DERIVED scope (registry
data context + test batch, the R2e / R2f and O4 technician rule) and answer 503
REGISTRY_DATA_CONTEXT_NOT_CONFIGURED before any read when it is not configured.
No query parameter selects a scope.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from app.api.v1.registry_mutation_body import effective_test_batch_id
from app.config import Settings
from app.context import RequestContext
from app.dependencies import get_current_context, get_repository, get_settings_dependency
from app.domain.authz import CAN_VIEW, require_capability
from app.domain.common import Page, PageParams
from app.domain.personnel import PersonnelRecord, PersonnelService
from app.repositories.base import Repository

router = APIRouter(tags=["personnel"])


class PersonnelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    personnel_id: str
    # Exact source text; null when the source cell is blank (never substituted).
    first_name: str | None
    last_name: str | None
    # Raw source text, not an enum; null = blank/unknown, never defaulted to ACTIVE.
    active_status: str | None


def get_personnel_service(
    repository: Repository = Depends(get_repository),
    settings: Settings = Depends(get_settings_dependency),
) -> PersonnelService:
    return PersonnelService(repository, settings.registry_context_effective, effective_test_batch_id(settings))


def _response(record: PersonnelRecord) -> PersonnelResponse:
    return PersonnelResponse(
        personnel_id=record.personnel_id,
        first_name=record.first_name,
        last_name=record.last_name,
        active_status=record.active_status,
    )


_COMMON: dict[int | str, dict[str, Any]] = {
    403: {"description": "HTTP_ERROR — the caller lacks the 'can_view' capability. No data is read."},
    500: {
        "description": (
            "PERSONNEL_MASTER_SCHEMA_INVALID (details: tab, problem, headers; in the TEST context also a "
            "missing test_batch_id header) or "
            "PERSONNEL_MASTER_DATA_INVALID (details: tab, issues — counts only, no ids or names)."
        )
    },
    503: {
        "description": (
            "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED (no data context, or TEST without a batch; before any read) / "
            "PERSONNEL_MASTER_READ_FAILED. A failed read is never answered with an empty list."
        )
    },
}


@router.get("/personnel", response_model=Page[PersonnelResponse], responses=_COMMON)
async def list_personnel(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    context: RequestContext = Depends(get_current_context),
    service: PersonnelService = Depends(get_personnel_service),
) -> Page[PersonnelResponse]:
    require_capability(context, CAN_VIEW, "รายชื่อบุคลากร (personnel list)")
    result = await service.list_personnel(PageParams(page=page, page_size=page_size))
    return Page[PersonnelResponse](
        items=[_response(r) for r in result.items],
        page=result.page,
        page_size=result.page_size,
        total_items=result.total_items,
    )


@router.get(
    "/personnel/{personnel_id}",
    response_model=PersonnelResponse,
    responses={
        **_COMMON,
        404: {"description": "PERSONNEL_NOT_FOUND — no record of the server scope has exactly this personnel_id."},
        409: {"description": "PERSONNEL_ID_AMBIGUOUS (details: match_count)."},
    },
)
async def get_personnel(
    personnel_id: str,
    context: RequestContext = Depends(get_current_context),
    service: PersonnelService = Depends(get_personnel_service),
) -> PersonnelResponse:
    require_capability(context, CAN_VIEW, "ข้อมูลบุคลากร (personnel detail)")
    return _response(await service.get_personnel(personnel_id))
