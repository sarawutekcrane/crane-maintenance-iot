from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.domain.asset import AssetType
from app.domain.lifetime_rule import LifetimeTriggerType
from app.domain.part_instance import (
    HistoricalEvidenceType,
    InstallationSegmentStatus,
    LifecycleStartReason,
    PartInstanceStatus,
    PriorUsageQuality,
    ReferenceStatus,
)
from app.domain.vehicle_model import ComponentRole


class PriorUsageInput(BaseModel):
    """Historical usage declaration (R6 FINAL §7.3a). The server sets
    `reference_status`, `declared_by` and `declared_at`; any such key in the
    body is ignored."""

    quality: PriorUsageQuality
    value: float | None = None
    note: str | None = Field(default=None, max_length=500)
    basis: LifetimeTriggerType | None = None
    component_role: ComponentRole | None = None
    as_of: date | None = None
    evidence_type: HistoricalEvidenceType | None = None
    evidence_reference: str | None = Field(default=None, max_length=500)

    def to_domain(self):
        from app.domain.part_instance import PriorUsage

        return PriorUsage(quality=self.quality, value=self.value, note=self.note, basis=self.basis,
                          component_role=self.component_role, as_of=self.as_of, evidence_type=self.evidence_type,
                          evidence_reference=self.evidence_reference)


class PriorUsageResponse(BaseModel):
    quality: PriorUsageQuality
    value: float | None
    note: str | None
    basis: LifetimeTriggerType | None = None
    component_role: ComponentRole | None = None
    as_of: date | None = None
    evidence_type: HistoricalEvidenceType | None = None
    evidence_reference: str | None = None
    reference_status: ReferenceStatus | None = None
    declared_by: str | None = None
    declared_at: datetime | None = None


class CreatePartInstanceRequest(BaseModel):
    part_id: str = Field(min_length=1)
    serial_number: str | None = Field(default=None, max_length=200)
    tag_label: str | None = Field(default=None, max_length=200)
    storage_location: str | None = Field(default=None, max_length=200)
    initial_status: PartInstanceStatus = PartInstanceStatus.READY_FOR_INSTALL
    prior_usage: PriorUsageInput
    prior_cycle_usage: PriorUsageInput | None = None
    note: str | None = Field(default=None, max_length=500)


class InstallPartInstanceRequest(BaseModel):
    asset_type: AssetType
    asset_id: str = Field(min_length=1)
    position_code: str | None = Field(default=None, max_length=100)
    baseline_meter_snapshot_id: str | None = None
    note: str | None = Field(default=None, max_length=500)
    effective_at: datetime | None = None
    source_type: str | None = Field(default=None, max_length=50)
    source_id: str | None = Field(default=None, max_length=100)


class RemovePartInstanceRequest(BaseModel):
    next_status: PartInstanceStatus
    removal_meter_snapshot_id: str | None = None
    removal_reason: str | None = Field(default=None, max_length=500)
    storage_location: str | None = Field(default=None, max_length=200)
    effective_at: datetime | None = None
    source_type: str | None = Field(default=None, max_length=50)
    source_id: str | None = Field(default=None, max_length=100)


class TransferPartInstanceRequest(BaseModel):
    target_asset_type: AssetType
    target_asset_id: str = Field(min_length=1)
    position_code: str | None = Field(default=None, max_length=100)
    removal_meter_snapshot_id: str | None = None
    baseline_meter_snapshot_id: str | None = None
    removal_reason: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=500)
    effective_at: datetime | None = None
    source_type: str | None = Field(default=None, max_length=50)
    source_id: str | None = Field(default=None, max_length=100)


class StartNewLifecycleRequest(BaseModel):
    """Kept for route/body compatibility (A-2(ii)); the route always answers
    409 NEW_CYCLE_OPENS_AT_INSTALL and never creates a lifecycle."""

    approved_reason: str = Field(min_length=1, max_length=1000)


class PartInstanceResponse(BaseModel):
    part_instance_id: str
    part_id: str
    serial_number: str | None
    tag_label: str | None = None
    storage_location: str | None = None
    status: PartInstanceStatus
    prior_usage: PriorUsageResponse
    prior_cycle_usage: PriorUsageResponse | None = None
    current_lifecycle_id: str
    note: str | None
    state_version: int = 0
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
    start_trigger_event_id: str | None = None
    start_policy_state: str | None = None


class MeterAnchorResponse(BaseModel):
    vehicle_id: str
    component_id: str | None
    counter_type: str
    value: float
    observed_at: datetime
    received_at: datetime
    time_quality: str
    device_id: str
    device_event_id: str


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
    installed_effective_at: datetime | None = None
    removed_effective_at: datetime | None = None
    source_type: str | None = None
    source_id: str | None = None
    baseline_anchors: list[MeterAnchorResponse] = Field(default_factory=list)
    removal_anchors: list[MeterAnchorResponse] = Field(default_factory=list)


class PartInstanceStatusEventResponse(BaseModel):
    event_id: str
    part_instance_id: str
    operation: str
    from_status: PartInstanceStatus | None
    to_status: PartInstanceStatus
    effective_at: datetime
    recorded_at: datetime
    actor: str | None
    reason: str | None
    source_type: str | None
    source_id: str | None
    meter_snapshot_id: str | None
    storage_location: str | None
    new_cycle_approved: bool
    approval_reason_code: str | None
    approval_policy_state: str | None
    repair_reference: str | None
    approved_by: str | None


class PartInstanceDetailResponse(BaseModel):
    instance: PartInstanceResponse
    lifecycles: list[PartLifecycleResponse]
    segments: list[InstallationSegmentResponse]
    status_events: list[PartInstanceStatusEventResponse] = Field(default_factory=list)
