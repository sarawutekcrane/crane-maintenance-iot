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
    observed_at: datetime | None = None


class MeterSnapshotResponse(BaseModel):
    meter_snapshot_id: str
    asset_type: AssetType
    asset_id: str
    readings: list[MeterReadingResponse]
    recorded_at: datetime
    recorded_by: str | None
    is_automatic: bool = False
    latitude: float | None = None
    longitude: float | None = None
    gps_observed_at: datetime | None = None
    source_note: str | None = None


class CurrentMachineStateResponse(BaseModel):
    """Read-only preview of an asset's current backend-derived machine
    state — never persisted, so a normal user-facing form can display it
    without creating a new automatic snapshot on every page view."""

    asset_type: AssetType
    asset_id: str
    readings: list[MeterReadingResponse]
    latitude: float | None = None
    longitude: float | None = None
    gps_observed_at: datetime | None = None
    note: str = (
        "แสดงค่าล่าสุดที่ระบบทราบเท่านั้น (อ่านอย่างเดียว) — "
        "ไม่มีแหล่งข้อมูล GPS/มิเตอร์แบบเรียลไทม์ในระบบนี้"
    )
