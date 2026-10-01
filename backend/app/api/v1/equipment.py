"""Workshop equipment routes (Phase 2).

`/equipment/{equipment_id}` backs the stable QR entry point for
non-vehicle machinery (baseline section 5/7): the frontend route
`/equipment/{equipment_id}` calls `GET /api/v1/equipment/{equipment_id}`.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.v1.equipment_schemas import (
    ChangeEquipmentStatusRequest,
    EquipmentResponse,
    EquipmentStatusHistoryEntryResponse,
)
from app.context import RequestContext
from app.dependencies import get_current_context, get_equipment_service
from app.domain.common import Page, PageParams
from app.domain.equipment import EquipmentCategory
from app.domain.equipment_service import EquipmentService

router = APIRouter(tags=["equipment"])


_EQUIPMENT_Q_DESCRIPTION = (
    "Phase 7 Batch 7J2: whitespace-separated terms, all of which must match "
    "(case-insensitive substrings) the name, equipment_id or equipment_code. "
    "equipment_id/equipment_code also match with spaces and '-' ignored; a Thai+digit "
    "term (e.g. 'กลึง1') may match when all its parts occur in the name. A term made "
    "only of '-' is ignored; a q of only such terms matches nothing."
)


# Phase 7 Batch 7K2: documented error envelopes of the validated equipment paths.
_LIST_ERRORS: dict[int | str, dict[str, Any]] = {
    500: {
        "description": (
            "EQUIPMENT_MASTER_SCHEMA_INVALID (details: tab, problem, headers) or "
            "EQUIPMENT_MASTER_DATA_INVALID (details: issue_counts per row, no ids) — any row with a "
            "blank/unrecognized category or status, or an unmappable row, fails the whole list."
        )
    },
    503: {"description": "EQUIPMENT_MASTER_READ_FAILED — equipment_master could not be read."},
}
_LOOKUP_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"description": "EQUIPMENT_NOT_FOUND — no equipment_master record has exactly this equipment_id."},
    409: {"description": "EQUIPMENT_ID_AMBIGUOUS (details: match_count) — more than one record has this equipment_id; nothing was changed."},
    500: {"description": "EQUIPMENT_MASTER_SCHEMA_INVALID or EQUIPMENT_MASTER_DATA_INVALID for the located record."},
    503: {"description": "EQUIPMENT_MASTER_READ_FAILED."},
}
_HISTORY_ERRORS: dict[int | str, dict[str, Any]] = {
    **_LOOKUP_ERRORS,
    500: {
        "description": (
            "EQUIPMENT_MASTER_SCHEMA_INVALID / EQUIPMENT_MASTER_DATA_INVALID, "
            "EQUIPMENT_STATUS_HISTORY_SCHEMA_INVALID, or EQUIPMENT_STATUS_HISTORY_DATA_INVALID "
            "(details: issue_counts per row: BLANK_STATUS, UNRECOGNIZED_STATUS, UNMAPPABLE_ROW, "
            "MIXED_TIMEZONE_TIMESTAMP)."
        )
    },
    503: {"description": "EQUIPMENT_MASTER_READ_FAILED or EQUIPMENT_STATUS_HISTORY_READ_FAILED."},
}
_STATUS_ERRORS: dict[int | str, dict[str, Any]] = {
    **_LOOKUP_ERRORS,
    500: {
        "description": (
            "EQUIPMENT_MASTER_SCHEMA_INVALID, EQUIPMENT_MASTER_DATA_INVALID or "
            "EQUIPMENT_STATUS_HISTORY_SCHEMA_INVALID — detected before anything is written."
        )
    },
    503: {
        "description": (
            "EQUIPMENT_MASTER_READ_FAILED / EQUIPMENT_STATUS_HISTORY_READ_FAILED (nothing written); "
            "EQUIPMENT_MASTER_WRITE_FAILED (equipment_write_outcome 'rejected' | 'unknown'; history "
            "not attempted); EQUIPMENT_STATUS_HISTORY_WRITE_FAILED (equipment_status_updated: true = "
            "the status update request was acknowledged, not re-read; history_write_outcome). "
            "Never retried."
        )
    },
}

@router.get("/equipment", response_model=Page[EquipmentResponse], responses=_LIST_ERRORS)
async def list_equipment(
    q: str | None = Query(default=None, description=_EQUIPMENT_Q_DESCRIPTION),
    category: EquipmentCategory | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    service: EquipmentService = Depends(get_equipment_service),
) -> Page[EquipmentResponse]:
    result = await service.list_equipment(
        q=q, category=category, params=PageParams(page=page, page_size=page_size)
    )
    return Page[EquipmentResponse](
        items=[EquipmentResponse.model_validate(e.model_dump()) for e in result.items],
        page=result.page,
        page_size=result.page_size,
        total_items=result.total_items,
    )


@router.get("/equipment/{equipment_id}", response_model=EquipmentResponse, responses=_LOOKUP_ERRORS)
async def get_equipment(
    equipment_id: str, service: EquipmentService = Depends(get_equipment_service)
) -> EquipmentResponse:
    equipment = await service.get_equipment(equipment_id)
    return EquipmentResponse.model_validate(equipment.model_dump())


@router.post(
    "/equipment/{equipment_id}/status", response_model=EquipmentResponse, responses=_STATUS_ERRORS
)
async def change_equipment_status(
    equipment_id: str,
    body: ChangeEquipmentStatusRequest,
    service: EquipmentService = Depends(get_equipment_service),
    context: RequestContext = Depends(get_current_context),
) -> EquipmentResponse:
    equipment = await service.change_status(
        equipment_id=equipment_id,
        new_status=body.status,
        reason=body.reason,
        changed_by=context.user_id,
    )
    return EquipmentResponse.model_validate(equipment.model_dump())


@router.get(
    "/equipment/{equipment_id}/status-history",
    response_model=list[EquipmentStatusHistoryEntryResponse],
    responses=_HISTORY_ERRORS,
)
async def list_equipment_status_history(
    equipment_id: str, service: EquipmentService = Depends(get_equipment_service)
) -> list[EquipmentStatusHistoryEntryResponse]:
    entries = await service.list_status_history(equipment_id)
    return [
        EquipmentStatusHistoryEntryResponse.model_validate(e.model_dump()) for e in entries
    ]
