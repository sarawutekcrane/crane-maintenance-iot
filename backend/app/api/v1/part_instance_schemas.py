from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.asset import AssetType
from app.domain.part_instance import (
    InstallationSegmentStatus,
    LifecycleStartReason,
    PartInstanceStatus,
    PriorUsageQuality,
)


class PriorUsageInput(BaseModel):
    quality: PriorUsageQuality
    value: float | None = None
    note: str | None = Field(default=None, max_length=500)


class PriorUsageResponse(BaseModel):
    quality: PriorUsageQuality
    value: float | None
    note: str | None


class CreatePartInstanceRequest(BaseModel):
    part_id: str = Field(min_length=1)
    serial_number: str | None = Field(default=None, max_length=200)
    prior_usage: PriorUsageInput
    note: str | None = Field(default=None, max_length=500)


class InstallPartInstanceRequest(BaseModel):
    asset_type: AssetType
    asset_id: str = Field(min_length=1)
    position_code: str | None = Field(default=None, max_length=100)
    baseline_meter_snapshot_id: str | None = None
    note: str | None = Field(default=None, max_length=500)


class RemovePartInstanceRequest(BaseModel):
    next_status: PartInstanceStatus
    removal_meter_snapshot_id: str | None = None
    removal_reason: str | None = Field(default=None, max_length=500)


class TransferPartInstanceRequest(BaseModel):
    target_asset_type: AssetType
    target_asset_id: str = Field(min_length=1)
    position_code: str | None = Field(default=None, max_length=100)
    removal_meter_snapshot_id: str | None = None
    baseline_meter_snapshot_id: str | None = None
    removal_reason: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=500)


class StartNewLifecycleRequest(BaseModel):
    approved_reason: str = Field(min_length=1, max_length=1000)


class PartInstanceResponse(BaseModel):
    part_instance_id: str
    part_id: str
    serial_number: str | None
    status: PartInstanceStatus
    prior_usage: PriorUsageResponse
    current_lifecycle_id: str
    note: str | None
    created_at: datetime
    updated_at: datetime


class PartLifecycleResponse(BaseModel):
    lifecycle_id: str
    part_instance_id: str
    cycle_number: int
    start_reason: LifecycleStartReason
    started_at: datetime
    started_by: str | None
    started_note: str | None
    ended_at: datetime | None


class InstallationSegmentResponse(BaseModel):
    segment_id: str
    part_instance_id: str
    lifecycle_id: str
    asset_type: AssetType
    asset_id: str
    position_code: str | None
    status: InstallationSegmentStatus
    installed_at: datetime
    installed_by: str | None
    baseline_meter_snapshot_id: str | None
    install_note: str | None
    removed_at: datetime | None
    removed_by: str | None
    removal_meter_snapshot_id: str | None
    removal_reason: str | None


class PartInstanceDetailResponse(BaseModel):
    instance: PartInstanceResponse
    lifecycles: list[PartLifecycleResponse]
    segments: list[InstallationSegmentResponse]
