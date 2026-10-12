"""R2 Batch R2f-g — request / response models of the personnel department movement routes.

The write body is ONE strict, operation-discriminated model (the R2f-d / R2f-f
shape): each operation accepts exactly its own fields (`extra="forbid"`), so
record id, record kind, revision chain, actor, timestamps, request id,
fingerprint, the recorded "from" department, test flags and
related_request_id are always server-set (any of them in a body is a 422). Ids
are opaque exact text; a null / blank `expected_current_department_id` means "I
expect no current department". There is no END operation in this batch.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

from app.api.v1.registry_schemas import EffectiveTimeInput


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DepartmentTransferRequest(_Body):
    """A movement, the latest event: the personnel is in `department_id` from the
    effective instant; the previous period ends at that instant (NOW allowed)."""

    operation: Literal["TRANSFER"]
    department_id: str
    effective: EffectiveTimeInput
    expected_current_department_id: str | None
    reason_th: str | None = None


class DepartmentInsertionRequest(_Body):
    """A backdated movement before a later in-force event (no NOW); reason required."""

    operation: Literal["INSERTION"]
    department_id: str
    effective: EffectiveTimeInput
    expected_current_department_id: str | None
    reason_th: str


class DepartmentCorrectionRequest(_Body):
    """A new revision of `event_id` (department and / or effective time)."""

    operation: Literal["CORRECTION"]
    event_id: str
    expected_revision_no: str
    department_id: str
    effective: EffectiveTimeInput
    expected_current_department_id: str | None
    reason_th: str


class DepartmentCancellationRequest(_Body):
    """The terminal revision of `event_id`."""

    operation: Literal["CANCELLATION"]
    event_id: str
    expected_revision_no: str
    expected_current_department_id: str | None
    reason_th: str


DepartmentEventBody = Annotated[
    DepartmentTransferRequest | DepartmentInsertionRequest | DepartmentCorrectionRequest
    | DepartmentCancellationRequest,
    Field(discriminator="operation"),
]


class DepartmentEventRequest(RootModel[DepartmentEventBody]):
    pass


class DepartmentChangedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    changed: Literal[True]
    record_id: str
    event_id: str
    timeline_status_after: Literal["VALID", "AMBIGUOUS_ORDER"]
    current_department_id: str | None


class DepartmentNoOpResponse(BaseModel):
    request_id: str
    changed: Literal[False]


class DepartmentReplayResponse(BaseModel):
    request_id: str
    replayed: Literal[True]
    record_ids: list[str]


class DepartmentPeriodResponse(BaseModel):
    event_id: str
    in_force: bool
    entry_operation: Literal["TRANSFER", "INSERTION"]
    revision_no: str
    head_record_id: str
    department_id: str | None
    effective_at: str | None
    effective_precision: str | None
    derived_end_at: str | None
    recorded_at: str
    recorded_by: str
    notes: list[str]


class PersonnelDepartmentHistoryResponse(BaseModel):
    personnel_id: str
    timeline_status: Literal["VALID", "AMBIGUOUS_ORDER"]
    current_status: Literal["EVENT", "NONE", "UNDETERMINED"]
    current_department_id: str | None
    current_since: str | None
    # Present (non-null) only when an as-of instant was asked.
    as_of: str | None
    as_of_status: Literal["EVENT", "NONE", "UNDETERMINED"] | None
    as_of_department_id: str | None
    as_of_since: str | None
    events: list[DepartmentPeriodResponse]


__all__ = [
    "DepartmentCancellationRequest",
    "DepartmentChangedResponse",
    "DepartmentCorrectionRequest",
    "DepartmentEventRequest",
    "DepartmentInsertionRequest",
    "DepartmentNoOpResponse",
    "DepartmentPeriodResponse",
    "DepartmentReplayResponse",
    "DepartmentTransferRequest",
    "PersonnelDepartmentHistoryResponse",
]
