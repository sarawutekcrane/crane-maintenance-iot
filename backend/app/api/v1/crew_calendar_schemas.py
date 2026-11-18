"""R8 early workstream — request / response models of the crew assignment and
resource calendar routes (Owner source approval 2026-11-18, OD-1…OD-4, OD-7).

The crew write body is ONE strict, operation-discriminated model
(`extra="forbid"`): record ids, record kinds, revision chains, actors,
timestamps, request ids, fingerprints and test flags are always server-set (any
of them in a body is a 422). There is no SUBSTITUTE or handover operation
(OD-4 = A). Responses carry stable ids, codes and the PUBLIC personnel name only
(first + last name): no phone, licence, account id, GPS or note from another
domain. "Assigned" never means verified attendance or actual work.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CrewShiftInput(_Body):
    """Explicit applied scheduled times (Asia/Bangkok HH:MM), as E2 (A2-3)."""

    start_time: str
    end_time: str
    end_day_offset: Literal[0, 1]


class CrewCreateRequest(_Body):
    operation: Literal["CREATE"]
    personnel_id: str
    crew_role: Literal["RIGGER", "SIGNALMAN", "OTHER"]
    crew_role_note_th: str | None = None  # required for OTHER, refused otherwise
    mode: Literal["FULL_DAY", "DAY_SHIFT", "NIGHT_SHIFT"]
    start_date: str
    end_date: str
    shift: CrewShiftInput | None = None
    reason_th: str | None = None  # required when start_date is before today (Bangkok)


class CrewReviseRequest(_Body):
    """A correction / extension: the full new state of the same person on the same
    vehicle (a different person is a new CREATE, OD-4)."""

    operation: Literal["REVISE"]
    event_id: str
    expected_revision_no: str
    reason_th: str
    crew_role: Literal["RIGGER", "SIGNALMAN", "OTHER"]
    crew_role_note_th: str | None = None
    mode: Literal["FULL_DAY", "DAY_SHIFT", "NIGHT_SHIFT"]
    start_date: str
    end_date: str
    shift: CrewShiftInput | None = None


class CrewCancelRequest(_Body):
    operation: Literal["CANCEL"]
    event_id: str
    expected_revision_no: str
    reason_th: str


class CrewEarlyEndNow(_Body):
    mode: Literal["NOW"]


class CrewEarlyEndAfterDate(_Body):
    mode: Literal["AFTER_DATE"]
    date: str


class CrewEarlyEndRequest(_Body):
    operation: Literal["EARLY_END"]
    event_id: str
    expected_revision_no: str
    end: Annotated[CrewEarlyEndNow | CrewEarlyEndAfterDate, Field(discriminator="mode")]
    reason_th: str


class CrewOperationRequest(RootModel[Annotated[
    CrewCreateRequest | CrewReviseRequest | CrewCancelRequest | CrewEarlyEndRequest,
    Field(discriminator="operation"),
]]):
    pass


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class CrewWarningResponse(BaseModel):
    code: str
    event_id: str | None = None
    personnel_id: str | None = None
    vehicle_id: str | None = None
    related_event_id: str | None = None


class CrewOperationChangedResponse(BaseModel):
    request_id: str
    changed: Literal[True]
    operation_id: str
    record_ids: list[str]
    event_ids: list[str]
    warnings: list[CrewWarningResponse]


class CrewOperationNoOpResponse(BaseModel):
    request_id: str
    changed: Literal[False]
    existing_event_id: str | None = None


class CrewOperationReplayResponse(BaseModel):
    request_id: str
    replayed: Literal[True]
    operation_id: str
    record_ids: list[str]
    event_ids: list[str]


class CrewIntervalResponse(BaseModel):
    event_id: str
    revision_no: str
    vehicle_id: str
    personnel_id: str
    personnel_name: str | None
    crew_role: str
    crew_role_note_th: str | None
    mode: str
    label_date: str
    effective_start: str
    effective_end: str
    status: Literal["VALID", "CONFLICTED", "IDENTITY_UNVERIFIED"]


class VehicleCrewResponse(BaseModel):
    vehicle_id: str
    intervals: list[CrewIntervalResponse]


class CrewHistoryEventResponse(BaseModel):
    event_id: str
    lifecycle: Literal["ACTIVE", "CANCELLED"]
    revision_no: str
    head_record_id: str
    personnel_id: str


class CrewHistoryRecordResponse(BaseModel):
    record_id: str
    operation_id: str
    record_kind: str
    entry_operation: str
    event_id: str
    revision_no: str
    supersedes_record_id: str | None
    personnel_id: str | None
    crew_role: str | None
    crew_role_note_th: str | None
    mode: str | None
    start_date: str | None
    end_date: str | None
    shift_start_time: str | None
    shift_end_time: str | None
    shift_end_day_offset: str | None
    excluded_dates: list[str]
    early_end_at: str | None
    reason_th: str | None
    recorded_at: str
    recorded_by: str
    request_id: str


class VehicleCrewHistoryResponse(BaseModel):
    vehicle_id: str
    events: list[CrewHistoryEventResponse]
    records: list[CrewHistoryRecordResponse]


class CalendarEntryResponse(BaseModel):
    """One assigned interval on the calendar. kind DRIVER = an E2 operational driver
    assignment; CREW = a crew assignment; UNKNOWN = an E2 elapsed span whose
    assignee cannot be stated (shown as unknown, never as free)."""

    kind: Literal["DRIVER", "CREW", "UNKNOWN"]
    event_id: str
    vehicle_id: str
    machine_no: str | None
    personnel_id: str | None
    personnel_name: str | None
    driver_id: str | None
    driver_name: str | None
    identity: Literal["LINKED", "UNLINKED", "AMBIGUOUS"] | None
    role: str | None
    role_note_th: str | None
    mode: str | None
    label_date: str
    effective_start: str
    effective_end: str
    status: Literal["VALID", "CONFLICTED", "IDENTITY_UNVERIFIED", "UNKNOWN"]


class CalendarConflictResponse(BaseModel):
    code: Literal["RESOURCE_CONFLICT", "CROSS_ROLE_IDENTITY_UNVERIFIED"]
    first_event_id: str
    second_event_id: str
    personnel_id: str | None


class ResourceCalendarResponse(BaseModel):
    view: Literal["VEHICLES", "PERSONNEL", "BOTH"]
    date_from: str
    date_to: str
    time_zone: Literal["Asia/Bangkok"]
    entries: list[CalendarEntryResponse]
    conflicts: list[CalendarConflictResponse]


__all__ = [
    "CalendarConflictResponse",
    "CalendarEntryResponse",
    "CrewHistoryEventResponse",
    "CrewHistoryRecordResponse",
    "CrewIntervalResponse",
    "CrewOperationChangedResponse",
    "CrewOperationNoOpResponse",
    "CrewOperationReplayResponse",
    "CrewOperationRequest",
    "CrewWarningResponse",
    "ResourceCalendarResponse",
    "VehicleCrewHistoryResponse",
    "VehicleCrewResponse",
]
