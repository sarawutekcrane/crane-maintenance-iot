from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SubmitRepairRequestRequest(BaseModel):
    """`แจ้งปัญหา/แจ้งซ่อม` — a reported problem, not a Repair Work Order
    (Core Demo Fixes Delta REV05 sections 2/3). Backend supplies
    actor/time and the automatic machine-state snapshot; the browser never
    supplies a manual counter/GPS value here."""

    vehicle_id: str = Field(min_length=1)
    symptom_th: str = Field(min_length=1, max_length=1000)
    priority: str | None = Field(default=None, max_length=50)
    note_th: str | None = Field(default=None, max_length=1000)
    # Present only when Maintenance is recording a request on behalf of
    # someone else (radio/phone/verbal report) — otherwise the actor
    # making this request IS the reporter, so these stay unset.
    reporter_type: str | None = Field(default=None, max_length=50)
    reporter_driver_id: str | None = Field(default=None, max_length=100)
    reporter_name_snapshot_th: str | None = Field(default=None, max_length=200)
    report_channel: str | None = Field(default=None, max_length=50)


class RepairRequestResponse(BaseModel):
    repair_request_id: str
    vehicle_id: str
    reported_at: datetime
    reported_by_user_id: str | None
    reporter_type: str | None
    reporter_driver_id: str | None
    reporter_name_snapshot_th: str | None
    report_channel: str | None
    symptom_th: str | None
    priority: str | None
    request_status: str
    reviewed_by_user_id: str | None
    reviewed_at: datetime | None
    repair_id: str | None
    converted_at: datetime | None
    note_th: str | None
    meter_snapshot_id: str | None


class SubmitRepairRequestResponse(BaseModel):
    request: RepairRequestResponse
    meter_snapshot_id: str | None
    """The automatic machine-state snapshot captured for this report
    (CORE-G01) — its linked GPS/location snapshot, when any, is reachable
    via `GET /location-snapshots/by-event/{meter_snapshot_id}`."""


class ConvertRepairRequestRequest(BaseModel):
    """Maintenance accepts a pending Repair Request as a Repair Work
    Order. Leaving `primary_technician` unset is normal — REV05 section 2A
    explicitly allows opening an RPR without assigning a technician
    immediately."""

    category: str | None = Field(default=None, max_length=200)
    primary_technician: str | None = None
    collaborators: list[str] = Field(default_factory=list)
