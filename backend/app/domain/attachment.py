"""Shared attachment metadata for files stored via `StorageProvider`.

Frozen storage rule (baseline section 17 / Phase 1): binary content never
lives in the database/sheet — only metadata + `storage_ref` do. This module
is the one shared attachment record used by both checklist reference
images and inspection evidence photos, distinguished by `purpose` so the
two concepts are never confused with each other (Phase 3 scope: "Reference
Image and Inspection Photo are separate").
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class AttachmentPurpose(str, Enum):
    CHECKLIST_REFERENCE_IMAGE = "CHECKLIST_REFERENCE_IMAGE"
    INSPECTION_EVIDENCE = "INSPECTION_EVIDENCE"
    # Phase 4 (PM / Repair) — additive, same shared Attachment record.
    PM_EVIDENCE = "PM_EVIDENCE"
    REPAIR_EVIDENCE = "REPAIR_EVIDENCE"
    # Core Demo Fixes Delta REV05 section 4 — additive, same shared
    # Attachment record; see `source_type`/`source_id` below.
    REPAIR_REQUEST_EVIDENCE = "REPAIR_REQUEST_EVIDENCE"
    # R7-A (Owner-approved bounded Mock/TEST scope): a PDF bound to exactly one
    # existing Vehicle Certificate (source_type="VEHICLE_CERTIFICATE",
    # source_id=certificate_id) or Model Document (source_type="MODEL_DOCUMENT",
    # source_id=model_document_id). Additive, same shared Attachment record. No
    # public route may create one until an Owner policy names the uploaders (see
    # `InspectionService.upload_attachment`); the record's own historical
    # `storage_ref` text is never read, rewritten or treated as one of these.
    VEHICLE_CERTIFICATE_DOCUMENT = "VEHICLE_CERTIFICATE_DOCUMENT"
    MODEL_DOCUMENT_FILE = "MODEL_DOCUMENT_FILE"


# R7-A: the document purposes. PDF only, Mock/TEST only, never a photo purpose.
DOCUMENT_ATTACHMENT_PURPOSES = frozenset(
    {AttachmentPurpose.VEHICLE_CERTIFICATE_DOCUMENT, AttachmentPurpose.MODEL_DOCUMENT_FILE}
)


class Attachment(BaseModel):
    attachment_id: str
    purpose: AttachmentPurpose
    storage_ref: str
    filename: str
    content_type: str
    size_bytes: int
    uploaded_at: datetime
    uploaded_by: str | None = None
    source_type: str | None = None
    """Core Demo Fixes Delta REV05 section 4, extended REV06.2: forward
    join back to this attachment's owning record, validated and
    authorization-gated by `AttachmentService.authorize_source`. Set for
    `REPAIR_REQUEST_EVIDENCE` (source_type="REPAIR_REQUEST", REV05),
    `REPAIR_EVIDENCE` (source_type="REPAIR", source_id=repair_id),
    `PM_EVIDENCE` (source_type="PM_WORK_ORDER", source_id=pm_work_order_id)
    and `INSPECTION_EVIDENCE` (source_type="INSPECTION_VEHICLE"/
    "INSPECTION_EQUIPMENT", source_id=asset_id — the asset being
    inspected, since no Inspection id exists yet at upload time). Left
    `None` only for `CHECKLIST_REFERENCE_IMAGE` (master/reference content
    with no per-instance owner — see `authorize_source`) and any
    attachment created before REV06.2, which now fails closed on download
    rather than being guessed at (REV06.2 section 9)."""
    source_id: str | None = None
