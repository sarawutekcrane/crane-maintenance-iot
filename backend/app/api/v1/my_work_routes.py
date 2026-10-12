"""R2 Batch R2f-h2 — V2 My Work (Final Contract C1 §24: `GET /my-work`, returning
`{resolution, items}`).

The authenticated actor's OWN current TECHNICIAN_V2 work only, resolved through
User Account -> Personnel -> Technician in the server's scope. No capability is
required beyond being the caller, exactly like the legacy My Work routes (which
are unchanged): the answer never concerns anyone else. An unresolved chain is an
explicit `resolution` with `items: null` — never an empty list. Read only.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import Settings
from app.context import RequestContext
from app.dependencies import get_current_context, get_repository, get_settings_dependency
from app.domain.my_work import MyWorkService
from app.domain.technician_assignment import cutover_from_settings
from app.repositories.base import Repository

router = APIRouter(tags=["my-work"])

Resolution = Literal[
    "RESOLVED", "UNAUTHENTICATED", "ACCOUNT_MISSING", "ACCOUNT_AMBIGUOUS", "ACCOUNT_SCOPE_UNPROVEN",
    "PERSONNEL_UNLINKED", "PERSONNEL_AMBIGUOUS", "PERSONNEL_SCOPE_MISMATCH", "TECHNICIAN_UNLINKED",
    "TECHNICIAN_MISSING", "TECHNICIAN_AMBIGUOUS", "TECHNICIAN_SCOPE_UNPROVEN",
]


class MyWorkItemResponse(BaseModel):
    work_type: Literal["REPAIR", "PM"]
    job_id: str
    asset_type: str
    asset_id: str
    status: str
    opened_at: datetime
    assignment_role: Literal["PRIMARY", "COLLABORATOR"]
    assignment_set_id: str
    assigned_at: datetime


class MyWorkResponse(BaseModel):
    resolution: Resolution
    technician_id: str | None
    items: list[MyWorkItemResponse] | None


_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"description": "RESOLVED with items (possibly empty), or an unresolved resolution with items null."},
    409: {"description": "TECHNICIAN_ASSIGNMENT_ORDER_AMBIGUOUS — a current set cannot be determined."},
    500: {"description": "TECHNICIAN_ASSIGNMENT_DATA_INVALID {issues}; *_SCHEMA_INVALID; PERSONNEL_MASTER_DATA_INVALID."},
    503: {"description": "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED; *_READ_FAILED."},
}


def get_my_work_service(
    repository: Repository = Depends(get_repository),
    settings: Settings = Depends(get_settings_dependency),
) -> MyWorkService:
    return MyWorkService(repository, cutover_from_settings(settings))


@router.get("/my-work", response_model=MyWorkResponse, responses=_RESPONSES)
async def get_my_work(
    context: RequestContext = Depends(get_current_context),
    service: MyWorkService = Depends(get_my_work_service),
) -> MyWorkResponse:
    result = await service.my_work(context.user_id)
    return MyWorkResponse(
        resolution=result.resolution,  # type: ignore[arg-type]
        technician_id=result.technician_id,
        items=None if result.items is None else [
            MyWorkItemResponse(
                work_type=i.work_type, job_id=i.job_id, asset_type=i.asset_type, asset_id=i.asset_id,  # type: ignore[arg-type]
                status=i.status, opened_at=i.opened_at, assignment_role=i.assignment_role,  # type: ignore[arg-type]
                assignment_set_id=i.assignment_set_id, assigned_at=i.assigned_at,
            )
            for i in result.items
        ],
    )
