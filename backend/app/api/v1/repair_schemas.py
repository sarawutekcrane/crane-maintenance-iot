from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.api.v1.read_signal_schemas import AssignmentModelSignal
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


class SubmitRepairCompletionRequest(BaseModel):
    """R3 W2: 'ส่งงานซ่อมเสร็จ' by the current V2 lead technician."""

    expected_set_id: str | None = None
    """TS-13: the assignment set the client saw; a stale value is refused."""
    note: str | None = Field(default=None, max_length=1000)


class CancelRepairRequest(BaseModel):
    """R3 W5: cancellation of an R3 Finding round before any recorded work."""

    reason: str | None = Field(default=None, max_length=1000)


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
    assignment_model: AssignmentModelSignal
    """R2 Batch R2f-h4 precondition (D-H4-1): the job's PERSISTED assignment
    model — "LEGACY" (blank marker), "TECHNICIAN_V2", or "INVALID" (an unknown
    stored value; fail closed, never reported as either model). Never derived
    from the current cutover setting."""
    # ---- R3 (contract §9–§10); null on every non-R3 Work Order ----
    finding_id: str | None = None
    completion_submitted_at: datetime | None = None
    completion_submitted_by: str | None = None
    completion_technician_id: str | None = None
    completion_note: str | None = None
    cancelled_at: datetime | None = None
    cancelled_by: str | None = None
    cancel_reason: str | None = None


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
    awaiting_parts: bool
    """Core Demo Fixes Delta section H: derived "งานรออะไหล่" indicator —
    True when this repair has a non-terminal MaterialRequest. Computed the
    same way (`MaterialRequestService.is_awaiting_parts`) on every endpoint
    that returns a `RepairDetailResponse` — create, convert, assign, add
    action, add part, close, and GET — never left `None`/unpopulated just
    because a response came from a write path."""


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
    finding_id: str | None = None
    completion_submitted_at: datetime | None = None


class RepairAssignmentHistoryEntryResponse(BaseModel):
    repair_assignment_id: str
    repair_id: str
    user_id: str
    assignment_role: str
    assigned_at: datetime
    assigned_by_user_id: str | None
    ended_at: datetime | None
    active_status: bool
    note: str | None = None
