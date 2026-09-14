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
    """Core Demo Fixes Delta REV05 section 4: "Repair Request attachments
    reuse existing `attachment`: source_type = REPAIR_REQUEST, source_id =
    repair_request_id." Additive/optional — every attachment purpose
    predating REV05 (checklist reference image, inspection/PM/repair
    evidence) keeps linking back to its owner via that owner's own
    `attachment_ids`/`evidence_attachment_ids` field instead, exactly as
    before; only `RepairRequest` (which the given `repair_request` sheet
    column list has no `attachment_ids` column for) needs this join-by-
    value alternative."""
    source_id: str | None = None
