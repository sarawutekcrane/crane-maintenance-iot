from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.api.v1.part_instance_schemas import MeterAnchorResponse, PriorUsageInput, PriorUsageResponse
from app.domain.asset import AssetType


class CreatePositionLifetimeRequest(BaseModel):
    # Required for an asset-hosted record; omitted for an instance-hosted one.
    asset_type: AssetType | None = None
    asset_id: str | None = Field(default=None, min_length=1)
    host_part_instance_id: str | None = None
    effective_at: datetime | None = None
    position_code: str = Field(min_length=1, max_length=100)
    part_id: str | None = None
    lifetime_rule_id: str | None = None
    baseline_meter_snapshot_id: str | None = None
    prior_usage: PriorUsageInput
    note: str | None = Field(default=None, max_length=500)


class PositionLifetimeResponse(BaseModel):
    position_lifetime_id: str
    asset_type: AssetType | None
    asset_id: str | None
    position_code: str
    part_id: str | None
    lifetime_rule_id: str | None
    baseline_meter_snapshot_id: str | None
    prior_usage: PriorUsageResponse
    started_at: datetime
    started_by: str | None
    note: str | None
    host_part_instance_id: str | None = None
    started_effective_at: datetime | None = None
    ended_at: datetime | None = None
    ended_effective_at: datetime | None = None
    end_snapshot_id: str | None = None
    end_reason: str | None = None
    superseded_by_id: str | None = None
    baseline_anchors: list[MeterAnchorResponse] = Field(default_factory=list)
    end_anchors: list[MeterAnchorResponse] = Field(default_factory=list)
