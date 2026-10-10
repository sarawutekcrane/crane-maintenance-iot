"""R2 Batch R2f-d — request / response models of the equipment caretaker routes.

The write body is ONE strict, operation-discriminated model: each operation
accepts exactly its own fields (`extra="forbid"`), so actor, timestamps, test
flags, request id, fingerprint, record kind, revision chain and the recorded
"from" caretaker are always server-set (any of them in a body is a 422). Ids
are opaque exact text; a null / blank `expected_current_technician_id` means
"I expect no current caretaker".
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

from app.api.v1.registry_schemas import EffectiveTimeInput


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaretakerTransferRequest(_Body):
    """The latest event: `technician_id` becomes the caretaker (NOW allowed)."""

    operation: Literal["TRANSFER"]
    technician_id: str
    effective: EffectiveTimeInput
    expected_current_technician_id: str | None
    reason_th: str | None = None


class CaretakerInsertionRequest(_Body):
    """A backdated assignment before a later in-force event (no NOW); reason required."""

    operation: Literal["INSERTION"]
    technician_id: str
    effective: EffectiveTimeInput
    expected_current_technician_id: str | None
    reason_th: str


class CaretakerEndRequest(_Body):
    """The latest event: no caretaker from the instant on (NOW allowed)."""

    operation: Literal["END"]
    effective: EffectiveTimeInput
    expected_current_technician_id: str | None
    reason_th: str | None = None


class CaretakerCorrectionRequest(_Body):
    """A new revision of `event_id`. An assignment needs `technician_id`; an END takes none."""

    operation: Literal["CORRECTION"]
    event_id: str
    expected_revision_no: str
    technician_id: str | None = None
    effective: EffectiveTimeInput
    expected_current_technician_id: str | None
    reason_th: str


class CaretakerCancellationRequest(_Body):
    """The terminal revision of `event_id`."""

    operation: Literal["CANCELLATION"]
    event_id: str
    expected_revision_no: str
    expected_current_technician_id: str | None
    reason_th: str


CaretakerEventBody = Annotated[
    CaretakerTransferRequest | CaretakerInsertionRequest | CaretakerEndRequest | CaretakerCorrectionRequest
    | CaretakerCancellationRequest,
    Field(discriminator="operation"),
]


class CaretakerEventRequest(RootModel[CaretakerEventBody]):
    pass


class CaretakerChangedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    changed: Literal[True]
    record_id: str
    event_id: str
    timeline_status_after: Literal["VALID", "AMBIGUOUS_ORDER"]
    current_status: Literal["EVENT", "ENDED", "NONE", "UNDETERMINED"]
    current_technician_id: str | None


class CaretakerNoOpResponse(BaseModel):
    request_id: str
    changed: Literal[False]


class CaretakerReplayResponse(BaseModel):
    request_id: str
    replayed: Literal[True]
    record_ids: list[str]


class CaretakerTechnicianResponse(BaseModel):
    """Display information only (e.g. for a checklist header); never an authorization."""

    technician_id: str
    first_name: str | None
    last_name: str | None
    active_status: str | None


class CaretakerPeriodResponse(BaseModel):
    event_id: str
    in_force: bool
    entry_operation: Literal["TRANSFER", "INSERTION", "END"]
    revision_no: str
    head_record_id: str
    technician_id: str | None
    effective_at: str | None
    effective_precision: str | None
    derived_end_at: str | None
    recorded_at: str
    recorded_by: str
    notes: list[str]


class EquipmentCaretakersResponse(BaseModel):
    equipment_id: str
    timeline_status: Literal["VALID", "AMBIGUOUS_ORDER"]
    current_status: Literal["EVENT", "ENDED", "NONE", "UNDETERMINED"]
    current_technician_id: str | None
    current_since: str | None
    current_technician_resolution: Literal["RESOLVED", "NONE", "UNDETERMINED", "UNRESOLVED"]
    current_technician: CaretakerTechnicianResponse | None
    events: list[CaretakerPeriodResponse]


class TechnicianEquipmentItemResponse(BaseModel):
    equipment_id: str
    since: str | None
    event_id: str


class TechnicianEquipmentResponse(BaseModel):
    technician_id: str
    items: list[TechnicianEquipmentItemResponse]


__all__ = [
    "CaretakerCancellationRequest",
    "CaretakerChangedResponse",
    "CaretakerCorrectionRequest",
    "CaretakerEndRequest",
    "CaretakerEventRequest",
    "CaretakerInsertionRequest",
    "CaretakerNoOpResponse",
    "CaretakerPeriodResponse",
    "CaretakerReplayResponse",
    "CaretakerTechnicianResponse",
    "CaretakerTransferRequest",
    "EquipmentCaretakersResponse",
    "TechnicianEquipmentItemResponse",
    "TechnicianEquipmentResponse",
]
