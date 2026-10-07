"""R2 Batch R2c-2 — read-only department master (`can_view`).

GET /departments and GET /departments/{department_id}. Only department_id,
department_name_th and is_active are public; is_test_data and test_batch_id
are not exposed, and no personnel, branch, workshop, account, technician or
driver data is read or joined. No mutation route in this batch.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from app.context import RequestContext
from app.dependencies import get_current_context, get_repository
from app.domain.authz import CAN_VIEW, require_capability
from app.domain.common import Page, PageParams
from app.domain.department import DepartmentRecord, DepartmentService
from app.repositories.base import Repository

router = APIRouter(tags=["departments"])


class DepartmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    department_id: str
    # Exact source text (display only, not identity, not necessarily unique).
    department_name_th: str
    # The source's exact TRUE / FALSE; inactive departments stay readable.
    is_active: bool


def get_department_service(repository: Repository = Depends(get_repository)) -> DepartmentService:
    return DepartmentService(repository)


def _response(record: DepartmentRecord) -> DepartmentResponse:
    return DepartmentResponse(
        department_id=record.department_id,
        department_name_th=record.department_name_th,
        is_active=record.is_active,
    )


_COMMON: dict[int | str, dict[str, Any]] = {
    403: {"description": "HTTP_ERROR — the caller lacks the 'can_view' capability. No data is read."},
    500: {
        "description": (
            "DEPARTMENT_MASTER_SCHEMA_INVALID (details: tab, problem, headers) or "
            "DEPARTMENT_MASTER_DATA_INVALID (details: tab, issues — counts only, no ids or names)."
        )
    },
    503: {"description": "DEPARTMENT_MASTER_READ_FAILED. A failed read is never answered with an empty list."},
}


@router.get("/departments", response_model=Page[DepartmentResponse], responses=_COMMON)
async def list_departments(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    context: RequestContext = Depends(get_current_context),
    service: DepartmentService = Depends(get_department_service),
) -> Page[DepartmentResponse]:
    require_capability(context, CAN_VIEW, "รายชื่อแผนก (department list)")
    result = await service.list_departments(PageParams(page=page, page_size=page_size))
    return Page[DepartmentResponse](
        items=[_response(r) for r in result.items],
        page=result.page,
        page_size=result.page_size,
        total_items=result.total_items,
    )


@router.get(
    "/departments/{department_id}",
    response_model=DepartmentResponse,
    responses={
        **_COMMON,
        404: {"description": "DEPARTMENT_NOT_FOUND — no operational record has exactly this department_id."},
        409: {"description": "DEPARTMENT_ID_AMBIGUOUS (details: match_count)."},
    },
)
async def get_department(
    department_id: str,
    context: RequestContext = Depends(get_current_context),
    service: DepartmentService = Depends(get_department_service),
) -> DepartmentResponse:
    require_capability(context, CAN_VIEW, "ข้อมูลแผนก (department detail)")
    return _response(await service.get_department(department_id))
