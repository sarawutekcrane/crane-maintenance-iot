from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.api.v1.part_instance_schemas import PriorUsageInput, PriorUsageResponse
from app.domain.asset import AssetType


class CreatePositionLifetimeRequest(BaseModel):
    asset_type: AssetType
    asset_id: str = Field(min_length=1)
    position_code: str = Field(min_length=1, max_length=100)
    part_id: str | None = None
    lifetime_rule_id: str | None = None
    baseline_meter_snapshot_id: str | None = None
    prior_usage: PriorUsageInput
    note: str | None = Field(default=None, max_length=500)


class PositionLifetimeResponse(BaseModel):
    position_lifetime_id: str
    asset_type: AssetType
    asset_id: str
    position_code: str
    part_id: str | None
    lifetime_rule_id: str | None
    baseline_meter_snapshot_id: str | None
    prior_usage: PriorUsageResponse
    started_at: datetime
    started_by: str | None
    note: str | None
