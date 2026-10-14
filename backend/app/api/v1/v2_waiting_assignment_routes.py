"""R2 Batch R2f-h4 B3 — U1 V2 waiting-assignment queues (C1 Amendment A1-§24,
owner decision O2). STRICTLY READ ONLY.

- GET /repairs/v2-waiting-assignment           (can_manage_repair)
- GET /pm/work-orders/v2-waiting-assignment    (can_manage_pm)

Order: capability (403, zero reads) -> data context (503, zero reads) ->
exactly three reads. OPEN `TECHNICIAN_V2` jobs of the server scope with
assignment status NONE / AMBIGUOUS / DATA_INVALID; VALID jobs are not listed.
Whole-queue integrity defects fail closed (no partial queue). No role or
capability is added; the legacy `/repairs/waiting-assignment` is unchanged.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.v1.read_signal_schemas import DataContextSignal
from app.api.v1.registry_mutation_body import effective_test_batch_id
from app.config import Settings
from app.context import RequestContext
from app.dependencies import get_current_context, get_repository, get_settings_dependency
from app.domain.authz import CAN_MANAGE_PM, CAN_MANAGE_REPAIR, require_capability
from app.domain.common import PageParams
from app.domain.technician_assignment import PM, REPAIR, WorkKind
from app.domain.v2_waiting_assignment import V2WaitingAssignmentService, WaitingQueue
from app.repositories.base import Repository

router = APIRouter(tags=["v2-waiting-assignment"])


class V2WaitingItemResponse(BaseModel):
    work_type: Literal["REPAIR", "PM"]
    job_id: str
    asset_type: str
    asset_id: str
    status: Literal["OPEN"]
    opened_at: datetime
    assignment_status: Literal["NONE", "AMBIGUOUS", "DATA_INVALID"]
    issues: dict[str, int]


class V2WaitingQueueResponse(BaseModel):
    data_context: DataContextSignal
    items: list[V2WaitingItemResponse]
    page: int
    page_size: int
    total_items: int


_RESPONSES: dict[int | str, dict[str, Any]] = {
    403: {"description": "HTTP_ERROR — the caller lacks the management capability. Zero repository reads."},
    500: {"description": "TECHNICIAN_ASSIGNMENT_DATA_INVALID {issues} (tab-wide / unattributable defects); "
                         "TECHNICIAN_ASSIGNMENT_JOB_DATA_INVALID {issues: JOB_SCOPE_FLAG_INVALID / "
                         "JOB_STATUS_INVALID / JOB_OPENED_AT_INVALID} (counts only); ASSIGNMENT_MODEL_DATA_INVALID "
                         "(an unknown assignment_model); *_SCHEMA_INVALID. Never a partial queue."},
    503: {"description": "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED (zero reads); *_READ_FAILED."},
}


def get_v2_waiting_assignment_service(
    repository: Repository = Depends(get_repository),
    settings: Settings = Depends(get_settings_dependency),
) -> V2WaitingAssignmentService:
    return V2WaitingAssignmentService(repository, settings.registry_context_effective,
                                      effective_test_batch_id(settings))


def _response(queue: WaitingQueue) -> V2WaitingQueueResponse:
    page = queue.page
    return V2WaitingQueueResponse(
        data_context=queue.data_context,  # type: ignore[arg-type]
        items=[V2WaitingItemResponse(
            work_type=i.work_type, job_id=i.job_id, asset_type=i.asset_type,  # type: ignore[arg-type]
            asset_id=i.asset_id, status=i.status, opened_at=i.opened_at,  # type: ignore[arg-type]
            assignment_status=i.assignment_status, issues=i.issues,  # type: ignore[arg-type]
        ) for i in page.items],
        page=page.page, page_size=page.page_size, total_items=page.total_items,
    )


async def _queue(kind: WorkKind, page: int, page_size: int,
                 service: V2WaitingAssignmentService) -> V2WaitingQueueResponse:
    return _response(await service.queue(kind, PageParams(page=page, page_size=page_size)))


@router.get("/repairs/v2-waiting-assignment", response_model=V2WaitingQueueResponse, responses=_RESPONSES)
async def list_repairs_v2_waiting_assignment(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    context: RequestContext = Depends(get_current_context),
    service: V2WaitingAssignmentService = Depends(get_v2_waiting_assignment_service),
) -> V2WaitingQueueResponse:
    require_capability(context, CAN_MANAGE_REPAIR, "รอมอบหมายช่าง V2 (V2 repair waiting-assignment queue)")
    return await _queue(REPAIR, page, page_size, service)


@router.get("/pm/work-orders/v2-waiting-assignment", response_model=V2WaitingQueueResponse, responses=_RESPONSES)
async def list_pm_v2_waiting_assignment(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    context: RequestContext = Depends(get_current_context),
    service: V2WaitingAssignmentService = Depends(get_v2_waiting_assignment_service),
) -> V2WaitingQueueResponse:
    require_capability(context, CAN_MANAGE_PM, "รอมอบหมายทีมช่าง PM V2 (V2 PM waiting-assignment queue)")
    return await _queue(PM, page, page_size, service)
