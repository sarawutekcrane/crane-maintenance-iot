"""R2 Batch R2d — request/response models of the EQUIPMENT branch writes.

Dedicated models: no equipment projection exists, so nothing here carries
expected_master_branch_id, projection_write, consistency or master. The
vehicle `Branch*` models are not changed. The no-op response reuses
`BranchNoOpResponse` (request_id, changed:false, warnings), which carries no
projection field.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.api.v1.registry_schemas import EffectiveTimeInput


class EquipmentBranchAssignmentRequest(BaseModel):
    """First assignment (expected_current_branch_id null: no branch known yet)
    and every later normal transfer."""

    model_config = ConfigDict(extra="forbid")

    to_branch_id: str
    effective: EffectiveTimeInput
    expected_current_branch_id: str | None
    expected_history_revision: str
    # Optional free note, kept exactly (as R1 C-c6).
    note_th: str | None = None


class EquipmentBranchInsertionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_branch_id: str
    effective: EffectiveTimeInput
    reason_th: str | None = None
    expected_history_revision: str


class EquipmentBranchCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_branch_id: str
    effective: EffectiveTimeInput
    reason_th: str | None = None
    expected_history_revision: str


class EquipmentBranchCancellationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_th: str | None = None
    expected_history_revision: str


class EquipmentBranchChangedResponse(BaseModel):
    """200 for a recorded equipment branch change (history only). The current
    branch is derived from the equipment's history; there is no projection."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    changed: Literal[True]
    record_id: str
    event_id: str | None
    timeline_status_after: Literal["VALID", "AMBIGUOUS_ORDER"]
    current_branch_id: str | None
    current_source: Literal["EVENT", "BASELINE", "NONE", "UNDETERMINED"]


class EquipmentBranchReplayResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    replayed: Literal[True]
    record_ids: list[str]
