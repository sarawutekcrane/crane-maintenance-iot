"""Repair routes (Phase 4). Separate from PM — never merges into a PM
work order, even for a `source_type=PM_RESULT` repair.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.v1.repair_schemas import (
    AddRepairActionRequest,
    AddRepairPartRequest,
    CloseRepairRequest,
    CreateRepairRequest,
    RepairActionResponse,
    RepairDetailResponse,
    RepairPartResponse,
    RepairResponse,
    RepairSummaryResponse,
)
from app.context import RequestContext
from app.dependencies import get_current_context, get_repair_service
from app.domain.asset import AssetType
from app.domain.common import Page, PageParams
from app.domain.repair import Repair, RepairDetail, RepairStatus
from app.domain.repair_service import RepairService

router = APIRouter(tags=["repairs"])


def _repair_response(repair: Repair) -> RepairResponse:
    return RepairResponse.model_validate(repair.model_dump())


def _detail_response(detail: RepairDetail) -> RepairDetailResponse:
    return RepairDetailResponse(
        repair=_repair_response(detail.repair),
        actions=[RepairActionResponse.model_validate(a.model_dump()) for a in detail.actions],
        parts=[RepairPartResponse.model_validate(p.model_dump()) for p in detail.parts],
    )


@router.post("/repairs", response_model=RepairDetailResponse)
async def create_repair(
    body: CreateRepairRequest,
    service: RepairService = Depends(get_repair_service),
    context: RequestContext = Depends(get_current_context),
) -> RepairDetailResponse:
    detail = await service.create_repair(
        asset_type=body.asset_type,
        asset_id=body.asset_id,
        source_type=body.source_type,
        source_id=body.source_id,
        category=body.category,
        symptom=body.symptom,
        meter_snapshot_id=body.meter_snapshot_id,
        opened_by=context.user_id,
    )
    return _detail_response(detail)


@router.get("/repairs", response_model=Page[RepairSummaryResponse])
async def list_repairs(
    asset_type: AssetType | None = Query(default=None),
    asset_id: str | None = Query(default=None),
    status: RepairStatus | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    service: RepairService = Depends(get_repair_service),
) -> Page[RepairSummaryResponse]:
    result = await service.list_repairs(
        asset_type=asset_type,
        asset_id=asset_id,
        repair_status=status,
        params=PageParams(page=page, page_size=page_size),
    )
    return Page[RepairSummaryResponse](
        items=[RepairSummaryResponse.model_validate(s.model_dump()) for s in result.items],
        page=result.page,
        page_size=result.page_size,
        total_items=result.total_items,
    )


@router.get("/repairs/{repair_id}", response_model=RepairDetailResponse)
async def get_repair(
    repair_id: str, service: RepairService = Depends(get_repair_service)
) -> RepairDetailResponse:
    detail = await service.get_repair(repair_id)
    return _detail_response(detail)


@router.post("/repairs/{repair_id}/actions", response_model=RepairDetailResponse)
async def add_repair_action(
    repair_id: str,
    body: AddRepairActionRequest,
    service: RepairService = Depends(get_repair_service),
    context: RequestContext = Depends(get_current_context),
) -> RepairDetailResponse:
    detail = await service.add_action(
        repair_id=repair_id,
        action_text=body.action_text,
        actor=context.user_id,
        attachment_ids=list(body.attachment_ids),
    )
    return _detail_response(detail)


@router.post("/repairs/{repair_id}/parts", response_model=RepairDetailResponse)
async def add_repair_part(
    repair_id: str,
    body: AddRepairPartRequest,
    service: RepairService = Depends(get_repair_service),
    context: RequestContext = Depends(get_current_context),
) -> RepairDetailResponse:
    detail = await service.add_part(
        repair_id=repair_id,
        part_description=body.part_description,
        quantity=body.quantity,
        unit=body.unit,
        recorded_by=context.user_id,
        part_id=body.part_id,
        part_instance_id=body.part_instance_id,
        action=body.action,
    )
    return _detail_response(detail)


@router.post("/repairs/{repair_id}/close", response_model=RepairDetailResponse)
async def close_repair(
    repair_id: str,
    body: CloseRepairRequest,
    service: RepairService = Depends(get_repair_service),
    context: RequestContext = Depends(get_current_context),
) -> RepairDetailResponse:
    detail = await service.close_repair(
        repair_id=repair_id, closed_by=context.user_id, close_note=body.close_note
    )
    return _detail_response(detail)
