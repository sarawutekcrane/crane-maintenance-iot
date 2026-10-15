"""R2 Batch R2-C1 — request / response models of the E2 operational driver
assignment routes.

The write body is ONE strict, operation-discriminated model: each operation
accepts exactly its own fields (`extra="forbid"`), so record ids, record kinds,
revision chains, actors, timestamps, request ids, fingerprints, test flags,
handover instants, UNKNOWN spans and relations are always server-set (any of
them in a body is a 422). There is no field for a mid-shift time: B20 / A2-4.6
are refused by the schema itself. Ids are opaque exact text. Responses carry
stable ids only (`assigned_driver_id` — an ASSIGNED driver, never a verified
actual driver; G-2) and stable codes (Thai presentation is the frontend's, G-3).
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ShiftInput(_Body):
    """Explicit applied scheduled times (local Asia/Bangkok HH:MM). The end is on
    the labelled date (offset 0) or the next day (offset 1); equal times with
    offset 1 are exactly 24 hours."""

    start_time: str
    end_time: str
    end_day_offset: Literal[0, 1]


class HandoverInput(_Body):
    """H2 / E2-H3: the predecessor this new assignment explicitly hands over from."""

    predecessor_event_id: str
    expected_revision_no: str


class CreateRequest(_Body):
    operation: Literal["CREATE"]
    driver_id: str
    mode: Literal["FULL_DAY", "DAY_SHIFT", "NIGHT_SHIFT"]
    start_date: str
    end_date: str
    shift: ShiftInput | None = None
    handover: HandoverInput | None = None
    reason_th: str | None = None  # required when start_date is before today (Bangkok)


class ReviseRequest(_Body):
    """A correction / extension (full new state, optionally removing specific
    erroneous units with `exclude_dates`), a shift-time split from
    `split_from_date`, or `void_elapsed: true` (DQ-6, no state fields)."""

    operation: Literal["REVISE"]
    event_id: str
    expected_revision_no: str
    reason_th: str
    void_elapsed: Literal[True] | None = None
    driver_id: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    shift: ShiftInput | None = None
    split_from_date: str | None = None
    exclude_dates: list[str] | None = Field(default=None, min_length=1, max_length=366)  # F3: remove erroneous units


class SubstituteRequest(_Body):
    """Whole calendar days (FULL_DAY) or whole shifts, by labelled date (O4)."""

    operation: Literal["SUBSTITUTE"]
    event_id: str
    expected_revision_no: str
    dates: list[str] = Field(min_length=1, max_length=366)
    driver_id: str
    reason_th: str


class CancelRequest(_Body):
    operation: Literal["CANCEL"]
    event_id: str
    expected_revision_no: str
    reason_th: str


class EarlyEndNow(_Body):
    mode: Literal["NOW"]


class EarlyEndAfterDate(_Body):
    mode: Literal["AFTER_DATE"]
    date: str


class EarlyEndRequest(_Body):
    operation: Literal["EARLY_END"]
    event_id: str
    expected_revision_no: str
    end: Annotated[EarlyEndNow | EarlyEndAfterDate, Field(discriminator="mode")]
    reason_th: str


class OperationRequest(RootModel[Annotated[
    CreateRequest | ReviseRequest | SubstituteRequest | CancelRequest | EarlyEndRequest,
    Field(discriminator="operation"),
]]):
    pass


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class WarningResponse(BaseModel):
    code: str
    event_id: str | None = None
    driver_id: str | None = None
    vehicle_id: str | None = None
    related_event_id: str | None = None


class OperationChangedResponse(BaseModel):
    request_id: str
    changed: Literal[True]
    operation_id: str
    record_ids: list[str]
    event_ids: list[str]
    warnings: list[WarningResponse]


class OperationNoOpResponse(BaseModel):
    request_id: str
    changed: Literal[False]
    existing_event_id: str | None = None  # B27: the identical active assignment


class OperationReplayResponse(BaseModel):
    request_id: str
    replayed: Literal[True]
    operation_id: str
    record_ids: list[str]
    event_ids: list[str]


class IntervalResponse(BaseModel):
    """One derived effective unit (half-open, UTC instants; label_date is the
    Bangkok date the unit belongs to — a NIGHT_SHIFT keeps its start date)."""

    event_id: str
    revision_no: str
    vehicle_id: str
    assigned_driver_id: str
    mode: str
    label_date: str
    effective_start: str
    effective_end: str


class UnknownResponse(BaseModel):
    """Elapsed coverage left genuinely uncertain by a post-handover correction."""

    vehicle_id: str
    start: str
    end: str
    handover_event_id: str


class ConflictResponse(BaseModel):
    axis: Literal["VEHICLE", "DRIVER"]
    key: str
    first: IntervalResponse
    second: IntervalResponse


class VehicleScheduleResponse(BaseModel):
    vehicle_id: str
    timeline_status: Literal["VALID", "CONFLICTED"]
    current_status: Literal["ASSIGNED", "UNKNOWN", "NONE", "CONFLICTED"]
    current: IntervalResponse | None
    intervals: list[IntervalResponse]
    unknown: list[UnknownResponse]
    conflicts: list[ConflictResponse]
    warnings: list[WarningResponse]


class DriverScheduleResponse(BaseModel):
    driver_id: str
    timeline_status: Literal["VALID", "CONFLICTED"]
    intervals: list[IntervalResponse]
    conflicts: list[ConflictResponse]
    warnings: list[WarningResponse]


class HistoryRecordResponse(BaseModel):
    """One immutable stored row (originals, revisions, handovers, cancellations)."""

    record_id: str
    operation_id: str
    record_kind: str
    entry_operation: str
    event_id: str
    revision_no: str
    supersedes_record_id: str | None
    assigned_driver_id: str | None
    mode: str | None
    start_date: str | None
    end_date: str | None
    shift_start_time: str | None
    shift_end_time: str | None
    shift_end_day_offset: str | None
    excluded_dates: list[str]
    related_event_id: str | None
    relation: str | None
    early_end_at: str | None
    voided: bool
    handover_kind: str | None
    predecessor_event_id: str | None
    predecessor_revision_no: str | None
    successor_event_id: str | None
    successor_revision_no: str | None
    handover_at: str | None
    unknown_start_at: str | None
    unknown_end_at: str | None
    reason_th: str | None
    recorded_at: str
    recorded_by: str
    request_id: str


class HistoryEventResponse(BaseModel):
    event_id: str
    kind: Literal["ASSIGNMENT", "HANDOVER"]
    lifecycle: Literal["ACTIVE", "CANCELLED", "VOIDED", "IN_FORCE"]
    revision_no: str
    head_record_id: str


class VehicleHistoryResponse(BaseModel):
    vehicle_id: str
    events: list[HistoryEventResponse]
    records: list[HistoryRecordResponse]
