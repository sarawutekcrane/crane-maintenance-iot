"""R5 request / response models: effective-dated vehicle status events,
effective-time corrections and derived downtime (OD-3)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.v1.vehicle_schemas import VehicleResponse, VehicleStatusHistoryResponse
from app.domain.common import OperationalStatus


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RecordVehicleStatusEventRequest(_Strict):
    status: OperationalStatus
    effective_at: datetime
    note: str | None = Field(default=None, max_length=500)


class CorrectVehicleStatusTimeRequest(_Strict):
    new_effective_at: datetime
    reason: str | None = Field(default=None, max_length=500)


class VehicleStatusTimeCorrectionResponse(BaseModel):
    correction_id: str
    vehicle_id: str
    history_id: str
    previous_effective_at: datetime
    new_effective_at: datetime
    reason: str
    corrected_by: str
    recorded_at: datetime


class VehicleStatusEventWriteResponse(BaseModel):
    vehicle: VehicleResponse
    history_entry: VehicleStatusHistoryResponse
    replayed: bool


class VehicleStatusCorrectionWriteResponse(BaseModel):
    correction: VehicleStatusTimeCorrectionResponse
    replayed: bool


class VehicleStatusEventResponse(BaseModel):
    history_id: str
    status: OperationalStatus
    effective_at: datetime
    effective_source: str
    """EXPLICIT (recorded effective time or a correction) or RECORDED_TIME (the server time of the change)."""
    recorded_at: datetime
    changed_by: str | None
    note: str | None
    corrections: list[VehicleStatusTimeCorrectionResponse]


class DowntimeIntervalResponse(BaseModel):
    started_at: datetime
    ended_at: datetime


class VehicleDowntimeResponse(BaseModel):
    vehicle_id: str
    from_: datetime = Field(serialization_alias="from")
    to: datetime
    unavailable_statuses: list[OperationalStatus]
    intervals: list[DowntimeIntervalResponse]
    total_seconds: int
    unknown: list[DowntimeIntervalResponse]
    """Ranges without status evidence (before the first event): never counted."""
    flags: list[str]

    model_config = ConfigDict(populate_by_name=True)
