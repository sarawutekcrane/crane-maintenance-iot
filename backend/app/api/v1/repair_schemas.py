from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.asset import AssetType
from app.domain.part import PartActionType
from app.domain.repair import RepairSourceType, RepairStatus


class CreateRepairRequest(BaseModel):
    asset_type: AssetType
    asset_id: str = Field(min_length=1)
    source_type: RepairSourceType
    source_id: str | None = Field(default=None)
    category: str | None = Field(default=None, max_length=200)
    symptom: str | None = Field(default=None, max_length=1000)
    # Normal path leaves this unset — the backend automatically captures
    # machine state (Core Demo Fixes prompt, APPROVED CORE RULE). Kept only
    # as an explicit-override escape hatch, never required by the UI.
    meter_snapshot_id: str | None = None
    primary_technician: str | None = None
    collaborators: list[str] = Field(default_factory=list)


class AssignRepairRequest(BaseModel):
    primary_technician: str | None = None
    collaborators: list[str] = Field(default_factory=list)


class AddRepairActionRequest(BaseModel):
    action_text: str = Field(min_length=1, max_length=1000)
    attachment_ids: list[str] = Field(default_factory=list)


class AddRepairPartRequest(BaseModel):
    part_description: str = Field(min_length=1)
    quantity: float | None = None
    unit: str | None = None
    part_id: str | None = None
    part_instance_id: str | None = None
    action: PartActionType | None = None


class CloseRepairRequest(BaseModel):
    close_note: str | None = Field(default=None, max_length=1000)


class RepairResponse(BaseModel):
    repair_id: str
    asset_type: AssetType
    asset_id: str
    source_type: RepairSourceType
    source_id: str | None
    category: str | None
    symptom: str | None
    meter_snapshot_id: str | None
    status: RepairStatus
    opened_at: datetime
    opened_by: str | None
    closed_at: datetime | None
    closed_by: str | None
    close_note: str | None
    closed_snapshot_id: str | None = None
    primary_technician: str | None = None
    collaborators: list[str] = Field(default_factory=list)


class RepairActionResponse(BaseModel):
    repair_action_id: str
    repair_id: str
    action_text: str
    actor: str | None
    created_at: datetime
    attachment_ids: list[str]


class RepairPartResponse(BaseModel):
    repair_part_id: str
    repair_id: str
    part_description: str
    quantity: float | None
    unit: str | None
    part_id: str | None
    part_instance_id: str | None
    action: PartActionType | None
    recorded_by: str | None
    recorded_at: datetime


class RepairDetailResponse(BaseModel):
    repair: RepairResponse
    actions: list[RepairActionResponse]
    parts: list[RepairPartResponse]


class RepairSummaryResponse(BaseModel):
    repair_id: str
    asset_type: AssetType
    asset_id: str
    source_type: RepairSourceType
    source_id: str | None
    status: RepairStatus
    opened_at: datetime
    closed_at: datetime | None
    action_count: int
    primary_technician: str | None = None
    collaborators: list[str] = Field(default_factory=list)
    symptom: str | None = None
