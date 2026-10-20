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

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel

from app.domain.asset import AssetType
from app.domain.checklist import InspectionResultValue


class FindingStatus(str, Enum):
    """Phase 3: every FAIL result created an OPEN finding for maintenance
    review. R3 (docs/project-governance/r3-implementation-contract.md §7)
    adds the episode end: an OPEN Finding becomes ENDED with an
    `end_reason`. There is no other state (no verified / accepted / failed)."""

    OPEN = "OPEN"
    ENDED = "ENDED"
    """R3 (contract §7): the episode has ended. ENDED is never a verification,
    an acceptance or a safety declaration."""


class FindingEndReason(str, Enum):
    """R3 (contract §7). TECHNICIAN_COMPLETION_SUBMITTED is Owner wording; the
    other two code names are proposed (TS-9)."""

    NORMAL_REINSPECTION = "NORMAL_REINSPECTION"
    TECHNICIAN_COMPLETION_SUBMITTED = "TECHNICIAN_COMPLETION_SUBMITTED"
    MANUAL_TERMINATION = "MANUAL_TERMINATION"


NORMAL_REINSPECTION_REASON_TH = "ตรวจครั้งล่าสุดแล้วไม่พบความผิดปกติ"
TECHNICIAN_COMPLETION_REASON_TH = "สิ้นสุดรอบติดตาม — ช่างส่งงานซ่อมแล้ว"


class FindingObservation(BaseModel):
    """R3 (R3-12): one dated inspection observation attached to a Finding.
    Append-only; the inspection itself stays immutable."""

    inspection_id: str
    result_id: str
    result: InspectionResultValue
    remark: str | None = None
    inspection_date: date
    observed_at: datetime


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
    machine_state_snapshot_id: str | None = None
    """Core Demo Fix: automatic backend-derived machine-state snapshot
    captured at submission time (see app.domain.meter_service.MeterService.
    capture_current_state). `None` only for inspections submitted before
    this field existed."""
    request_id: str | None = None
    """R3 (R3-20): the client's submission id. `None` on pre-R3 inspections."""
    inspection_date: date | None = None
    """R3 (R3-21): the Asia/Bangkok calendar date of submission. `None` on
    pre-R3 inspections."""


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
    item_key: str | None = None
    frequency: str | None = None
    """R3: the stable item identity and frequency snapshotted at submission.
    `None` on pre-R3 results."""


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
    # ---- R3 (contract §7); all `None` / empty on pre-R3 findings ----
    item_key: str | None = None
    observations: list[FindingObservation] = []
    end_reason: FindingEndReason | None = None
    ended_at: datetime | None = None
    ended_by: str | None = None
    end_note: str | None = None
    ended_inspection_id: str | None = None
    ended_repair_id: str | None = None
    previous_finding_id: str | None = None
    """Non-judgemental link to the previous ended episode of the same asset +
    item (R3-13); never a statement that the earlier repair failed."""

    @property
    def is_r3(self) -> bool:
        return self.item_key is not None


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
    item_key: str | None = None
    frequency: str | None = None


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
    usable_pending_repair_count: int = 0
    not_installed_count: int = 0
    inspection_date: date | None = None
