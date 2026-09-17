"""Driver / Operator + vehicle<->driver assignment request/response
schemas (Web/API Phase 6 Batch 1). See `app.domain.driver` for the
verified live-sheet field shapes and the NO-GUESSING RULE governing
`active_status`/`assignment_status` (plain optional strings, never an
Enum/fixed vocabulary)."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class CreateDriverRequest(BaseModel):
    driver_name_th: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    license_no: str | None = Field(default=None, max_length=100)
    license_expiry_date: date | None = None
    active_status: str | None = Field(default=None, max_length=50)
    note_th: str | None = Field(default=None, max_length=500)


class UpdateDriverRequest(BaseModel):
    driver_name_th: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    license_no: str | None = Field(default=None, max_length=100)
    license_expiry_date: date | None = None
    active_status: str | None = Field(default=None, max_length=50)
    note_th: str | None = Field(default=None, max_length=500)


class DriverResponse(BaseModel):
    driver_id: str
    driver_name_th: str
    phone: str | None
    license_no: str | None
    license_expiry_date: date | None
    active_status: str | None
    note_th: str | None


class AssignDriverRequest(BaseModel):
    driver_id: str = Field(min_length=1)
    is_primary: bool = False
    assignment_status: str | None = Field(default=None, max_length=50)
    note_th: str | None = Field(default=None, max_length=500)


class VehicleDriverAssignmentResponse(BaseModel):
    assignment_id: str
    vehicle_id: str
    driver_id: str
    start_at: datetime
    end_at: datetime | None
    is_primary: bool
    assignment_status: str | None
    changed_by_user_id: str | None
    note_th: str | None
