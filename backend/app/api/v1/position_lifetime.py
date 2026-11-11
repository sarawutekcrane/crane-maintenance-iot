"""POSITION_LIFETIME routes (Phase 5): lifetime tracked by asset+position,
never requiring a serialized PartInstance.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response

from app.api.v1.position_lifetime_schemas import (
    CreatePositionLifetimeRequest,
    PositionLifetimeResponse,
)
from app.api.v1.repairs import optional_client_request_id
from app.context import RequestContext
from app.dependencies import get_current_context, get_position_lifetime_service
from app.domain.asset import AssetType
from app.domain.part_instance_service import apply_replay_header
from app.domain.position_lifetime import PositionLifetimeRecord
from app.domain.position_lifetime_service import PositionLifetimeService

router = APIRouter(tags=["position-lifetime"])


def _response(record: PositionLifetimeRecord) -> PositionLifetimeResponse:
    return PositionLifetimeResponse.model_validate(record.model_dump(mode="json"))


@router.post("/position-lifetime", response_model=PositionLifetimeResponse)
async def create_position_lifetime(
    response: Response,
    body: CreatePositionLifetimeRequest,
    service: PositionLifetimeService = Depends(get_position_lifetime_service),
    context: RequestContext = Depends(get_current_context),
    request_id: str | None = Depends(optional_client_request_id),
) -> PositionLifetimeResponse:
    record = await service.create(
        asset_type=body.asset_type,
        asset_id=body.asset_id,
        position_code=body.position_code,
        part_id=body.part_id,
        lifetime_rule_id=body.lifetime_rule_id,
        baseline_meter_snapshot_id=body.baseline_meter_snapshot_id,
        prior_usage=body.prior_usage.to_domain(),
        started_by=context.user_id,
        note=body.note,
        host_part_instance_id=body.host_part_instance_id,
        effective_at=body.effective_at,
        request_id=request_id,
        body=body.model_dump(mode="json", exclude_unset=True),
    )
    apply_replay_header(response, record)
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
