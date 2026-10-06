"""R2 Batch R2c-1 — read-only personnel master (`can_view`).

GET /personnel and GET /personnel/{personnel_id}. Only the minimum operational
identity/display fields are public; account, technician, driver, department,
branch and test-data columns are not exposed or joined. No mutation route.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from app.context import RequestContext
from app.dependencies import get_current_context, get_repository
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


def get_personnel_service(repository: Repository = Depends(get_repository)) -> PersonnelService:
    return PersonnelService(repository)


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
            "PERSONNEL_MASTER_SCHEMA_INVALID (details: tab, problem, headers) or "
            "PERSONNEL_MASTER_DATA_INVALID (details: tab, issues — counts only, no ids or names)."
        )
    },
    503: {"description": "PERSONNEL_MASTER_READ_FAILED. A failed read is never answered with an empty list."},
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
        404: {"description": "PERSONNEL_NOT_FOUND — no record has exactly this personnel_id."},
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
