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


class Attachment(BaseModel):
    attachment_id: str
    purpose: AttachmentPurpose
    storage_ref: str
    filename: str
    content_type: str
    size_bytes: int
    uploaded_at: datetime
    uploaded_by: str | None = None
