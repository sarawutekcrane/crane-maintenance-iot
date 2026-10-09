"""R2 Batch R2e — request / response models of the personnel and department
lifecycle routes. Every request is `extra="forbid"`: the target state comes from
the route, and actor, timestamps, test flags, request id, fingerprint and
related_request_id are server-set (any of them in a body is a 422). The
existing R2c-1 / R2c-2 GET models are not changed.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool

PersonnelState = Literal["ACTIVE", "INACTIVE"]
Consistency = Literal["NO_HISTORY", "CONSISTENT", "MISMATCH"]
EventKind = Literal["DEACTIVATE", "REACTIVATE", "RECONCILIATION"]


class PersonnelLifecycleRequest(BaseModel):
    """Deactivate, reactivate and reconciliation bodies (reason mandatory)."""

    model_config = ConfigDict(extra="forbid")

    expected_active_status: PersonnelState
    reason_th: str


class DepartmentLifecycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_is_active: StrictBool
    reason_th: str


class LifecycleNoOpResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    changed: Literal[False]


class LifecycleReplayResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    replayed: Literal[True]
    record_ids: list[str]


class PersonnelLifecycleChangedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    changed: Literal[True]
    record_id: str
    previous_state: PersonnelState
    new_state: PersonnelState
    lifecycle_consistency_after: Consistency


class DepartmentLifecycleChangedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    changed: Literal[True]
    record_id: str
    previous_state: bool
    new_state: bool
    lifecycle_consistency_after: Consistency


class PersonnelLifecycleEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lifecycle_event_id: str
    event_kind: EventKind
    previous_state: PersonnelState
    new_state: PersonnelState
    recorded_at: str
    recorded_by: str
    reason_th: str


class DepartmentLifecycleEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lifecycle_event_id: str
    event_kind: EventKind
    previous_state: bool
    new_state: bool
    recorded_at: str
    recorded_by: str
    reason_th: str


class PersonnelLifecycleHistoryResponse(BaseModel):
    """`current_state` is the raw personnel_master text (null when blank),
    exactly as the R2c-1 read reports it; it is never normalised here."""

    model_config = ConfigDict(extra="forbid")

    entity_id: str
    current_state: str | None
    latest_history_state: PersonnelState | None
    lifecycle_consistency: Consistency
    events: list[PersonnelLifecycleEventResponse]


class DepartmentLifecycleHistoryResponse(BaseModel):
    """`current_state` is the department's is_active as a boolean (null when
    the source cell is not exactly TRUE / FALSE)."""

    model_config = ConfigDict(extra="forbid")

    entity_id: str
    current_state: bool | None
    latest_history_state: bool | None
    lifecycle_consistency: Consistency
    events: list[DepartmentLifecycleEventResponse]
