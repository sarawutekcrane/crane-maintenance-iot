"""Vehicle Certificate (Web/API Phase 6 Batch 2A; baseline section 21;
Phase 6 prompt scope item "Certificates").

LIVE GOOGLE SHEETS SCHEMA — VERIFIED (not guessed): the live "MAINTENANCE"
spreadsheet's `vehicle_certificate` tab was independently verified to
already exist, with exactly these headers (present, currently with no
data rows):

    certificate_id, vehicle_id, certificate_type_code,
    certificate_type_name_th, document_no, issue_date, expiry_date,
    alert_lead_days, certificate_status, replaced_by_certificate_id,
    storage_ref, created_by_user_id, created_at, note_th

`VehicleCertificate` below carries exactly those fields, one field per
verified header, and no other.

BATCH 2A SCOPE: create + list + get only. Renewal/replacement lifecycle
(auto-REPLACED transition, replaced_by_certificate_id linking, ACTIVE
exclusivity, EXPIRED derivation) is explicitly deferred to a later
Batch 2B pending unresolved project decisions — see the Batch 2
pre-implementation audit. This module and its service therefore never
write `replaced_by_certificate_id`; ordinary creates always leave it
`None`.

NO-GUESSING RULE: `certificate_type_code`/`certificate_type_name_th` are
plain opaque strings — no approved vocabulary exists for certificate
types anywhere in this repository's governance documents, so this module
does not invent one. `certificate_status`, by contrast, DOES have an
approved (if only partially specified) vocabulary — exactly
ACTIVE/REPLACED/EXPIRED (baseline/Phase 6 prompt) — so it is validated
against exactly those three values when supplied, but remains optional/
nullable (no default is fabricated) since the live sheet has no
production rows to confirm requiredness, and no document states it is
required.

`alert_lead_days` is a plain nullable integer — no default, no min/max,
no warning-window/alert-generation logic (that belongs to a future Alert
engine batch, entirely out of scope here).

`storage_ref` is a plain opaque text reference only in this batch — no
new file-upload mechanism, no new `AttachmentPurpose`, no binary
handling. A real upload/storage integration is deferred to a later
slice per the Batch 2 audit's storage_ref strategy section."""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel


class CertificateStatus(str, Enum):
    """The only approved status vocabulary (Phase 6 prompt scope item
    "Certificates"). Not exhaustive by omission — this IS the complete,
    approved set; no additional status may be added without an explicit
    project decision."""

    ACTIVE = "ACTIVE"
    REPLACED = "REPLACED"
    EXPIRED = "EXPIRED"


class VehicleCertificate(BaseModel):
    """One vehicle certificate record — mirrors `vehicle_certificate`
    1:1. Batch 2A never mutates a row after creation (no update/delete
    method exists); a later batch's renewal action, once its linking
    semantics are approved, would be the first code path to ever write
    `replaced_by_certificate_id` or transition `certificate_status`."""

    certificate_id: str
    vehicle_id: str
    certificate_type_code: str | None = None
    certificate_type_name_th: str | None = None
    document_no: str | None = None
    """Opaque passthrough string — see module docstring's NO-GUESSING
    RULE. May legitimately contain leading zeros; never numerically
    coerced (Phase 6 Batch 1 `phone` precedent)."""
    issue_date: date | None = None
    expiry_date: date | None = None
    alert_lead_days: int | None = None
    certificate_status: CertificateStatus | None = None
    replaced_by_certificate_id: str | None = None
    storage_ref: str | None = None
    created_by_user_id: str | None = None
    created_at: datetime
    note_th: str | None = None


__all__ = ["CertificateStatus", "VehicleCertificate"]
