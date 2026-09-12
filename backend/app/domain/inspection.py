"""Immutable inspection submissions and abnormal findings.

Baseline section 8 / Phase 3 scope: a submitted inspection is immutable
historical evidence. `InspectionItemResult` snapshots the checklist item's
display text (title/point/method/standard/instruction/is_critical) at
submission time, so a later checklist revision can never change what a
historical inspection shows, even though `item_id`/`revision_id` are also
kept for traceability. There is intentionally no update/void/supersede
model here (OPEN_DECISIONS_REGISTER_EN.txt D04 is not approved) — only
creation and read exist at the repository/service/API layers.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from app.domain.asset import AssetType
from app.domain.checklist import InspectionResultValue


class FindingStatus(str, Enum):
    """A single member today: FAIL results always create an OPEN finding
    for maintenance review (Phase 3 scope: "normal abnormal finding").
    Any further lifecycle (acknowledged/converted-to-repair/closed) is a
    Repair-workflow concept that belongs to Phase 4 (F01/F02 in
    OPEN_DECISIONS_REGISTER_EN.txt are not approved) and is deliberately
    not modeled here."""

    OPEN = "OPEN"


class InspectionHeader(BaseModel):
    inspection_id: str
    asset_type: AssetType
    asset_id: str
    checklist_id: str
    revision_id: str
    revision_number: int
    submitted_at: datetime
    inspector_user_id: str | None = None
    overall_remark: str | None = None


class InspectionItemResult(BaseModel):
    """Immutable per-item answer, with the checklist item's display text
    snapshotted at submission time (see module docstring)."""

    result_id: str
    inspection_id: str
    item_id: str
    sequence: int
    title: str
    inspection_point: str | None = None
    method: str | None = None
    standard: str | None = None
    instruction: str | None = None
    is_critical: bool
    result: InspectionResultValue
    remark: str | None = None
    evidence_attachment_ids: list[str] = []


class InspectionFinding(BaseModel):
    """Created for every FAIL result (Phase 3 scope). Does not itself carry
    a severity/alert level: the alert-severity model (A06) and the
    critical-item rule (D03) are not approved, so `is_critical` is only a
    snapshot flag for a later, explicitly-approved phase to branch on."""

    finding_id: str
    inspection_id: str
    result_id: str
    asset_type: AssetType
    asset_id: str
    item_title: str
    is_critical: bool
    status: FindingStatus
    created_at: datetime


class InspectionDetail(BaseModel):
    header: InspectionHeader
    items: list[InspectionItemResult]
    findings: list[InspectionFinding]


class NewInspectionItemInput(BaseModel):
    """One validated item answer, ready to persist. Built by
    `InspectionService` after checking the answer against its
    `ChecklistItem` definition (item exists in the active revision, FAIL
    remark/photo rules, evidence attachments exist) — the repository only
    persists what it is given, it does not re-validate business rules."""

    item_id: str
    sequence: int
    title: str
    inspection_point: str | None = None
    method: str | None = None
    standard: str | None = None
    instruction: str | None = None
    is_critical: bool
    result: InspectionResultValue
    remark: str | None = None
    evidence_attachment_ids: list[str] = []


class InspectionSummary(BaseModel):
    """Lightweight row for history/list views."""

    inspection_id: str
    asset_type: AssetType
    asset_id: str
    checklist_id: str
    revision_number: int
    submitted_at: datetime
    inspector_user_id: str | None = None
    pass_count: int
    fail_count: int
    na_count: int
    has_fail: bool
