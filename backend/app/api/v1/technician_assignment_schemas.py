"""R2 Batch R2f-h1 — request / response models of the V2 technician assignment
routes (Repair and PM work orders).

The write body is ONE strict model (`extra="forbid"`): the actor, timestamps,
test flags, request id, fingerprint, record ids, assignee type and the legacy
`user_id` / `ended_at` / `active_status` cells are always server-set (any of
them in a body is a 422). Technician ids are opaque exact text. The set is
exactly one PRIMARY plus zero or more COLLABORATORs; there is no empty set
(V2 unassignment is not offered — owner decision PENDING).
`expected_current` is REQUIRED: null means "I expect no current set".
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExpectedAssignmentSet(_Body):
    primary_technician_id: str
    collaborator_technician_ids: list[str] = Field(default_factory=list)


class TechnicianAssignmentRequest(_Body):
    primary_technician_id: str
    collaborator_technician_ids: list[str] = Field(default_factory=list)
    expected_current: ExpectedAssignmentSet | None
    reason_th: str | None = None


class AssignmentSetResponse(BaseModel):
    assignment_set_id: str
    assigned_at: datetime
    assigned_by_user_id: str
    primary_technician_id: str
    collaborator_technician_ids: list[str]
    reason_th: str | None = None
    record_ids: list[str]


class TechnicianAssignmentChangedResponse(BaseModel):
    request_id: str
    changed: Literal[True]
    record_ids: list[str]
    current: AssignmentSetResponse


class TechnicianAssignmentNoOpResponse(BaseModel):
    request_id: str
    changed: Literal[False]


class TechnicianAssignmentReplayResponse(BaseModel):
    request_id: str
    replayed: Literal[True]
    record_ids: list[str]


class TechnicianAssignmentsResponse(BaseModel):
    job_id: str
    assignment_model: Literal["TECHNICIAN_V2"]
    status: Literal["NONE", "VALID", "AMBIGUOUS"]
    current: AssignmentSetResponse | None
    sets: list[AssignmentSetResponse]
