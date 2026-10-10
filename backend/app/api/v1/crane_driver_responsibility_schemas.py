"""R2 Batch R2f-f — request / response models of the crane driver responsibility routes.

The write body is ONE strict, operation-discriminated model (the R2f-d shape):
each operation accepts exactly its own fields (`extra="forbid"`), so record id,
record kind, revision chain, actor, timestamps, request id, fingerprint, the
recorded "from" driver, test flags and related_request_id are always
server-set (any of them in a body is a 422). Ids are opaque exact text; a null
/ blank `expected_current_driver_id` means "I expect no current driver". The
responses carry stable ids only — no Driver name, phone, licence or expiry.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

from app.api.v1.registry_schemas import EffectiveTimeInput


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResponsibilityTransferRequest(_Body):
    """The latest event: `driver_id` becomes the responsible driver (NOW allowed)."""

    operation: Literal["TRANSFER"]
    driver_id: str
    effective: EffectiveTimeInput
    expected_current_driver_id: str | None
    reason_th: str | None = None


class ResponsibilityInsertionRequest(_Body):
    """A backdated assignment before a later in-force event (no NOW); reason required."""

    operation: Literal["INSERTION"]
    driver_id: str
    effective: EffectiveTimeInput
    expected_current_driver_id: str | None
    reason_th: str


class ResponsibilityEndRequest(_Body):
    """The latest event: no responsible driver from the instant on (NOW allowed)."""

    operation: Literal["END"]
    effective: EffectiveTimeInput
    expected_current_driver_id: str | None
    reason_th: str | None = None


class ResponsibilityCorrectionRequest(_Body):
    """A new revision of `event_id`. An assignment needs `driver_id`; an END takes none."""

    operation: Literal["CORRECTION"]
    event_id: str
    expected_revision_no: str
    driver_id: str | None = None
    effective: EffectiveTimeInput
    expected_current_driver_id: str | None
    reason_th: str


class ResponsibilityCancellationRequest(_Body):
    """The terminal revision of `event_id`."""

    operation: Literal["CANCELLATION"]
    event_id: str
    expected_revision_no: str
    expected_current_driver_id: str | None
    reason_th: str


ResponsibilityEventBody = Annotated[
    ResponsibilityTransferRequest | ResponsibilityInsertionRequest | ResponsibilityEndRequest | ResponsibilityCorrectionRequest
    | ResponsibilityCancellationRequest,
    Field(discriminator="operation"),
]


class ResponsibilityEventRequest(RootModel[ResponsibilityEventBody]):
    pass


class ResponsibilityChangedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    changed: Literal[True]
    record_id: str
    event_id: str
    timeline_status_after: Literal["VALID", "AMBIGUOUS_ORDER"]
    current_status: Literal["EVENT", "ENDED", "NONE", "UNDETERMINED"]
    current_driver_id: str | None


class ResponsibilityNoOpResponse(BaseModel):
    request_id: str
    changed: Literal[False]


class ResponsibilityReplayResponse(BaseModel):
    request_id: str
    replayed: Literal[True]
    record_ids: list[str]


class ResponsibilityPeriodResponse(BaseModel):
    event_id: str
    in_force: bool
    entry_operation: Literal["TRANSFER", "INSERTION", "END"]
    revision_no: str
    head_record_id: str
    driver_id: str | None
    effective_at: str | None
    effective_precision: str | None
    derived_end_at: str | None
    recorded_at: str
    recorded_by: str
    notes: list[str]


class VehicleResponsibleDriversResponse(BaseModel):
    vehicle_id: str
    timeline_status: Literal["VALID", "AMBIGUOUS_ORDER"]
    current_status: Literal["EVENT", "ENDED", "NONE", "UNDETERMINED"]
    current_driver_id: str | None
    current_since: str | None
    events: list[ResponsibilityPeriodResponse]


class DriverVehicleItemResponse(BaseModel):
    vehicle_id: str
    since: str | None
    event_id: str


class DriverVehiclesResponse(BaseModel):
    driver_id: str
    items: list[DriverVehicleItemResponse]


__all__ = [
    "DriverVehicleItemResponse",
    "DriverVehiclesResponse",
    "ResponsibilityCancellationRequest",
    "ResponsibilityChangedResponse",
    "ResponsibilityCorrectionRequest",
    "ResponsibilityEndRequest",
    "ResponsibilityEventRequest",
    "ResponsibilityInsertionRequest",
    "ResponsibilityNoOpResponse",
    "ResponsibilityPeriodResponse",
    "ResponsibilityReplayResponse",
    "ResponsibilityTransferRequest",
    "VehicleResponsibleDriversResponse",
]
