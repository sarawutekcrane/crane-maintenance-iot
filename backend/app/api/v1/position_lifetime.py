"""POSITION_LIFETIME routes (Phase 5): lifetime tracked by asset+position,
never requiring a serialized PartInstance.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.v1.position_lifetime_schemas import (
    CreatePositionLifetimeRequest,
    PositionLifetimeResponse,
)
from app.context import RequestContext
from app.dependencies import get_current_context, get_position_lifetime_service
from app.domain.asset import AssetType
from app.domain.part_instance import PriorUsage
from app.domain.position_lifetime import PositionLifetimeRecord
from app.domain.position_lifetime_service import PositionLifetimeService

router = APIRouter(tags=["position-lifetime"])


def _response(record: PositionLifetimeRecord) -> PositionLifetimeResponse:
    return PositionLifetimeResponse.model_validate(record.model_dump())


@router.post("/position-lifetime", response_model=PositionLifetimeResponse)
async def create_position_lifetime(
    body: CreatePositionLifetimeRequest,
    service: PositionLifetimeService = Depends(get_position_lifetime_service),
    context: RequestContext = Depends(get_current_context),
) -> PositionLifetimeResponse:
    record = await service.create(
        asset_type=body.asset_type,
        asset_id=body.asset_id,
        position_code=body.position_code,
        part_id=body.part_id,
        lifetime_rule_id=body.lifetime_rule_id,
        baseline_meter_snapshot_id=body.baseline_meter_snapshot_id,
        prior_usage=PriorUsage(
            quality=body.prior_usage.quality,
            value=body.prior_usage.value,
            note=body.prior_usage.note,
        ),
        started_by=context.user_id,
        note=body.note,
    )
    return _response(record)


@router.get("/position-lifetime/{position_lifetime_id}", response_model=PositionLifetimeResponse)
async def get_position_lifetime(
    position_lifetime_id: str,
    service: PositionLifetimeService = Depends(get_position_lifetime_service),
) -> PositionLifetimeResponse:
    record = await service.get(position_lifetime_id)
    return _response(record)


@router.get("/position-lifetime", response_model=list[PositionLifetimeResponse])
async def list_position_lifetime(
    asset_type: AssetType = Query(...),
    asset_id: str = Query(...),
    service: PositionLifetimeService = Depends(get_position_lifetime_service),
) -> list[PositionLifetimeResponse]:
    records = await service.list_for_asset(asset_type, asset_id)
    return [_response(r) for r in records]
