from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.domain.asset import AssetType
from app.domain.checklist import InspectionResultValue


class AttachmentResponse(BaseModel):
    attachment_id: str
    purpose: str
    filename: str
    content_type: str
    size_bytes: int
    uploaded_at: datetime
    uploaded_by: str | None
    url: str
    source_type: str | None = None
    source_id: str | None = None


class ChecklistItemResponse(BaseModel):
    item_id: str
    revision_id: str
    sequence: int
    title: str
    inspection_point: str | None
    method: str | None
    standard: str | None
    instruction: str | None
    frequency: str | None
    required_photo_on_fail: bool
    required_remark_on_fail: bool
    is_critical: bool
    reference_image: AttachmentResponse | None = None
    item_key: str | None = None


class ChecklistMasterResponse(BaseModel):
    checklist_id: str
    asset_type: AssetType
    code: str
    name: str


class ChecklistRevisionResponse(BaseModel):
    revision_id: str
    checklist_id: str
    revision_number: int
    effective_date: date
    created_at: datetime


class ChecklistRevisionDetailResponse(BaseModel):
    checklist: ChecklistMasterResponse
    revision: ChecklistRevisionResponse
    items: list[ChecklistItemResponse]


class SubmitInspectionItemRequest(BaseModel):
    item_id: str = Field(min_length=1)
    result: InspectionResultValue
    remark: str | None = Field(default=None, max_length=1000)
    evidence_attachment_ids: list[str] = Field(default_factory=list)


class SubmitInspectionRequest(BaseModel):
    asset_type: AssetType
    asset_id: str = Field(min_length=1)
    overall_remark: str | None = Field(default=None, max_length=1000)
    items: list[SubmitInspectionItemRequest] = Field(min_length=1)


class InspectionItemResultResponse(BaseModel):
    result_id: str
    inspection_id: str
    item_id: str
    sequence: int
    title: str
    inspection_point: str | None
    method: str | None
    standard: str | None
    instruction: str | None
    is_critical: bool
    result: InspectionResultValue
    remark: str | None
    evidence: list[AttachmentResponse] = Field(default_factory=list)
    item_key: str | None = None
    frequency: str | None = None


class FindingObservationResponse(BaseModel):
    inspection_id: str
    result_id: str
    result: InspectionResultValue
    remark: str | None
    inspection_date: date
    observed_at: datetime


class InspectionFindingResponse(BaseModel):
    finding_id: str
    inspection_id: str
    result_id: str
    asset_type: AssetType
    asset_id: str
    item_title: str
    is_critical: bool
    status: str
    created_at: datetime
    # ---- R3 (contract §7); null / empty on pre-R3 findings ----
    item_key: str | None = None
    observations: list[FindingObservationResponse] = Field(default_factory=list)
    end_reason: str | None = None
    ended_at: datetime | None = None
    ended_by: str | None = None
    end_note: str | None = None
    ended_inspection_id: str | None = None
    ended_repair_id: str | None = None
    previous_finding_id: str | None = None


class InspectionHeaderResponse(BaseModel):
    inspection_id: str
    asset_type: AssetType
    asset_id: str
    checklist_id: str
    revision_id: str
    revision_number: int
    submitted_at: datetime
    inspector_user_id: str | None
    overall_remark: str | None
    machine_state_snapshot_id: str | None = None
    request_id: str | None = None
    inspection_date: date | None = None


class InspectionDetailResponse(BaseModel):
    header: InspectionHeaderResponse
    items: list[InspectionItemResultResponse]
    findings: list[InspectionFindingResponse]
    replayed: bool = False
    """R3 S2: True when this response returns the original inspection for a
    retried request_id (nothing new was written)."""


class InspectionSummaryResponse(BaseModel):
    inspection_id: str
    asset_type: AssetType
    asset_id: str
    checklist_id: str
    revision_number: int
    submitted_at: datetime
    inspector_user_id: str | None
    pass_count: int
    fail_count: int
    na_count: int
    has_fail: bool
    usable_pending_repair_count: int = 0
    not_installed_count: int = 0
    inspection_date: date | None = None


class InspectionFormItemResponse(BaseModel):
    item: ChecklistItemResponse
    due_reason: str
    last_result_date: date | None


class InspectionFormResponse(BaseModel):
    """R3 (contract §5–§6): the checklist resolved for this asset and the
    items due on `inspection_date` (Asia/Bangkok)."""

    asset_type: AssetType
    asset_id: str
    inspection_date: date
    checklist: ChecklistMasterResponse
    revision: ChecklistRevisionResponse
    items: list[InspectionFormItemResponse]
    submitted_inspection_id: str | None


class FindingRepairResponse(BaseModel):
    repair_id: str
    status: str
    opened_at: datetime
    closed_at: datetime | None
    completion_submitted_at: datetime | None
    cancelled_at: datetime | None


class FindingDetailResponse(BaseModel):
    finding: InspectionFindingResponse
    repairs: list[FindingRepairResponse]
    followup_group: str | None


class TerminateFindingRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)
