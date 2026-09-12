"""Revision-controlled inspection checklist master data.

Baseline section 8 / Phase 3 scope: checklist definitions are
revision-controlled, historical submissions retain the exact revision
used, and old revisions remain readable. `ChecklistItem` rows belong to
exactly one immutable `ChecklistRevision` — a new revision is a new set of
items, never an edit of a previous revision's items.

GOVERNANCE NOTE (OPEN_DECISIONS_REGISTER_EN.txt D01/D02/D03): there is no
approved asset/model -> checklist assignment policy, no approved daily/
weekly scheduling rule, and no source data naming any item critical. This
module therefore does not encode a checklist-assignment matrix (see
`Repository.get_active_checklist_revision`, which resolves "the" active
checklist for an `AssetType` — one family per asset type is the simplest
placeholder that does not require an assignment policy), `frequency` is
free text left unset by seed data, and `is_critical` defaults to `False`
and must never be set `True` without an explicit approved source.

CORRECTION (post-Phase-3 verification): a FAIL result being required to
carry a remark is likewise not an approved, unconditional rule — there is
no source document that mandates it globally. `required_remark_on_fail`
mirrors `required_photo_on_fail`'s design exactly: a per-item, source-data
-driven flag defaulting to `False`. No placeholder/seed item may set it
`True` without an explicit approved source, same restriction as
`is_critical`.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel

from app.domain.asset import AssetType


class InspectionResultValue(str, Enum):
    """Stable English result codes (Phase 3 scope). Thai labels live in the
    frontend's `lib/labels.ts`, never here."""

    PASS = "PASS"
    FAIL = "FAIL"
    NA = "NA"


class ChecklistMaster(BaseModel):
    """Stable checklist identity. `asset_type` fixes which kind of asset
    this checklist family applies to (see the governance note above for
    why there is exactly one active family per asset type in Phase 3)."""

    checklist_id: str
    asset_type: AssetType
    code: str
    name: str
    created_at: datetime
    updated_at: datetime


class ChecklistItem(BaseModel):
    """One item within a specific, immutable `ChecklistRevision`.

    `reference_image_attachment_id` points at an `Attachment` with purpose
    `CHECKLIST_REFERENCE_IMAGE` — master guidance imagery, never the
    evidence photo captured during an actual inspection.
    """

    item_id: str
    revision_id: str
    sequence: int
    title: str
    inspection_point: str | None = None
    method: str | None = None
    standard: str | None = None
    instruction: str | None = None
    frequency: str | None = None
    reference_image_attachment_id: str | None = None
    required_photo_on_fail: bool = False
    required_remark_on_fail: bool = False
    is_critical: bool = False


class ChecklistRevision(BaseModel):
    """One immutable revision of a checklist. `effective_date` selects
    which revision is "active" as of a given date; once created, a
    revision's own fields and its items never change."""

    revision_id: str
    checklist_id: str
    revision_number: int
    effective_date: date
    created_at: datetime


class ChecklistRevisionDetail(BaseModel):
    checklist: ChecklistMaster
    revision: ChecklistRevision
    items: list[ChecklistItem]
