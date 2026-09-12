from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.asset import AssetType
from app.domain.meter import CounterType


class MeterReadingInputRequest(BaseModel):
    component_id: str | None = Field(default=None)
    counter_type: CounterType
    value: float | None = Field(default=None)


class CreateMeterSnapshotRequest(BaseModel):
    asset_type: AssetType
    asset_id: str = Field(min_length=1)
    readings: list[MeterReadingInputRequest] = Field(default_factory=list)


class MeterReadingResponse(BaseModel):
    component_id: str | None
    counter_type: CounterType
    value: float | None


class MeterSnapshotResponse(BaseModel):
    meter_snapshot_id: str
    asset_type: AssetType
    asset_id: str
    readings: list[MeterReadingResponse]
    recorded_at: datetime
    recorded_by: str | None
