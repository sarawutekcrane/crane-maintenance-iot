"""Driver / Operator master + vehicle<->driver assignment history (Web/API
Phase 6 Batch 1; baseline section 20; Phase 6 prompt scope item A).

LIVE GOOGLE SHEETS SCHEMA — VERIFIED (not guessed): the live "MAINTENANCE"
spreadsheet's `driver_master` and `vehicle_driver` tabs were independently
verified to already exist, with exactly these headers (present, but with
no production rows yet):

    driver_master:  driver_id, driver_name_th, phone, license_no,
                     license_expiry_date, active_status, note_th
    vehicle_driver: assignment_id, vehicle_id, driver_id, start_at,
                     end_at, is_primary, assignment_status,
                     changed_by_user_id, note_th

`Driver`/`VehicleDriverAssignment` below carry exactly those fields, one
field per verified header, and no other — no column is added merely
because a prior repository declaration happened to omit it (see
`app.repositories.google_sheets.schemas`).

NO-GUESSING RULE (CRITICAL): the live tabs have no production rows yet,
so no vocabulary for `active_status`/`assignment_status` can be inferred
from real data, and no approved vocabulary for either is named anywhere
in this repository's governance documents
(OPEN_DECISIONS_REGISTER_EN.txt has no Driver-specific status entry).
Both fields are therefore plain optional strings, never an `Enum` —
this module does NOT assume ACTIVE/INACTIVE or any other vocabulary.
Whatever string a caller supplies is stored/returned verbatim; blank/
`None` stays honestly unset. "Is this assignment currently in effect" is
derived structurally from `end_at is None` (a technical fact the live
schema itself encodes via the start/end period columns), never from the
opaque `assignment_status` string.

DRIVER LICENSE / CERTIFICATE GUARDRAIL: the verified `driver_master` tab
provides exactly `license_no` + `license_expiry_date` as the driver's own
credential representation. Per the Phase 6 Batch 1 instruction, this is
the intended Batch 1 representation of "license/certificate" (Phase 6
prompt scope item A) — no separate driver-certificate table/columns are
invented here. This is a distinct concept from `vehicle_certificate`
(vehicle-owned, renewal-as-new-record history — a later Phase 6 batch),
and this module never reuses that concept for a driver-held credential.

ASSIGNMENT HISTORY (Phase 6 prompt scope item A / acceptance test
"driver assignment history preserved"): a new assignment is always a new
`VehicleDriverAssignment` row; an existing row is only ever closed in
place (`end_at` set) via an explicit `DriverService.end_assignment` call
for that exact row, never deleted or overwritten. `DriverService
.assign_driver` never modifies any other row as a side effect (project
decision, targeted correction — approved Phase 6 Batch 1 requirements are
only "assignment start/end history" and "preservation of previous
history"; no PRIMARY-exclusivity/overlap/auto-termination rule is
approved). `DriverService.end_assignment` is idempotent: ending an
already-ended assignment is a no-op that returns the existing row
unchanged, never a second history row, never an error, and never a
correction of the original `end_at` (no correction/edit policy is
approved)."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class Driver(BaseModel):
    """Driver/operator master record — mirrors `driver_master` 1:1."""

    driver_id: str
    driver_name_th: str
    phone: str | None = None
    license_no: str | None = None
    license_expiry_date: date | None = None
    active_status: str | None = None
    """Opaque passthrough string — see module docstring's NO-GUESSING RULE."""
    note_th: str | None = None


class VehicleDriverAssignment(BaseModel):
    """One vehicle<->driver assignment period — mirrors `vehicle_driver`
    1:1. Never mutated except to set `end_at`/`changed_by_user_id` when
    the period is closed (see `DriverService.end_assignment`)."""

    assignment_id: str
    vehicle_id: str
    driver_id: str
    start_at: datetime
    end_at: datetime | None = None
    is_primary: bool = False
    assignment_status: str | None = None
    """Opaque passthrough string — see module docstring's NO-GUESSING RULE."""
    changed_by_user_id: str | None = None
    note_th: str | None = None

    @property
    def is_active(self) -> bool:
        """Structural "currently in effect" signal — `end_at is None`.
        Never derived from `assignment_status`, whose vocabulary is
        unresolved (see module docstring)."""
        return self.end_at is None


__all__ = ["Driver", "VehicleDriverAssignment"]
