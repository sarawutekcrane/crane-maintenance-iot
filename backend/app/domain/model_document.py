"""Model Document (Web/API Phase 6 Batch 3A create/list/get + Batch 3B
revision lifecycle; baseline section 21 / Phase 6 prompt scope item
"Model Documents").

LIVE GOOGLE SHEETS SCHEMA — VERIFIED (not guessed): the live "MAINTENANCE"
spreadsheet's `model_document` tab was independently verified to already
exist, with exactly these headers (present, currently with no data rows):

    model_document_id, model_id, document_type, document_name_th,
    version, effective_from, effective_to, storage_ref, file_status,
    active_status, replaced_by_document_id, note_th

`ModelDocument` below carries exactly those fields, one field per
verified header, and no other.

REVISION LIFECYCLE (Batch 3B, `ModelDocumentService.revise_document`):
revising a document always creates a NEW row — `model_id`/`document_type`
inherited unconditionally from the source, `effective_to` always `None`
on the new row — and links the source to it via
`replaced_by_document_id`, closing the source's own `effective_to` to
the day before the new row's `effective_from`. Ordinary create
(`create_document`) is completely unaffected by this and still never
writes `replaced_by_document_id` itself. `active_status`/`file_status`
are never used to determine which revision is "the effective one" — no
such derivation exists anywhere in this module; the only authoritative
chain link is `replaced_by_document_id`.

NO-GUESSING RULE: `document_type`/`document_name_th`/`file_status`/
`active_status` are plain opaque strings — no approved vocabulary exists
for any of them anywhere in this repository's governance documents (the
Phase 6 prompt names "Load Chart"/"Operation Manual"/"Service Manual" as
product-scope examples only, never as machine-readable codes), so this
module does not invent one. This mirrors the identical precedent already
established for `driver_master.active_status` (Batch 1) and
`vehicle_certificate.certificate_type_code` (Batch 2A) — `active_status`
reusing the exact same column name on a second live tab is direct
evidence it should get the same opaque-passthrough treatment here.

`version` is also a plain opaque string, never coerced/validated/ordered
— no authoritative source defines its format, and real document versions
commonly look like "Rev.A"/"2026.01"/"1.0", not a simple sequential
integer (contrast with this project's own `PartSetRevision.revision_number`/
`ChecklistRevision.revision_number`, which ARE plain integers — a
different, unrelated convention this field must not be assumed to share).

`storage_ref` is a plain opaque text reference only — no file-upload
mechanism, no new `AttachmentPurpose`, no binary/base64 handling. Real
upload/storage integration is deferred to a later slice per the Batch 3
audit's storage_ref strategy section (mirrors the identical Batch 2A
decision for `VehicleCertificate.storage_ref`)."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class ModelDocument(BaseModel):
    """One model-document record — mirrors `model_document` 1:1. No
    update/delete method exists — a row is only ever created
    (`create_model_document`) or, once (Batch 3B), narrowly finalized by
    a revision (`finalize_model_document_revision`, which sets exactly
    `effective_to`/`replaced_by_document_id` and nothing else)."""

    model_document_id: str
    model_id: str
    document_type: str | None = None
    document_name_th: str | None = None
    version: str | None = None
    """Opaque passthrough string — see module docstring. May legitimately
    contain leading zeros or punctuation ("001", "1.0", "Rev.A"); never
    numerically coerced, never used for ordering/uniqueness (Phase 6
    Batch 1 `phone` / Batch 2A `document_no` precedent)."""
    effective_from: date | None = None
    effective_to: date | None = None
    storage_ref: str | None = None
    file_status: str | None = None
    active_status: str | None = None
    replaced_by_document_id: str | None = None
    note_th: str | None = None


__all__ = ["ModelDocument"]
