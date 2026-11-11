"""R6 request / response schemas for the new part-lifecycle routes
(FINAL §8). Lifetime-status responses are returned as the read service's
plain JSON contract (documented on `PartLifetimeStatusService`)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.api.v1.part_instance_schemas import MeterAnchorResponse, PartInstanceDetailResponse, PriorUsageInput
from app.domain.part_instance import PartInstanceStatus
from app.domain.part_maintenance_event import MaintenanceAction, MaintenanceTargetType


class ReturnFromRepairRequest(BaseModel):
    outcome: str | None = Field(default=None, max_length=500)
    repair_reference: str | None = Field(default=None, max_length=100)
    new_cycle_approved: bool = False
    approval_reason_code: str | None = Field(default=None, max_length=100)
    storage_location: str | None = Field(default=None, max_length=200)
    effective_at: datetime | None = None
    note: str | None = Field(default=None, max_length=500)


class StatusChangeRequest(BaseModel):
    to_status: PartInstanceStatus
    storage_location: str | None = Field(default=None, max_length=200)
    reason: str | None = Field(default=None, max_length=500)
    effective_at: datetime | None = None


class AssignIdentifiersRequest(BaseModel):
    serial_number: str | None = Field(default=None, max_length=200)
    tag_label: str | None = Field(default=None, max_length=200)


class MaintenanceEventRequest(BaseModel):
    action: MaintenanceAction
    lifetime_rule_id: str | None = None
    condition_group_key: str | None = Field(default=None, max_length=100)
    outcome: str | None = Field(default=None, max_length=500)
    effective_at: datetime | None = None
    source_type: str | None = Field(default=None, max_length=50)
    source_id: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=500)


class MaintenanceEventResponse(BaseModel):
    event_id: str
    target_type: MaintenanceTargetType
    target_id: str
    lifetime_rule_id: str | None
    condition_group_key: str | None
    action: MaintenanceAction
    outcome: str | None
    lifecycle_id: str | None
    effective_at: datetime
    recorded_at: datetime
    actor: str | None
    anchors: list[MeterAnchorResponse] = Field(default_factory=list)
    source_type: str | None
    source_id: str | None
    note: str | None


class ReplacePositionRequest(BaseModel):
    part_id: str | None = None
    prior_usage: PriorUsageInput
    reason: str | None = Field(default=None, max_length=500)
    effective_at: datetime | None = None
    end_snapshot_id: str | None = None
    note: str | None = Field(default=None, max_length=500)


class PartInstancePageResponse(BaseModel):
    items: list[PartInstanceDetailResponse]
    page: int
    page_size: int
    total_items: int


class TestMeterObservationRequest(BaseModel):
    """A-4 TEST-ONLY: one explicitly fake verified reading (never real data)."""

    __test__ = False
    vehicle_id: str = Field(min_length=1)
    component_id: str | None = None
    counter_type: str = Field(pattern="^(ENGINE_HOUR|ODOMETER)$")
    value: float = Field(ge=0)
