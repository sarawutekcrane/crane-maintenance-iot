"""Driver / Operator master (Web/API Phase 6 Batch 1; baseline section 20;
Phase 6 prompt scope item A).

LIVE GOOGLE SHEETS SCHEMA — VERIFIED (not guessed): the live "MAINTENANCE"
spreadsheet's `driver_master` tab was independently verified to already
exist, with exactly these headers (present, but with no production rows
yet):

    driver_master:  driver_id, driver_name_th, phone, license_no,
                     license_expiry_date, active_status, note_th

`Driver` below carries exactly those fields, one field per verified header, and no other — no column is added merely
because a prior repository declaration happened to omit it (see
`app.repositories.google_sheets.schemas`).

NO-GUESSING RULE (CRITICAL): the live tab has no production rows yet, so
no vocabulary for `active_status` can be inferred from real data, and no
approved vocabulary is named anywhere in this repository's governance
documents (OPEN_DECISIONS_REGISTER_EN.txt has no Driver-specific status
entry). It is therefore a plain optional string, never an `Enum` — this
module does NOT assume ACTIVE/INACTIVE or any other vocabulary. Whatever
string a caller supplies is stored/returned verbatim; blank/`None` stays
honestly unset.

DRIVER LICENSE / CERTIFICATE GUARDRAIL: the verified `driver_master` tab
provides exactly `license_no` + `license_expiry_date` as the driver's own
credential representation. Per the Phase 6 Batch 1 instruction, this is
the intended Batch 1 representation of "license/certificate" (Phase 6
prompt scope item A) — no separate driver-certificate table/columns are
invented here. This is a distinct concept from `vehicle_certificate`
(vehicle-owned, renewal-as-new-record history — a later Phase 6 batch),
and this module never reuses that concept for a driver-held credential.

R2 Batch R2-C3 (A2-8 / A2-10, owner decisions D1-D4): the Phase 6
`vehicle_driver` assignment model, its three routes, service methods and
repository methods are RETIRED. The live `vehicle_driver` tab and any rows
in it are left untouched (never read, written, migrated or deleted); the
vehicle's permanent responsible driver is R2f-f and its day / shift
assignment is E2."""
from __future__ import annotations

from datetime import date

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


__all__ = ["Driver"]
