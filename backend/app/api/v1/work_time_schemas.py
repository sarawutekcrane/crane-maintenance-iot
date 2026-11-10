"""R5 request / response models: Repair substates and technician work time.

Request models refuse unknown keys (`extra="forbid"`), so two different
accepted bodies never collapse into one replay fingerprint. `breaks` is
declared but optional at the schema level so that a missing or null value is
refused by the service with the stable code WORK_TIME_BREAKS_REQUIRED (never
silently treated as "no break")."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.work_time import RepairSubstatePeriod, WorkTimeConfirmation, WorkTimeEntry


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BreakIn(_Strict):
    started_at: datetime
    ended_at: datetime


class RecordSubstateRequest(_Strict):
    substate: str
    started_at: datetime | None = None
    """Omitted / null = the server's own current time (whole seconds), so a "now" change never depends
    on the client clock; an identical resend replays the first request."""
    ended_at: datetime | None = None
    material_request_id: str | None = None
    close_ongoing: bool = False
    """End the currently ongoing period at `started_at` in the same request (e.g. กำลังซ่อม → รออะไหล่)."""


class ReviseSubstateRequest(_Strict):
    action: str
    expected_revision: int = Field(ge=1)
    reason: str | None = None
    substate: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None


class RecordWorkTimeRequest(_Strict):
    started_at: datetime
    ended_at: datetime
    time_class: str
    description: str | None = None
    breaks: list[BreakIn] | None = None
    technician_id: str | None = None
    """Optional and never authority: when given it must equal the caller's own technician."""


class ReviseWorkTimeRequest(_Strict):
    action: str
    expected_revision: int = Field(ge=1)
    reason: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    time_class: str | None = None
    description: str | None = None
    breaks: list[BreakIn] | None = None


class EntryRevisionRef(_Strict):
    entry_id: str = Field(min_length=1)
    revision: int = Field(ge=1)


class ConfirmWorkTimeRequest(_Strict):
    entries: list[EntryRevisionRef]
    note: str | None = Field(default=None, max_length=1000)


class SubstateDurationsResponse(BaseModel):
    repairing_seconds: int
    awaiting_parts_seconds: int
    other_seconds: int
    elapsed_seconds: int


class RepairSubstatesResponse(BaseModel):
    repair_id: str
    periods: list[RepairSubstatePeriod]
    history: list[RepairSubstatePeriod]
    durations: SubstateDurationsResponse
    as_of: datetime


class RepairSubstateWriteResponse(RepairSubstatesResponse):
    replayed: bool


class TechnicianTotalsResponse(BaseModel):
    regular_seconds: int
    overtime_seconds: int
    total_seconds: int
    workdays: list[str]


class TeamTotalsResponse(BaseModel):
    regular_seconds: int
    overtime_seconds: int
    total_seconds: int
    technician_count: int


class WorkTimeEntryView(BaseModel):
    entry: WorkTimeEntry
    confirmed: bool
    revisions: list[WorkTimeEntry]


class JobWorkTimeResponse(BaseModel):
    work_kind: str
    job_id: str
    status: str
    entries: list[WorkTimeEntryView]
    confirmations: list[WorkTimeConfirmation]
    technicians: dict[str, TechnicianTotalsResponse]
    team: TeamTotalsResponse
    elapsed_seconds: int
    """Whole Work Order elapsed time; never a man-hour figure."""
    unconfirmed_count: int


class JobWorkTimeWriteResponse(JobWorkTimeResponse):
    replayed: bool


class TechnicianWorkTimeResponse(BaseModel):
    technician_id: str
    from_: datetime = Field(serialization_alias="from")
    to: datetime
    entries: list[WorkTimeEntry]
    totals: TechnicianTotalsResponse

    model_config = ConfigDict(populate_by_name=True)


__all__ = [
    "BreakIn", "ConfirmWorkTimeRequest", "JobWorkTimeResponse", "JobWorkTimeWriteResponse", "RecordSubstateRequest",
    "RecordWorkTimeRequest", "RepairSubstateWriteResponse", "RepairSubstatesResponse", "ReviseSubstateRequest",
    "ReviseWorkTimeRequest", "TechnicianWorkTimeResponse",
]
